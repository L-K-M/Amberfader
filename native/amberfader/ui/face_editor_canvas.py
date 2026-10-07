"""A logical-coordinate canvas for editing presentation without player commands.

Pointer and keyboard conventions follow Mac drawing apps:

    drag element          move (Shift: horizontal or vertical only)
    drag corner handle    resize around the opposite corner
    drag round handle     rotate (Shift: 15° steps)
    Option while dragging bypass Snap to Grid
    arrow keys            nudge 1 px (Shift: 10 px); a held key is one undo step
    Delete                remove the selected element
    Space-drag, scroll    pan; pinch, ⌘-scroll: zoom
    Escape                cancel the drag in progress
"""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from ..face_document import FaceDocument
from ..face_library import MAX_DRAFT_GEOMETRY, Face, control_bounds
from . import face_elements
from .editor_widgets import high_contrast
from .face_surface import FaceArtwork, control_path, draw_face_preview

MIN_ZOOM = 0.1
MAX_ZOOM = 8.0
ZOOM_STEPS = (0.1, 0.25, 0.33, 0.5, 0.66, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0)
WHEEL_ZOOM_FACTOR = 1.15
HANDLE_EXTENT = 4  # Half the handle size, in screen pixels.
HANDLE_HIT_RADIUS = 9
ROTATION_STEM = 24
CHECKER_TILE = 16
SHIFT_ROTATION_STEP = 15
DRAG_REGION_COLOR = QColor("#f39b2f")
FIT_MARGINS = (-28, -36, 28, 28)
MOVE_TEXT = "Move"
NUDGE_LARGE = 10


class _Gesture(Enum):
    MOVE = "move"
    RESIZE = "resize"
    ROTATE = "rotate"


GESTURE_LABELS = {_Gesture.MOVE: "Move", _Gesture.RESIZE: "Resize", _Gesture.ROTATE: "Rotate"}

# Resize cursors per corner (top-left, top-right, bottom-right, bottom-left).
CORNER_CURSORS = (
    Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor,
    Qt.CursorShape.SizeFDiagCursor, Qt.CursorShape.SizeBDiagCursor,
)


def _rotate_cursor() -> QCursor:
    """A small curved arrow; Qt has no standard rotation cursor."""
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.arcMoveTo(QRectF(5, 5, 14, 14), 200)
    path.arcTo(QRectF(5, 5, 14, 14), 200, -250)
    for color, width in ((QColor("white"), 4.0), (QColor("black"), 1.6)):
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawPath(path)
        end = path.currentPosition()
        painter.drawLine(end, end + QPointF(-4, -1))
        painter.drawLine(end, end + QPointF(0, -4))
    painter.end()
    return QCursor(pixmap, 12, 12)


class _FaceItem(QGraphicsItem):
    def __init__(self) -> None:
        super().__init__()
        self.face: Face | None = None
        self.artwork: FaceArtwork | None = None
        self.cover = QPixmap()

    def face_rect(self) -> QRectF:
        return QRectF(0, 0, *(self.face.size if self.face else (440, 280)))

    def boundingRect(self) -> QRectF:
        bounds = self.face_rect()
        if self.face is not None:
            bounds = bounds.united(QRectF(*self.face.drag))
            for name, rect in self.face.controls.items():
                region = QRectF(*control_bounds(rect, self.face.control_rotations.get(name, 0)))
                bounds = bounds.united(region)
        return bounds

    def set_face(self, face: Face, artwork: FaceArtwork, cover: QPixmap) -> None:
        self.prepareGeometryChange()
        self.face, self.artwork, self.cover = face, artwork, cover
        self.update()

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if self.face is not None and self.artwork is not None:
            draw_face_preview(painter, self.face, self.artwork, self.cover)


def _control_transform(rect: QRectF, angle: float) -> QTransform:
    center = rect.center()
    transform = QTransform()
    transform.translate(center.x(), center.y())
    transform.rotate(angle)
    transform.translate(-center.x(), -center.y())
    return transform


class FaceEditorCanvas(QGraphicsView):
    """Gestures change one document transaction, including their live preview."""

    selectionChanged = Signal(str)
    documentChanged = Signal()
    zoomChanged = Signal(float)
    imageDropped = Signal(str, str)  # PNG path, target element ("" for the background)
    faceDropped = Signal(str)  # a face folder or its face.json, to open
    contextMenuRequested = Signal(str, object)  # element ("" for none), global QPoint
    removeRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        scene = QGraphicsScene(parent)
        super().__init__(scene, parent)
        self.setObjectName("faceEditorCanvas")
        self.setAccessibleName("Face layout canvas")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_MacShowFocusRect, True)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        # Pan by scrolling or Space-drag, as on Mac canvases. Scroll bars that
        # appear while fitting would resize the view and refit it in a loop.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform,
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.viewport().setMouseTracking(True)
        self.viewport().grabGesture(Qt.GestureType.PinchGesture)
        self._item = _FaceItem()
        scene.addItem(self._item)
        self._document: FaceDocument | None = None
        self._selected = "play"
        self._hovered: str | None = None
        self._drop_target: str | None = None
        self._show_guides = True
        self.snap = False
        self.grid_size = 8
        self._gesture: _Gesture | None = None
        self._start = QPointF()
        self._start_rect = QRectF()
        self._start_angle = 0.0
        self._corner = 0
        self._fitting = True
        self._panning = False
        self._nudge_session: object = None
        self._rotate_cursor = _rotate_cursor()
        # A bound method, so the connection ends with this canvas.
        self._style_hints = QGuiApplication.styleHints()
        self._style_hints.accessibility().contrastPreferenceChanged.connect(
            self._contrast_changed,
        )

    @property
    def selected(self) -> str:
        return self._selected

    @property
    def zoom(self) -> float:
        return self.transform().m11()

    @property
    def guides_visible(self) -> bool:
        return self._show_guides

    @property
    def gesture_active(self) -> bool:
        return self._gesture is not None

    def set_document(self, document: FaceDocument) -> None:
        self.cancel_gesture()
        self._document = document
        self._hovered = None
        controls = document.manifest["controls"]
        self._selected = "play" if "play" in controls else next(iter(controls), "drag")

    def set_preview(self, face: Face, artwork: FaceArtwork, cover: QPixmap) -> None:
        previous_size = self._item.face_rect().size()
        self._item.set_face(face, artwork, cover)
        self.setSceneRect(self._item.boundingRect().adjusted(-64, -64, 64, 64))
        if self._fitting or previous_size != self._item.face_rect().size():
            self.fit_face()
        self.viewport().update()

    def _contrast_changed(self, _preference) -> None:
        self.viewport().update()

    def select(self, name: str) -> None:
        if self._document is None:
            return
        if name != "drag" and name not in self._document.manifest["controls"]:
            return
        if name == self._selected:
            return
        # A gesture belongs to its initial element; switching selection abandons it.
        self.cancel_gesture()
        self._selected = name
        self.selectionChanged.emit(name)
        self.viewport().update()

    def set_guides(self, visible: bool) -> None:
        self._show_guides = visible
        self.viewport().update()

    # ------------------------------------------------------------- zoom
    def fit_face(self) -> None:
        self._fitting = True
        self.fitInView(
            self._item.face_rect().adjusted(*FIT_MARGINS), Qt.AspectRatioMode.KeepAspectRatio,
        )
        if self.zoom > MAX_ZOOM:
            self.set_zoom(MAX_ZOOM)
            self._fitting = True
        self.zoomChanged.emit(self.zoom)

    def set_zoom(self, scale: float) -> None:
        self._fitting = False
        scale = max(MIN_ZOOM, min(MAX_ZOOM, scale))
        self.scale(scale / self.zoom, scale / self.zoom)
        self.zoomChanged.emit(self.zoom)

    def zoom_in(self) -> None:
        self._zoom_around_center(next((s for s in ZOOM_STEPS if s > self.zoom + 0.001), MAX_ZOOM))

    def zoom_out(self) -> None:
        smaller = [s for s in ZOOM_STEPS if s < self.zoom - 0.001]
        self._zoom_around_center(smaller[-1] if smaller else MIN_ZOOM)

    def _zoom_around_center(self, scale: float) -> None:
        anchor = self.transformationAnchor()
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.set_zoom(scale)
        self.setTransformationAnchor(anchor)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fitting:
            self.fit_face()

    # ---------------------------------------------------------- drawing
    def _dark(self) -> bool:
        return self.palette().color(QPalette.ColorRole.Window).lightness() < 128

    def _accent(self) -> QColor:
        return self.palette().color(QPalette.ColorRole.Accent)

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        dark = self._dark()
        painter.fillRect(rect, QColor("#1c1c1e" if dark else "#d9d9de"))
        face_rect = self._item.face_rect()
        area = face_rect.intersected(rect)
        painter.save()
        painter.setClipRect(face_rect)
        light, shade = ("#3a3a3c", "#2c2c2e") if dark else ("#ffffff", "#ececef")
        first_x = math.floor(area.left() / CHECKER_TILE)
        first_y = math.floor(area.top() / CHECKER_TILE)
        for x in range(first_x, math.ceil(area.right() / CHECKER_TILE)):
            for y in range(first_y, math.ceil(area.bottom() / CHECKER_TILE)):
                color = shade if (x + y) % 2 else light
                painter.fillRect(
                    QRectF(x * CHECKER_TILE, y * CHECKER_TILE, CHECKER_TILE, CHECKER_TILE),
                    QColor(color),
                )
        if self.snap:
            grid = QColor(self._accent())
            grid.setAlpha(60)
            painter.setPen(QPen(grid, 0))
            for x in range(0, int(area.right()) + 1, self.grid_size):
                painter.drawLine(QPointF(x, 0), QPointF(x, face_rect.bottom()))
            for y in range(0, int(area.bottom()) + 1, self.grid_size):
                painter.drawLine(QPointF(0, y), QPointF(face_rect.right(), y))
        painter.restore()

    def _geometry(self, name: str) -> tuple[QRectF, float]:
        if self._document is None:
            return QRectF(), 0.0
        data = self._document.manifest
        rect = data["drag"] if name == "drag" else data["controls"][name]
        return QRectF(*rect), float(data.get("controlRotations", {}).get(name, 0))

    def _outline(self, name: str) -> QPainterPath:
        region, angle = self._geometry(name)
        return _control_transform(region, angle).map(control_path(region, "rectangle", 0))

    def _handles(self) -> tuple[list[QPointF], QPointF]:
        rect, angle = self._geometry(self._selected)
        transform = _control_transform(rect, angle)
        corners = [
            transform.map(point)
            for point in (
                rect.topLeft(),
                rect.topRight(),
                rect.bottomRight(),
                rect.bottomLeft(),
            )
        ]
        rotation = transform.map(
            QPointF(rect.center().x(), rect.top() - ROTATION_STEM / self.zoom),
        )
        return corners, rotation

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._document is None:
            return
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        accent = self._accent()
        if self._drop_target is not None:
            self._draw_drop_target(painter, accent)
        if not self._show_guides:
            painter.restore()
            return
        # Increase Contrast makes outlines solid and the selection heavier.
        contrast = high_contrast()
        stroke = (2.5 if contrast else 1.5) / self.zoom
        if self._gesture is None:
            outline = QColor(accent)
            outline.setAlpha(220 if contrast else 90)
            style = Qt.PenStyle.SolidLine if contrast else Qt.PenStyle.DotLine
            painter.setPen(QPen(outline, 1 / self.zoom if contrast else 0, style))
            for name in self._document.manifest["controls"]:
                if name not in (self._selected, self._hovered):
                    painter.drawPath(self._outline(name))
            if self._hovered not in (None, self._selected):
                painter.setPen(QPen(accent, stroke))
                painter.drawPath(self._outline(self._hovered))
        color = DRAG_REGION_COLOR if self._selected == "drag" else accent
        painter.setPen(QPen(color, stroke))
        painter.drawPath(self._outline(self._selected))
        corners, rotation = self._handles()
        extent = HANDLE_EXTENT / self.zoom
        painter.setPen(QPen(color, 1 / self.zoom))
        painter.setBrush(QColor("white"))
        region, angle = self._geometry(self._selected)
        if self._selected != "drag":
            top = _control_transform(region, angle).map(QPointF(region.center().x(), region.top()))
            painter.drawLine(top, rotation)
            painter.drawEllipse(rotation, extent * 1.3, extent * 1.3)
        for corner in corners:
            painter.drawRect(
                QRectF(corner.x() - extent, corner.y() - extent, extent * 2, extent * 2)
            )
        painter.restore()

    def _draw_drop_target(self, painter: QPainter, accent: QColor) -> None:
        fill = QColor(accent)
        fill.setAlpha(50)
        painter.setPen(QPen(accent, 2.5 / self.zoom))
        painter.setBrush(fill)
        if self._drop_target == "":
            painter.drawRect(self._item.face_rect())
            label = "Background"
            anchor = self._item.face_rect().topLeft()
        else:
            painter.drawPath(self._outline(self._drop_target))
            label = f"{face_elements.LABELS[self._drop_target]} Artwork"
            anchor = self._geometry(self._drop_target)[0].topLeft()
        # A badge naming what the dropped image will become.
        painter.setTransform(QTransform())
        position = self.mapFromScene(anchor)
        font = QFont(self.font())
        font.setBold(True)
        painter.setFont(font)
        width = painter.fontMetrics().horizontalAdvance(label) + 14
        badge = QRectF(position.x(), position.y() - 24, width, 20)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(accent)
        painter.drawRoundedRect(badge, 6, 6)
        painter.setPen(QColor("white"))
        painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, label)

    # ----------------------------------------------------------- hit tests
    def _hit(self, point: QPointF) -> str | None:
        if self._document is None:
            return None
        data = self._document.manifest
        names = list(data["controls"])
        if self._selected in names:
            names.remove(self._selected)
            names.append(self._selected)
        for name in reversed(names):
            rect, angle = self._geometry(name)
            local = _control_transform(rect, angle).inverted()[0].map(point)
            shape = data.get("controlShapes", {}).get(name, "rectangle")
            if control_path(rect, shape, data.get("radius", 4)).contains(local):
                return name
        if QRectF(*data["drag"]).contains(point):
            return "drag"
        return None

    def _handle_at(self, point: QPointF) -> tuple[_Gesture | None, int]:
        if not self._show_guides or self._document is None:
            return None, 0
        corners, rotation = self._handles()
        radius = HANDLE_HIT_RADIUS / self.zoom
        for index, corner in enumerate(corners):
            if math.hypot(point.x() - corner.x(), point.y() - corner.y()) <= radius:
                return _Gesture.RESIZE, index
        if (
            self._selected != "drag"
            and math.hypot(point.x() - rotation.x(), point.y() - rotation.y()) <= radius
        ):
            return _Gesture.ROTATE, 0
        return None, 0

    def _update_hover(self, point: QPointF) -> None:
        handle, corner = self._handle_at(point)
        if handle is _Gesture.RESIZE:
            angle = self._geometry(self._selected)[1]
            # Pick the diagonal closest to the rotated corner direction.
            turned = (corner + round(angle / 90)) % 4
            self.viewport().setCursor(CORNER_CURSORS[turned])
        elif handle is _Gesture.ROTATE:
            self.viewport().setCursor(self._rotate_cursor)
        else:
            self.viewport().unsetCursor()
        hovered = None if handle is not None else self._hit(point)
        if hovered != self._hovered:
            self._hovered = hovered
            self.viewport().update()

    # ------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        if self._panning or event.button() == Qt.MouseButton.MiddleButton:
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton or self._document is None:
            super().mousePressEvent(event)
            return
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        point = self.mapToScene(event.position().toPoint())
        gesture, corner = self._handle_at(point)
        if gesture is _Gesture.RESIZE:
            self._corner = corner
        if gesture is None:
            name = self._hit(point)
            if name is None:
                event.accept()
                return
            self.select(name)
            gesture = _Gesture.MOVE
        self._gesture = gesture
        self._start = point
        self._start_rect, self._start_angle = self._geometry(self._selected)
        self._document.begin_gesture(GESTURE_LABELS[gesture])
        self._hovered = None
        event.accept()

    def _snap_value(self, value: float, event) -> int:
        step = (
            self.grid_size
            if self.snap and not (event.modifiers() & Qt.KeyboardModifier.AltModifier)
            else 1
        )
        return round(value / step) * step

    def _set_rect(self, coordinates: list[int], *, label: str = "", coalesce=None) -> None:
        if self._document is None:
            return
        bounded = [
            max(-MAX_DRAFT_GEOMETRY if index < 2 else 1, min(MAX_DRAFT_GEOMETRY, value))
            for index, value in enumerate(coordinates)
        ]
        self._document.set_rect(self._selected, bounded, label=label, coalesce=coalesce)

    def mouseMoveEvent(self, event) -> None:
        document = self._document
        if document is None or self._gesture is None:
            if document is not None and not self._panning and not event.buttons():
                self._update_hover(self.mapToScene(event.position().toPoint()))
            super().mouseMoveEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        rect = QRectF(self._start_rect)
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if self._gesture == _Gesture.ROTATE:
            center = rect.center()
            angle = math.degrees(math.atan2(point.y() - center.y(), point.x() - center.x()))
            start = math.degrees(
                math.atan2(
                    self._start.y() - center.y(),
                    self._start.x() - center.x(),
                )
            )
            degrees = ((self._start_angle + angle - start + 180) % 360) - 180
            if shift:
                degrees = round(degrees / SHIFT_ROTATION_STEP) * SHIFT_ROTATION_STEP
            document.set_rotation(self._selected, round(degrees, 1))
        elif self._gesture == _Gesture.MOVE:
            delta = point - self._start
            if shift:
                # Constrain to the dominant axis.
                if abs(delta.x()) >= abs(delta.y()):
                    delta.setY(0)
                else:
                    delta.setX(0)
            rect.moveTopLeft(
                QPointF(
                    self._snap_value(rect.x() + delta.x(), event),
                    self._snap_value(rect.y() + delta.y(), event),
                )
            )
            self._set_rect([
                round(value) for value in (rect.x(), rect.y(), rect.width(), rect.height())
            ])
        else:
            # Resize in the element's rotated coordinate frame around its opposite corner.
            transform = _control_transform(rect, self._start_angle)
            opposite = (self._corner + 2) % 4
            fixed = transform.map(
                [
                    rect.topLeft(),
                    rect.topRight(),
                    rect.bottomRight(),
                    rect.bottomLeft(),
                ][opposite]
            )
            inverse = QTransform().rotate(-self._start_angle)
            vector = inverse.map(point - fixed)
            sign_x = -1 if self._corner in (0, 3) else 1
            sign_y = -1 if self._corner in (0, 1) else 1
            width = max(1, self._snap_value(vector.x() * sign_x, event))
            height = max(1, self._snap_value(vector.y() * sign_y, event))
            half = (
                QTransform()
                .rotate(self._start_angle)
                .map(
                    QPointF(sign_x * width / 2, sign_y * height / 2),
                )
            )
            center = fixed + half
            self._set_rect(
                [
                    round(center.x() - width / 2),
                    round(center.y() - height / 2),
                    width,
                    height,
                ],
            )
        self.documentChanged.emit()
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self._gesture is not None
            and self._document is not None
        ):
            self.finish_gesture()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._hovered is not None:
            self._hovered = None
            self.viewport().update()
        super().leaveEvent(event)

    def finish_gesture(self) -> None:
        """Commit the current pointer edit so undo can restore and redo it."""
        if self._gesture is None or self._document is None:
            return
        self._document.end_gesture()
        self._gesture = None
        self.documentChanged.emit()

    def cancel_gesture(self) -> None:
        if self._gesture is None or self._document is None:
            return
        self._document.cancel_gesture()
        self._gesture = None
        self.documentChanged.emit()

    def contextMenuEvent(self, event) -> None:
        if self._document is None:
            return
        point = self.mapToScene(event.pos())
        name = self._hit(point)
        if name is not None:
            self.select(name)
        self.contextMenuRequested.emit(name or "", event.globalPos())
        event.accept()

    # ---------------------------------------------------------- keyboard
    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.cancel_gesture()
            event.accept()
            return
        if key == Qt.Key.Key_Space and self._gesture is None:
            if not event.isAutoRepeat():
                self._panning = True
                self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete) and self._gesture is None:
            self.removeRequested.emit()
            event.accept()
            return
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if key in directions and self._document is not None and self._gesture is None:
            rect, _ = self._geometry(self._selected)
            factor = NUDGE_LARGE if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = directions[key]
            if not event.isAutoRepeat():
                self._nudge_session = object()
            self._set_rect(
                [
                    round(rect.x()) + dx * factor,
                    round(rect.y()) + dy * factor,
                    round(rect.width()),
                    round(rect.height()),
                ],
                label=MOVE_TEXT, coalesce=self._nudge_session,
            )
            self.documentChanged.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat() and self._panning:
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().unsetCursor()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def focusOutEvent(self, event) -> None:
        if self._panning:
            self._panning = False
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
            self.viewport().unsetCursor()
        super().focusOutEvent(event)

    # ------------------------------------------------- wheel and gestures
    def wheelEvent(self, event) -> None:
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            factor = WHEEL_ZOOM_FACTOR if event.angleDelta().y() > 0 else 1 / WHEEL_ZOOM_FACTOR
            self.set_zoom(self.zoom * factor)
            event.accept()
            return
        super().wheelEvent(event)

    def viewportEvent(self, event) -> bool:
        if (
            event.type() == QEvent.Type.NativeGesture
            and event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture
        ):
            # Trackpad pinch on macOS.
            self.set_zoom(self.zoom * (1 + event.value()))
            return True
        return super().viewportEvent(event)

    # --------------------------------------------------------- drag & drop
    @staticmethod
    def _png_drop(event) -> Path | None:
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        return path if path.suffix.lower() == ".png" else None

    def _drop_target_at(self, position) -> str:
        """The element under the pointer if it takes artwork, else the background."""
        if self._document is None:
            return ""
        name = self._hit(self.mapToScene(position.toPoint()))
        style = self._document.manifest.get("sliderStyle", "classic")
        if name is not None and face_elements.can_hold_artwork(name, style):
            return name
        return ""

    @staticmethod
    def _face_drop(event) -> Path | None:
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        if path.name == "face.json" or (path.is_dir() and (path / "face.json").is_file()):
            return path
        return None

    def dragEnterEvent(self, event) -> None:
        if self._face_drop(event) is not None:
            event.acceptProposedAction()
            self._set_drop_target(None)
            return
        if self._png_drop(event) is None:
            event.ignore()
            return
        event.acceptProposedAction()
        self._set_drop_target(self._drop_target_at(event.position()))

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drop_target(None)
        super().dragLeaveEvent(event)

    def _set_drop_target(self, target: str | None) -> None:
        if target != self._drop_target:
            self._drop_target = target
            self.viewport().update()

    def dropEvent(self, event) -> None:
        self._set_drop_target(None)
        face = self._face_drop(event)
        if face is not None:
            event.acceptProposedAction()
            self.faceDropped.emit(str(face))
            return
        path = self._png_drop(event)
        if path is None:
            event.ignore()
            return
        self.imageDropped.emit(str(path), self._drop_target_at(event.position()))
        event.acceptProposedAction()

