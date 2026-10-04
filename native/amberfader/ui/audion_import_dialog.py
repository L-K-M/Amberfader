"""Preview legacy Audion artwork before creating an editable Amberfader copy."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..face_library import FaceError
from .face_surface import draw_face_preview, prepare_face
from .placeholder import placeholder_png

if TYPE_CHECKING:
    from ..audion_import import AudionFaceSource, AudionImportResult


def _list_faces(source: Path) -> tuple[AudionFaceSource, ...]:
    from ..audion_import import list_audion_faces

    return list_audion_faces(source)


def _convert_face(candidate: AudionFaceSource) -> AudionImportResult:
    from ..audion_import import import_audion_face

    return import_audion_face(candidate)


def _default_folder() -> Path:
    installed = Path.home() / (
        "Library/Containers/com.panic.Audion/Data/Library/Application Support/Audion/Faces"
    )
    return installed if installed.is_dir() else Path.home()


class _Preview(QLabel):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(240, 180)
        self.setStyleSheet("background: #30343b; border-radius: 5px;")
        self._original = QPixmap()

    def set_preview(self, pixmap: QPixmap) -> None:
        self._original = pixmap
        self._fit()

    def _fit(self) -> None:
        if self._original.isNull():
            self.clear()
            return
        self.setPixmap(self._original.scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit()


class AudionImportDialog(QDialog):
    """Conversion is read-only, with a single selected preview kept in memory."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Audion face")
        self.resize(860, 650)
        self.setMinimumSize(640, 480)
        self._import_result: AudionImportResult | None = None
        self._cached_candidate: AudionFaceSource | None = None
        self._folder = _default_folder()
        root = QVBoxLayout(self)
        hint = QLabel(
            "Choose a converted Audion face folder, a collection of faces, or a ZIP archive. "
            "Preview the conversion before importing an editable copy.", self,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        browse = QHBoxLayout()
        folder = QPushButton("Browse folder…", self)
        folder.clicked.connect(self._browse_folder)
        archive = QPushButton("Browse ZIP…", self)
        archive.clicked.connect(self._browse_zip)
        browse.addWidget(folder)
        browse.addWidget(archive)
        browse.addStretch(1)
        root.addLayout(browse)
        self._source = QLabel("No source selected", self)
        self._source.setTextFormat(Qt.TextFormat.PlainText)
        self._source.setWordWrap(True)
        root.addWidget(self._source)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        collection = QWidget(splitter)
        left = QVBoxLayout(collection)
        left.setContentsMargins(0, 0, 0, 0)
        self._filter = QLineEdit(collection)
        self._filter.setPlaceholderText("Filter faces by name")
        self._filter.setAccessibleName("Filter Audion faces")
        left.addWidget(self._filter)
        self._faces = QListWidget(collection)
        self._faces.setAccessibleName("Available Audion faces")
        left.addWidget(self._faces)
        details = QWidget(splitter)
        right = QVBoxLayout(details)
        right.setContentsMargins(0, 0, 0, 0)
        self._preview = _Preview(details)
        self._preview.setAccessibleName("Converted face preview")
        right.addWidget(self._preview, 1)
        self._details = QPlainTextEdit(details)
        self._details.setReadOnly(True)
        self._details.setAccessibleName("Original credits and conversion notes")
        self._details.setPlainText("Select a face to see its preview and conversion notes.")
        right.addWidget(self._details, 1)
        splitter.addWidget(collection)
        splitter.addWidget(details)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([250, 560])
        root.addWidget(splitter, 1)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, self)
        self._import_button = self._buttons.addButton(
            "Import editable copy", QDialogButtonBox.ButtonRole.AcceptRole,
        )
        self._import_button.setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)
        self._filter.textChanged.connect(self._filter_faces)
        self._faces.currentItemChanged.connect(self._select_face)

    @property
    def import_result(self) -> AudionImportResult | None:
        return self._import_result

    def _browse_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose a converted Audion face folder or collection", str(self._folder),
        )
        if directory:
            self.load_source(Path(directory))

    def _browse_zip(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an Audion face ZIP archive", str(self._folder), "ZIP archives (*.zip)",
        )
        if path:
            self.load_source(Path(path))

    def load_source(self, source: Path) -> bool:
        """Discover a supported source without modifying its files."""
        try:
            candidates = _list_faces(Path(source))
            if not candidates:
                raise FaceError("No supported Audion faces were found in this source.")
        except (FaceError, OSError, ValueError) as exc:
            self._faces.clear()
            self._clear_preview()
            self._source.setText(str(source))
            self._details.setPlainText(
                f"Could not read Audion faces: {exc}\n\n"
                "Choose the containing face folder so its images are accessible, "
                "or choose a supported ZIP archive."
            )
            return False
        self._folder = Path(source) if Path(source).is_dir() else Path(source).parent
        self._source.setText(str(source))
        self._faces.clear()
        self._cached_candidate = None
        self._clear_preview()
        for candidate in candidates:
            item = QListWidgetItem(candidate.name)
            item.setData(Qt.ItemDataRole.UserRole, candidate)
            self._faces.addItem(item)
        self._filter_faces()
        return True

    def _filter_faces(self) -> None:
        query = self._filter.text().casefold().strip()
        visible = []
        for index in range(self._faces.count()):
            item = self._faces.item(index)
            item.setHidden(query not in item.text().casefold())
            if not item.isHidden():
                visible.append(item)
        current = self._faces.currentItem()
        if current is None or current.isHidden():
            self._faces.setCurrentItem(visible[0] if visible else None)
        if not visible:
            self._clear_preview()
            self._details.setPlainText("No faces match this filter.")

    def _clear_preview(self) -> None:
        self._import_result = None
        self._cached_candidate = None
        self._import_button.setEnabled(False)
        self._preview.set_preview(QPixmap())

    def _select_face(self, item: QListWidgetItem | None, previous=None) -> None:
        if item is None:
            self._clear_preview()
            return
        candidate = item.data(Qt.ItemDataRole.UserRole)
        if candidate == self._cached_candidate and self._import_result is not None:
            return
        self._clear_preview()
        try:
            result = _convert_face(candidate)
            face = result.document.preview(validate_layout=True)
            artwork = prepare_face(face)
            cover = QPixmap()
            cover.loadFromData(QByteArray(placeholder_png()))
            preview = QPixmap(*face.size)
            painter = QPainter(preview)
            try:
                for x in range(0, face.size[0], 16):
                    for y in range(0, face.size[1], 16):
                        color = "#c9cdd3" if (x // 16 + y // 16) % 2 else "#e8ebef"
                        painter.fillRect(x, y, 16, 16, QColor(color))
                draw_face_preview(painter, face, artwork, cover)
            finally:
                painter.end()
        except (FaceError, OSError, ValueError) as exc:
            self._details.setPlainText(f"Could not convert {candidate.name}: {exc}")
            return
        self._cached_candidate = candidate
        self._import_result = result
        self._preview.set_preview(preview)
        data = result.document.manifest
        credits = data.get("sourceCredit") or f"{data['name']}\nAuthor: {data['author']}"
        notes = "\n".join(f"• {warning}" for warning in result.warnings)
        self._details.setPlainText(
            credits + "\n\nConversion notes\n" + (notes or "No conversion warnings.")
            + "\n\nImport creates an unsaved copy. The original files remain unchanged."
        )
        self._import_button.setEnabled(True)

    def accept(self) -> None:
        if self._import_result is not None:
            super().accept()
