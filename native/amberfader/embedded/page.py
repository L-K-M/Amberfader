"""QtWebEngine side of Amberfader.

Owns the persistent profile (the Google sign-in lives here), the guarded
YouTube Music page, the injected adapter bundle, and the window that shows
the page for sign-in and browsing.

Isolation: the bundle and Qt's qwebchannel.js run in QtWebEngine's
application world, the equivalent of an extension content script. Page
scripts run in the main world and cannot reach the channel. Host-side, page
messages are accepted only while the top-level page is on the expected origin.

Ad blocking: while it is on, the ad filter script runs in the main world
(it has to change the page's own objects) and holds no bridge, and
AdRequestFilter blocks ad requests for the whole profile.
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from enum import Enum
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices, QResizeEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
    QWebEngineUrlRequestInfo,
    QWebEngineUrlRequestInterceptor,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QMainWindow

from ..settings import AppSettings
from .adblock import is_ad_request
from .navigation import MUSIC_ORIGIN, navigation_allowed, opens_externally, origin_of

HOST_OBJECT_NAME = "amberfader"
PROFILE_NAME = "amberfader-embedded"
TEST_PAGE_ORIGIN = "https://amberfader.invalid"
TEST_PAGE_HTML = (
    "<!doctype html><meta charset='utf-8'><title>Amberfader test page</title>"
    "<p>Scripted test page for Amberfader. "
    "No YouTube Music session is involved.</p>"
)
# YouTube Music hides its player bar's Like button below 936 CSS px and
# switches to a mobile layout without a usable one below about 616 px
# (measured 2026-10-07). Amberfader reads and presses the laid-out button,
# so the page always lays out at least this wide. The margin absorbs zoom
# rounding and small breakpoint changes.
MIN_LAYOUT_WIDTH = 1024
# QWebEnginePage ignores smaller zoom factors.
MIN_ZOOM = 0.25
# Zoom factors pass through single precision on their way back from Chromium.
ZOOM_TOLERANCE = 1e-3
WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld
BRIDGE_SCRIPT_NAME = "amberfader-page-bridge"
AD_FILTER_SCRIPT_NAME = "amberfader-ad-filter"


class PageMode(Enum):
    """Values match the bundle's adapter configuration."""

    YOUTUBE_MUSIC = "youtube-music"
    # The scripted FakeAdapter on a local page: exercises the whole bridge in
    # real QtWebEngine without network access or a Google account.
    TEST_PAGE = "fake"

    @property
    def origin(self) -> str:
        return MUSIC_ORIGIN if self is PageMode.YOUTUBE_MUSIC else TEST_PAGE_ORIGIN


class BundleMissingError(RuntimeError):
    pass


def _load_page_script(name: str) -> str:
    resource = resources.files("amberfader.embedded") / "web" / name
    try:
        return resource.read_text("utf-8")
    except FileNotFoundError as exc:
        raise BundleMissingError(
            "The page bundle is missing. Build it with: npm run build"
        ) from exc


def load_bundle() -> str:
    return _load_page_script("adapter.js")


def load_ad_filter() -> str:
    return _load_page_script("ad-filter.js")


def _qwebchannel_source() -> str:
    source = QFile(":/qtwebchannel/qwebchannel.js")
    if not source.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Qt WebChannel's qwebchannel.js resource is unavailable")
    try:
        return bytes(source.readAll().data()).decode("utf-8")
    finally:
        source.close()


def _match_header(mode: PageMode) -> str:
    # @match keeps QtWebEngine from injecting anywhere else.
    return f"// ==UserScript==\n// @match {mode.origin}/*\n// ==/UserScript==\n"


def script_source(bundle: str, mode: PageMode, *, continue_playing: bool) -> str:
    # The bundle also checks the origin and the top frame itself.
    config = json.dumps({
        "adapter": mode.value, "origin": mode.origin, "continuePlaying": continue_playing,
    })
    return (
        f"{_match_header(mode)}{_qwebchannel_source()}\n"
        f"var __AMBERFADER_EMBEDDED__ = {config};\n{bundle}"
    )


def ad_filter_source(source: str, mode: PageMode) -> str:
    return f"{_match_header(mode)}{source}"


class AdRequestFilter(QWebEngineUrlRequestInterceptor):
    """Blocks ad and ad-tracking requests (embedded/adblock.py) while
    enabled. Qt calls interceptRequest on the UI thread."""

    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = enabled

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        if self.enabled and is_ad_request(info.requestUrl().toString()):
            info.block(True)


def create_profile(mode: PageMode, storage: Path, cache: Path) -> QWebEngineProfile:
    """The real page keeps cookies on disk so sign-in survives restarts. The
    test page uses an off-the-record profile and never touches them."""
    if mode is PageMode.TEST_PAGE:
        profile = QWebEngineProfile()
    else:
        for directory in (storage, cache):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            directory.chmod(0o700)
        profile = QWebEngineProfile(PROFILE_NAME)
        profile.setPersistentStoragePath(str(storage))
        profile.setCachePath(str(cache))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies,
        )
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.DiskHttpCache)

    profile.downloadRequested.connect(lambda download: download.cancel())
    settings = profile.settings()
    # Commands click site controls from script; those are not user gestures.
    settings.setAttribute(QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture, False)
    settings.setAttribute(QWebEngineSettings.WebAttribute.WebRTCPublicInterfacesOnly, True)
    return profile


class _QuietPage(QWebEnginePage):
    """Denies every permission prompt (notifications, camera, location, ...)
    and keeps page console output, which can contain track names and
    queries, off stderr. Every page this module creates derives from it."""

    def __init__(self, profile: QWebEngineProfile, parent: QObject | None = None) -> None:
        super().__init__(profile, parent)
        self.permissionRequested.connect(lambda permission: permission.deny())

    def javaScriptConsoleMessage(self, *_args: object) -> None:
        pass


class GuardedPage(_QuietPage):
    """Keeps top-level navigation on YouTube Music and Google sign-in and
    sends other web links to the system browser."""

    def __init__(self, profile: QWebEngineProfile, home_origin: str) -> None:
        super().__init__(profile)
        self.home_origin = home_origin
        self._expect_test_page = False

    def load_test_page(self) -> None:
        # setHtml arrives at acceptNavigationRequest as a data: URL.
        self._expect_test_page = True
        self.setHtml(TEST_PAGE_HTML, QUrl(f"{TEST_PAGE_ORIGIN}/"))

    def acceptNavigationRequest(
        self, url: QUrl, navigation_type: QWebEnginePage.NavigationType, is_main_frame: bool,
    ) -> bool:
        if not is_main_frame:
            return True
        if self._expect_test_page and url.scheme() == "data":
            self._expect_test_page = False
            return True
        # The allowance covers only the navigation load_test_page started.
        self._expect_test_page = False
        return self.route(url)

    def route(self, url: QUrl) -> bool:
        """True when the view may load `url` itself."""
        text = url.toString()
        if navigation_allowed(text, self.home_origin):
            return True
        if opens_externally(text):
            QDesktopServices.openUrl(url)
        return False

    def createWindow(self, _window_type: QWebEnginePage.WebWindowType) -> QWebEnginePage:
        return _PopupCatcher(self)


class _PopupCatcher(_QuietPage):
    """New windows (target=_blank, window.open) never become a second page.
    Their first navigation goes through the opener's policy: allowed URLs
    load in the main view, other web links open in the system browser."""

    def __init__(self, opener: GuardedPage) -> None:
        super().__init__(opener.profile(), opener)
        self._opener = opener

    def acceptNavigationRequest(self, url: QUrl, *_args: object) -> bool:
        if self._opener.route(url):
            self._opener.load(url)
        self.deleteLater()
        return False


class PageBridge(QObject):
    """The object the page sees as `channel.objects.amberfader`."""

    command = Signal(str)

    def __init__(self, accept: Callable[[], bool], deliver: Callable[[str], None]) -> None:
        super().__init__()
        self._accept = accept
        self._deliver = deliver

    @Slot(str)
    def post(self, message: str) -> None:
        if self._accept():
            self._deliver(message)


class BrowserWindow(QMainWindow):
    """Shows the page for sign-in and browsing. Closing it only hides it:
    playback continues until the player window quits Amberfader.

    The page always lays out at least MIN_LAYOUT_WIDTH wide:

    - A page that loads behind a hidden window would lay out 0 px wide, so
      the window shows off screen while it loads and hides again after.
      The page then keeps that size while hidden.
    - A narrower window zooms the page out. Your own zoom, for example
      Ctrl+wheel, applies up to that limit and returns in a wider window.
    """

    def __init__(self, page: GuardedPage, go_home: Callable[[], None]) -> None:
        super().__init__()
        self.setWindowTitle("Amberfader – YouTube Music")
        self.view = QWebEngineView(self)
        self.view.setPage(page)
        # Narrower, even the smallest zoom could not fit MIN_LAYOUT_WIDTH.
        self.view.setMinimumWidth(math.ceil(MIN_LAYOUT_WIDTH * MIN_ZOOM))
        self.setCentralWidget(self.view)

        toolbar = self.addToolBar("Navigation")
        toolbar.setMovable(False)
        for action in (
            QWebEnginePage.WebAction.Back,
            QWebEnginePage.WebAction.Forward,
            QWebEnginePage.WebAction.Reload,
        ):
            toolbar.addAction(page.action(action))
        toolbar.addAction("YouTube Music", go_home)
        # Always show where the page is, so a sign-in form's origin is visible.
        self._origin = QLabel()
        self._origin.setContentsMargins(8, 0, 8, 0)
        toolbar.addWidget(self._origin)
        page.urlChanged.connect(self._show_origin)

        self._chosen_zoom = page.zoomFactor()
        self._zoom = self._chosen_zoom
        page.zoomFactorChanged.connect(self._zoom_changed)
        page.loadStarted.connect(self._load_started)
        page.loadFinished.connect(self._load_finished)
        page.renderProcessTerminated.connect(self._renderer_exited)
        self.resize(1100, 800)

    def reveal(self) -> None:
        self._end_offscreen_layout()
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def conceal(self) -> None:
        if self.view.page().isLoading():
            self._start_offscreen_layout()
        else:
            self.hide()

    def _show_origin(self, url: QUrl) -> None:
        self._origin.setText(origin_of(url.toString()) or url.scheme() or "")

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.conceal()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit_zoom()

    # ---- layout size while hidden -----------------------------------------

    def _load_started(self) -> None:
        if not self.isVisible():
            self._start_offscreen_layout()

    def _load_finished(self, _ok: bool) -> None:
        # A newer load may still be running; it ends the layout instead.
        if self.view.page().isLoading():
            return
        # A new renderer starts at the default zoom.
        self._fit_zoom()
        self._end_offscreen_layout()

    def _renderer_exited(self, *_args: object) -> None:
        # No load finishes after this; the next load lays out again.
        self._end_offscreen_layout()

    def _start_offscreen_layout(self) -> None:
        if self._offscreen():
            return
        self.hide()
        # Shown for Qt and the page, never on screen.
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.show()

    def _end_offscreen_layout(self) -> None:
        if not self._offscreen():
            return
        self.hide()
        self.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, False)

    def _offscreen(self) -> bool:
        return self.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)

    # ---- zoom -------------------------------------------------------------

    def _fit_zoom(self) -> None:
        # A window that was never shown has no real width yet.
        if not self.isVisible():
            return
        fit = self.view.width() / MIN_LAYOUT_WIDTH
        self._zoom = max(MIN_ZOOM, min(self._chosen_zoom, fit))
        if not math.isclose(self.view.page().zoomFactor(), self._zoom, abs_tol=ZOOM_TOLERANCE):
            self.view.page().setZoomFactor(self._zoom)

    def _zoom_changed(self, zoom: float) -> None:
        # Fitting and loads announce the zoom already applied.
        if math.isclose(zoom, self._zoom, abs_tol=ZOOM_TOLERANCE):
            return
        # Only a window on screen takes your own zoom (Ctrl+wheel). Otherwise
        # this is a new page at its default zoom.
        if self.isVisible() and not self._offscreen():
            self._chosen_zoom = zoom
        self._fit_zoom()


class PageHost(QObject):
    """Glue between the guarded page and the router callbacks."""

    def __init__(
        self,
        profile: QWebEngineProfile,
        mode: PageMode,
        bundle: str,
        *,
        ad_filter: str,
        settings: AppSettings,
        on_message: Callable[[str], None],
        on_lost: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._mode = mode
        self._bundle = bundle
        self._ad_filter = ad_filter
        self._on_lost = on_lost
        self.page: GuardedPage | None = GuardedPage(profile, mode.origin)
        self._bridge = PageBridge(self.on_home_origin, on_message)
        self._channel = QWebChannel(self)
        self._channel.registerObject(HOST_OBJECT_NAME, self._bridge)
        self.page.setWebChannel(self._channel, WORLD)
        self.apply_settings(settings)

        self.page.urlChanged.connect(self._url_changed)
        self.page.renderProcessTerminated.connect(self._renderer_exited)
        self.window: BrowserWindow | None = BrowserWindow(self.page, self.load)

    def apply_settings(self, settings: AppSettings) -> None:
        """Replace the injected scripts. Takes effect at the next page load."""
        if self.page is None:
            return
        scripts = self.page.scripts()
        for name in (BRIDGE_SCRIPT_NAME, AD_FILTER_SCRIPT_NAME):
            for old in scripts.find(name):
                scripts.remove(old)

        bridge = QWebEngineScript()
        bridge.setName(BRIDGE_SCRIPT_NAME)
        bridge.setSourceCode(script_source(
            self._bundle, self._mode, continue_playing=settings.continue_playing,
        ))
        bridge.setWorldId(WORLD)
        # Same timing as a browser extension's run_at: document_idle.
        bridge.setInjectionPoint(QWebEngineScript.InjectionPoint.Deferred)
        bridge.setRunsOnSubFrames(False)
        scripts.insert(bridge)

        if settings.block_ads:
            ads = QWebEngineScript()
            ads.setName(AD_FILTER_SCRIPT_NAME)
            ads.setSourceCode(ad_filter_source(self._ad_filter, self._mode))
            # Before the page's own scripts, which parse the player data.
            ads.setWorldId(QWebEngineScript.ScriptWorldId.MainWorld)
            ads.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentCreation)
            ads.setRunsOnSubFrames(False)
            scripts.insert(ads)

    def on_home_origin(self) -> bool:
        return self.page is not None and origin_of(self.page.url().toString()) == self._mode.origin

    def load(self) -> None:
        if self.page is None:
            return
        if self._mode is PageMode.TEST_PAGE:
            self.page.load_test_page()
        else:
            self.page.load(QUrl(f"{MUSIC_ORIGIN}/"))

    def send_command(self, command: dict) -> bool:
        if not self.on_home_origin():
            return False
        self._bridge.command.emit(json.dumps(command))
        return True

    def set_visible(self, visible: bool) -> bool:
        if self.window is None:
            return False
        if visible:
            self.window.reveal()
        else:
            self.window.conceal()
        return True

    def shutdown(self) -> None:
        """Delete the view before the page, and both before the profile."""
        self.window = None
        self.page = None

    def _url_changed(self, url: QUrl) -> None:
        if origin_of(url.toString()) != self._mode.origin:
            self._on_lost("YouTube Music is showing another page, for example Google sign-in.")

    def _renderer_exited(self, *_args: object) -> None:
        self._on_lost("The YouTube Music page stopped. Reload it from Show YT.")
