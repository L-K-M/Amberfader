"""Image-backed presentation of the host's existing Qt controls."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from math import ceil, floor

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import (
    QBitmap,
    QColor,
    QFont,
    QFontDatabase,
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
    QFrame,
    QGraphicsEffect,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QPushButton,
    QSlider,
    QStyle,
    QStyleOptionButton,
    QStyleOptionSlider,
    QVBoxLayout,
    QWidget,
)

from ..face_library import FACE_FORMAT_VERSION, Face, FaceError, Rect, control_polygon

FONT_FAMILIES = {"sans": "sans-serif", "mono": "monospace", "serif": "serif"}
TRANSPORT_CONTROLS = frozenset(("previous", "play", "next"))
READOUT_CONTROLS = frozenset(("title", "artists", "time", "playback", "status"))
PREVIEW_LABELS = {
    "title": "A face for your music", "artists": "Amberfader · Face preview",
    "time": "03:48 / 04:30", "playback": "PREVIEW", "previous": "⏮", "play": "▶",
    "next": "⏭", "like": "♥", "search": "Search", "show": "Show YT", "hide": "Hide",
    "menu": "☰", "minimize": "\u2212", "close": "\u00d7", "status": "Firefox keeps playing",
}

READOUT_ALIGNMENT = {
    "left": Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
    "center": Qt.AlignmentFlag.AlignCenter,
    "right": Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
}


@dataclass(frozen=True)
class ReadoutStyle:
    alignment: Qt.AlignmentFlag
    font: str
    size: int
    bold: bool
    font_family: str | None = None
    color: str | None = None
    italic: bool = False


def readout_style(face: Face, name: str) -> ReadoutStyle:
    """Resolve each face afresh so a centered lens cannot restyle the next face."""
    style = face.readout_styles.get(name, {})
    return ReadoutStyle(
        alignment=READOUT_ALIGNMENT[style.get("align", "left")],
        font=style.get("font", "mono" if name == "time" else face.font),
        size=style.get("size", face.time_size if name == "time" else 12),
        bold=style.get("bold", name == "title"),
        font_family=style.get("fontFamily"),
        color=style.get("color"),
        italic=style.get("italic", False),
    )


def readout_font(face: Face, name: str, scale: float = 1.0) -> QFont:
    style = readout_style(face, name)
    font = _readout_base_font(style)
    if style.font == "mono" and style.font_family is None:
        # macOS may resolve the generic family to a proportional system font.
        font.setStyleHint(QFont.StyleHint.Monospace)
    # Large plugin fonts fit their allotted row instead of clipping into a bevel.
    size = min(style.size, face.controls[name][3] - 2)
    font.setPixelSize(max(6 if face.format_version >= 3 else 10, round(size * scale)))
    font.setBold(style.bold)
    font.setItalic(style.italic)
    return font


def _readout_base_font(style: ReadoutStyle) -> QFont:
    if style.font_family is None:
        return QFont(FONT_FAMILIES[style.font])
    # An obsolete imported family can make CoreText attempt a synchronous
    # font download. Match only Qt's available families; retain the requested
    # name in the document for another machine with that font installed.
    requested = style.font_family.casefold()
    family = next((family for family in QFontDatabase.families()
                   if family.casefold() == requested), None)
    if family is not None:
        return QFont(family)
    system = (
        QFontDatabase.SystemFont.FixedFont if style.font == "mono"
        else QFontDatabase.SystemFont.GeneralFont
    )
    return QFontDatabase.systemFont(system)


def fit_readout_font(font: QFont, text: str, rect: QRect, minimum_size: int = 10) -> QFont:
    """Keep every time digit visible in the player and the face chooser."""
    fitted = QFont(font)
    fitted.setPixelSize(min(fitted.pixelSize(), rect.height() - 2))
    width = QFontMetrics(fitted).horizontalAdvance(text)
    if width > rect.width():
        fitted.setPixelSize(max(minimum_size, int(fitted.pixelSize() * rect.width() / width)))
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


class _SliderPopup(QFrame):
    dismissed = Signal()

    def hideEvent(self, event) -> None:
        self.dismissed.emit()
        super().hideEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
            return
        super().keyPressEvent(event)


class _PopupSlider(QSlider):
    """Commit changed keyboard values through the owner's native gesture path."""

    def __init__(self, owner: FaceSlider, parent: QWidget) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._owner = owner
        self._keyboard_action = False
        self.actionTriggered.connect(self._begin_keyboard_gesture)

    def _begin_keyboard_gesture(self, _action: int) -> None:
        # Qt adjusts sliderPosition before actionTriggered and propagates value
        # afterwards. Start here so unchanged keys at a bound do not commit.
        if self._keyboard_action and self.sliderPosition() != self.value():
            self.setSliderDown(True)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() not in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down,
            Qt.Key.Key_Home, Qt.Key.Key_End, Qt.Key.Key_PageUp, Qt.Key.Key_PageDown,
        ):
            super().keyPressEvent(event)
            return
        if (
            not self._owner.isEnabled() or not self.isEnabled() or not self.isVisible()
            or self.isSliderDown() or self._owner.isSliderDown()
        ):
            event.accept()
            return
        self._keyboard_action = True
        try:
            super().keyPressEvent(event)
        finally:
            self._keyboard_action = False
        # Disabling, dismissal or a face change during the gesture cancels both
        # sliders. Release only a gesture which survived those existing guards.
        if self.isSliderDown():
            self.setSliderDown(False)


class FaceSlider(QSlider):
    """Face painting keeps QSlider's input, accessibility and signal behavior."""

    gestureCancelled = Signal()

    def __init__(self, orientation: Qt.Orientation, parent: QWidget) -> None:
        super().__init__(orientation, parent)
        self._face: Face | None = None
        self._sprites: dict[str, QPixmap] = {}
        self._popup_parent = parent.window()
        self._popup: _SliderPopup | None = None
        self._popup_slider: QSlider | None = None
        self._popup_anchor: Callable[[], QPoint] | None = None
        self.valueChanged.connect(self._sync_popup_value)

    def set_face(self, face: Face, sprites: dict[str, QPixmap] | None = None) -> None:
        if self._face is not None and (
            self._face.info.id != face.info.id
            or self._face.slider_style != face.slider_style
        ) and (self._face.slider_style == "popup" or face.slider_style == "popup"):
            self.cancel_popup()
        self._face = face
        self._sprites = sprites or {}
        self.update()

    def set_popup_anchor(self, anchor: Callable[[], QPoint]) -> None:
        self._popup_anchor = anchor

    def _sync_popup_value(self, value: int) -> None:
        if self._popup_slider is not None:
            with QSignalBlocker(self._popup_slider):
                self._popup_slider.setValue(value)

    def _cancel_popup_gesture(self) -> None:
        if self._popup_slider is not None:
            with QSignalBlocker(self._popup_slider):
                self._popup_slider.setSliderDown(False)
        if self.isSliderDown():
            with QSignalBlocker(self):
                self.setSliderDown(False)
            self.gestureCancelled.emit()

    def cancel_popup(self) -> None:
        self._cancel_popup_gesture()
        if self._popup is not None:
            self._popup.hide()

    def _show_popup(self) -> None:
        if not self.isEnabled():
            return
        if self._popup is None:
            self._popup = _SliderPopup(
                self._popup_parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint,
            )
            self._popup.setFrameShape(QFrame.Shape.StyledPanel)
            layout = QVBoxLayout(self._popup)
            layout.setContentsMargins(8, 8, 8, 8)
            self._popup_slider = _PopupSlider(self, self._popup)
            self._popup_slider.setMinimumWidth(192)
            self._popup_slider.setAccessibleName(self.accessibleName())
            self._popup_slider.setToolTip(self.toolTip())
            layout.addWidget(self._popup_slider)
            self._popup_slider.sliderPressed.connect(lambda: self.setSliderDown(True))
            self._popup_slider.sliderMoved.connect(self.setSliderPosition)
            self._popup_slider.valueChanged.connect(self.setValue)
            self._popup_slider.sliderReleased.connect(lambda: self.setSliderDown(False))
            self._popup.dismissed.connect(self._cancel_popup_gesture)
        self._popup_slider.setRange(self.minimum(), self.maximum())
        self._popup_slider.setSingleStep(self.singleStep())
        self._popup_slider.setPageStep(self.pageStep())
        self._sync_popup_value(self.value())
        self._popup.adjustSize()
        anchor = (
            self._popup_anchor() if self._popup_anchor is not None
            else self.mapToGlobal(QPoint(0, self.height()))
        )
        screen = self._popup.screen()
        if screen is not None:
            available = screen.availableGeometry()
            anchor.setX(max(
                available.left(), min(anchor.x(), available.right() - self._popup.width()),
            ))
            anchor.setY(max(
                available.top(), min(anchor.y(), available.bottom() - self._popup.height()),
            ))
        self._popup.move(anchor)
        self._popup.show()
        self._popup_slider.setFocus(Qt.FocusReason.PopupFocusReason)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.cancel_popup()
        super().changeEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            self._face is not None and self._face.slider_style == "popup"
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._show_popup()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._face is not None and self._face.slider_style == "popup":
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._face is not None and self._face.slider_style == "popup":
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if (
            self._face is not None and self._face.slider_style == "popup"
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space)
        ):
            self._show_popup()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        if self._face is not None and self._face.slider_style == "popup":
            painter = QPainter(self)
            if self._sprites:
                state = "disabled" if not self.isEnabled() else (
                    "pressed" if self._popup is not None and self._popup.isVisible()
                    else "hover" if self.underMouse() else "normal"
                )
                if state == "disabled" and state not in self._sprites:
                    painter.setOpacity(0.5)
                painter.drawPixmap(self.rect(), self._sprites.get(state, self._sprites["normal"]))
            if self.hasFocus():
                painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.PenStyle.DashLine))
                painter.drawRect(self.rect().adjusted(1, 1, -1, -1))
            return
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
            self.isEnabled(), self.hasFocus(), option.upsideDown,
        )


@dataclass(frozen=True)
class DigitArtwork:
    rect: Rect
    images: tuple[QPixmap, ...]


@dataclass(frozen=True)
class FaceArtwork:
    background: QPixmap
    mask: QRegion
    buttons: dict[str, dict[str, QPixmap]]
    time_digits: tuple[DigitArtwork, ...] = ()
    alpha_mask: QPixmap | None = None
    format_version: int = FACE_FORMAT_VERSION
    _hit_source: QPixmap | None = None

    def scaled_mask(self, size: tuple[int, int]) -> QRegion:
        source = self.alpha_mask or self._hit_source or self.background
        return _alpha_mask(source, size, self.format_version)


def _alpha_mask(background: QPixmap, size: tuple[int, int], format_version: int) -> QRegion:
    # QPixmap.mask() is empty for fully opaque images. An explicit alpha mask
    # keeps rectangular and sculpted faces on the same hit-testing path.
    image = background.toImage().scaled(*size)
    if not image.hasAlphaChannel():
        return QRegion(QRect(0, 0, *size))
    if format_version >= 3:
        # Imported screens may be intentionally almost transparent. Premultiply
        # first so alpha-zero RGB data cannot create invisible native hit areas.
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        # QBitmap/QRegion treat black pixels as set; MaskInColor paints the
        # matching transparent-zero pixels white and every visible pixel black.
        alpha = image.createMaskFromColor(0, Qt.MaskMode.MaskInColor)
    else:
        alpha = image.createAlphaMask(Qt.ImageConversionFlag.ThresholdAlphaDither)
    return QRegion(QBitmap.fromImage(alpha))


def _decode(data: bytes) -> QPixmap:
    image = QImage.fromData(data, "PNG")
    if image.isNull():
        raise FaceError("Face contains a PNG that Qt cannot decode")
    return QPixmap.fromImage(image)


def prepare_face(face: Face) -> FaceArtwork:
    """Decode before committing a selection; invisible controls are invalid."""
    artwork = prepare_face_preview(face)
    for name, rect in {**face.controls, "drag": face.drag}.items():
        rotation = face.control_rotations.get(name, 0)
        if rotation:
            polygon = QPolygonF([QPointF(x, y) for x, y in control_polygon(rect, rotation)])
            footprint = QRegion(polygon.toPolygon())
        else:
            footprint = QRegion(QRect(*rect))
        if face.format_version >= 3:
            invisible = footprint.intersected(artwork.mask).isEmpty()
        else:
            invisible = not footprint.subtracted(artwork.mask).isEmpty()
        if invisible:
            raise FaceError(f"{name} must sit on the opaque face, not a transparent cutout")
    return artwork


def prepare_face_preview(face: Face) -> FaceArtwork:
    """Decode an unfinished editor draft without accepting it for installation."""
    decoded: dict[bytes, QPixmap] = {}

    def decode(data: bytes) -> QPixmap:
        if data not in decoded:
            decoded[data] = _decode(data)
        return decoded[data]

    background = decode(face.background)
    alpha_mask = decode(face.alpha_mask) if face.alpha_mask is not None else None
    buttons = {
        name: {state: decode(data) for state, data in images.items()}
        for name, images in face.buttons.items()
    }
    digits = tuple(DigitArtwork(digit.rect, tuple(decode(data) for data in digit.images))
                   for digit in face.time_digits)
    hit_source = (
        _assembled_hit_source(face, background, buttons)
        if face.format_version >= 3 and alpha_mask is None else None
    )
    mask = _alpha_mask(alpha_mask or hit_source or background, face.size, face.format_version)
    return FaceArtwork(
        background=background, mask=mask, buttons=buttons, time_digits=digits,
        alpha_mask=alpha_mask, format_version=face.format_version, _hit_source=hit_source,
    )


def _assembled_hit_source(face: Face, background: QPixmap, buttons) -> QPixmap:
    """Keep maskless shells hittable across sprites, changing text and cover art."""
    composite = QPixmap(*face.size)
    composite.fill(Qt.GlobalColor.transparent)
    painter = QPainter(composite)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(QRect(0, 0, *face.size), background)
    for name, coordinates in face.controls.items():
        painter.save()
        rect = QRect(*coordinates)
        rotation = face.control_rotations.get(name, 0)
        if rotation:
            center = QRectF(rect).center()
            painter.translate(center)
            painter.rotate(rotation)
            painter.translate(-center)
        if name in READOUT_CONTROLS or name == "art":
            # Text and artwork change shape independently of the shell. All
            # clock glyphs (including textual fallback) fit their time region.
            painter.fillRect(rect, Qt.GlobalColor.black)
        elif name in buttons:
            if name not in ("seek", "volume"):
                painter.setClipPath(control_path(
                    QRectF(rect), face.control_shapes.get(name, "rectangle"), face.radius,
                ))
            # A pause/pressed/disabled sprite may extend beyond normal's alpha.
            for image in buttons[name].values():
                painter.drawPixmap(rect, image)
        elif name not in ("seek", "volume"):
            painter.fillPath(control_path(
                QRectF(rect), face.control_shapes.get(name, "rectangle"), face.radius,
            ), Qt.GlobalColor.black)
        elif face.slider_style != "popup":
            painter.fillRect(rect, Qt.GlobalColor.black)
        painter.restore()
    painter.end()
    return composite


def _elapsed_digits(text: str) -> tuple[int, int, int, int] | None:
    elapsed = text.split("/", 1)[0].strip()
    minutes, separator, seconds = elapsed.partition(":")
    if not separator or not minutes.isdecimal() or not seconds.isdecimal():
        return None
    minute, second = int(minutes), int(seconds)
    if not 0 <= minute < 100 or not 0 <= second < 60:
        return None
    return minute // 10, minute % 10, second // 10, second % 10


def draw_time_digits(
    painter: QPainter, digits: tuple[DigitArtwork, ...], text: str, rect: QRect,
) -> bool:
    """Preserve Audion's four elapsed-time sprites and its baked-in colon."""
    values = _elapsed_digits(text)
    if len(digits) != 4 or values is None:
        return False
    bounds = QRectF()
    for digit in digits:
        bounds = bounds.united(QRectF(*digit.rect))
    if bounds.isEmpty() or rect.isEmpty():
        return False
    painter.save()
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / bounds.width(), rect.height() / bounds.height())
    painter.translate(-bounds.x(), -bounds.y())
    for digit, value in zip(digits, values, strict=True):
        painter.drawPixmap(QRect(*digit.rect), digit.images[value])
    painter.restore()
    return True


def draw_face_preview(
    painter: QPainter, face: Face, artwork: FaceArtwork, cover: QPixmap,
    labels: dict[str, str] | None = None,
) -> None:
    """Paint the picker and editor using one logical-coordinate face renderer."""
    labels = PREVIEW_LABELS if labels is None else {**PREVIEW_LABELS, **labels}
    if artwork.alpha_mask is not None:
        # Audion masks its assembled view once, after sprites and readouts.
        # Applying it to individual layers changes antialiased edge opacity.
        composite = QPixmap(*face.size)
        composite.fill(Qt.GlobalColor.transparent)
        layers = QPainter(composite)
        _draw_face_layers(layers, face, artwork, cover, labels)
        layers.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        layers.drawPixmap(QRect(0, 0, *face.size), artwork.alpha_mask)
        layers.end()
        painter.drawPixmap(0, 0, composite)
        return
    _draw_face_layers(painter, face, artwork, cover, labels)


def _draw_face_layers(painter, face, artwork, cover, labels) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawPixmap(QRect(0, 0, *face.size), artwork.background)
    for name, coordinates in face.controls.items():
        painter.save()
        rect = QRect(*coordinates)
        rotation = face.control_rotations.get(name, 0)
        if rotation:
            center = QRectF(rect).center()
            painter.translate(center)
            painter.rotate(rotation)
            painter.translate(-center)
        _draw_preview_control(painter, face, artwork, cover, labels, name, coordinates)
        painter.restore()
    painter.restore()


def _draw_preview_control(painter, face, artwork, cover, labels, name, coordinates) -> None:
    p = face.palette
    rect = QRect(*coordinates)
    style = readout_style(face, name) if name in READOUT_CONTROLS else None
    painter.setPen(QColor(style.color if style and style.color else p["readout"]))
    if name in READOUT_CONTROLS:
        font = readout_font(face, name)
    else:
        font = QFont(FONT_FAMILIES[face.font])
        font.setPixelSize(like_font_size(face) if name == "like" else 12)
    if name == "time":
        if draw_time_digits(painter, artwork.time_digits, labels["time"], rect):
            return
        text = labels["time"].split("/", 1)[0].strip() if artwork.time_digits else labels["time"]
        font = fit_readout_font(font, text, rect, 1 if artwork.time_digits else 10)
    painter.setFont(font)
    if name == "art":
        draw_cover(
            painter, cover, QRectF(rect), face.control_shapes.get("art", "rectangle"),
            face.radius, face.cover_glass,
        )
        return
    if name in ("seek", "volume"):
        if face.slider_style == "popup":
            if name in artwork.buttons:
                painter.drawPixmap(rect, artwork.buttons[name]["normal"])
            return
        if face.slider_style == "inset":
            groove = QRectF(rect.x(), rect.y() + (rect.height() - 4) / 2, rect.width(), 4)
            # The 12px QSS handle has a 1px border on either side.
            handle = QRectF(
                rect.center().x() - 6, rect.y() + (rect.height() - 14) / 2, 14, 14,
            )
            draw_slider(painter, groove, handle, p)
            return
        groove = rect.adjusted(4, rect.height() // 2 - 2, -4, -(rect.height() // 2 - 2))
        painter.fillRect(groove, QColor(p["display"]))
        groove.setWidth(groove.width() // 2)
        painter.fillRect(groove, QColor(p["accent"]))
        return
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
            sprites = artwork.buttons[name]
            state = "playing" if name == "play" and labels[name] == "⏸" else "normal"
            painter.drawPixmap(rect, sprites.get(state, sprites["normal"]))
        else:
            gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            gradient.setColorAt(0, QColor(p["buttonTop"]))
            gradient.setColorAt(1, QColor(p["buttonBottom"]))
            painter.setBrush(gradient)
            painter.setPen(QColor(p["border"]))
            painter.drawPath(path)
        painter.restore()
        if name in artwork.buttons and not face.sprite_labels:
            return
        painter.setPen(QColor(p["text"]))
    elif name == "status" and not (style and style.color):
        painter.setPen(QColor(p["muted"]))
    if name in TRANSPORT_CONTROLS:
        draw_transport_icon(painter, name, labels[name], rect, QColor(p["text"]))
        return
    text = labels.get(name, "")
    if name == "time" and artwork.time_digits:
        text = text.split("/", 1)[0].strip()
    if name != "time":
        text = painter.fontMetrics().elidedText(
            text, Qt.TextElideMode.ElideRight, rect.width()
        )
    alignment = (
        readout_style(face, name).alignment if name in READOUT_CONTROLS
        else Qt.AlignmentFlag.AlignCenter
    )
    painter.drawText(rect, alignment, text)


def like_font_size(face: Face) -> int:
    # A narrow v1 plugin button must still display the unknown-state question mark.
    return 18 if face.controls.get("like", (0, 0, 40, 22))[2] >= 40 else 12


def face_stylesheet(face: Face, scale: float) -> str:
    """Generate styles from constrained tokens; packs cannot inject QSS."""
    p = face.palette
    font_size = max(10, round(12 * scale))
    radius = round(face.radius * scale)
    handle = round(12 * scale)
    family_rule = (
        f"font-family: {FONT_FAMILIES[face.font]};" if face.format_version < 3 else ""
    )
    stylesheet = f"""
    QWidget {{
      color: {p['text']}; {family_rule} font-size: {font_size}px;
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
        corner = max(0, round(min(face.radius, width // 2 - 1, height // 2 - 1) * scale))
        stylesheet += f"QPushButton#{name} {{ border-radius: {corner}px; }}\n"
    for name in sorted(READOUT_CONTROLS.intersection(face.controls)):
        font = readout_font(face, name, scale)
        weight = "bold" if font.bold() else "normal"
        family = f"font-family: {font.family()}; " if face.format_version < 3 else ""
        italic = "italic" if font.italic() else "normal"
        stylesheet += (
            f"QLabel#{name} {{ {family}font-size: {font.pixelSize()}px; "
            f"font-weight: {weight}; font-style: {italic}; }}\n"
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
        color = self.property("readoutColor")
        painter.setPen(QColor(color) if color else self.palette().windowText().color())
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, self.width())
        painter.drawText(self.rect(), self.alignment(), text)


class ReadoutLabel(QLabel):
    """Fit the complete position/duration readout instead of clipping digits."""

    def __init__(self, text: str, parent: QWidget) -> None:
        super().__init__(text, parent)
        self._digits: tuple[DigitArtwork, ...] = ()

    def set_time_digits(self, digits: tuple[DigitArtwork, ...]) -> None:
        self._digits = digits
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        if draw_time_digits(painter, self._digits, self.text(), self.rect()):
            return
        text = self.text().split("/", 1)[0].strip() if self._digits else self.text()
        font = fit_readout_font(
            self.font(), text, self.rect(),
            1 if self._digits else (self.property("minimumReadoutSize") or 10),
        )
        painter.setFont(font)
        color = self.property("readoutColor")
        painter.setPen(QColor(color) if color else self.palette().windowText().color())
        painter.drawText(self.rect(), self.alignment(), text)


class CoverLabel(QLabel):
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
        self._pressed = False

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
        if self.hasFocus():
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.PenStyle.DashLine))
            painter.drawPath(control_path(
                QRectF(self.rect()).adjusted(2, 2, -2, -2), self._shape, self._radius,
            ))

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._pressed = (
            event.button() == Qt.MouseButton.LeftButton
            and self._cover_path().contains(event.position())
        )
        if self._pressed:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if (
            self._pressed and event.button() == Qt.MouseButton.LeftButton
            and self._cover_path().contains(event.position())
        ):
            self.activated.emit()
        self._pressed = False
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
        self._shape = "rectangle"
        self._radius = 0.0
        self._sprite_labels = True

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

    def set_sprites(self, sprites: dict[str, QPixmap], *, labels: bool = True) -> None:
        self._sprites = sprites
        self._sprite_labels = labels
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
            playing = self.objectName() == "play" and self.property("playing")
            base = "playing" if playing and "playing" in self._sprites else "normal"
            key = base if state == "normal" else (
                f"playing-{state}" if base == "playing" else state
            )
            if state == "disabled" and key not in self._sprites:
                painter.setOpacity(0.5)
            painter.drawPixmap(self.rect(), self._sprites.get(key, self._sprites[base]))
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
        if self._sprites and not self._sprite_labels:
            pass
        elif transport:
            draw_transport_icon(painter, self.objectName(), self.text(), label_rect, color)
        else:
            painter.setPen(color)
            painter.drawText(label_rect, Qt.AlignmentFlag.AlignCenter, self.text())
        if self.hasFocus() or self.property("pending"):
            painter.setPen(QPen(self.palette().highlight().color(), 1, Qt.PenStyle.DashLine))
            painter.drawPath(self._indicator_path())


class RotatedControl(QGraphicsView):
    """Embed the real native control; Qt maps pointer and keyboard events back."""

    def __init__(self, widget: QWidget, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform,
        )
        self.setStyleSheet("QGraphicsView { background: transparent; border: none; }")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.viewport().setAutoFillBackground(False)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        widget.hide()
        widget.setParent(None)
        widget.setGeometry(0, 0, widget.width(), widget.height())
        self._proxy: QGraphicsProxyWidget = self._scene.addWidget(widget)
        widget.show()
        self.setFocusPolicy(widget.focusPolicy())

    def apply_geometry(self, rect: Rect, rotation: float) -> None:
        x, y, width, height = rect
        polygon = QPolygonF([QPointF(px, py) for px, py in control_polygon(rect, rotation)])
        bounds = polygon.boundingRect()
        left, top = floor(bounds.left()), floor(bounds.top())
        right, bottom = ceil(bounds.right()), ceil(bounds.bottom())
        self.setGeometry(left, top, right - left, bottom - top)
        self.setSceneRect(0, 0, right - left, bottom - top)
        self._proxy.setRotation(0)
        self._proxy.widget().resize(width, height)
        self._proxy.setTransformOriginPoint(width / 2, height / 2)
        self._proxy.setPos(x - left, y - top)
        self._proxy.setRotation(rotation)
        polygon.translate(-left, -top)
        # Bounding-box corners remain available to the shell and adjacent
        # controls, rather than forming an invisible rectangular click blocker.
        self.setMask(QRegion(polygon.toPolygon()))
        self.show()

    def map_control_to_global(self, point: QPoint) -> QPoint:
        position = self.mapFromScene(self._proxy.mapToScene(QPointF(point)))
        return self.viewport().mapToGlobal(position)

    def detach(self, parent: QWidget) -> QWidget:
        widget = self._proxy.widget()
        self._proxy.setWidget(None)
        widget.setParent(parent)
        widget.setStyleSheet("")
        widget.show()
        self.hide()
        self.deleteLater()
        return widget


class _FaceMaskEffect(QGraphicsEffect):
    """Mask the shell and all child controls in one composition, including proxies."""

    def __init__(self, surface: QWidget) -> None:
        super().__init__(surface)
        self._surface = surface
        self._mask = QPixmap()

    def set_mask(self, mask: QPixmap) -> None:
        self._mask = mask
        self.update()

    def draw(self, painter: QPainter) -> None:
        offset = QPoint()
        source = self.sourcePixmap(
            Qt.CoordinateSystem.LogicalCoordinates, offset, QGraphicsEffect.PixmapPadMode.NoPad,
        )
        if source.isNull():
            return
        # sourcePixmap retains its physical DPR; mask placement uses logical
        # coordinates so 1x and 2x displays retain the same source geometry.
        mask = QPixmap(source.size())
        mask.setDevicePixelRatio(source.devicePixelRatio())
        mask.fill(Qt.GlobalColor.transparent)
        mask_painter = QPainter(mask)
        mask_painter.drawPixmap(self._surface.rect().translated(-offset), self._mask)
        mask_painter.end()
        composition = QPainter(source)
        composition.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        composition.drawPixmap(0, 0, mask)
        composition.end()
        painter.drawPixmap(offset, source)


class FaceSurface(QWidget):
    menuRequested = Signal(QPoint)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("faceSurface")
        self._background = QPixmap()
        self._drag = QRect()
        self._drag_offset: QPoint | None = None
        self._rotated: dict[str, RotatedControl] = {}

    def apply_face(self, face: Face, artwork: FaceArtwork, scale: float) -> None:
        self._background = artwork.background
        self._drag = QRect(*(round(value * scale) for value in face.drag))
        if artwork.alpha_mask is None:
            if self.graphicsEffect() is not None:
                self.setGraphicsEffect(None)
        else:
            effect = self.graphicsEffect()
            if not isinstance(effect, _FaceMaskEffect):
                effect = _FaceMaskEffect(self)
                self.setGraphicsEffect(effect)
            effect.set_mask(artwork.alpha_mask)
        self.update()

    def place_control(
        self, name: str, widget: QWidget, rect: Rect, rotation: float, stylesheet: str,
    ) -> None:
        wrapper = self._rotated.get(name)
        focused = widget.hasFocus()
        if rotation:
            if wrapper is None:
                wrapper = RotatedControl(widget, self)
                self._rotated[name] = wrapper
            # The embedded top-level widget needs the same constrained style
            # as its siblings; it no longer inherits from the player window.
            widget.setStyleSheet(stylesheet)
            wrapper.apply_geometry(rect, rotation)
            if focused:
                wrapper.setFocus()
                wrapper._proxy.setFocus()
                widget.setFocus()
            return
        if wrapper is not None:
            wrapper.detach(self)
            del self._rotated[name]
        widget.setGeometry(*rect)
        widget.show()
        if focused:
            widget.setFocus()

    def needs_rehosting(self, name: str, rotation: float) -> bool:
        return (name in self._rotated) != bool(rotation)

    def hide_control(self, name: str, widget: QWidget) -> None:
        wrapper = self._rotated.pop(name, None)
        if wrapper is not None:
            wrapper.detach(self)
        widget.hide()

    def control_global_position(self, name: str, widget: QWidget, point: QPoint) -> QPoint:
        wrapper = self._rotated.get(name)
        return wrapper.map_control_to_global(point) if wrapper else widget.mapToGlobal(point)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawPixmap(self.rect(), self._background)

    def contextMenuEvent(self, event) -> None:
        self.menuRequested.emit(event.globalPos())
        event.accept()

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
