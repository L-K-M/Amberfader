"""A logical-coordinate canvas for editing presentation without player commands."""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGraphicsItem, QGraphicsScene, QGraphicsView, QWidget

from ..face_document import FaceDocument
from ..face_library import MAX_DRAFT_GEOMETRY, Face, control_bounds
from .face_surface import FaceArtwork, control_path, draw_face_preview


class _Gesture(Enum):
    MOVE = "move"
    RESIZE = "resize"
    ROTATE = "rotate"


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
    imageDropped = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        scene = QGraphicsScene(parent)
        super().__init__(scene, parent)
        self.setObjectName("faceEditorCanvas")
        self.setAccessibleName("Face layout canvas")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(True)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform,
        )
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self._item = _FaceItem()
        scene.addItem(self._item)
        self._document: FaceDocument | None = None
        self._selected = "play"
        self._show_guides = True
        self.snap = False
        self.grid_size = 8
        self._gesture: _Gesture | None = None
        self._start = QPointF()
        self._start_rect = QRectF()
        self._start_angle = 0.0
        self._corner = 0
        self._fitting = True

    @property
    def selected(self) -> str:
        return self._selected

    @property
    def zoom(self) -> float:
        return self.transform().m11()

    def set_document(self, document: FaceDocument) -> None:
        self.cancel_gesture()
        self._document = document
        controls = document.manifest["controls"]
        self._selected = "play" if "play" in controls else next(iter(controls), "drag")

    def set_preview(self, face: Face, artwork: FaceArtwork, cover: QPixmap) -> None:
        previous_size = self._item.face_rect().size()
        self._item.set_face(face, artwork, cover)
        self.setSceneRect(self._item.boundingRect().adjusted(-64, -64, 64, 64))
        if self._fitting or previous_size != self._item.face_rect().size():
            self.fit_face()
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

    def fit_face(self) -> None:
        self._fitting = True
        self.fitInView(
            self._item.face_rect().adjusted(-28, -36, 28, 28), Qt.AspectRatioMode.KeepAspectRatio
        )
        self.zoomChanged.emit(self.zoom)

    def set_zoom(self, scale: float) -> None:
        self._fitting = False
        scale = max(0.25, min(4.0, scale))
        self.scale(scale / self.zoom, scale / self.zoom)
        self.zoomChanged.emit(self.zoom)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fitting:
            self.fit_face()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, QColor("#30343b"))
        area = self._item.face_rect().intersected(rect)
        painter.save()
        painter.setClipRect(self._item.face_rect())
        tile = 16
        first_x, first_y = math.floor(area.left() / tile), math.floor(area.top() / tile)
        for x in range(first_x, math.ceil(area.right() / tile)):
            for y in range(first_y, math.ceil(area.bottom() / tile)):
                color = "#c9cdd3" if (x + y) % 2 else "#e8ebef"
                painter.fillRect(QRectF(x * tile, y * tile, tile, tile), QColor(color))
        if self.snap:
            painter.setPen(QPen(QColor(95, 109, 132, 90), 0))
            for x in range(0, int(area.right()) + 1, self.grid_size):
                painter.drawLine(QPointF(x, 0), QPointF(x, self._item.face_rect().bottom()))
            for y in range(0, int(area.bottom()) + 1, self.grid_size):
                painter.drawLine(QPointF(0, y), QPointF(self._item.face_rect().right(), y))
        painter.restore()

    def _geometry(self, name: str) -> tuple[QRectF, float]:
        if self._document is None:
            return QRectF(), 0.0
        data = self._document.manifest
        rect = data["drag"] if name == "drag" else data["controls"][name]
        return QRectF(*rect), float(data.get("controlRotations", {}).get(name, 0))

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
        rotation = transform.map(QPointF(rect.center().x(), rect.top() - 24 / self.zoom))
        return corners, rotation

    def drawForeground(self, painter: QPainter, rect: QRectF) -> None:
        if self._document is None or not self._show_guides:
            return
        data = self._document.manifest
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._gesture is None:
            painter.setPen(QPen(QColor(45, 110, 220, 75), 0, Qt.PenStyle.DotLine))
            for name in data["controls"]:
                if name == self._selected:
                    continue
                region, angle = self._geometry(name)
                path = _control_transform(region, angle).map(control_path(region, "rectangle", 0))
                painter.drawPath(path)
        region, angle = self._geometry(self._selected)
        color = QColor("#ffae43" if self._selected == "drag" else "#2179e9")
        painter.setPen(QPen(color, 0, Qt.PenStyle.DashLine))
        transform = _control_transform(region, angle)
        painter.drawPath(transform.map(control_path(region, "rectangle", 0)))
        corners, rotation = self._handles()
        extent = 4 / self.zoom
        painter.setPen(QPen(color, 0))
        painter.setBrush(QColor("white"))
        for corner in corners:
            painter.drawRect(
                QRectF(corner.x() - extent, corner.y() - extent, extent * 2, extent * 2)
            )
        if self._selected != "drag":
            top = transform.map(QPointF(region.center().x(), region.top()))
            painter.drawLine(top, rotation)
            painter.drawEllipse(rotation, extent * 1.3, extent * 1.3)
        painter.restore()

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

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._document is None:
            super().mousePressEvent(event)
            return
        self.setFocus()
        point = self.mapToScene(event.position().toPoint())
        gesture = None
        corners, rotation = self._handles()
        hit_radius = 9 / self.zoom
        if self._show_guides:
            if (
                self._selected != "drag"
                and math.hypot(
                    point.x() - rotation.x(),
                    point.y() - rotation.y(),
                )
                <= hit_radius
            ):
                gesture = _Gesture.ROTATE
            for index, corner in enumerate(corners):
                if math.hypot(point.x() - corner.x(), point.y() - corner.y()) <= hit_radius:
                    gesture, self._corner = _Gesture.RESIZE, index
                    break
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
        self._document.begin_gesture()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        event.accept()

    def _snap_value(self, value: float, event) -> int:
        step = (
            self.grid_size
            if self.snap and not (event.modifiers() & Qt.KeyboardModifier.AltModifier)
            else 1
        )
        return round(value / step) * step

    def _set_rect(self, coordinates: list[int]) -> None:
        if self._document is None:
            return
        bounded = [
            max(-MAX_DRAFT_GEOMETRY if index < 2 else 1, min(MAX_DRAFT_GEOMETRY, value))
            for index, value in enumerate(coordinates)
        ]
        self._document.set_rect(self._selected, bounded)

    def mouseMoveEvent(self, event) -> None:
        document = self._document
        if document is None or self._gesture is None:
            super().mouseMoveEvent(event)
            return
        point = self.mapToScene(event.position().toPoint())
        rect = QRectF(self._start_rect)
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
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                degrees = round(degrees / 15) * 15
            document.set_rotation(self._selected, round(degrees, 1))
        elif self._gesture == _Gesture.MOVE:
            delta = point - self._start
            rect.moveTopLeft(
                QPointF(
                    self._snap_value(rect.x() + delta.x(), event),
                    self._snap_value(rect.y() + delta.y(), event),
                )
            )
            self._set_rect(
                [
                    round(value)
                    for value in (
                        rect.x(),
                        rect.y(),
                        rect.width(),
                        rect.height(),
                    )
                ],
            )
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

    def finish_gesture(self) -> None:
        """Commit the current pointer edit so undo can restore and redo it."""
        if self._gesture is None or self._document is None:
            return
        self._document.end_gesture()
        self._gesture = None
        self.unsetCursor()
        self.documentChanged.emit()

    def cancel_gesture(self) -> None:
        if self._gesture is None or self._document is None:
            return
        self._document.cancel_gesture()
        self._gesture = None
        self.unsetCursor()
        self.documentChanged.emit()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancel_gesture()
            event.accept()
            return
        directions = {
            Qt.Key.Key_Left: (-1, 0),
            Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1),
            Qt.Key.Key_Down: (0, 1),
        }
        if event.key() in directions and self._document is not None:
            rect, _ = self._geometry(self._selected)
            factor = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            dx, dy = directions[event.key()]
            self._set_rect(
                [
                    round(rect.x()) + dx * factor,
                    round(rect.y()) + dy * factor,
                    round(rect.width()),
                    round(rect.height()),
                ],
            )
            self.documentChanged.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        if event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        ):
            self.set_zoom(self.zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15))
            event.accept()
            return
        super().wheelEvent(event)

    @staticmethod
    def _png_drop(event) -> Path | None:
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        return path if path.suffix.lower() == ".png" else None

    def dragEnterEvent(self, event) -> None:
        if self._png_drop(event) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        self.dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        path = self._png_drop(event)
        if path is None:
            event.ignore()
            return
        self.imageDropped.emit(str(path), self._selected)
        event.acceptProposedAction()
