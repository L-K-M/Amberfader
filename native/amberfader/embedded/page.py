"""QtWebEngine side of the embedded prototype.

Owns the persistent profile (the Google sign-in lives here), the guarded
YouTube Music page, the injected adapter bundle, and the window that shows
the page for sign-in and browsing.

Isolation: the bundle and Qt's qwebchannel.js run in QtWebEngine's
application world, the equivalent of an extension content script. Page
scripts run in the main world and cannot reach the channel. Host-side, page
messages are accepted only while the top-level page is on the expected origin.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from enum import Enum
from importlib import resources
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (
    QWebEnginePage,
    QWebEngineProfile,
    QWebEngineScript,
    QWebEngineSettings,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QMainWindow

from .navigation import MUSIC_ORIGIN, navigation_allowed, opens_externally, origin_of

HOST_OBJECT_NAME = "amberfader"
PROFILE_NAME = "amberfader-embedded"
TEST_PAGE_ORIGIN = "https://amberfader.invalid"
TEST_PAGE_HTML = (
    "<!doctype html><meta charset='utf-8'><title>Amberfader test page</title>"
    "<p>Scripted test page for the embedded prototype. "
    "No YouTube Music session is involved.</p>"
)
WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld


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


def load_bundle() -> str:
    resource = resources.files("amberfader.embedded") / "web" / "adapter.js"
    try:
        return resource.read_text("utf-8")
    except FileNotFoundError as exc:
        raise BundleMissingError(
            "The embedded page bundle is missing. Build it with: npm run embedded:build"
        ) from exc


def _qwebchannel_source() -> str:
    source = QFile(":/qtwebchannel/qwebchannel.js")
    if not source.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError("Qt WebChannel's qwebchannel.js resource is unavailable")
    try:
        return bytes(source.readAll().data()).decode("utf-8")
    finally:
        source.close()


def script_source(bundle: str, mode: PageMode) -> str:
    # @match keeps QtWebEngine from injecting anywhere else; the bundle also
    # checks the origin and the top frame itself.
    header = f"// ==UserScript==\n// @match {mode.origin}/*\n// ==/UserScript==\n"
    config = json.dumps({"adapter": mode.value, "origin": mode.origin})
    return f"{header}{_qwebchannel_source()}\nvar __AMBERFADER_EMBEDDED__ = {config};\n{bundle}"


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


class GuardedPage(QWebEnginePage):
    """Keeps top-level navigation on YouTube Music and Google sign-in, sends
    other web links to the system browser, and denies every permission
    prompt (notifications, camera, location, ...)."""

    def __init__(self, profile: QWebEngineProfile, home_origin: str) -> None:
        super().__init__(profile)
        self.home_origin = home_origin
        self._expect_test_page = False
        self.permissionRequested.connect(lambda permission: permission.deny())

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

    def javaScriptConsoleMessage(self, *_args: object) -> None:
        # Page logs can contain track names and queries; keep them off stderr.
        pass


class _PopupCatcher(QWebEnginePage):
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
    playback continues until the player window quits Amberfader."""

    def __init__(self, page: GuardedPage, go_home: Callable[[], None]) -> None:
        super().__init__()
        self.setWindowTitle("Amberfader – YouTube Music")
        self.view = QWebEngineView(self)
        self.view.setPage(page)
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
        self.resize(1100, 800)

    def _show_origin(self, url: QUrl) -> None:
        self._origin.setText(origin_of(url.toString()) or url.scheme() or "")

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.hide()


class PageHost(QObject):
    """Glue between the guarded page and the router callbacks."""

    def __init__(
        self,
        profile: QWebEngineProfile,
        mode: PageMode,
        bundle: str,
        *,
        on_message: Callable[[str], None],
        on_lost: Callable[[str], None],
    ) -> None:
        super().__init__()
        self._mode = mode
        self._on_lost = on_lost
        self.page: GuardedPage | None = GuardedPage(profile, mode.origin)
        self._bridge = PageBridge(self.on_home_origin, on_message)
        self._channel = QWebChannel(self)
        self._channel.registerObject(HOST_OBJECT_NAME, self._bridge)
        self.page.setWebChannel(self._channel, WORLD)

        script = QWebEngineScript()
        script.setName("amberfader-page-bridge")
        script.setSourceCode(script_source(bundle, mode))
        script.setWorldId(WORLD)
        # Same timing as the extension's run_at: document_idle.
        script.setInjectionPoint(QWebEngineScript.InjectionPoint.Deferred)
        script.setRunsOnSubFrames(False)
        self.page.scripts().insert(script)

        self.page.urlChanged.connect(self._url_changed)
        self.page.renderProcessTerminated.connect(self._renderer_exited)
        self.window: BrowserWindow | None = BrowserWindow(self.page, self.load)

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
            self.window.showNormal()
            self.window.raise_()
            self.window.activateWindow()
        else:
            self.window.hide()
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
