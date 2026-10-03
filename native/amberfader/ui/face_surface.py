"""Image-backed presentation of the host's existing Qt controls."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBitmap,
    QColor,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
)
from PySide6.QtWidgets import QLabel, QPushButton, QStyle, QStyleOptionButton, QWidget

from ..face_library import Face, FaceError

FONT_FAMILIES = {"sans": "sans-serif", "mono": "monospace", "serif": "serif"}
TRANSPORT_CONTROLS = frozenset(("previous", "play", "next"))


@dataclass(frozen=True)
class FaceArtwork:
    background: QPixmap
    mask: QRegion
    buttons: dict[str, dict[str, QPixmap]]

    def scaled_mask(self, size: tuple[int, int]) -> QRegion:
        return _alpha_mask(self.background, size)


def _alpha_mask(background: QPixmap, size: tuple[int, int]) -> QRegion:
    # QPixmap.mask() is empty for fully opaque images. An explicit alpha mask
    # keeps rectangular and sculpted faces on the same hit-testing path.
    image = background.toImage().scaled(*size)
    if not image.hasAlphaChannel():
        return QRegion(QRect(0, 0, *size))
    alpha = image.createAlphaMask(Qt.ImageConversionFlag.ThresholdAlphaDither)
    return QRegion(QBitmap.fromImage(alpha))


def _decode(data: bytes) -> QPixmap:
    image = QImage.fromData(data, "PNG")
    if image.isNull():
        raise FaceError("Face contains a PNG that Qt cannot decode")
    return QPixmap.fromImage(image)


def prepare_face(face: Face) -> FaceArtwork:
    """Decode before committing a selection; invisible controls are invalid."""
    background = _decode(face.background)
    mask = _alpha_mask(background, face.size)
    for name, rect in {**face.controls, "drag": face.drag}.items():
        if not QRegion(QRect(*rect)).subtracted(mask).isEmpty():
            raise FaceError(f"{name} must sit on the opaque face, not a transparent cutout")
    return FaceArtwork(background, mask, {
        name: {state: _decode(data) for state, data in images.items()}
        for name, images in face.buttons.items()
    })


def face_stylesheet(face: Face, scale: float) -> str:
    """Generate styles from constrained tokens; packs cannot inject QSS."""
    p = face.palette
    font_size = max(10, round(12 * scale))
    radius = round(face.radius * scale)
    handle = round(12 * scale)
    stylesheet = f"""
    QWidget {{
      color: {p['text']}; font-family: {FONT_FAMILIES[face.font]}; font-size: {font_size}px;
    }}
    QMainWindow, QWidget#faceSurface {{ background: transparent; }}
    QDialog, QMenu {{ background: {p['window']}; }}
    QLabel {{ background: transparent; }}
    QLabel#title {{ font-weight: bold; }}
    QLabel#title, QLabel#artists, QLabel#time, QLabel#playback {{ color: {p['readout']}; }}
    QLabel#time {{ font-family: monospace; font-size: {round(face.time_size * scale)}px; }}
    QLabel#dim, QLabel#status {{ color: {p['muted']}; }}
    QLabel#status[error="true"] {{ color: {p['danger']}; }}
    QLabel#art {{ background: {p['display']}; border: 1px solid {p['border']}; }}
    QPushButton {{
      background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {p['buttonTop']}, stop:1 {p['buttonBottom']});
      border: 1px solid {p['border']}; border-radius: {radius}px;
      padding: 0px {round(2 * scale)}px;
    }}
    QPushButton#like {{ font-size: {round(18 * scale)}px; }}
    QPushButton:hover:!disabled, QPushButton:focus {{ border-color: {p['accent']}; }}
    QPushButton:pressed, QPushButton[pending="true"] {{
      background: {p['accent']}; color: {p['window']};
    }}
    QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; }}
    QSlider {{ background: transparent; }}
    QSlider::groove:horizontal {{ height: {round(4 * scale)}px; background: {p['display']}; }}
    QSlider::handle:horizontal {{
      width: {handle}px; margin: -{round(5 * scale)}px 0;
      background: {p['accent']}; border: 1px solid {p['border']}; border-radius: {handle // 2}px;
    }}
    QSlider::sub-page:horizontal {{ background: {p['accent']}; }}
    QLineEdit, QListWidget {{
      background: {p['panel']}; color: {p['text']}; border: 1px solid {p['border']};
    }}
    QLineEdit {{ padding: 4px; }}
    QListWidget::item {{ padding: 4px; border-bottom: 1px solid {p['border']}; }}
    QListWidget::item:selected, QMenu::item:selected {{
      background: {p['accent']}; color: {p['window']};
    }}
    QToolTip {{ background: {p['panel']}; color: {p['text']}; border: 1px solid {p['border']}; }}
    """
    for name, (_, _, width, height) in face.controls.items():
        corner = round(min(face.radius, width // 2 - 1, height // 2 - 1) * scale)
        stylesheet += f"QPushButton#{name} {{ border-radius: {corner}px; }}\n"
    return stylesheet


def draw_transport_icon(
    painter: QPainter, name: str, text: str, rect: QRect, color: QColor
) -> None:
    """Draw transport symbols independently of installed Unicode fonts."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.translate(rect.center())
    size = min(rect.width(), rect.height()) * 0.42
    painter.scale(size, size)
    if name == "play":
        if text == "⏸":
            painter.drawRect(QRectF(-0.4, -0.45, 0.25, 0.9))
            painter.drawRect(QRectF(0.15, -0.45, 0.25, 0.9))
        else:
            painter.drawPolygon(QPolygonF([
                QPointF(-0.3, -0.5), QPointF(0.5, 0), QPointF(-0.3, 0.5),
            ]))
    else:
        if name == "next":
            painter.scale(-1, 1)
        painter.drawRect(QRectF(-0.55, -0.45, 0.12, 0.9))
        for x in (-0.35, 0.05):
            painter.drawPolygon(QPolygonF([
                QPointF(x, 0), QPointF(x + 0.36, -0.45), QPointF(x + 0.36, 0.45),
            ]))
    painter.restore()


class ElidedLabel(QLabel):
    """Keep full metadata available while narrow faces display an ellipsis."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(self.palette().windowText().color())
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), self.alignment(), text)


class ReadoutLabel(QLabel):
    """Fit the complete position/duration readout instead of clipping digits."""

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        font = self.font()
        font.setPixelSize(min(font.pixelSize(), self.height() - 2))
        width = QFontMetrics(font).horizontalAdvance(self.text())
        if width > self.width():
            font.setPixelSize(max(10, int(font.pixelSize() * self.width() / width)))
        painter.setFont(font)
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.rect(), self.alignment(), self.text())


class CoverLabel(QLabel):
    activated = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("View album cover")
        self.setToolTip("View album cover")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.rect().contains(event.position().toPoint())
        ):
            self.activated.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)


class FaceButton(QPushButton):
    """Optional artist sprites retain host labels, focus and pending states."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self._sprites: dict[str, QPixmap] = {}

    def set_sprites(self, sprites: dict[str, QPixmap]) -> None:
        self._sprites = sprites
        self.update()

    def paintEvent(self, event) -> None:
        transport = self.objectName() in TRANSPORT_CONTROLS
        if not self._sprites and not transport:
            super().paintEvent(event)
            return
        state = "normal"
        if not self.isEnabled():
            state = "disabled"
        elif self.isDown() or self.property("pending"):
            state = "pressed"
        elif self.underMouse():
            state = "hover"
        painter = QPainter(self)
        if self._sprites:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            if state == "disabled" and state not in self._sprites:
                painter.setOpacity(0.5)
            painter.drawPixmap(self.rect(), self._sprites.get(state, self._sprites["normal"]))
            # Dimming belongs to the artist surface; host labels and state
            # indicators keep the contrast chosen by the disabled palette.
            painter.setOpacity(1.0)
        else:
            option = QStyleOptionButton()
            self.initStyleOption(option)
            option.text = ""
            self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        color = self.palette().buttonText().color()
        if transport:
            draw_transport_icon(painter, self.objectName(), self.text(), self.rect(), color)
        else:
            painter.setPen(color)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.text())
        if self.hasFocus() or self.property("pending"):
            painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.PenStyle.DashLine))
            painter.drawRect(self.rect().adjusted(2, 2, -3, -3))


class FaceSurface(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("faceSurface")
        self._background = QPixmap()
        self._drag = QRect()
        self._drag_offset: QPoint | None = None

    def apply_face(self, face: Face, artwork: FaceArtwork, scale: float) -> None:
        self._background = artwork.background
        self._drag = QRect(*(round(value * scale) for value in face.drag))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self._background)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() != Qt.MouseButton.LeftButton
            or not self._drag.contains(event.position().toPoint())
        ):
            super().mousePressEvent(event)
            return
        window = self.window()
        handle = window.windowHandle()
        # Let the compositor own moving on Wayland; use coordinates only when
        # the platform cannot start a native move (for example, offscreen Qt).
        if handle is None or not handle.startSystemMove():
            self._drag_offset = event.globalPosition().toPoint() - window.pos()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        super().mouseReleaseEvent(event)
