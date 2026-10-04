"""Wires the embedded prototype: page host, router, artwork, and the
existing desktop client (AmberfaderApp + MainWindow) on top.

Requires a QApplication created after QtWebEngineWidgets was imported.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QTimer

from ..app import AmberfaderApp
from ..hosts import PlaybackHost
from .artwork import ArtworkFetcher
from .history import SearchHistoryStore
from .page import PageHost, PageMode, create_profile
from .router import EmbeddedRouter
from .upstream import EmbeddedUpstream

# Long enough for a slow first load of YouTube Music; the message only says
# that nothing attached yet, it does not stop anything.
ATTACH_TIMEOUT_MS = 20_000
ATTACH_STALLED = (
    "Amberfader could not attach to the YouTube Music page yet. Use Show YT to check it."
)


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
    profile_storage: Path = field(
        default_factory=lambda: _xdg_path("XDG_DATA_HOME", ".local/share") / "webengine",
    )
    profile_cache: Path = field(
        default_factory=lambda: _xdg_path("XDG_CACHE_HOME", ".cache") / "webengine",
    )


class EmbeddedRuntime:
    def __init__(self, options: RuntimeOptions, bundle: str) -> None:
        self.profile = create_profile(options.mode, options.profile_storage, options.profile_cache)
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
            on_message=self.router.on_page_message, on_lost=self.router.on_page_lost,
        )
        self.artwork.assetReady.connect(self.router.on_asset)
        self.upstream.requested.connect(self.router.handle_request)
        self.amber = AmberfaderApp(
            options.socket_path, scale=options.scale,
            host=PlaybackHost.EMBEDDED, show_page=self.host.set_visible,
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

    def _report_stall(self) -> None:
        window = self.amber.window
        if window is not None and not self.router.attached and self.host.on_home_origin():
            window.show_status(ATTACH_STALLED, error=True)
