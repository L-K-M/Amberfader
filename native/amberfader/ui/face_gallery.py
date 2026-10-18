"""The Face Gallery: start a face from a template or open an installed one.

    ┌ Face Gallery ──────────────────────────── [🔍 Search      ] ┐
    │ LIBRARY      │ ┌────┐ ┌────┐ ┌────┐                          │
    │ Built-in 18  │ │    │ │    │ │    │   thumbnails render      │
    │ Installed 2  │ └────┘ └────┘ └────┘   lazily, visible first  │
    ├──────────────┴───────────────────────────────────────────────┤
    │ Open Other…                                 Cancel  [Create] │
    └──────────────────────────────────────────────────────────────┘

Built-in faces become an untitled copy; installed faces open for editing
in place. The gallery only reports the choice; its owner opens documents.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from .. import desktop
from ..face_library import BUILTIN_DIRECTORY, FaceError, FaceInfo, FaceLibrary, load_face
from .editor_widgets import (
    MACOS,
    sample_cover,
    symbol_icon,
    use_secondary_text,
    use_source_list_background,
)
from .face_surface import draw_face_preview, prepare_face_preview

THUMBNAIL = QSize(176, 112)
GRID = QSize(200, 156)
RENDER_INTERVAL_MS = 0
SOURCE_ROLE = Qt.ItemDataRole.UserRole
INFO_ROLE = Qt.ItemDataRole.UserRole + 1
MAX_LISTED_PROBLEMS = 20

# Rendered thumbnails, shared by every gallery: (folder, face.json mtime) -> pixmap.
_THUMBNAILS: dict[tuple[Path, int], QPixmap] = {}


class GallerySource(Enum):
    BUILT_IN = 0
    INSTALLED = 1


SOURCE_TITLES = {GallerySource.BUILT_IN: "Built-in", GallerySource.INSTALLED: "Installed"}


def _thumbnail_key(source: Path) -> tuple[Path, int] | None:
    try:
        return source, (source / "face.json").stat().st_mtime_ns
    except OSError:
        return None


def render_thumbnail(source: Path, scale: float) -> QPixmap:
    """Draw a face as the player would, scaled into a thumbnail cell."""
    face = load_face(source)
    artwork = prepare_face_preview(face)
    full = QPixmap(*face.size)
    full.fill(Qt.GlobalColor.transparent)
    painter = QPainter(full)
    draw_face_preview(painter, face, artwork, sample_cover())
    painter.end()
    target = QSize(round(THUMBNAIL.width() * scale), round(THUMBNAIL.height() * scale))
    pixmap = full.scaled(
        target, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
    )
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def _placeholder(scale: float) -> QPixmap:
    pixmap = QPixmap(round(THUMBNAIL.width() * scale), round(THUMBNAIL.height() * scale))
    pixmap.setDevicePixelRatio(scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(128, 128, 128, 40)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(QRect(8, 8, THUMBNAIL.width() - 16, THUMBNAIL.height() - 16), 8, 8)
    painter.end()
    return pixmap


class _ThumbnailDelegate(QStyledItemDelegate):
    """Finder-style cells: a rounded highlight behind the face, a pill behind its name."""

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        active = bool(option.state & QStyle.StateFlag.State_Active)
        palette = option.palette
        image_area = QRectF(rect.x() + 4, rect.y() + 4, rect.width() - 8, THUMBNAIL.height() + 8)
        if selected:
            shade = QColor(palette.color(QPalette.ColorRole.WindowText))
            shade.setAlphaF(0.12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(shade)
            painter.drawRoundedRect(image_area, 8, 8)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None:
            pixmap = icon if isinstance(icon, QPixmap) else icon.pixmap(THUMBNAIL)
            size = pixmap.deviceIndependentSize()
            target = QRectF(
                image_area.center().x() - size.width() / 2,
                image_area.center().y() - size.height() / 2,
                size.width(), size.height(),
            )
            painter.drawPixmap(target.toRect(), pixmap)
        text = index.data(Qt.ItemDataRole.DisplayRole) or ""
        metrics = option.fontMetrics
        label = metrics.elidedText(text, Qt.TextElideMode.ElideRight, rect.width() - 16)
        width = metrics.horizontalAdvance(label) + 14
        pill = QRectF(
            rect.center().x() - width / 2, image_area.bottom() + 4, width, metrics.height() + 4,
        )
        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            accent = palette.color(QPalette.ColorRole.Accent)
            painter.setBrush(accent if active else palette.color(QPalette.ColorRole.Mid))
            painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
            painter.setPen(QColor("white"))
        else:
            painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, label)
        painter.restore()

    def sizeHint(self, option, index) -> QSize:
        return GRID


class FaceGallery(QDialog):
    createRequested = Signal(Path)  # start an untitled copy of this face
    editRequested = Signal(Path)  # open this installed face in place
    openOtherRequested = Signal()

    def __init__(self, library: FaceLibrary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("faceGallery")
        self.setWindowTitle("Face Gallery")
        self.setModal(False)
        self.setSizeGripEnabled(True)
        self.resize(900, 600)
        self.setMinimumSize(560, 380)
        self._library = library
        self._source = GallerySource.BUILT_IN
        self._faces: dict[GallerySource, list[FaceInfo]] = {source: [] for source in GallerySource}
        self._pending: list[QListWidgetItem] = []
        self._render_timer = QTimer(self)
        self._render_timer.setInterval(RENDER_INTERVAL_MS)
        self._render_timer.timeout.connect(self._render_next)

        self._search = QLineEdit(self)
        self._search.setObjectName("gallerySearch")
        self._search.setPlaceholderText("Search")
        self._search.setClearButtonEnabled(True)
        self._search.setAccessibleName("Search faces")
        search_icon = symbol_icon("magnifyingglass", "edit-find")
        if not search_icon.isNull():
            self._search.addAction(search_icon, QLineEdit.ActionPosition.LeadingPosition)
        self._search.setMaximumWidth(260)
        self._search.textChanged.connect(self._filter)
        QShortcut(QKeySequence.StandardKey.Find, self, self._focus_search)

        self._sources = QListWidget(self)
        self._sources.setObjectName("gallerySources")
        self._sources.setAccessibleName("Face sources")
        self._sources.setFrameShape(QFrame.Shape.NoFrame)
        self._sources.setIconSize(QSize(16, 16))
        for source, symbol in (
            (GallerySource.BUILT_IN, "square.grid.2x2"),
            (GallerySource.INSTALLED, "folder"),
        ):
            item = QListWidgetItem(symbol_icon(symbol, "folder"), SOURCE_TITLES[source])
            item.setData(SOURCE_ROLE, source)
            self._sources.addItem(item)
        self._sources.currentRowChanged.connect(
            lambda row: self.show_source(GallerySource(row)) if row >= 0 else None,
        )
        use_source_list_background(self._sources)

        self._grid = QListWidget(self)
        self._grid.setObjectName("galleryFaces")
        self._grid.setAccessibleName("Faces")
        self._grid.setViewMode(QListView.ViewMode.IconMode)
        self._grid.setIconSize(THUMBNAIL)
        self._grid.setGridSize(GRID)
        self._grid.setResizeMode(QListView.ResizeMode.Adjust)
        self._grid.setMovement(QListView.Movement.Static)
        self._grid.setUniformItemSizes(True)
        self._grid.setWordWrap(True)
        self._grid.setSpacing(8)
        self._grid.setFrameShape(QFrame.Shape.NoFrame)
        self._grid.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._grid.customContextMenuRequested.connect(self._context_menu)
        self._grid.itemActivated.connect(lambda _item: self._choose())
        self._grid.currentItemChanged.connect(lambda *_: self._update_buttons())
        self._grid.verticalScrollBar().valueChanged.connect(lambda _: self._schedule())
        self._grid.setItemDelegate(_ThumbnailDelegate(self._grid))

        self._empty = QLabel(self)
        self._empty.setObjectName("galleryEmpty")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setWordWrap(True)
        self._empty.setTextFormat(Qt.TextFormat.PlainText)
        use_secondary_text(self._empty)
        self._content = QStackedWidget(self)
        self._content.addWidget(self._grid)
        self._content.addWidget(self._empty)

        self._problems = QPushButton(self)
        self._problems.setObjectName("galleryProblems")
        self._problems.setFlat(True)
        self._problems.setIcon(symbol_icon("exclamationmark.triangle.fill", "dialog-warning"))
        self._problems.clicked.connect(self._show_problems)

        self._buttons = QDialogButtonBox(self)
        self._open_other = QPushButton("Open Other…", self)
        self._open_other.setObjectName("galleryOpenOther")
        self._open_other.setToolTip("Open a face folder with the Open panel")
        self._open_other.clicked.connect(self.openOtherRequested)
        self._cancel = self._buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self._cancel.clicked.connect(self.close)
        self._primary = self._buttons.addButton("Create", QDialogButtonBox.ButtonRole.AcceptRole)
        self._primary.setObjectName("galleryPrimary")
        self._primary.setDefault(True)
        self._primary.clicked.connect(self._choose)

        header = QHBoxLayout()
        header.setContentsMargins(12, 10, 12, 6)
        self._heading = QLabel(self)
        self._heading.setObjectName("galleryHeading")
        font = self._heading.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 2)
        self._heading.setFont(font)
        header.addWidget(self._heading, 1)
        header.addWidget(self._search)
        splitter = QSplitter(self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._sources)
        splitter.addWidget(self._content)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([170, 700])
        footer = QHBoxLayout()
        footer.setContentsMargins(12, 6, 12, 12)
        footer.addWidget(self._open_other)
        footer.addWidget(self._problems)
        footer.addStretch(1)
        footer.addWidget(self._buttons)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setForegroundRole(QPalette.ColorRole.Mid)
        layout.addWidget(line)
        layout.addWidget(splitter, 1)
        layout.addLayout(footer)
        self.reload()
        self._sources.setCurrentRow(0)

    # ------------------------------------------------------------ content
    @property
    def source(self) -> GallerySource:
        return self._source

    def reload(self, select: Path | None = None) -> None:
        """Rescan the faces folder, e.g. after an import or a save.

        A failed rescan keeps the previous list and reports why.
        """
        problems: tuple[str, ...]
        try:
            self._library.refresh()
            problems = self._library.problems
        except FaceError as exc:
            problems = (str(exc),)
        else:
            bundled_root = BUILTIN_DIRECTORY.resolve()
            faces: dict[GallerySource, list[FaceInfo]] = {source: [] for source in GallerySource}
            for info in self._library.faces:
                source = (
                    GallerySource.BUILT_IN if info.source.is_relative_to(bundled_root)
                    else GallerySource.INSTALLED
                )
                faces[source].append(info)
            for items in faces.values():
                items.sort(key=lambda face: (face.name.casefold(), face.id))
            self._faces = faces
        for row, source in enumerate(GallerySource):
            item = self._sources.item(row)
            item.setText(f"{SOURCE_TITLES[source]}  {len(self._faces[source])}")
        self._problem_list = problems
        self._problems.setVisible(bool(problems))
        count = len(problems)
        self._problems.setText(
            f"{count} face folder{'s' if count != 1 else ''} could not be loaded" if count
            else ""
        )
        self._populate(select)

    def show_source(self, source: GallerySource, select: Path | None = None) -> None:
        self._source = source
        if self._sources.currentRow() != source.value:
            self._sources.blockSignals(True)
            self._sources.setCurrentRow(source.value)
            self._sources.blockSignals(False)
        self._populate(select)

    def _populate(self, select: Path | None = None) -> None:
        source = self._source
        self._heading.setText(
            "Choose a Template" if source is GallerySource.BUILT_IN else "Installed Faces"
        )
        self._primary.setText("Create" if source is GallerySource.BUILT_IN else "Open")
        scale = self.devicePixelRatioF()
        placeholder = _placeholder(scale)
        self._grid.clear()
        self._pending = []
        selected_item = None
        for info in self._faces[source]:
            item = QListWidgetItem(info.name)
            item.setData(SOURCE_ROLE, info.source)
            item.setData(INFO_ROLE, info)
            item.setToolTip(f"{info.name}\n{info.author}\n{info.description}".strip())
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            key = _thumbnail_key(info.source)
            cached = _THUMBNAILS.get(key) if key is not None else None
            item.setIcon(cached if cached is not None else placeholder)
            if cached is None:
                self._pending.append(item)
            self._grid.addItem(item)
            if select is not None and info.source == select.resolve():
                selected_item = item
        if selected_item is None and self._grid.count():
            selected_item = self._grid.item(0)
        if selected_item is not None:
            self._grid.setCurrentItem(selected_item)
            self._grid.scrollToItem(selected_item)
        self._filter()
        self._schedule()

    def _filter(self) -> None:
        query = self._search.text().casefold().strip()
        shown = 0
        for index in range(self._grid.count()):
            item = self._grid.item(index)
            hidden = query not in item.text().casefold()
            item.setHidden(hidden)
            shown += not hidden
        current = self._grid.currentItem()
        if current is not None and current.isHidden():
            visible = [
                self._grid.item(index) for index in range(self._grid.count())
                if not self._grid.item(index).isHidden()
            ]
            self._grid.setCurrentItem(visible[0] if visible else None)
        if shown:
            self._content.setCurrentWidget(self._grid)
        else:
            self._empty.setText(self._empty_text(query))
            self._content.setCurrentWidget(self._empty)
        self._update_buttons()
        self._schedule()

    def _empty_text(self, query: str) -> str:
        if query:
            return f"No faces match “{self._search.text().strip()}”."
        if self._source is GallerySource.INSTALLED:
            return (
                "No Installed Faces\n\nFaces you save to Amberfader's faces folder, "
                "install in the player, or import from an Audion collection appear here."
            )
        return "Built-in faces are unavailable. Reinstall Amberfader."

    def _update_buttons(self) -> None:
        item = self._grid.currentItem()
        self._primary.setEnabled(item is not None and not item.isHidden())

    def _focus_search(self) -> None:
        self._search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self._search.selectAll()

    # ----------------------------------------------------------- thumbnails
    def _schedule(self) -> None:
        if self._pending and self.isVisible():
            self._render_timer.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Arrow keys browse faces; ⌘F or a click reaches the search field.
        self._grid.setFocus(Qt.FocusReason.OtherFocusReason)
        self._schedule()

    def hideEvent(self, event) -> None:
        self._render_timer.stop()
        super().hideEvent(event)

    def _render_next(self) -> None:
        """Render one thumbnail per event loop pass, visible items first."""
        self._pending = [item for item in self._pending if item.listWidget() is self._grid]
        if not self._pending:
            self._render_timer.stop()
            return
        viewport = self._grid.viewport().rect()
        item = next(
            (
                candidate for candidate in self._pending
                if not candidate.isHidden()
                and self._grid.visualItemRect(candidate).intersects(viewport)
            ),
            self._pending[0],
        )
        self._pending.remove(item)
        source = item.data(SOURCE_ROLE)
        key = _thumbnail_key(source)
        try:
            pixmap = render_thumbnail(source, self.devicePixelRatioF())
        except (FaceError, OSError, ValueError):
            pixmap = None
        if pixmap is not None:
            if key is not None:
                _THUMBNAILS[key] = pixmap
            item.setIcon(pixmap)

    # ------------------------------------------------------------- choices
    def selected_source(self) -> Path | None:
        item = self._grid.currentItem()
        if item is None or item.isHidden():
            return None
        return item.data(SOURCE_ROLE)

    def _choose(self) -> None:
        source = self.selected_source()
        if source is None:
            return
        if self._source is GallerySource.BUILT_IN:
            self.createRequested.emit(source)
        else:
            self.editRequested.emit(source)

    def _context_menu(self, position) -> None:
        item = self._grid.itemAt(position)
        if item is None:
            return
        self._grid.setCurrentItem(item)
        source = item.data(SOURCE_ROLE)
        menu = QMenu(self)
        if self._source is GallerySource.INSTALLED:
            menu.addAction("Open", lambda: self.editRequested.emit(source))
        menu.addAction("New Face from Template", lambda: self.createRequested.emit(source))
        if self._source is GallerySource.INSTALLED:
            menu.addSeparator()
            menu.addAction(
                "Show in Finder" if MACOS else "Show in Folder",
                lambda: desktop.reveal(source),
            )
        menu.exec(self._grid.viewport().mapToGlobal(position))

    def _show_problems(self) -> None:
        problems = self._problem_list
        message = QMessageBox(QMessageBox.Icon.Warning, "Face Gallery", "", parent=self)
        message.setText("Some face folders could not be loaded.")
        message.setInformativeText(
            "Fix or remove these folders in Amberfader's faces folder."
        )
        shown = list(problems[:MAX_LISTED_PROBLEMS])
        if len(problems) > MAX_LISTED_PROBLEMS:
            shown.append(f"…and {len(problems) - MAX_LISTED_PROBLEMS} more")
        message.setDetailedText("\n".join(shown))
        message.setWindowModality(Qt.WindowModality.WindowModal)
        message.exec()

    def keyPressEvent(self, event) -> None:
        # Return chooses the selected face even while the search field has focus.
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._choose()
            event.accept()
            return
        super().keyPressEvent(event)
