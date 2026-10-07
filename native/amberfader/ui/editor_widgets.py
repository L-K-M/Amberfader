"""Inspector controls that behave like their AppKit counterparts.

- NumberField / AngleField: Return or Tab commits, Escape reverts a pending
  edit, Shift-arrow steps by 10, and the scroll wheel scrolls the inspector
  unless the field has focus.
- TextField: commits on Return or focus loss, Escape reverts.
- ColorWell: a swatch that edits live through the shared color panel; every
  change of one panel session can share one undo step.
- InspectorSection: a titled, collapsible group.
- UndoPassthrough: lets ⌘Z reach the document once a focused text field has
  nothing left to undo, as AppKit's responder chain does.
"""
from __future__ import annotations

import sys

from PySide6.QtCore import QEvent, QObject, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MACOS = sys.platform == "darwin"
LARGE_STEP = 10


def symbol_icon(name: str, fallback: str | None = None) -> QIcon:
    """An SF Symbol on macOS (Qt draws it with the current appearance);
    elsewhere a freedesktop theme icon, or an empty icon."""
    icon = QIcon.fromTheme(name)
    if icon.isNull() and fallback is not None:
        icon = QIcon.fromTheme(fallback)
    return icon


def sample_cover() -> QPixmap:
    """Stand-in album artwork for previews, since no track is playing."""
    cover = QPixmap(160, 160)
    painter = QPainter(cover)
    gradient = QLinearGradient(0, 0, 160, 160)
    gradient.setColorAt(0, QColor("#4b326a"))
    gradient.setColorAt(1, QColor("#db9467"))
    painter.fillRect(cover.rect(), gradient)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("#f5d292"), 2))
    for inset in (18, 35, 52):
        painter.drawEllipse(cover.rect().adjusted(inset, inset, -inset, -inset))
    painter.end()
    return cover


def secondary_color(palette: QPalette) -> QColor:
    """The equivalent of NSColor.secondaryLabelColor for this palette."""
    color = QColor(palette.color(QPalette.ColorRole.WindowText))
    color.setAlphaF(0.55)
    return color


def caption(text: str, parent: QWidget) -> QLabel:
    """A small secondary label, such as "Width" under a number field."""
    label = QLabel(text, parent)
    font = label.font()
    font.setPointSizeF(max(8.0, font.pointSizeF() - 2))
    label.setFont(font)
    label.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    palette = label.palette()
    palette.setColor(QPalette.ColorRole.WindowText, secondary_color(palette))
    label.setPalette(palette)
    return label


def focused_line_edit(widget: QWidget | None) -> QLineEdit | None:
    """The text editor behind a focused field, if it edits text."""
    if isinstance(widget, QLineEdit):
        return widget
    if isinstance(widget, QAbstractSpinBox):
        return widget.findChild(QLineEdit)
    if isinstance(widget, QComboBox) and widget.isEditable():
        return widget.lineEdit()
    return None


class UndoPassthrough(QObject):
    """Event filter for text fields.

    QLineEdit claims ⌘Z and ⇧⌘Z even when it has nothing to undo, which
    would make Edit ▸ Undo dead while a field has focus. Releasing those
    shortcuts lets the document undo, while typing remains undoable first.
    """

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.ShortcutOverride:
            return False
        line = focused_line_edit(watched)
        if line is None:
            return False
        if event.matches(QKeySequence.StandardKey.Undo) and not line.isUndoAvailable():
            event.ignore()
            return True
        if event.matches(QKeySequence.StandardKey.Redo) and not line.isRedoAvailable():
            event.ignore()
            return True
        return False


class _FieldBehavior:
    """Shared by the integer and angle fields (mixed into QAbstractSpinBox)."""

    def _init_behavior(self) -> None:
        self.setKeyboardTracking(False)
        self.setAccelerated(True)
        self.setCorrectionMode(QAbstractSpinBox.CorrectionMode.CorrectToPreviousValue)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._stepping = False

    @property
    def stepping(self) -> bool:
        """True while an arrow click or key changes the value."""
        return self._stepping

    def stepBy(self, steps: int) -> None:
        self._stepping = True
        try:
            super().stepBy(steps)
        finally:
            self._stepping = False

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape and self.text() != self._committed_text():
            # Revert to the committed value, as an AppKit field does.
            self.setValue(self.value())
            self.selectAll()
            event.accept()
            return
        shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        if shift and key in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.stepBy(LARGE_STEP if key == Qt.Key.Key_Up else -LARGE_STEP)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event) -> None:
        # Scrolling the inspector must not change values under the pointer.
        if not self.hasFocus():
            event.ignore()
            return
        super().wheelEvent(event)

    def _committed_text(self) -> str:
        return self.prefix() + self.textFromValue(self.value()) + self.suffix()


class NumberField(_FieldBehavior, QSpinBox):
    def __init__(
        self, parent: QWidget, minimum: int, maximum: int, *, suffix: str = " px",
        name: str = "",
    ) -> None:
        super().__init__(parent)
        self._init_behavior()
        self.setRange(minimum, maximum)
        self.setSuffix(suffix)
        self.setObjectName(name)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)


class AngleField(_FieldBehavior, QDoubleSpinBox):
    def __init__(self, parent: QWidget, *, name: str = "") -> None:
        super().__init__(parent)
        self._init_behavior()
        self.setRange(-180, 180)
        self.setDecimals(1)
        self.setSuffix("°")
        self.setWrapping(True)
        self.setObjectName(name)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)


class TextField(QLineEdit):
    """A line edit that commits like an inspector field.

    `committed` fires on Return or focus loss when the text differs from the
    model value. Escape restores the model value.
    """

    committed = Signal(str)

    def __init__(self, parent: QWidget, *, limit: int, name: str = "") -> None:
        super().__init__(parent)
        self.setMaxLength(limit)
        self.setObjectName(name)
        self._model = ""
        self.editingFinished.connect(self._finish)

    @property
    def model_text(self) -> str:
        return self._model

    def show_model_value(self, value: str) -> None:
        """Show the committed value, unless the user is typing over the same value.

        Undo and document replacement still update a focused field, because
        they change the committed model value.
        """
        if not self.hasFocus() or value != self._model:
            self.setText(value)
            if not self.hasFocus():
                self.setCursorPosition(0)
        self._model = value

    def has_pending_edit(self) -> bool:
        return self.text() != self._model

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self.has_pending_edit():
            self.setText(self._model)
            self.selectAll()
            event.accept()
            return
        super().keyPressEvent(event)

    def _finish(self) -> None:
        if self.has_pending_edit():
            self.committed.emit(self.text())


class _ColorPanel(QObject):
    """The one color panel, attached to one well at a time.

    On macOS this is the system's shared NSColorPanel. Each attachment is a
    session; wells pass the session to the document so that dragging through
    the color wheel is one undo step.
    """

    _shared: _ColorPanel | None = None

    def __init__(self) -> None:
        super().__init__()
        self._dialog: QColorDialog | None = None
        self._well: ColorWell | None = None
        self._session: object = None

    @classmethod
    def shared(cls) -> _ColorPanel:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    def attach(self, well: ColorWell) -> None:
        if self._dialog is None:
            self._dialog = QColorDialog()
            self._dialog.setOption(QColorDialog.ColorDialogOption.NoButtons, True)
            self._dialog.setWindowTitle("Colors")
            self._dialog.currentColorChanged.connect(self._changed)
            self._dialog.finished.connect(lambda _result: self.detach())
        if self._well is not well:
            self.detach()
            self._well = well
            well.destroyed.connect(self._forget)
        self._session = object()
        well.set_active(True)
        with QSignalBlocker(self._dialog):
            self._dialog.setCurrentColor(well.color())
        self._dialog.show()
        self._dialog.raise_()

    def detach(self) -> None:
        well, self._well = self._well, None
        self._session = None
        if well is not None:
            well.destroyed.disconnect(self._forget)
            well.set_active(False)

    def follow(self, well: ColorWell) -> None:
        """Show a well's new model color, e.g. after undo, without editing."""
        if self._dialog is not None and well is self._well:
            with QSignalBlocker(self._dialog):
                self._dialog.setCurrentColor(well.color())

    def _forget(self) -> None:
        self._well = None
        self._session = None

    def _changed(self, color: QColor) -> None:
        if self._well is not None and color.isValid():
            self._well.picked.emit(color, self._session)


class ColorWell(QAbstractButton):
    """A color swatch. `picked(color, session)` fires live while the panel edits it."""

    picked = Signal(QColor, object)

    def __init__(self, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self._title = title
        self._color = QColor("#000000")
        self._active = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: _ColorPanel.shared().attach(self))
        self._describe()

    def color(self) -> QColor:
        return QColor(self._color)

    def set_color(self, color: str | QColor) -> None:
        color = QColor(color)
        if color == self._color:
            return
        self._color = color
        self._describe()
        self.update()
        _ColorPanel.shared().follow(self)

    def set_active(self, active: bool) -> None:
        self._active = active
        self.update()

    def _describe(self) -> None:
        name = self._color.name()
        self.setAccessibleName(f"{self._title} color")
        self.setAccessibleDescription(name)
        self.setToolTip(f"{self._title}: {name}")

    def sizeHint(self) -> QSize:
        return QSize(44, 22)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        outer = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        accent = palette.color(QPalette.ColorRole.Accent)
        if self._active or self.isDown():
            painter.setPen(QPen(accent, 2))
        else:
            border = QColor(palette.color(QPalette.ColorRole.WindowText))
            border.setAlphaF(0.25)
            painter.setPen(QPen(border, 1))
        painter.setBrush(palette.color(QPalette.ColorRole.Base))
        painter.drawRoundedRect(outer, 5, 5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._color if self.isEnabled() else palette.color(QPalette.ColorRole.Mid))
        painter.drawRoundedRect(outer.adjusted(3, 3, -3, -3), 3, 3)
        if self.hasFocus() and not self._active:
            ring = QColor(accent)
            ring.setAlphaF(0.5)
            painter.setPen(QPen(ring, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(outer, 5, 5)
        painter.end()


class _DisclosureHeader(QAbstractButton):
    """A section title with a disclosure chevron, drawn flat like Xcode's."""

    def __init__(self, title: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.setText(title)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expanded = True
        font = QFont(self.font())
        font.setBold(True)
        self.setFont(font)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self.text()) + 26, metrics.height() + 8)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        chevron = secondary_color(palette)
        pen = QPen(chevron, 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        middle = self.height() / 2
        if self.expanded:
            points = ((6.0, middle - 2), (9.5, middle + 2), (13.0, middle - 2))
        else:
            points = ((8.0, middle - 3.5), (11.5, middle), (8.0, middle + 3.5))
        path = QPainterPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        painter.drawPath(path)
        painter.setPen(palette.color(QPalette.ColorRole.WindowText))
        painter.setFont(self.font())
        text_rect = self.rect().adjusted(20, 0, 0, 0)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         self.text())
        if self.hasFocus():
            ring = QColor(palette.color(QPalette.ColorRole.Accent))
            ring.setAlphaF(0.6)
            painter.setPen(QPen(ring, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 4, 4)
        painter.end()


class InspectorSection(QWidget):
    """A titled group whose content collapses with its disclosure header."""

    def __init__(self, title: str, parent: QWidget, *, name: str) -> None:
        super().__init__(parent)
        self.setObjectName(name)
        self._header = _DisclosureHeader(title, self)
        self._header.setObjectName(f"{name}Header")
        self._header.setAccessibleName(f"{title} section")
        self._header.clicked.connect(lambda: self._toggle(not self._expanded))
        self._expanded = True
        self.body = QWidget(self)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Plain)
        line.setForegroundRole(QPalette.ColorRole.Mid)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 6)
        layout.setSpacing(4)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(6, 0, 6, 0)
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        layout.addLayout(header_row)
        layout.addWidget(self.body)
        layout.addWidget(line)
        self._toggle(True)

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        self._toggle(expanded)

    def _toggle(self, expanded: bool) -> None:
        self._expanded = expanded
        self._header.expanded = expanded
        self._header.setAccessibleDescription("Expanded" if expanded else "Collapsed")
        self._header.update()
        self.body.setVisible(expanded)


class SegmentedButtons(QWidget):
    """A row of icon toggles, exclusive (alignment) or independent (bold, italic)."""

    toggled = Signal(str, bool)

    def __init__(
        self, parent: QWidget, items: list[tuple[str, str, str]], *, exclusive: bool,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self._exclusive = exclusive
        self._buttons: dict[str, QToolButton] = {}
        for key, label, symbol in items:
            button = QToolButton(self)
            button.setObjectName(key)
            button.setCheckable(True)
            button.setToolTip(label)
            button.setAccessibleName(label)
            icon = symbol_icon(symbol)
            if icon.isNull():
                button.setText(label[0])
            else:
                button.setIcon(icon)
            button.toggled.connect(lambda checked, key=key: self._toggled(key, checked))
            layout.addWidget(button)
            self._buttons[key] = button
        layout.addStretch(1)

    def button(self, key: str) -> QToolButton:
        return self._buttons[key]

    def set_checked(self, key: str, checked: bool) -> None:
        with QSignalBlocker(self._buttons[key]):
            self._buttons[key].setChecked(checked)

    def set_current(self, key: str) -> None:
        for name, button in self._buttons.items():
            with QSignalBlocker(button):
                button.setChecked(name == key)

    def _toggled(self, key: str, checked: bool) -> None:
        if self._exclusive:
            if not checked:
                # An exclusive choice cannot be unset by clicking it again.
                self.set_checked(key, True)
                return
            self.set_current(key)
        self.toggled.emit(key, checked)
