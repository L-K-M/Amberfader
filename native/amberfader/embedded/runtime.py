"""Wires the app together: page host, router, artwork, and the player
client (AmberfaderApp + MainWindow) on top.

Requires a QApplication created after QtWebEngineWidgets was imported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

from PySide6.QtCore import QTimer

from ..app import AmberfaderApp
from ..settings import AppSettings, SettingsStore
from .artwork import ArtworkFetcher
from .history import SearchHistoryStore
from .page import AdRequestFilter, PageHost, PageMode, create_profile
from .router import EmbeddedRouter
from .upstream import EmbeddedUpstream

# Long enough for a slow first load of YouTube Music; the message only says
# that nothing attached yet, it does not stop anything.
ATTACH_TIMEOUT_MS = 20_000
ATTACH_STALLED = (
    "Amberfader could not attach to the YouTube Music page yet. Use Show YT to check it."
)
SETTING_SAVED = "Saved. It applies fully the next time YouTube Music loads."
SETTING_NOT_SAVED = "Applied for now, but could not be saved: {reason}"


def _xdg_path(variable: str, fallback: str) -> Path:
    configured = os.environ.get(variable, "")
    base = Path(configured) if configured and Path(configured).is_absolute() else (
        Path.home() / fallback
    )
    return base / "amberfader"


@dataclass(frozen=True)
class RuntimeOptions:
    mode: PageMode
    socket_path: str
    history_path: Path
    scale: float = 1.0
    # None keeps settings in memory (the scripted test page uses this).
    settings_path: Path | None = None
    profile_storage: Path = field(
        default_factory=lambda: _xdg_path("XDG_DATA_HOME", ".local/share") / "webengine",
    )
    profile_cache: Path = field(
        default_factory=lambda: _xdg_path("XDG_CACHE_HOME", ".cache") / "webengine",
    )


class EmbeddedRuntime:
    def __init__(self, options: RuntimeOptions, bundle: str, *, ad_filter: str) -> None:
        self.settings_store = SettingsStore(options.settings_path)
        self.settings = self.settings_store.load()
        self.profile = create_profile(options.mode, options.profile_storage, options.profile_cache)
        self.ad_requests = AdRequestFilter(self.settings.block_ads)
        self.profile.setUrlRequestInterceptor(self.ad_requests)
        self.upstream = EmbeddedUpstream()
        self.artwork = ArtworkFetcher()
        self.router = EmbeddedRouter(
            emit=self.upstream.deliver,
            send_to_page=lambda command: self.host.send_command(command),
            request_artwork=self.artwork.request,
            history=SearchHistoryStore(options.history_path),
        )
        self.host = PageHost(
            self.profile, options.mode, bundle,
            ad_filter=ad_filter, settings=self.settings,
            on_message=self.router.on_page_message, on_lost=self.router.on_page_lost,
        )
        self.artwork.assetReady.connect(self.router.on_asset)
        self.upstream.requested.connect(self.router.handle_request)
        self.amber = AmberfaderApp(
            options.socket_path, show_page=self.host.set_visible, scale=options.scale,
        )
        self._stall = QTimer()
        self._stall.setSingleShot(True)
        self._stall.setInterval(ATTACH_TIMEOUT_MS)
        self._stall.timeout.connect(self._report_stall)
        self._started = False

    def start(self) -> bool:
        """Show the player and load the page. False when another process
        owns the single-instance socket. FaceError propagates."""
        if not self.amber.start():
            return False
        self._started = True
        window = self.amber.window
        assert window is not None
        window.add_page_option(
            "Block ads", self.settings.block_ads,
            lambda on: self._change(replace(self.settings, block_ads=on)),
        )
        window.add_page_option(
            "Continue playing automatically", self.settings.continue_playing,
            lambda on: self._change(replace(self.settings, continue_playing=on)),
        )
        self.amber.attach_upstream(self.upstream)
        assert self.host.page is not None
        self.host.page.loadFinished.connect(lambda _ok: self._stall.start())
        self.host.load()
        return True

    def shutdown(self) -> None:
        """Release the page before its profile. Safe after a failed start:
        the socket is closed only when this process owns it."""
        self._stall.stop()
        if self._started:
            self.amber.close()
        self.host.shutdown()
        # The profile does not own its interceptor; detach it before either
        # Python object can be freed.
        self.profile.setUrlRequestInterceptor(None)

    def _change(self, settings: AppSettings) -> None:
        """Apply a switch from the menu: request blocking at once, the page
        scripts at the next load. A save failure keeps it for this session."""
        self.settings = settings
        self.ad_requests.enabled = settings.block_ads
        self.host.apply_settings(settings)
        window = self.amber.window
        try:
            self.settings_store.save(settings)
        except OSError as exc:
            if window is not None:
                window.show_status(
                    SETTING_NOT_SAVED.format(reason=exc.strerror or type(exc).__name__),
                    error=True,
                )
            return
        if window is not None:
            window.show_status(SETTING_SAVED)

    def _report_stall(self) -> None:
        window = self.amber.window
        if window is not None and not self.router.attached and self.host.on_home_origin():
            window.show_status(ATTACH_STALLED, error=True)
