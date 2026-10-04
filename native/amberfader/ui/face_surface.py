"""Image-backed presentation of the host's existing Qt controls."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBitmap,
    QColor,
    QFont,
    QFontMetrics,
    QImage,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRegion,
)
from PySide6.QtWidgets import (
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSlider,
    QWidget,
)

from ..face_library import Face, FaceError

FONT_FAMILIES = {"sans": "sans-serif", "mono": "monospace", "serif": "serif"}
TRANSPORT_CONTROLS = frozenset(("previous", "play", "next"))
READOUT_CONTROLS = frozenset(("title", "artists", "time", "playback", "status"))
READOUT_ALIGNMENT = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
}
KEYBOARD_FOCUS_REASONS = frozenset((
    Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason,
    Qt.FocusReason.ShortcutFocusReason,
))
# Window activation and closed popups return focus without new navigation.
RESTORED_FOCUS_REASONS = frozenset((
    Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.PopupFocusReason,
    Qt.FocusReason.MenuBarFocusReason,
))


@dataclass(frozen=True)
class ReadoutStyle:
    alignment: Qt.AlignmentFlag
    font: str
    size: int
    bold: bool


def readout_style(face: Face, name: str) -> ReadoutStyle:
    """Resolve each face afresh so a centered lens cannot restyle the next face."""
    style = face.readout_styles.get(name, {})
    return ReadoutStyle(
        alignment=READOUT_ALIGNMENT[style.get("align", "left")],
        font=style.get("font", "mono" if name == "time" else face.font),
        size=style.get("size", face.time_size if name == "time" else 12),
        bold=style.get("bold", name == "title"),
    )


def readout_font(face: Face, name: str, scale: float = 1.0) -> QFont:
    style = readout_style(face, name)
    font = QFont(FONT_FAMILIES[style.font])
    if style.font == "mono":
        # macOS may resolve the generic family to a proportional system font.
        font.setStyleHint(QFont.StyleHint.Monospace)
    # Large plugin fonts fit their allotted row instead of clipping into a bevel.
    size = min(style.size, face.controls[name][3] - 2)
    font.setPixelSize(max(10, round(size * scale)))
    font.setBold(style.bold)
    return font


def fit_readout_font(font: QFont, text: str, rect: QRect) -> QFont:
    """Keep every time digit visible in the player and the face chooser."""
    fitted = QFont(font)
    fitted.setPixelSize(min(fitted.pixelSize(), rect.height() - 2))
    width = QFontMetrics(fitted).horizontalAdvance(text)
    if width > rect.width():
        fitted.setPixelSize(max(10, int(fitted.pixelSize() * rect.width() / width)))
    return fitted


def control_path(rect: QRectF, shape: str, radius: float) -> QPainterPath:
    """A constrained contour shared by painting, focus and pointer hits."""
    path = QPainterPath()
    if shape == "ellipse":
        path.addEllipse(rect)
    elif shape in ("rounded", "capsule"):
        corner = min(rect.width(), rect.height()) / 2 if shape == "capsule" else radius
        path.addRoundedRect(rect, corner, corner)
    else:
        path.addRect(rect)
    return path


def draw_cover(
    painter: QPainter, pixmap: QPixmap, rect: QRectF, shape: str, radius: float, glass: bool,
) -> None:
    """Fill a physical aperture without stretching or drawing over its bezel."""
    if pixmap.isNull() or rect.isEmpty():
        return
    path = control_path(rect, shape, radius)
    source = QRectF(pixmap.rect())
    ratio = rect.width() / rect.height()
    if source.width() / source.height() > ratio:
        width = source.height() * ratio
        source.setLeft((source.width() - width) / 2)
        source.setWidth(width)
    else:
        height = source.width() / ratio
        source.setTop((source.height() - height) / 2)
        source.setHeight(height)
    painter.save()
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform,
    )
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    painter.drawPixmap(rect, pixmap, source)
    if glass:
        reflection = QLinearGradient(rect.topLeft(), rect.bottomRight())
        reflection.setColorAt(0, QColor(255, 255, 255, 55))
        reflection.setColorAt(0.45, QColor(255, 255, 255, 0))
        reflection.setColorAt(1, QColor(0, 0, 0, 30))
        painter.fillPath(path, reflection)
    painter.restore()


def draw_slider(
    painter: QPainter, groove: QRectF, handle: QRectF, palette,
    enabled: bool = True, focused: bool = False, upside_down: bool = False,
) -> None:
    """Paint an inset track at the same coordinates Qt uses for interaction."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rim = groove.adjusted(0, -1, 0, 1)
    painter.setPen(QPen(QColor(palette["border"]), 0.8))
    painter.setBrush(QColor(palette["display"]).darker(140))
    painter.drawRoundedRect(rim, rim.height() / 2, rim.height() / 2)
    track = groove.adjusted(1, 0.5, -1, -0.5)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette["accent"] if enabled else palette["muted"]))
    filled = QRectF(track)
    position = max(track.left(), min(track.right(), handle.center().x()))
    if upside_down:
        filled.setLeft(position)
    else:
        filled.setRight(position)
    painter.drawRoundedRect(filled, track.height() / 2, track.height() / 2)
    diameter = min(handle.width(), handle.height()) - 1
    thumb = QRectF(0, 0, diameter, diameter)
    thumb.moveCenter(handle.center())
    gradient = QLinearGradient(thumb.topLeft(), thumb.bottomLeft())
    gradient.setColorAt(0, QColor(palette["buttonTop"]))
    gradient.setColorAt(1, QColor(palette["buttonBottom"]))
    painter.setBrush(gradient)
    painter.setPen(QPen(QColor(palette["border"]), 0.8))
    painter.drawEllipse(thumb)
    core = thumb.adjusted(2, 2, -2, -2)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette["accent"] if enabled else palette["muted"]))
    painter.drawEllipse(core)
    if focused:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(palette["accent"]), 1, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(rim.adjusted(-1, -1, 1, 1), 4, 4)
    painter.restore()


class KeyboardFocusRing:
    """Mark focus reached by keyboard, not the control a pointer just used.

    Qt focuses the cover when the window opens and keeps focus on clicked
    buttons; drawing those rings would leave dashed outlines over every face.
    Programmatic focus (setFocus() defaults to OtherFocusReason) hides the
    ring, so pass a keyboard reason when code moves focus for a keyboard user.
    """

    _keyboard_focus = False

    def focusInEvent(self, event) -> None:
        reason = event.reason()
        if reason in KEYBOARD_FOCUS_REASONS:
            self._keyboard_focus = True
        elif reason not in RESTORED_FOCUS_REASONS:
            self._keyboard_focus = False
        super().focusInEvent(event)

    def focus_ring_visible(self) -> bool:
        return self.hasFocus() and self._keyboard_focus


class FaceSlider(KeyboardFocusRing, QSlider):
    """Face painting keeps QSlider's input, accessibility and signal behavior."""

    def __init__(self, orientation: Qt.Orientation, parent: QWidget) -> None:
        super().__init__(orientation, parent)
        self._face: Face | None = None

    def set_face(self, face: Face) -> None:
        self._face = face
        self.update()

    def paintEvent(self, event) -> None:
        if self._face is None or self._face.slider_style == "classic":
            super().paintEvent(event)
            return
        option = QStyleOptionSlider()
        self.initStyleOption(option)
        style = self.style()
        groove = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderGroove, self,
        )
        handle = style.subControlRect(
            QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, self,
        )
        painter = QPainter(self)
        draw_slider(
            painter, QRectF(groove), QRectF(handle), self._face.palette,
            self.isEnabled(), self.focus_ring_visible(), option.upsideDown,
        )


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


def like_font_size(face: Face) -> int:
    # Scale the heart with its button like the drawn transport glyphs. The
    # 12 px floor still fits the unknown-state "♡?" in a 22 px v1 button.
    _, _, width, height = face.controls["like"]
    return max(12, min(18, round(min(width, height) / 2)))


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
    QLabel#title, QLabel#artists, QLabel#time, QLabel#playback {{ color: {p['readout']}; }}
    QLabel#dim, QLabel#status {{ color: {p['muted']}; }}
    QLabel#status[error="true"] {{ color: {p['danger']}; }}
    QPushButton {{
      background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
        stop:0 {p['buttonTop']}, stop:1 {p['buttonBottom']});
      border: 1px solid {p['border']}; border-radius: {radius}px;
      padding: 0px {round(2 * scale)}px;
    }}
    QPushButton#like {{ font-size: {round(like_font_size(face) * scale)}px; }}
    QPushButton:hover:!disabled, QPushButton:focus {{ border-color: {p['accent']}; }}
    QPushButton:pressed, QPushButton[pending="true"] {{
      background: {p['accent']}; color: {p['window']};
    }}
    QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; }}
    QDialog QLabel#dim {{ color: {p['text']}; }}
    QDialog QPushButton:disabled {{ color: {p['text']}; background: {p['panel']}; }}
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
    for name in sorted(READOUT_CONTROLS):
        font = readout_font(face, name, scale)
        weight = "bold" if font.bold() else "normal"
        stylesheet += (
            f"QLabel#{name} {{ font-family: {font.family()}; "
            f"font-size: {font.pixelSize()}px; font-weight: {weight}; }}\n"
        )
    return stylesheet


def draw_transport_icon(
    painter: QPainter, name: str, text: str, rect: QRect, color: QColor
) -> None:
    """Draw transport symbols independently of installed Unicode fonts."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    # QRect.center() rounds down, which shifts glyphs on even-sized buttons.
    painter.translate(QRectF(rect).center())
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
        # Bar and triangles span -0.48..0.48, so the skip glyph's ink is centered.
        painter.drawRect(QRectF(-0.48, -0.45, 0.12, 0.9))
        for x in (-0.28, 0.12):
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
        font = fit_readout_font(self.font(), self.text(), self.rect())
        painter.setFont(font)
        painter.setPen(self.palette().windowText().color())
        painter.drawText(self.rect(), self.alignment(), self.text())


class CoverLabel(KeyboardFocusRing, QLabel):
    activated = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("View album cover")
        self.setToolTip("View album cover")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._shape = "rectangle"
        self._radius = 0.0
        self._glass = False

    def set_shape(self, shape: str, radius: float, glass: bool) -> None:
        self._shape, self._radius, self._glass = shape, radius, glass
        self.update()

    def _cover_path(self) -> QPainterPath:
        return control_path(QRectF(self.rect()), self._shape, self._radius)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        draw_cover(
            painter, self.pixmap(), QRectF(self.rect()), self._shape, self._radius, self._glass,
        )
        if self.focus_ring_visible():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.PenStyle.DashLine))
            painter.drawPath(control_path(
                QRectF(self.rect()).adjusted(2, 2, -2, -2), self._shape, self._radius,
            ))

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._cover_path().contains(event.position())
        ):
            self.activated.emit()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.activated.emit()
            return
        super().keyPressEvent(event)


class FaceButton(KeyboardFocusRing, QPushButton):
    """Optional artist sprites retain host labels, focus and pending states."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self._sprites: dict[str, QPixmap] = {}
        self._shape = "rectangle"
        self._radius = 0.0

    def set_shape(self, shape: str, radius: float) -> None:
        self._shape, self._radius = shape, radius
        self.update()

    def hitButton(self, position: QPoint) -> bool:
        path = control_path(QRectF(self.rect()), self._shape, self._radius)
        return path.contains(QPointF(position))

    def _indicator_path(self) -> QPainterPath:
        return control_path(
            QRectF(self.rect()).adjusted(2, 2, -2, -2), self._shape, self._radius,
        )

    def set_sprites(self, sprites: dict[str, QPixmap]) -> None:
        self._sprites = sprites
        self.update()

    def paintEvent(self, event) -> None:
        transport = self.objectName() in TRANSPORT_CONTROLS
        if not self._sprites and not transport and self._shape == "rectangle":
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, self._shape != "rectangle")
        painter.setClipPath(control_path(QRectF(self.rect()), self._shape, self._radius))
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
            option.state &= ~QStyle.StateFlag.State_HasFocus
            self.style().drawControl(QStyle.ControlElement.CE_PushButton, option, painter, self)
        color = self.palette().buttonText().color()
        label_rect = self.rect().translated(0, 1) if self.isDown() else self.rect()
        if transport:
            draw_transport_icon(painter, self.objectName(), self.text(), label_rect, color)
        else:
            painter.setPen(color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.text())
        if self.focus_ring_visible() or self.property("pending"):
            painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.PenStyle.DashLine))
            painter.drawPath(self._indicator_path())


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
