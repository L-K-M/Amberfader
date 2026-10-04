"""Face browser, previews and local folder installation."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QRect, QRectF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QFont,
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
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..face_library import Face, FaceError, FaceLibrary, load_face
from .face_surface import (
    FONT_FAMILIES,
    READOUT_CONTROLS,
    TRANSPORT_CONTROLS,
    FaceArtwork,
    control_path,
    draw_cover,
    draw_slider,
    draw_transport_icon,
    fit_readout_font,
    like_font_size,
    prepare_face,
    readout_font,
    readout_style,
)

PREVIEW_LABELS = {
    "title": "A face for your music", "artists": "Amberfader · Face preview",
    "time": "03:48 / 04:30", "playback": "PREVIEW", "previous": "⏮", "play": "▶",
    "next": "⏭", "like": "♥", "search": "Search", "show": "Show YT", "hide": "Hide",
    "menu": "☰", "minimize": "\u2212", "close": "\u00d7", "status": "Firefox keeps playing",
}


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
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(QRect(0, 0, *face.size), artwork.background)
        p = face.palette
        for name, coordinates in face.controls.items():
            rect = QRect(*coordinates)
            painter.setPen(QColor(p["readout"]))
            if name in READOUT_CONTROLS:
                font = readout_font(face, name)
            else:
                font = QFont(FONT_FAMILIES[face.font])
                font.setPixelSize(like_font_size(face) if name == "like" else 12)
            if name == "time":
                font = fit_readout_font(font, PREVIEW_LABELS["time"], rect)
            painter.setFont(font)
            if name == "art":
                draw_cover(
                    painter, self._cover, QRectF(rect), face.control_shapes.get("art", "rectangle"),
                    face.radius, face.cover_glass,
                )
                continue
            if name in ("seek", "volume"):
                if face.slider_style == "inset":
                    groove = QRectF(rect.x(), rect.y() + (rect.height() - 4) / 2, rect.width(), 4)
                    # The 12px QSS handle has a 1px border on either side.
                    handle = QRectF(
                        rect.center().x() - 6, rect.y() + (rect.height() - 14) / 2, 14, 14,
                    )
                    draw_slider(painter, groove, handle, p)
                    continue
                groove = rect.adjusted(4, rect.height() // 2 - 2, -4, -(rect.height() // 2 - 2))
                painter.fillRect(groove, QColor(p["display"]))
                groove.setWidth(groove.width() // 2)
                painter.fillRect(groove, QColor(p["accent"]))
                continue
            button = name in (
                "previous", "play", "next", "like", "search", "show", "hide", "menu",
                "minimize", "close",
            )
            if button:
                painter.save()
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = control_path(
                    QRectF(rect), face.control_shapes.get(name, "rectangle"), face.radius,
                )
                painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
                if name in artwork.buttons:
                    painter.drawPixmap(rect, artwork.buttons[name]["normal"])
                else:
                    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                    gradient.setColorAt(0, QColor(p["buttonTop"]))
                    gradient.setColorAt(1, QColor(p["buttonBottom"]))
                    painter.setBrush(gradient)
                    painter.setPen(QColor(p["border"]))
                    painter.drawPath(path)
                painter.restore()
                painter.setPen(QColor(p["text"]))
            elif name == "status":
                painter.setPen(QColor(p["muted"]))
            if name in TRANSPORT_CONTROLS:
                draw_transport_icon(painter, name, PREVIEW_LABELS[name], rect, QColor(p["text"]))
                continue
            text = PREVIEW_LABELS.get(name, "")
            if name != "time":
                text = painter.fontMetrics().elidedText(
                    text, Qt.TextElideMode.ElideRight, rect.width()
                )
            alignment = (
                readout_style(face, name).alignment if name in READOUT_CONTROLS
                else Qt.AlignmentFlag.AlignCenter
            )
            painter.drawText(rect, alignment, text)


class FacesWindow(QDialog):
    def __init__(
        self, library: FaceLibrary, choose: Callable[[str], None], parent: QWidget
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Amberfader · Faces")
        self.resize(760, 540)
        self._library = library
        self._choose = choose
        self._selected: str | None = None
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
        install = QPushButton("Install face folder…", self)
        folder = QPushButton("Open faces folder", self)
        close = QPushButton("Close", self)

        root = QVBoxLayout(self)
        heading = QLabel("Faces change the shell. Your music keeps playing.", self)
        root.addWidget(heading)
        body = QHBoxLayout()
        body.addWidget(self._list, 1)
        right = QVBoxLayout()
        right.addWidget(self._preview, 1)
        right.addWidget(self._description)
        body.addLayout(right, 3)
        root.addLayout(body, 1)
        root.addWidget(self._status)
        buttons = QHBoxLayout()
        for button in (install, folder):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self._apply)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self._list.currentItemChanged.connect(self._preview_item)
        self._list.itemActivated.connect(lambda _: self._use_face())
        self._apply.clicked.connect(self._use_face)
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

    def _preview_item(self, item: QListWidgetItem | None, previous=None) -> None:
        self._selected = None
        self._apply.setEnabled(False)
        if item is None:
            return
        try:
            face = self._library.load(item.data(Qt.ItemDataRole.UserRole))
            self._preview.set_face(face, prepare_face(face))
            self._description.setText(
                f"{face.info.name} · {face.info.author}\n{face.info.description}"
            )
            self._selected = face.info.id
            self._apply.setEnabled(True)
        except FaceError as exc:
            self._status.setText(str(exc))

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
