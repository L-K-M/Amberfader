"""Face browser, previews and local folder installation."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..face_library import Face, FaceError, FaceLibrary, load_face
from .face_surface import (
    PREVIEW_LABELS as PREVIEW_LABELS,
)
from .face_surface import (
    FaceArtwork,
    draw_face_preview,
    prepare_face,
)


class FacePreview(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setMinimumSize(420, 280)
        self._face: Face | None = None
        self._artwork: FaceArtwork | None = None
        self._cover = QPixmap(128, 128)
        painter = QPainter(self._cover)
        gradient = QLinearGradient(0, 0, 128, 128)
        gradient.setColorAt(0, QColor("#efac64"))
        gradient.setColorAt(1, QColor("#24334b"))
        painter.fillRect(self._cover.rect(), gradient)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#ffe6b2"), 2))
        for inset in (16, 32, 48):
            painter.drawEllipse(self._cover.rect().adjusted(inset, inset, -inset, -inset))
        painter.end()

    def set_face(self, face: Face, artwork: FaceArtwork) -> None:
        self._face, self._artwork = face, artwork
        self.update()

    def clear(self) -> None:
        self._face, self._artwork = None, None
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#34363d"))
        face, artwork = self._face, self._artwork
        if face is None or artwork is None:
            return
        scale = min((self.width() - 24) / face.size[0], (self.height() - 24) / face.size[1])
        painter.translate(
            (self.width() - face.size[0] * scale) / 2,
            (self.height() - face.size[1] * scale) / 2,
        )
        painter.scale(scale, scale)
        draw_face_preview(painter, face, artwork, self._cover)


class FacesWindow(QDialog):
    def __init__(
        self, library: FaceLibrary, choose: Callable[[str], None], parent: QWidget,
        *, edit: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Amberfader · Faces")
        self.resize(760, 540)
        self._library = library
        self._choose = choose
        self._edit = edit
        self._selected: str | None = None
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter faces by name")
        self._filter.setAccessibleName("Filter faces")
        self._filter.setClearButtonEnabled(True)
        self._list = QListWidget(self)
        self._list.setMinimumWidth(180)
        self._preview = FacePreview(self)
        self._description = QLabel(self)
        self._description.setWordWrap(True)
        self._description.setTextFormat(Qt.TextFormat.PlainText)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        self._apply = QPushButton("Use face", self)
        self._edit_button = QPushButton("Edit a copy…", self)
        self._edit_button.setObjectName("editFace")
        self._edit_button.setVisible(edit is not None)
        self._edit_button.setEnabled(False)
        install = QPushButton("Install face folder…", self)
        folder = QPushButton("Open faces folder", self)
        close = QPushButton("Close", self)

        root = QVBoxLayout(self)
        heading = QLabel("Faces change the shell. Your music keeps playing.", self)
        root.addWidget(heading)
        body = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(self._filter)
        left.addWidget(self._list, 1)
        body.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(self._preview, 1)
        right.addWidget(self._description)
        body.addLayout(right, 3)
        root.addLayout(body, 1)
        root.addWidget(self._status)
        buttons = QHBoxLayout()
        for button in (install, folder, self._edit_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self._apply)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._filter.textChanged.connect(self._filter_faces)
        self._list.currentItemChanged.connect(self._preview_item)
        self._list.itemActivated.connect(lambda _: self._use_face())
        self._apply.clicked.connect(self._use_face)
        self._edit_button.clicked.connect(self._edit_copy)
        install.clicked.connect(self._install)
        folder.clicked.connect(self._open_folder)
        close.clicked.connect(self.close)

    def refresh(self, current_id: str) -> None:
        self._library.refresh()
        self._list.clear()
        for face in self._library.faces:
            item = QListWidgetItem(face.name)
            item.setData(Qt.ItemDataRole.UserRole, face.id)
            self._list.addItem(item)
            if face.id == current_id:
                self._list.setCurrentItem(item)
        self._status.setText("\n".join(self._library.problems))
        self._filter_faces()

    def _filter_faces(self) -> None:
        query = self._filter.text().casefold().strip()
        first = None
        for index in range(self._list.count()):
            item = self._list.item(index)
            item.setHidden(query not in item.text().casefold())
            if first is None and not item.isHidden():
                first = item
        current = self._list.currentItem()
        if current is None or current.isHidden():
            # Use face and Edit a copy must never act on a hidden face.
            self._list.setCurrentItem(first)
        if first is None:
            self._description.setText("No faces match this filter.")

    def _preview_item(self, item: QListWidgetItem | None, previous=None) -> None:
        self._selected = None
        self._apply.setEnabled(False)
        self._edit_button.setEnabled(False)
        if item is None:
            self._preview.clear()
            self._description.clear()
            return
        try:
            face = self._library.load(item.data(Qt.ItemDataRole.UserRole))
            self._preview.set_face(face, prepare_face(face))
            self._description.setText(
                f"{face.info.name} · {face.info.author}\n{face.info.description}"
            )
            self._selected = face.info.id
            self._apply.setEnabled(True)
            self._edit_button.setEnabled(self._edit is not None)
        except FaceError as exc:
            self._status.setText(str(exc))

    def _edit_copy(self) -> None:
        if self._selected is not None and self._edit is not None:
            self._edit(self._selected)

    def _use_face(self) -> None:
        if self._selected is None:
            return
        try:
            self._choose(self._selected)
            self._status.setText("Face saved. Playback is unchanged.")
        except FaceError as exc:
            self._status.setText(str(exc))

    def _install(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose an Amberfader face folder containing face.json"
        )
        if not path:
            return
        try:
            prepare_face(load_face(Path(path)))
            info = self._library.install(Path(path))
            self._filter.clear()  # Show the installed face even if the filter would hide it.
            self.refresh(info.id)
            self._status.setText(f"Installed {info.name}. Select Use face to apply it.")
        except FaceError as exc:
            self._status.setText(str(exc))

    def _open_folder(self) -> None:
        try:
            path = self._library.ensure_directory()
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self._status.setText(f"Open this folder in your file manager: {path}")
        except FaceError as exc:
            self._status.setText(str(exc))
