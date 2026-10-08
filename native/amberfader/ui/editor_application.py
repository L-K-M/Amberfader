"""The standalone editor's document controller, after NSDocumentController.

- One window per face. Opening a face that is already open brings its window
  forward; an untouched untitled window is reused instead of adding another.
- Closing the last window keeps the app running on macOS, where the menu bar
  still offers New and Open and clicking the Dock icon shows the gallery.
  Elsewhere the editor quits with its last window.
- Finder hands over face folders (Open With, a drop on the Dock icon) as
  file-open events.
- Unsaved work is autosaved for crash recovery and reopens at the next launch.
- Faces open at quit reopen when macOS keeps windows ("Close windows when
  quitting an application" turned off in System Settings).
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QPoint, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QApplication, QMenu, QMenuBar, QMessageBox, QWidget

from ..face_autosave import AutosaveStore
from ..face_document import FaceDocument
from ..face_library import FaceError, FaceLibrary
from .editor_settings import EditorSettings
from .editor_widgets import MACOS
from .face_editor import APP_NAME, FaceEditorWindow, _choose_face_folder, show_about
from .face_gallery import FaceGallery, GallerySource

AUTOSAVE_DELAY_MS = 3000
CASCADE_OFFSET = QPoint(24, 24)
GLOBAL_PREFERENCES = Path.home() / "Library" / "Preferences" / ".GlobalPreferences.plist"
RECOVERED_MESSAGE = "Recovered unsaved changes from when the editor last quit unexpectedly."


def _system_keeps_windows() -> bool:
    """macOS: "Close windows when quitting an application" is turned off."""
    if not MACOS:
        return False
    value = QSettings(str(GLOBAL_PREFERENCES), QSettings.Format.NativeFormat).value(
        "NSQuitAlwaysKeepsWindows", False,
    )
    return value in (True, "true", "1", 1)


def _log(message: str) -> None:
    print(f"amberfader-face-editor: {message}", file=sys.stderr)


class FaceEditorApplication(QObject):
    def __init__(
        self,
        app: QApplication,
        *,
        library: FaceLibrary | None = None,
        settings: EditorSettings | None = None,
        autosave: AutosaveStore | None = None,
    ) -> None:
        super().__init__(app)
        self._app = app
        self._library = library or FaceLibrary()
        self._settings = settings or EditorSettings()
        self._autosave = autosave or AutosaveStore()
        self._windows: list[FaceEditorWindow] = []
        self._gallery: FaceGallery | None = None
        self._gallery_origin: FaceEditorWindow | None = None
        self._launch_gallery = False
        self._edited: set[FaceEditorWindow] = set()
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(AUTOSAVE_DELAY_MS)
        self._autosave_timer.timeout.connect(self.autosave_now)
        self._state = app.applicationState()
        app.applicationStateChanged.connect(self._state_changed)
        app.installEventFilter(self)
        app.aboutToQuit.connect(self._autosave.close)
        if MACOS:
            app.setQuitOnLastWindowClosed(False)
            self._menu_bar = self._default_menu_bar()
            self._dock_menu = QMenu()
            self._dock_menu.addAction("New Face…", self._new_face)
            self._dock_menu.addAction("Open Installed Face…", self._open_installed)
            self._dock_menu.setAsDockMenu()

    # ------------------------------------------------------------- startup
    def start(self, documents: list[FaceDocument]) -> None:
        """Open documents from the command line, else recover or restore."""
        recovered = self._recover()
        for document in documents:
            self.adopt_document(document, None)
            if document.path is not None:
                self.note_recent(document.path)
        if documents or recovered:
            return
        if _system_keeps_windows():
            for path in self._settings.session_faces():
                if path.is_dir():
                    self.open_face(path, None)
        if not self._windows:
            # Finder may still deliver a face to open; that closes this gallery.
            self._launch_gallery = True
            self.show_gallery(GallerySource.BUILT_IN, None)

    def _recover(self) -> int:
        faces, problems = self._autosave.recover()
        for problem in problems:
            _log(f"autosave could not be recovered ({problem.split(':', 1)[0]})")
        for face in faces:
            window = self._new_window(face.document, RECOVERED_MESSAGE)
            # Keep updating the same snapshot until the face is saved or closed.
            window.autosave_token = face.token
        return len(faces)

    def _default_menu_bar(self) -> QMenuBar:
        """The menu bar shown when no document window is active (macOS)."""
        bar = QMenuBar(None)
        file_menu = bar.addMenu("File")
        new = QAction("New Face…", bar)
        new.setShortcut(QKeySequence.StandardKey.New)
        new.triggered.connect(self._new_face)
        file_menu.addAction(new)
        open_action = QAction("Open…", bar)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(lambda: self.open_face_dialog(None))
        file_menu.addAction(open_action)
        installed = QAction("Open Installed Face…", bar)
        installed.setShortcut(QKeySequence("Ctrl+Shift+O"))
        installed.triggered.connect(self._open_installed)
        file_menu.addAction(installed)
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._fill_recent_menu()
        file_menu.addSeparator()
        close = QAction("Close", bar)
        close.setShortcut(QKeySequence.StandardKey.Close)
        close.triggered.connect(self._close_active)
        file_menu.addAction(close)
        window_menu = bar.addMenu("Window")
        minimize = QAction("Minimize", bar)
        minimize.setShortcut(QKeySequence("Ctrl+M"))
        minimize.triggered.connect(self._minimize_active)
        window_menu.addAction(minimize)
        window_menu.addSeparator()
        gallery = QAction("Face Gallery", bar)
        gallery.triggered.connect(self._new_face)
        window_menu.addAction(gallery)
        help_menu = bar.addMenu("Help")
        help_action = QAction(f"{APP_NAME} Help", bar)
        help_action.triggered.connect(self._open_help)
        help_menu.addAction(help_action)
        about = QAction(f"About {APP_NAME}", bar)
        about.setMenuRole(QAction.MenuRole.AboutRole)
        about.triggered.connect(lambda: show_about(None))
        help_menu.addAction(about)
        return bar

    @staticmethod
    def _open_help() -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices

        from .face_editor import HELP_URL

        QDesktopServices.openUrl(QUrl(HELP_URL))

    def _fill_recent_menu(self) -> None:
        menu = self._recent_menu
        menu.clear()
        recent = [path for path in self.recent_faces() if path.is_dir()]
        for path in recent:
            action = menu.addAction(path.name)
            action.triggered.connect(lambda _checked=False, path=path: self.open_face(path, None))
        if recent:
            menu.addSeparator()
        menu.addAction("Clear Menu", self.clear_recent).setEnabled(bool(recent))

    def _close_active(self) -> None:
        window = QApplication.activeWindow()
        if window is not None:
            window.close()

    def _minimize_active(self) -> None:
        window = QApplication.activeWindow()
        if window is not None:
            window.showMinimized()

    # ----------------------------------------------------------- windows
    def windows(self) -> list[FaceEditorWindow]:
        return [window for window in self._windows if window.isVisible()]

    def _new_window(self, document: FaceDocument, message: str = "") -> FaceEditorWindow:
        previous = self.windows()[-1] if self.windows() else None
        window = FaceEditorWindow(
            document=document, library=self._library, workspace=self, settings=self._settings,
        )
        window.documentStateChanged.connect(lambda window=window: self._edited_window(window))
        window.closed.connect(lambda window=window: self._window_closed(window))
        if previous is not None and not previous.isMinimized():
            window.move(previous.pos() + CASCADE_OFFSET)
        self._windows.append(window)
        window.show()
        window.raise_()
        window.activateWindow()
        if message:
            window.statusBar().showMessage(message, 15000)
        return window

    def _window_closed(self, window: FaceEditorWindow) -> None:
        if window in self._windows:
            self._windows.remove(window)
        self._edited.discard(window)
        self._autosave.remove(window.autosave_token)
        if self._gallery_origin is window:
            self._gallery_origin = None
        window.deleteLater()

    def _window_for(self, path: Path) -> FaceEditorWindow | None:
        try:
            resolved = path.resolve()
        except OSError:
            return None
        return next(
            (window for window in self.windows() if window.document.path == resolved), None,
        )

    def _replaceable(self, window: FaceEditorWindow | None) -> FaceEditorWindow | None:
        if window is not None and window in self._windows and window.is_replaceable:
            return window
        return None

    # ---------------------------------------------------------- workspace
    def show_gallery(self, source: GallerySource, window: FaceEditorWindow | None) -> None:
        if self._gallery is None:
            self._gallery = FaceGallery(self._library)
            self._gallery.createRequested.connect(self._create_from_template)
            self._gallery.editRequested.connect(
                lambda path: self._gallery_chose(self.open_face(path, self._gallery_origin)),
            )
            self._gallery.openOtherRequested.connect(lambda: self.open_face_dialog(None))
            self._gallery.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, not MACOS)
        else:
            self._gallery.reload()
        if window is not None:
            self._launch_gallery = False
        self._gallery_origin = window
        self._gallery.show_source(source)
        self._gallery.show()
        self._gallery.raise_()
        self._gallery.activateWindow()

    def _new_face(self) -> None:
        self.show_gallery(GallerySource.BUILT_IN, None)

    def _open_installed(self) -> None:
        self.show_gallery(GallerySource.INSTALLED, None)

    def _gallery_chose(self, opened: bool) -> None:
        if opened and self._gallery is not None:
            self._gallery.close()

    def _create_from_template(self, source: Path) -> None:
        try:
            document = FaceDocument.from_template(source)
        except (FaceError, OSError) as exc:
            self._alert(self._gallery, "A face could not be created from this template.", exc)
            return
        self._gallery_chose(self.adopt_document(document, self._gallery_origin))

    def open_face_dialog(self, window: FaceEditorWindow | None) -> None:
        parent: QWidget | None = window
        if parent is None and self._gallery is not None and self._gallery.isVisible():
            parent = self._gallery
        path = _choose_face_folder(parent, self._settings)
        if path is not None:
            self._gallery_chose(self.open_face(path, window))

    def open_face(self, directory: Path, window: FaceEditorWindow | None) -> bool:
        directory = Path(directory)
        if directory.name == "face.json":
            directory = directory.parent
        existing = self._window_for(directory)
        if existing is not None:
            existing._activate()
            return True
        target = self._replaceable(window)
        if target is not None:
            return target.open_face(directory)
        try:
            document = FaceDocument.open(directory)
        except (FaceError, OSError) as exc:
            self._alert(window, f"“{directory.name}” could not be opened.", exc)
            return False
        self._new_window(document)
        if document.path is not None:
            self.note_recent(document.path)
        return True

    def adopt_document(
        self, document: FaceDocument, window: FaceEditorWindow | None, message: str = "",
    ) -> bool:
        # A face folder is open in at most one window, e.g. after recovery.
        existing = self._window_for(document.path) if document.path is not None else None
        if existing is not None:
            existing._activate()
            return True
        target = self._replaceable(window)
        if target is not None:
            return target.adopt_document(document, message)
        self._new_window(document, message)
        return True

    def recent_faces(self) -> list[Path]:
        return self._settings.recent_faces()

    def clear_recent(self) -> None:
        self._settings.clear_recent()
        self._recent_changed()

    def note_recent(self, path: Path) -> None:
        self._settings.note_recent(path)
        self._recent_changed()

    def _recent_changed(self) -> None:
        if MACOS:
            self._fill_recent_menu()
        for window in self._windows:
            window.refresh_recent_menu()

    def library_changed(self, select: Path | None = None) -> None:
        if self._gallery is not None:
            self._gallery.reload(select)

    @staticmethod
    def _alert(parent: QWidget | None, text: str, error: Exception) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, text, parent=parent)
        box.setInformativeText(str(error))
        if parent is not None:
            box.setWindowModality(Qt.WindowModality.WindowModal)
        box.exec()
        box.deleteLater()

    # ----------------------------------------------------------- autosave
    def _edited_window(self, window: FaceEditorWindow) -> None:
        self._edited.add(window)
        # Not restarted per edit: a long drag or color pick still autosaves.
        if not self._autosave_timer.isActive():
            self._autosave_timer.start()

    def autosave_now(self) -> None:
        for window in list(self._edited):
            self._edited.discard(window)
            if window not in self._windows:
                continue
            document = window.document
            try:
                if document.needs_save:
                    self._autosave.write(window.autosave_token, document)
                else:
                    self._autosave.remove(window.autosave_token)
            except FaceError as exc:
                _log(f"autosave failed ({type(exc).__name__})")

    # ------------------------------------------------------ app lifecycle
    def _state_changed(self, state: Qt.ApplicationState) -> None:
        # macOS reports a Dock click as another activation while already active.
        reopened = (
            state == Qt.ApplicationState.ApplicationActive
            and self._state == Qt.ApplicationState.ApplicationActive
        )
        self._state = state
        if state != Qt.ApplicationState.ApplicationActive:
            # Leaving the app is a natural moment to protect unsaved work.
            if self._edited:
                self.autosave_now()
            return
        if reopened and MACOS and not self.windows() and not (
            self._gallery is not None and self._gallery.isVisible()
        ):
            self.show_gallery(GallerySource.BUILT_IN, None)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._app and event.type() == QEvent.Type.FileOpen:
            self._open_from_finder(Path(event.file()))
            return True
        if watched is self._app and event.type() == QEvent.Type.Quit:
            self._remember_session()
        return False

    def _open_from_finder(self, path: Path) -> None:
        launch_gallery = (
            self._launch_gallery and self._gallery is not None and self._gallery.isVisible()
        )
        if self.open_face(path, None) and launch_gallery:
            self._gallery.close()
        self._launch_gallery = False

    def _remember_session(self) -> None:
        paths = [window.document.path for window in self.windows() if window.document.path]
        self._settings.set_session_faces(paths)
        self._settings.sync()
