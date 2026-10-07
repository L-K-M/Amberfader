"""Native visual editing of portable, data-only face packs.

    ┌─────────────────────────── toolbar ────────────────────────────┐
    │ [◧] [+ ▾]               [100% ▾] [#] [⬚]                  [◨] │
    ├─────────────┬────────────────────────────────┬─────────────────┤
    │ Elements    │             canvas             │   Inspector     │
    │ (sidebar)   │                                │ [Element|Face]  │
    ├─────────────┴────────────────────────────────┴─────────────────┤
    │ transient messages                        ⚠ validation problem │
    └────────────────────────────────────────────────────────────────┘

One window edits one document with its own undo history, selection and
zoom. A Workspace decides where new and opened faces go: the standalone app
opens a window per face, and inside the player the window replaces its own
document after asking to save.

Edit menu commands follow the focus like AppKit's responder chain: Undo
undoes typing in the focused field first, then document changes; Cut, Copy,
Paste and Select All act on the focused field; Delete removes the selected
element when the canvas or element list has focus.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import uuid4

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QDesktopServices,
    QGuiApplication,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QToolButton,
    QWidget,
)

from .. import desktop
from ..face_document import FaceDocument
from ..face_library import (
    BUILTIN_DIRECTORY,
    DEFAULT_FACE_ID,
    FaceError,
    FaceLibrary,
)
from . import face_elements
from .editor_settings import EditorSettings, ToolbarStyle
from .editor_widgets import MACOS, focused_line_edit, sample_cover, symbol_icon
from .element_sidebar import ElementSidebar
from .face_editor_canvas import FaceEditorCanvas
from .face_gallery import FaceGallery, GallerySource
from .face_inspector import Inspector, InspectorCommand, InspectorEdit, InspectorPane
from .face_surface import FaceArtwork, prepare_face, prepare_face_preview

if TYPE_CHECKING:
    from ..audion_import import AudionImportResult

APP_NAME = "Amberfader Face Editor"
HELP_URL = "https://github.com/L-K-M/Amberfader/blob/main/docs/face-editor.md"
STATUS_MESSAGE_MS = 6000
VALIDATION_DELAY_MS = 200
DEFAULT_WINDOW_SIZE = QSize(1180, 740)
MINIMUM_WINDOW_SIZE = QSize(720, 460)
SIDEBAR_WIDTH = 200
INSPECTOR_WIDTH = 290
PNG_FILTER = "PNG Images (*.png)"
ZIP_FILTER = "ZIP Archives (*.zip)"
ZOOM_PRESETS = (0.5, 1.0, 2.0, 4.0)
TOOLBAR_STYLES = {
    ToolbarStyle.ICON_ONLY: Qt.ToolButtonStyle.ToolButtonIconOnly,
    ToolbarStyle.ICON_AND_TEXT: Qt.ToolButtonStyle.ToolButtonTextUnderIcon,
    ToolbarStyle.TEXT_ONLY: Qt.ToolButtonStyle.ToolButtonTextOnly,
}
TOOLBAR_STYLE_LABELS = (
    (ToolbarStyle.ICON_AND_TEXT, "Icon and Text"),
    (ToolbarStyle.ICON_ONLY, "Icon Only"),
    (ToolbarStyle.TEXT_ONLY, "Text Only"),
)


class Workspace(Protocol):
    """Where faces open. The app opens windows; the player reuses one."""

    def windows(self) -> list[FaceEditorWindow]: ...
    def show_gallery(self, source: GallerySource, window: FaceEditorWindow | None) -> None: ...
    def open_face_dialog(self, window: FaceEditorWindow | None) -> None: ...
    def open_face(self, directory: Path, window: FaceEditorWindow | None) -> bool: ...
    def adopt_document(
        self, document: FaceDocument, window: FaceEditorWindow | None, message: str = "",
    ) -> bool: ...
    def recent_faces(self) -> list[Path]: ...
    def clear_recent(self) -> None: ...
    def note_recent(self, path: Path) -> None: ...
    def library_changed(self, select: Path | None = None) -> None: ...


def _choose_face_folder(parent: QWidget, settings: EditorSettings) -> Path | None:
    """An Open panel for face folders. face.json opens its folder."""
    folder = QFileDialog.getExistingDirectory(
        parent, "Open Face", str(settings.last_folder()),
    )
    if not folder:
        return None
    path = Path(folder)
    settings.set_last_folder(path.parent)
    return path


class _SingleWindowWorkspace:
    """Inside the player: one window whose face is replaced in place."""

    def __init__(self, window: FaceEditorWindow, library: FaceLibrary) -> None:
        self._window = window
        self._library = library
        self._gallery: FaceGallery | None = None

    def windows(self) -> list[FaceEditorWindow]:
        return [self._window]

    def show_gallery(self, source: GallerySource, window: FaceEditorWindow | None) -> None:
        if self._gallery is None:
            self._gallery = FaceGallery(self._library, self._window)
            self._gallery.createRequested.connect(
                lambda path: self._chosen(self._window.new_from_template(path)),
            )
            self._gallery.editRequested.connect(
                lambda path: self._chosen(self._window.open_face(path)),
            )
            self._gallery.openOtherRequested.connect(lambda: self.open_face_dialog(None))
        else:
            self._gallery.reload()
        self._gallery.show_source(source, self._window.document.path)
        self._gallery.show()
        self._gallery.raise_()
        self._gallery.activateWindow()

    def _chosen(self, opened: bool) -> None:
        if opened and self._gallery is not None:
            self._gallery.close()

    def open_face_dialog(self, window: FaceEditorWindow | None) -> None:
        path = _choose_face_folder(self._gallery or self._window, self._window.settings)
        if path is not None:
            self._chosen(self._window.open_face(path))

    def open_face(self, directory: Path, window: FaceEditorWindow | None) -> bool:
        return self._window.open_face(directory)

    def adopt_document(
        self, document: FaceDocument, window: FaceEditorWindow | None, message: str = "",
    ) -> bool:
        return self._window.adopt_document(document, message)

    def recent_faces(self) -> list[Path]:
        return []

    def clear_recent(self) -> None:
        pass

    def note_recent(self, path: Path) -> None:
        pass

    def library_changed(self, select: Path | None = None) -> None:
        if self._gallery is not None:
            self._gallery.reload(select)


# Schema errors for draft geometry, e.g. "Invalid controls.play.0: minimum constraint".
_SCHEMA_GEOMETRY = re.compile(r"Invalid (?:controls\.)?(\w+)\.\d: (?:minimum|maximum) constraint")


def _normalized_problem(problem: str) -> str:
    match = _SCHEMA_GEOMETRY.fullmatch(problem)
    return f"{match.group(1)} must fit inside the face" if match else problem


def _problem_element(problem: str, names) -> str | None:
    """The element a layout problem names first ("play overlaps next")."""
    first = _normalized_problem(problem).split(" ", 1)[0]
    return first if first in names else None


def _readable_problem(problem: str) -> str:
    """Replace manifest names with element labels for display."""
    words = _normalized_problem(problem).split(" ")
    return " ".join(face_elements.LABELS.get(word, word) for word in words)


class FaceEditorWindow(QMainWindow):
    """A document window; its canvas never sends commands to the music player."""

    documentStateChanged = Signal()
    closed = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        document: FaceDocument | None = None,
        library: FaceLibrary | None = None,
        workspace: Workspace | None = None,
        settings: EditorSettings | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("faceEditorWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setUnifiedTitleAndToolBarOnMac(True)
        self.setMinimumSize(MINIMUM_WINDOW_SIZE)
        self._settings = settings or EditorSettings()
        self._document = document or FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
        # A shared library (the player's) may predate faces added since.
        if library is None:
            library = FaceLibrary()
        else:
            library.refresh()
        self._library = library
        self._workspace: Workspace = workspace or _SingleWindowWorkspace(self, library)
        # Inside the player, the player owns About and Quit.
        self._standalone = workspace is not None
        self.autosave_token = uuid4().hex
        self._artwork: FaceArtwork | None = None
        self._artwork_key = None
        self._problem: str | None = None
        self._cover = sample_cover()
        self._watched_line: QLineEdit | None = None
        self._validation_timer = QTimer(self)
        self._validation_timer.setSingleShot(True)
        self._validation_timer.setInterval(VALIDATION_DELAY_MS)
        self._validation_timer.timeout.connect(self._validate)

        self._canvas = FaceEditorCanvas(self)
        self._canvas.set_document(self._document)
        self._create_actions()
        self._sidebar = ElementSidebar(self._add_menu, self)
        self._inspector = Inspector(list(self._document.manifest["palette"]), self)
        self._build_layout()
        self._build_toolbar()
        self._build_menus()
        self._build_status_bar()
        self._connect()
        self._restore_layout()
        self._set_document(self._document)

    # --------------------------------------------------------- properties
    @property
    def document(self) -> FaceDocument:
        return self._document

    @property
    def settings(self) -> EditorSettings:
        return self._settings

    @property
    def library(self) -> FaceLibrary:
        return self._library

    @property
    def is_replaceable(self) -> bool:
        """An untouched untitled copy, which opening another face may replace."""
        return self._document.path is None and not self._document.needs_save

    def display_name(self) -> str:
        return self._document.manifest["name"] or "Untitled Face"

    # ------------------------------------------------------------ actions
    def _action(
        self, text: str, slot: Callable, shortcut=None, *, symbol: str | None = None,
        fallback: str | None = None, checkable: bool = False, name: str = "",
    ) -> QAction:
        action = QAction(text, self)
        if name:
            action.setObjectName(name)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                action.setShortcuts([QKeySequence(item) for item in shortcut])
            else:
                action.setShortcut(QKeySequence(shortcut))
        if symbol is not None:
            action.setIcon(symbol_icon(symbol, fallback))
        action.setCheckable(checkable)
        if checkable:
            action.toggled.connect(slot)
        else:
            action.triggered.connect(lambda _checked=False: slot())
        self.addAction(action)
        return action

    def _create_actions(self) -> None:
        # File
        self._new_action = self._action(
            "New Face…", lambda: self._workspace.show_gallery(GallerySource.BUILT_IN, self),
            QKeySequence.StandardKey.New, name="newFace",
        )
        self._open_action = self._action(
            "Open…", lambda: self._workspace.open_face_dialog(self),
            QKeySequence.StandardKey.Open, name="openFace",
        )
        self._open_installed_action = self._action(
            "Open Installed Face…",
            lambda: self._workspace.show_gallery(GallerySource.INSTALLED, self),
            "Ctrl+Shift+O", name="openInstalledFace",
        )
        self._close_action = self._action(
            "Close", self.close, QKeySequence.StandardKey.Close, name="closeWindow",
        )
        self._save_action = self._action(
            "Save", self.save, QKeySequence.StandardKey.Save, name="save",
        )
        self._save_as_action = self._action(
            "Save As…", self.save_as, QKeySequence.StandardKey.SaveAs, name="saveAs",
        )
        self._revert_action = self._action("Revert to Saved", self.revert, name="revert")
        self._export_action = self._action(
            "Export Copy…", self.export, "Ctrl+Shift+E", name="exportCopy",
        )
        self._audion_import_action = self._action(
            "Import Audion Face…", self._import_audion, name="importAudionFace",
        )
        self._audion_archive_action = self._action(
            "Import Audion Collection…", self._import_audion_archive,
            name="importAudionCollection",
        )
        self._reveal_action = self._action(
            "Show in Finder" if MACOS else "Show in Folder", self._reveal, name="reveal",
        )
        # Edit
        self._undo_action = self._action(
            "Undo", self._undo, QKeySequence.StandardKey.Undo,
            symbol="arrow.uturn.backward", fallback="edit-undo", name="undo",
        )
        self._redo_action = self._action(
            "Redo", self._redo, QKeySequence.StandardKey.Redo,
            symbol="arrow.uturn.forward", fallback="edit-redo", name="redo",
        )
        self._cut_action = self._action("Cut", self._cut, QKeySequence.StandardKey.Cut)
        self._copy_action = self._action("Copy", self._copy, QKeySequence.StandardKey.Copy)
        self._paste_action = self._action("Paste", self._paste, QKeySequence.StandardKey.Paste)
        self._delete_action = self._action("Delete", self._delete, name="delete")
        self._select_all_action = self._action(
            "Select All", self._select_all, QKeySequence.StandardKey.SelectAll,
        )
        # View
        self._toggle_sidebar_action = self._action(
            "Hide Sidebar", self._toggle_sidebar, "Ctrl+Meta+S",
            symbol="sidebar.left", fallback="view-left-pane", name="toggleSidebar",
        )
        self._toggle_sidebar_action.setIconText("Sidebar")
        self._toggle_inspector_action = self._action(
            "Hide Inspector", self._toggle_inspector, "Ctrl+Alt+I",
            symbol="sidebar.right", fallback="view-right-pane", name="toggleInspector",
        )
        self._toggle_inspector_action.setIconText("Inspector")
        self._element_pane_action = self._action(
            "Element Inspector", lambda: self._show_inspector(InspectorPane.ELEMENT), "Ctrl+Alt+1",
        )
        self._face_pane_action = self._action(
            "Face Inspector", lambda: self._show_inspector(InspectorPane.FACE), "Ctrl+Alt+2",
        )
        self._zoom_in_action = self._action(
            "Zoom In", self._canvas.zoom_in, [QKeySequence.StandardKey.ZoomIn, "Ctrl+="],
            symbol="plus.magnifyingglass", fallback="zoom-in", name="zoomIn",
        )
        self._zoom_out_action = self._action(
            "Zoom Out", self._canvas.zoom_out, QKeySequence.StandardKey.ZoomOut,
            symbol="minus.magnifyingglass", fallback="zoom-out", name="zoomOut",
        )
        self._actual_action = self._action(
            "Actual Size", lambda: self._canvas.set_zoom(1), "Ctrl+0", name="actualSize",
        )
        self._fit_action = self._action(
            "Zoom to Fit", self._canvas.fit_face, "Ctrl+9", name="zoomToFit",
        )
        self._guides_action = self._action(
            "Guides", self._set_guides, "Ctrl+;", symbol="rectangle.dashed",
            checkable=True, name="guides",
        )
        self._guides_action.setToolTip("Show element outlines and selection handles")
        self._snap_action = self._action(
            "Snap to Grid", self._snap_changed, "Ctrl+'", symbol="square.grid.3x3",
            fallback="snap-to-grid", checkable=True, name="snap",
        )
        self._snap_action.setIconText("Snap")
        self._snap_action.setToolTip(
            "Snap moves and resizes to an 8 px grid. Hold Option to bypass."
            if MACOS else "Snap moves and resizes to an 8 px grid. Hold Alt to bypass."
        )
        self._toggle_toolbar_action = self._action(
            "Hide Toolbar", self._toggle_toolbar, "Ctrl+Alt+T", name="toggleToolbar",
        )
        # Element
        self._add_menu = QMenu("Add Element", self)
        self._add_menu.setObjectName("addElementMenu")
        self._add_menu.aboutToShow.connect(self._fill_add_menu)
        self._add_menu.setIcon(symbol_icon("plus", "list-add"))
        self._add_element_action = self._add_menu.menuAction()
        self._add_element_action.setIconText("Add")
        self._add_element_action.setToolTip("Add an element to the face")
        self._remove_element_action = self._action(
            "Remove Element", self._remove_element, name="removeElement",
        )
        self._import_artwork_action = self._action(
            "Import Artwork…", self._import_selected_artwork, name="importArtwork",
        )
        self._remove_artwork_action = self._action(
            "Remove Artwork", self._remove_selected_artwork, name="removeArtwork",
        )
        self._reset_rotation_action = self._action(
            "Reset Rotation", self._reset_rotation, name="resetRotation",
        )
        self._center_h_action = self._action(
            "Center Horizontally", lambda: self._center(horizontal=True), name="centerH",
        )
        self._center_v_action = self._action(
            "Center Vertically", lambda: self._center(horizontal=False), name="centerV",
        )
        # Face
        self._import_background_action = self._action(
            "Import Background…", self._import_background, name="importBackground",
        )
        self._import_mask_action = self._action(
            "Import Window Mask…", self._import_alpha_mask, name="importMask",
        )
        self._remove_mask_action = self._action(
            "Remove Window Mask", self._clear_alpha_mask, name="removeMask",
        )
        # Window and Help
        self._minimize_action = self._action(
            "Minimize", self.showMinimized, "Ctrl+M", name="minimize",
        )
        self._zoom_window_action = self._action("Zoom", self._zoom_window, name="zoomWindow")
        self._gallery_action = self._action(
            "Face Gallery", lambda: self._workspace.show_gallery(GallerySource.BUILT_IN, self),
            name="faceGallery",
        )
        self._front_action = self._action(
            "Bring All to Front", self._bring_all_to_front, name="bringAllToFront",
        )
        self._help_action = self._action(
            f"{APP_NAME} Help", lambda: QDesktopServices.openUrl(QUrl(HELP_URL)), name="help",
        )
        self._about_action = self._action(f"About {APP_NAME}", self._about, name="about")
        self._about_action.setMenuRole(QAction.MenuRole.AboutRole)
        self._quit_action = self._action(
            "Quit", QApplication.quit, QKeySequence.StandardKey.Quit, name="quit",
        )
        self._quit_action.setMenuRole(QAction.MenuRole.QuitRole)

    # ------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setObjectName("editorSplitter")
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setHandleWidth(1)
        self._splitter.addWidget(self._sidebar)
        self._splitter.addWidget(self._canvas)
        self._splitter.addWidget(self._inspector)
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._splitter.setStretchFactor(2, 0)
        self._sidebar.setMinimumWidth(160)
        self._inspector.setMinimumWidth(260)
        self._canvas.setMinimumWidth(240)
        self._splitter.setSizes([SIDEBAR_WIDTH, 700, INSPECTOR_WIDTH])
        self.setCentralWidget(self._splitter)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Toolbar", self)
        toolbar.setObjectName("editorToolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setIconSize(QSize(18, 18))
        toolbar.toggleViewAction().setVisible(False)
        toolbar.addAction(self._toggle_sidebar_action)
        toolbar.addAction(self._add_element_action)
        add_button = toolbar.widgetForAction(self._add_element_action)
        if isinstance(add_button, QToolButton):
            add_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            add_button.setObjectName("toolbarAddElement")
        toolbar.addWidget(self._spacer(toolbar))
        self._zoom_menu = QMenu(self)
        self._zoom_menu.addAction(self._zoom_in_action)
        self._zoom_menu.addAction(self._zoom_out_action)
        self._zoom_menu.addSeparator()
        self._zoom_menu.addAction(self._fit_action)
        self._zoom_menu.addAction(self._actual_action)
        self._zoom_menu.addSeparator()
        for scale in ZOOM_PRESETS:
            self._zoom_menu.addAction(
                f"{round(scale * 100)}%", lambda scale=scale: self._canvas.set_zoom(scale),
            )
        self._zoom_button_action = QAction("100%", self)
        self._zoom_button_action.setObjectName("zoomMenu")
        self._zoom_button_action.setMenu(self._zoom_menu)
        self._zoom_button_action.setToolTip("Zoom")
        toolbar.addAction(self._zoom_button_action)
        zoom_button = toolbar.widgetForAction(self._zoom_button_action)
        if isinstance(zoom_button, QToolButton):
            zoom_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            zoom_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            zoom_button.setObjectName("toolbarZoom")
            zoom_button.setMinimumWidth(64)
            zoom_button.setAccessibleName("Zoom")
        toolbar.addAction(self._snap_action)
        toolbar.addAction(self._guides_action)
        toolbar.addWidget(self._spacer(toolbar))
        toolbar.addAction(self._toggle_inspector_action)
        self.addToolBar(toolbar)
        self._toolbar = toolbar
        default = ToolbarStyle.ICON_ONLY if MACOS else ToolbarStyle.ICON_AND_TEXT
        self._apply_toolbar_style(self._settings.toolbar_style(default))

    @staticmethod
    def _spacer(parent: QWidget) -> QWidget:
        spacer = QWidget(parent)
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return spacer

    def _apply_toolbar_style(self, style: ToolbarStyle) -> None:
        self._toolbar_style = style
        self._toolbar.setToolButtonStyle(TOOLBAR_STYLES[style])
        zoom_button = self._toolbar.widgetForAction(self._zoom_button_action)
        if isinstance(zoom_button, QToolButton):
            zoom_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)

    def createPopupMenu(self) -> QMenu:
        """The toolbar's context menu, as for a native toolbar."""
        menu = QMenu(self)
        group = QActionGroup(menu)
        for style, label in TOOLBAR_STYLE_LABELS:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(style is self._toolbar_style)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, style=style: self._choose_toolbar_style(
                style,
            ))
        menu.addSeparator()
        menu.addAction(self._toggle_toolbar_action)
        return menu

    def _choose_toolbar_style(self, style: ToolbarStyle) -> None:
        self._settings.set_toolbar_style(style)
        for window in self._workspace.windows():
            window._apply_toolbar_style(style)

    def _build_menus(self) -> None:
        menu_bar = self.menuBar()
        menu_bar.setNativeMenuBar(True)
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction(self._new_action)
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._open_installed_action)
        self._recent_menu = file_menu.addMenu("Open Recent")
        self._recent_menu.setObjectName("openRecentMenu")
        self.refresh_recent_menu()
        file_menu.addSeparator()
        file_menu.addAction(self._close_action)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._save_as_action)
        file_menu.addAction(self._revert_action)
        file_menu.addSeparator()
        file_menu.addAction(self._audion_import_action)
        file_menu.addAction(self._audion_archive_action)
        file_menu.addAction(self._export_action)
        file_menu.addSeparator()
        file_menu.addAction(self._reveal_action)
        if self._standalone and not MACOS:
            # macOS keeps Quit in the application menu.
            file_menu.addSeparator()
            file_menu.addAction(self._quit_action)

        edit_menu = menu_bar.addMenu("&Edit")
        edit_menu.aboutToShow.connect(self._update_edit_actions)
        for action in (self._undo_action, self._redo_action):
            edit_menu.addAction(action)
        edit_menu.addSeparator()
        for action in (
            self._cut_action, self._copy_action, self._paste_action, self._delete_action,
            self._select_all_action,
        ):
            edit_menu.addAction(action)

        view_menu = menu_bar.addMenu("&View")
        view_menu.addAction(self._toggle_sidebar_action)
        view_menu.addAction(self._toggle_inspector_action)
        view_menu.addSeparator()
        view_menu.addAction(self._element_pane_action)
        view_menu.addAction(self._face_pane_action)
        view_menu.addSeparator()
        for action in (
            self._zoom_in_action, self._zoom_out_action, self._actual_action, self._fit_action,
        ):
            view_menu.addAction(action)
        view_menu.addSeparator()
        view_menu.addAction(self._guides_action)
        view_menu.addAction(self._snap_action)
        view_menu.addSeparator()
        view_menu.addAction(self._toggle_toolbar_action)

        element_menu = menu_bar.addMenu("E&lement")
        element_menu.addMenu(self._add_menu)
        element_menu.addAction(self._remove_element_action)
        element_menu.addSeparator()
        element_menu.addAction(self._import_artwork_action)
        element_menu.addAction(self._remove_artwork_action)
        element_menu.addSeparator()
        element_menu.addAction(self._reset_rotation_action)
        element_menu.addAction(self._center_h_action)
        element_menu.addAction(self._center_v_action)

        face_menu = menu_bar.addMenu("F&ace")
        face_menu.addAction(self._import_background_action)
        face_menu.addAction(self._import_mask_action)
        face_menu.addAction(self._remove_mask_action)

        self._window_menu = menu_bar.addMenu("&Window")
        self._window_menu.aboutToShow.connect(self._fill_window_menu)
        self._fill_window_menu()

        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction(self._help_action)
        if self._standalone:
            # Qt moves this into the application menu on macOS.
            help_menu.addAction(self._about_action)

    def _build_status_bar(self) -> None:
        status = self.statusBar()
        status.setSizeGripEnabled(False)
        self._issue = QToolButton(status)
        self._issue.setObjectName("validationIssue")
        self._issue.setAutoRaise(True)
        self._issue.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._issue.setIcon(symbol_icon("exclamationmark.triangle.fill", "dialog-warning"))
        self._issue.setIconSize(QSize(14, 14))
        self._issue.clicked.connect(self._show_issue)
        self._issue.hide()
        status.addPermanentWidget(self._issue)

    def _connect(self) -> None:
        self._canvas.selectionChanged.connect(self._select_canvas)
        self._canvas.documentChanged.connect(self._changed)
        self._canvas.zoomChanged.connect(self._zoom_changed)
        self._canvas.imageDropped.connect(self._drop_image)
        self._canvas.contextMenuRequested.connect(self._canvas_menu)
        self._canvas.removeRequested.connect(self._remove_element)
        self._sidebar.selected.connect(self._select_sidebar)
        self._sidebar.removeRequested.connect(self._remove_element)
        self._sidebar.contextMenuRequested.connect(
            lambda _name, position: self._element_menu().exec(position),
        )
        self._inspector.element.edited.connect(self._apply_edit)
        self._inspector.face.edited.connect(self._apply_edit)
        self._inspector.element.command.connect(self._inspector_command)
        self._inspector.face.command.connect(self._inspector_command)
        app = QApplication.instance()
        app.focusChanged.connect(self._focus_changed)
        QGuiApplication.clipboard().dataChanged.connect(self._update_edit_actions)

    def _restore_layout(self) -> None:
        geometry = self._settings.window_geometry()
        if geometry is None or not self.restoreGeometry(geometry):
            self.resize(DEFAULT_WINDOW_SIZE)
        self._fit_to_screen()
        self._set_panel(self._sidebar, self._settings.panel_visible("sidebar"))
        self._set_panel(self._inspector, self._settings.panel_visible("inspector"))
        self._guides_action.setChecked(True)

    def _fit_to_screen(self) -> None:
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available: QRect = screen.availableGeometry()
        width = min(self.width(), available.width())
        height = min(self.height(), available.height())
        if (width, height) != (self.width(), self.height()):
            self.resize(width, height)

    # ----------------------------------------------------------- document
    def _set_document(self, document: FaceDocument) -> None:
        self._document = document
        self._canvas.set_document(document)
        self._artwork_key = None
        self._artwork = None
        self._changed()
        self._canvas.fit_face()

    def _changed(self) -> None:
        """Bring every view up to date with the document after any edit."""
        data = self._document.manifest
        names = [*data["controls"], face_elements.DRAG]
        if self._canvas.selected not in names:
            self._canvas.select("play" if "play" in names else names[0])
        selected = self._canvas.selected
        self._sidebar.set_elements(names, selected)
        can_add = any(name not in data["controls"] for name in face_elements.ADDABLE)
        self._sidebar.set_can_add(can_add)
        preview_error = None
        try:
            face = self._document.preview()
            key = (
                face.background,
                face.alpha_mask,
                tuple((name, tuple(images.items())) for name, images in face.buttons.items()),
                face.time_digits,
            )
            if key != self._artwork_key or self._artwork is None:
                self._artwork = prepare_face_preview(face)
                self._artwork_key = key
            self._canvas.set_preview(face, self._artwork, self._cover)
        except (FaceError, OSError, ValueError) as exc:
            preview_error = str(exc)
        if preview_error is not None:
            self._set_problem(preview_error)
        elif self._canvas.gesture_active:
            # Validation decodes every image; during a drag, wait for a pause.
            self._validation_timer.start()
        else:
            self._validate()
        self._inspector.element.sync(data, selected, self._artwork)
        self._inspector.face.sync(data, self._artwork)
        self._update_document_actions()
        self._update_title()
        self.documentStateChanged.emit()

    def _validate(self) -> None:
        problems = list(self._document.validate())
        if not problems:
            try:
                prepare_face(self._document.preview(validate_layout=True))
            except (FaceError, OSError, ValueError) as exc:
                problems.append(str(exc))
        self._set_problem(problems[0] if problems else None)

    def _set_problem(self, problem: str | None) -> None:
        self._problem = problem
        if problem is None:
            self._issue.hide()
            return
        text = _readable_problem(problem)
        self._issue.setText(f"Can't save: {text}")
        self._issue.setToolTip(f"{text}\nClick to select the element.")
        self._issue.show()

    @property
    def validation_problem(self) -> str | None:
        return self._problem

    def _show_issue(self) -> None:
        if self._problem is None:
            return
        data = self._document.manifest
        name = _problem_element(self._problem, [*data["controls"], face_elements.DRAG])
        if name is not None:
            self._canvas.select(name)
            self._show_inspector(InspectorPane.ELEMENT)

    def _update_title(self) -> None:
        name = self.display_name()
        if MACOS:
            self.setWindowTitle(f"{name}[*]")
        else:
            self.setWindowTitle(f"{name}[*] — {APP_NAME}")
        self.setWindowModified(self._document.needs_save)
        path = self._document.path
        self.setWindowFilePath(str(path) if path is not None else "")

    def _update_document_actions(self) -> None:
        document = self._document
        data = document.manifest
        selected = self._canvas.selected
        self._revert_action.setEnabled(document.path is not None and document.dirty)
        self._reveal_action.setEnabled(document.path is not None)
        is_drag = selected == face_elements.DRAG
        self._remove_element_action.setEnabled(not is_drag)
        self._add_element_action.setEnabled(
            any(name not in data["controls"] for name in face_elements.ADDABLE),
        )
        artwork = face_elements.can_hold_artwork(selected, data.get("sliderStyle", "classic"))
        sprites = data.get("buttons", {}).get(selected, {})
        self._import_artwork_action.setEnabled(artwork)
        self._remove_artwork_action.setEnabled(artwork and bool(sprites))
        self._reset_rotation_action.setEnabled(
            bool(data.get("controlRotations", {}).get(selected, 0)),
        )
        self._remove_mask_action.setEnabled("alphaMask" in data)
        self._update_edit_actions()

    # ---------------------------------------------------- responder chain
    def _focus_widget(self) -> QWidget | None:
        focus = QApplication.focusWidget()
        return focus if focus is not None and self.isAncestorOf(focus) else None

    def _focus_changed(self, _old: QWidget | None, new: QWidget | None) -> None:
        line = focused_line_edit(new) if new is not None and self.isAncestorOf(new) else None
        if line is not self._watched_line:
            if self._watched_line is not None:
                try:
                    self._watched_line.textChanged.disconnect(self._update_edit_actions)
                    self._watched_line.selectionChanged.disconnect(self._update_edit_actions)
                except (RuntimeError, TypeError):
                    pass
            self._watched_line = line
            if line is not None:
                line.textChanged.connect(self._update_edit_actions)
                line.selectionChanged.connect(self._update_edit_actions)
        self._update_edit_actions()

    def _text_target(self) -> QLineEdit | QPlainTextEdit | None:
        focus = self._focus_widget()
        line = focused_line_edit(focus)
        if line is not None:
            return line
        return focus if isinstance(focus, QPlainTextEdit) else None

    def _element_focus(self) -> bool:
        focus = self._focus_widget()
        return focus is not None and (
            focus is self._canvas or self._canvas.isAncestorOf(focus)
            or self._sidebar.isAncestorOf(focus)
        )

    def _update_edit_actions(self) -> None:
        target = self._text_target()
        document = self._document
        if isinstance(target, QLineEdit) and target.isUndoAvailable():
            undo, undo_enabled = "Undo Typing", True
        else:
            label = document.undo_label
            undo, undo_enabled = (f"Undo {label}" if label else "Undo"), label is not None
        if isinstance(target, QLineEdit) and target.isRedoAvailable():
            redo, redo_enabled = "Redo Typing", True
        else:
            label = document.redo_label
            redo, redo_enabled = (f"Redo {label}" if label else "Redo"), label is not None
        self._undo_action.setText(undo)
        self._undo_action.setEnabled(undo_enabled)
        self._redo_action.setText(redo)
        self._redo_action.setEnabled(redo_enabled)
        editable = isinstance(target, QLineEdit) and not target.isReadOnly()
        has_selection = (
            target.hasSelectedText() if isinstance(target, QLineEdit)
            else target is not None and target.textCursor().hasSelection()
        )
        clipboard = QGuiApplication.clipboard()
        self._cut_action.setEnabled(editable and has_selection)
        self._copy_action.setEnabled(has_selection)
        self._paste_action.setEnabled(editable and bool(clipboard.text()))
        self._select_all_action.setEnabled(target is not None)
        self._delete_action.setEnabled(
            (editable and has_selection)
            or (self._element_focus() and self._canvas.selected != face_elements.DRAG)
        )

    def _undo(self) -> None:
        target = self._text_target()
        if isinstance(target, QLineEdit) and target.isUndoAvailable():
            target.undo()
            self._update_edit_actions()
            return
        self._canvas.finish_gesture()
        self._document.undo()
        self._changed()

    def _redo(self) -> None:
        target = self._text_target()
        if isinstance(target, QLineEdit) and target.isRedoAvailable():
            target.redo()
            self._update_edit_actions()
            return
        self._canvas.finish_gesture()
        self._document.redo()
        self._changed()

    def _cut(self) -> None:
        target = self._text_target()
        if isinstance(target, QLineEdit):
            target.cut()

    def _copy(self) -> None:
        target = self._text_target()
        if target is not None:
            target.copy()

    def _paste(self) -> None:
        target = self._text_target()
        if isinstance(target, QLineEdit):
            target.paste()

    def _select_all(self) -> None:
        target = self._text_target()
        if target is not None:
            target.selectAll()

    def _delete(self) -> None:
        target = self._text_target()
        if isinstance(target, QLineEdit):
            target.del_()
            return
        if self._element_focus():
            self._remove_element()

    # --------------------------------------------------------- selection
    def _select_canvas(self, name: str) -> None:
        self._sidebar.select(name)
        self._inspector.element.sync(self._document.manifest, name, self._artwork)
        self._update_document_actions()

    def _select_sidebar(self, name: str) -> None:
        self._canvas.select(name)

    # ------------------------------------------------------------- edits
    def _apply_edit(self, edit: InspectorEdit) -> None:
        try:
            self._document.set_value(
                edit.path, edit.value, label=edit.label, coalesce=edit.coalesce,
            )
        except FaceError as exc:
            self._show_error("The change could not be made.", exc)
        self._changed()

    def _inspector_command(self, command: InspectorCommand, state: str) -> None:
        if command is InspectorCommand.IMPORT_ARTWORK:
            self._import_sprite(state)
        elif command is InspectorCommand.REMOVE_ARTWORK:
            self._remove_artwork(state)
        elif command is InspectorCommand.IMPORT_BACKGROUND:
            self._import_background()
        elif command is InspectorCommand.IMPORT_MASK:
            self._import_alpha_mask()
        elif command is InspectorCommand.REMOVE_MASK:
            self._clear_alpha_mask()

    def _fill_add_menu(self) -> None:
        menu = self._add_menu
        menu.clear()
        present = set(self._document.manifest["controls"])
        for title, group in face_elements.GROUPS:
            missing = [name for name in group if name != face_elements.DRAG and name not in present]
            if not missing:
                continue
            menu.addSection(title)
            for name in missing:
                action = menu.addAction(
                    symbol_icon(face_elements.SYMBOLS[name]), face_elements.LABELS[name],
                )
                action.triggered.connect(lambda _checked=False, name=name: self.add_element(name))
        if menu.isEmpty():
            placeholder = menu.addAction("Every element is on the face")
            placeholder.setEnabled(False)

    def add_element(self, name: str) -> None:
        """Place a new element in the middle of the face, selected."""
        if name not in face_elements.ADDABLE or name in self._document.manifest["controls"]:
            return
        self._flush_inspector()
        self._canvas.finish_gesture()
        width, height = self._document.manifest["size"]
        control_width, control_height = face_elements.DEFAULT_SIZES.get(
            name, face_elements.DEFAULT_READOUT_SIZE,
        )
        control_width, control_height = min(control_width, width), min(control_height, height)
        self._document.set_rect(name, [
            (width - control_width) // 2, (height - control_height) // 2,
            control_width, control_height,
        ], label=f"Add {face_elements.LABELS[name]}")
        self._canvas.select(name)
        self._changed()

    def _remove_element(self) -> None:
        name = self._canvas.selected
        if name == face_elements.DRAG:
            return
        self._flush_inspector()
        self._canvas.finish_gesture()
        self._document.set_value(
            ("controls", name), None, label=f"Remove {face_elements.LABELS[name]}",
        )
        self._changed()

    def _reset_rotation(self) -> None:
        name = self._canvas.selected
        if self._document.manifest.get("controlRotations", {}).get(name):
            self._document.set_value(("controlRotations", name), None, label="Reset Rotation")
            self._changed()

    def _center(self, *, horizontal: bool) -> None:
        name = self._canvas.selected
        data = self._document.manifest
        x, y, width, height = data["drag"] if name == face_elements.DRAG else data["controls"][name]
        face_width, face_height = data["size"]
        if horizontal:
            x = (face_width - width) // 2
        else:
            y = (face_height - height) // 2
        self._canvas.finish_gesture()
        self._document.set_rect(name, [x, y, width, height], label="Center")
        self._changed()

    def _element_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(self._import_artwork_action)
        menu.addAction(self._remove_artwork_action)
        menu.addSeparator()
        menu.addAction(self._reset_rotation_action)
        menu.addAction(self._center_h_action)
        menu.addAction(self._center_v_action)
        menu.addSeparator()
        menu.addAction(self._remove_element_action)
        return menu

    def _canvas_menu(self, name: str, position) -> None:
        if name:
            menu = self._element_menu()
        else:
            menu = QMenu(self)
            menu.addMenu(self._add_menu)
            menu.addAction(self._import_background_action)
            menu.addSeparator()
            menu.addAction(self._fit_action)
            menu.addAction(self._actual_action)
            menu.addSeparator()
            menu.addAction(self._guides_action)
            menu.addAction(self._snap_action)
        menu.exec(position)

    # -------------------------------------------------------------- view
    def _set_panel(self, panel: QWidget, visible: bool) -> None:
        panel.setVisible(visible)
        if panel is self._sidebar:
            self._toggle_sidebar_action.setText("Hide Sidebar" if visible else "Show Sidebar")
            self._toggle_sidebar_action.setIconText("Sidebar")
        else:
            self._toggle_inspector_action.setText(
                "Hide Inspector" if visible else "Show Inspector",
            )
            self._toggle_inspector_action.setIconText("Inspector")

    def _toggle_sidebar(self) -> None:
        visible = not self._sidebar.isVisible()
        self._set_panel(self._sidebar, visible)
        self._settings.set_panel_visible("sidebar", visible)

    def _toggle_inspector(self) -> None:
        visible = not self._inspector.isVisible()
        self._set_panel(self._inspector, visible)
        self._settings.set_panel_visible("inspector", visible)

    def _show_inspector(self, pane: InspectorPane) -> None:
        if not self._inspector.isVisible():
            self._toggle_inspector()
        self._inspector.show_pane(pane)

    def _toggle_toolbar(self) -> None:
        visible = not self._toolbar.isVisible()
        self._toolbar.setVisible(visible)
        self._toggle_toolbar_action.setText("Hide Toolbar" if visible else "Show Toolbar")

    def _set_guides(self, visible: bool) -> None:
        self._canvas.set_guides(visible)
        self._guides_action.setText("Guides")

    def _snap_changed(self, enabled: bool) -> None:
        self._canvas.snap = enabled
        self._canvas.viewport().update()

    def _zoom_changed(self, scale: float) -> None:
        self._zoom_button_action.setText(f"{round(scale * 100)}%")

    def _zoom_window(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _bring_all_to_front(self) -> None:
        for window in self._workspace.windows():
            if window.isVisible() and not window.isMinimized():
                window.raise_()
        self.raise_()
        self.activateWindow()

    def _fill_window_menu(self) -> None:
        menu = self._window_menu
        menu.clear()
        menu.addAction(self._minimize_action)
        menu.addAction(self._zoom_window_action)
        menu.addSeparator()
        menu.addAction(self._gallery_action)
        menu.addSeparator()
        menu.addAction(self._front_action)
        windows = [window for window in self._workspace.windows() if window.isVisible()]
        if windows:
            menu.addSeparator()
        for window in windows:
            action = menu.addAction(window.display_name())
            action.setCheckable(True)
            action.setChecked(window is self)
            action.triggered.connect(lambda _checked=False, window=window: window._activate())

    def _activate(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def refresh_recent_menu(self) -> None:
        """Rebuild Open Recent; the workspace calls this when the list changes."""
        menu = self._recent_menu
        menu.clear()
        recent = [path for path in self._workspace.recent_faces() if path.is_dir()]
        for path in recent:
            action = menu.addAction(path.name)
            action.setToolTip(str(path))
            action.triggered.connect(
                lambda _checked=False, path=path: self._workspace.open_face(path, self),
            )
        if recent:
            menu.addSeparator()
        clear = menu.addAction("Clear Menu", self._workspace.clear_recent)
        clear.setEnabled(bool(recent))

    # ------------------------------------------------------------ imports
    def _choose_png(self, caption: str) -> Path | None:
        path, _ = QFileDialog.getOpenFileName(
            self, caption, str(self._settings.last_folder()), PNG_FILTER,
        )
        if not path:
            return None
        self._settings.set_last_folder(Path(path).parent)
        return Path(path)

    def _import_background(self) -> None:
        path = self._choose_png("Import Background")
        if path is not None:
            self._apply_import(path)

    def _import_alpha_mask(self) -> None:
        path = self._choose_png("Import Window Mask")
        if path is None:
            return
        try:
            self._document.import_alpha_mask(path)
        except (FaceError, OSError) as exc:
            self._show_error("The window mask could not be imported.", exc)
            return
        self._changed()

    def _clear_alpha_mask(self) -> None:
        if "alphaMask" in self._document.manifest:
            self._document.import_alpha_mask(None)
            self._changed()

    def _import_selected_artwork(self) -> None:
        self._show_inspector(InspectorPane.ELEMENT)
        self._import_sprite(self._inspector.element.artwork_state)

    def _remove_selected_artwork(self) -> None:
        self._remove_artwork(self._inspector.element.artwork_state)

    def _import_sprite(self, state: str) -> None:
        name = self._canvas.selected
        if not face_elements.can_hold_artwork(
            name, self._document.manifest.get("sliderStyle", "classic"),
        ):
            return
        path = self._choose_png(f"Import {face_elements.LABELS[name]} Artwork")
        if path is not None:
            self._apply_import(path, name, state)

    def _remove_artwork(self, state: str) -> None:
        name = self._canvas.selected
        if state in self._document.manifest.get("buttons", {}).get(name, {}):
            self._document.remove_button_image(name, state)
            self._changed()

    def _drop_image(self, filename: str, target: str) -> None:
        self._apply_import(Path(filename), target or None)

    def _apply_import(self, path: Path, control: str | None = None, state: str = "normal") -> None:
        try:
            if control is None:
                self._document.import_background(
                    path, adopt_size=self._inspector.face.adopt_background_size,
                )
            else:
                self._canvas.select(control)
                self._document.import_button(control, state, path)
        except (FaceError, OSError) as exc:
            self._show_error(f"“{path.name}” could not be imported.", exc)
            return
        self._changed()

    # ----------------------------------------------------- alerts, prompts
    def _show_error(self, title: str, error: Exception | str) -> None:
        box = QMessageBox(QMessageBox.Icon.Warning, APP_NAME, title, parent=self)
        box.setInformativeText(str(error))
        box.setWindowModality(Qt.WindowModality.WindowModal)
        box.exec()
        box.deleteLater()

    def _flush_inspector(self) -> None:
        # Shortcut saves and window closes need text that has not lost focus yet.
        self._inspector.commit_pending()
        self._changed()

    def _confirm_discard(self) -> bool:
        # Flush before finishing: its refresh must not erase pending inspector text.
        # Save and Cancel preserve the current visible edit, including a drag.
        self._flush_inspector()
        self._canvas.finish_gesture()
        if not self._document.needs_save:
            return True
        choice = QMessageBox.warning(
            self,
            "Save Changes",
            f"Do you want to save the changes you made to “{self.display_name()}”?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if choice == QMessageBox.StandardButton.Save else True

    # ------------------------------------------- replacing this document
    def adopt_document(self, document: FaceDocument, message: str = "") -> bool:
        """Show another document here, after saving or discarding this one."""
        if not self._confirm_discard():
            return False
        self._set_document(document)
        if message:
            self.statusBar().showMessage(message, STATUS_MESSAGE_MS * 2)
        return True

    def new_from_template(self, directory: Path) -> bool:
        """Start an independent copy without modifying its original pack."""
        try:
            document = FaceDocument.from_template(Path(directory))
        except (FaceError, OSError) as exc:
            self._show_error("A face could not be created from this template.", exc)
            return False
        return self.adopt_document(document)

    def open_face(self, directory: Path) -> bool:
        """Open a pack safely, preserving the current document on any failure."""
        directory = Path(directory)
        if directory.name == "face.json":
            directory = directory.parent
        try:
            document = FaceDocument.open(directory)
        except (FaceError, OSError) as exc:
            self._show_error(f"“{directory.name}” could not be opened.", exc)
            return False
        if not self.adopt_document(document):
            return False
        if document.path is not None:
            self._workspace.note_recent(document.path)
        return True

    def import_audion_result(self, result: AudionImportResult) -> bool:
        """Apply a prepared conversion only after preserving the current working face."""
        try:
            prepare_face(result.document.preview(validate_layout=True))
        except (FaceError, OSError, ValueError) as exc:
            self._show_error("The Audion face could not be imported.", exc)
            return False
        return self.adopt_document(
            result.document,
            "Imported an editable copy. Save it to a new folder before installing it.",
        )

    def _import_audion(self) -> None:
        from .audion_import_dialog import AudionImportDialog

        dialog = AudionImportDialog(self)
        try:
            if dialog.exec() == dialog.DialogCode.Accepted and dialog.import_result is not None:
                result = dialog.import_result
                try:
                    prepare_face(result.document.preview(validate_layout=True))
                except (FaceError, OSError, ValueError) as exc:
                    self._show_error("The Audion face could not be imported.", exc)
                    return
                self._workspace.adopt_document(
                    result.document, self,
                    "Imported an editable copy. Save it to a new folder before installing it.",
                )
        finally:
            dialog.deleteLater()

    def _import_audion_archive(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Audion Collection", str(self._settings.last_folder()), ZIP_FILTER,
        )
        if path:
            self._settings.set_last_folder(Path(path).parent)
            self.import_audion_archive(Path(path))

    def import_audion_archive(self, path: Path) -> bool:
        """Install every face in the ZIP and list them in the gallery.

        The open document is unaffected; installed faces open from the gallery.
        """
        from .audion_archive_import import import_audion_archive

        try:
            batch = import_audion_archive(path, self._library, self)
        except FaceError as exc:
            self._show_error("The Audion collection could not be imported.", exc)
            return False
        first = None
        if batch.installed:
            first_id = batch.installed[0].face_id
            first = next((info.source for info in self._library.faces if info.id == first_id), None)
        self._workspace.library_changed(first)
        text, details = batch.summary()
        message = QMessageBox(QMessageBox.Icon.Information, APP_NAME, text,
                              QMessageBox.StandardButton.Ok, self)
        message.setDetailedText(details)
        message.setWindowModality(Qt.WindowModality.WindowModal)
        message.exec()
        message.deleteLater()
        if batch.installed:
            self._workspace.show_gallery(GallerySource.INSTALLED, self)
            self._workspace.library_changed(first)
        return True

    # -------------------------------------------------------------- saving
    def save(self) -> bool:
        self._flush_inspector()
        self._canvas.finish_gesture()
        if self._document.path is None:
            return self.save_as()
        return self._save_to(self._document.path)

    def _destination_folder(self, caption: str) -> Path | None:
        """A Save panel naming a new folder for the face."""
        if self._document.path is not None:
            start = self._document.path.parent
        else:
            start = self._settings.last_folder()
        suggested = start / self.display_name().replace("/", "-")
        chosen, _ = QFileDialog.getSaveFileName(self, caption, str(suggested))
        if not chosen:
            return None
        path = Path(chosen)
        self._settings.set_last_folder(path.parent)
        return path

    def save_as(self) -> bool:
        self._flush_inspector()
        self._canvas.finish_gesture()
        destination = self._destination_folder("Save Face")
        return self._save_to(destination) if destination is not None else False

    def export(self) -> bool:
        """Write a portable copy while preserving the editable working document."""
        self._flush_inspector()
        self._canvas.finish_gesture()
        destination = self._destination_folder("Export Copy")
        if destination is None:
            return False
        try:
            prepare_face(self._document.preview(validate_layout=True))
            exported = self._document.export(destination)
        except (FaceError, OSError, ValueError) as exc:
            self._show_error(f"“{self.display_name()}” could not be exported.", exc)
            return False
        self.statusBar().showMessage(f"Exported a copy to {exported}", STATUS_MESSAGE_MS)
        return True

    def _save_to(self, path: Path) -> bool:
        self._canvas.finish_gesture()
        try:
            prepare_face(self._document.preview(validate_layout=True))
            saved = self._document.save(path)
        except (FaceError, OSError, ValueError) as exc:
            self._show_error(f"“{self.display_name()}” could not be saved.", exc)
            return False
        self._changed()
        self._workspace.note_recent(saved)
        # A saved installed face may have a new name.
        self._workspace.library_changed(saved)
        self.statusBar().showMessage(f"Saved to {saved}", STATUS_MESSAGE_MS)
        return True

    def revert(self) -> bool:
        """Reload the saved folder after confirming that edits will be lost."""
        path = self._document.path
        if path is None or not self._document.dirty:
            return False
        self._flush_inspector()
        self._canvas.finish_gesture()
        box = QMessageBox(
            QMessageBox.Icon.Warning, APP_NAME,
            f"Do you want to revert “{self.display_name()}” to the saved version?",
            parent=self,
        )
        box.setInformativeText("Your current changes will be lost.")
        revert = box.addButton("Revert", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.setWindowModality(Qt.WindowModality.WindowModal)
        box.exec()
        confirmed = box.clickedButton() is revert
        box.deleteLater()
        if not confirmed:
            return False
        try:
            document = FaceDocument.open(path)
        except (FaceError, OSError) as exc:
            self._show_error(f"“{path.name}” could not be reopened.", exc)
            return False
        self._set_document(document)
        return True

    def _about(self) -> None:
        from .. import __version__

        QMessageBox.about(
            self, f"About {APP_NAME}",
            f"<b>{APP_NAME}</b><br>Version {__version__}<br><br>"
            "Design faces for Amberfader, the compact player for YouTube Music.",
        )

    def _reveal(self) -> None:
        path = self._document.path
        if path is not None and not desktop.reveal(path):
            self._show_error("The folder could not be shown.", str(path))

    # ------------------------------------------------------- window events
    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            self._settings.set_window_geometry(self.saveGeometry())
            event.accept()
            self.closed.emit()
        else:
            event.ignore()
