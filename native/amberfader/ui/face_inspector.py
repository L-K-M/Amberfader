"""The inspector: properties of the selected element, or of the whole face.

    ┌ [ Element | Face ] ┐   segmented control
    │ ⏯ Play / Pause     │   what the Element pane edits
    │ ▾ Layout           │   position, size, rotation, shape
    │ ▾ Text             │   screen text only
    │ ▾ Artwork          │   button sprites per state
    └────────────────────┘

Panes never touch the document. They emit `edited` with an InspectorEdit
(manifest path, value, undo name, coalescing key) or `command` for imports;
the window applies them, which keeps one undo history per document.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QCompleter,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from ..face_library import MAX_DRAFT_GEOMETRY
from . import face_elements
from .editor_widgets import (
    AngleField,
    ColorWell,
    InspectorSection,
    NumberField,
    SegmentedButtons,
    TextField,
    UndoPassthrough,
    caption,
    secondary_color,
    symbol_icon,
)
from .face_surface import READOUT_CONTROLS, FaceArtwork

# A held stepper or arrow key is one undo step; a pause starts another.
STEP_SESSION_SECONDS = 1.5
THUMBNAIL = QSize(40, 28)
BACKGROUND_PREVIEW_HEIGHT = 96

SHAPES = (("rectangle", "Rectangle"), ("rounded", "Rounded"), ("capsule", "Capsule"),
          ("ellipse", "Ellipse"))
FONTS = (("sans", "Sans Serif"), ("mono", "Monospaced"), ("serif", "Serif"))
SLIDER_STYLES = (("classic", "Classic"), ("inset", "Inset"), ("popup", "Pop-up"))
ALIGNMENTS = (
    ("left", "Align Left", "text.alignleft"),
    ("center", "Center", "text.aligncenter"),
    ("right", "Align Right", "text.alignright"),
)
TEXT_STYLES = (("bold", "Bold", "bold"), ("italic", "Italic", "italic"))
STATES = ("normal", "hover", "pressed", "disabled")
PLAYING_STATES = ("playing", "playing-hover", "playing-pressed", "playing-disabled")
STATE_LABELS = {state: state.replace("-", ", ").capitalize() for state in STATES + PLAYING_STATES}
PALETTE_LABELS = {
    "window": "Window", "panel": "Panel", "display": "Display", "text": "Text",
    "muted": "Muted Text", "readout": "Screen Text", "accent": "Accent", "border": "Border",
    "buttonTop": "Button Top", "buttonBottom": "Button Bottom", "danger": "Warning",
}
IDENTITY_FIELDS = (
    ("name", "Name", 64), ("id", "ID", 48), ("author", "Author", 96),
    ("description", "Description", 240),
)
METADATA_LABELS = {"name": "Name", "id": "ID", "author": "Author", "description": "Description"}


@dataclass(frozen=True)
class InspectorEdit:
    path: tuple[str, ...]
    value: Any
    label: str
    coalesce: object = None


class InspectorCommand(Enum):
    IMPORT_ARTWORK = "import-artwork"
    REMOVE_ARTWORK = "remove-artwork"
    IMPORT_BACKGROUND = "import-background"
    IMPORT_MASK = "import-mask"
    REMOVE_MASK = "remove-mask"


class InspectorPane(Enum):
    ELEMENT = 0
    FACE = 1


def _popup(parent: QWidget, items, name: str) -> QComboBox:
    box = QComboBox(parent)
    box.setObjectName(name)
    for value, label in items:
        box.addItem(label, value)
    return box


def _select_data(box: QComboBox, value) -> None:
    with QSignalBlocker(box):
        index = box.findData(value)
        box.setCurrentIndex(index if index >= 0 else 0)


def _form(parent: QWidget) -> QFormLayout:
    form = QFormLayout(parent)
    form.setContentsMargins(10, 0, 10, 4)
    form.setHorizontalSpacing(8)
    form.setVerticalSpacing(6)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return form


def _pair(parent: QWidget, fields, captions) -> QWidget:
    """Two fields side by side with captions under them (X and Y)."""
    box = QWidget(parent)
    grid = QGridLayout(box)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(1)
    for column, (field, text) in enumerate(zip(fields, captions, strict=True)):
        grid.addWidget(field, 0, column)
        grid.addWidget(caption(text, box), 1, column)
    return box


def _scrolling(page: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setWidget(page)
    return scroll


class _StepSessions:
    """Coalescing keys for stepper bursts, one per field and element."""

    def __init__(self) -> None:
        self._last: dict[str, tuple[float, object]] = {}

    def key(self, field: str) -> object:
        now = time.monotonic()
        last = self._last.get(field)
        if last is not None and now - last[0] < STEP_SESSION_SECONDS:
            key = last[1]
        else:
            key = (field, object())
        self._last[field] = (now, key)
        return key


class ElementInspector(QWidget):
    edited = Signal(object)  # InspectorEdit
    command = Signal(object, str)  # InspectorCommand, sprite state

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("elementInspector")
        self._name = "play"
        self._syncing = False
        self._steps = _StepSessions()
        self._undo_filter = UndoPassthrough(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)
        layout.addLayout(self._header())
        layout.addWidget(self._layout_section())
        layout.addWidget(self._text_section())
        layout.addWidget(self._artwork_section())
        layout.addStretch(1)
        for field in self.findChildren(QWidget):
            if isinstance(field, (NumberField, AngleField, TextField)):
                field.installEventFilter(self._undo_filter)

    # ------------------------------------------------------------- layout
    def _header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(12, 0, 12, 4)
        self._icon = QLabel(self)
        self._icon.setFixedSize(22, 22)
        self._title = QLabel(self)
        self._title.setObjectName("elementTitle")
        font = QFont(self._title.font())
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 1)
        self._title.setFont(font)
        self._kind = QLabel(self)
        palette = self._kind.palette()
        palette.setColor(self._kind.foregroundRole(), secondary_color(palette))
        self._kind.setPalette(palette)
        text = QVBoxLayout()
        text.setSpacing(0)
        text.addWidget(self._title)
        text.addWidget(self._kind)
        row.addWidget(self._icon, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(text, 1)
        return row

    def _layout_section(self) -> InspectorSection:
        section = InspectorSection("Layout", self, name="layoutSection")
        form = _form(section.body)
        self._rect_fields: list[NumberField] = []
        for index, label in enumerate(("X", "Y", "Width", "Height")):
            field = NumberField(
                section.body, -MAX_DRAFT_GEOMETRY if index < 2 else 1, MAX_DRAFT_GEOMETRY,
                name=f"element{label}",
            )
            field.setAccessibleName(label)
            field.valueChanged.connect(lambda _value, index=index: self._edit_rect(index))
            self._rect_fields.append(field)
        form.addRow("Position", _pair(section.body, self._rect_fields[:2], ("X", "Y")))
        form.addRow("Size", _pair(section.body, self._rect_fields[2:], ("Width", "Height")))
        self._rotation = AngleField(section.body, name="elementRotation")
        self._rotation.setAccessibleName("Rotation")
        self._rotation.valueChanged.connect(self._edit_rotation)
        self._rotation_row = QWidget(section.body)
        rotation = QHBoxLayout(self._rotation_row)
        rotation.setContentsMargins(0, 0, 0, 0)
        rotation.addWidget(self._rotation, 1)
        self._reset_rotation = QPushButton("Reset", self._rotation_row)
        self._reset_rotation.setObjectName("resetRotation")
        self._reset_rotation.setToolTip("Set the rotation to 0°")
        self._reset_rotation.clicked.connect(lambda: self._rotation.setValue(0))
        rotation.addWidget(self._reset_rotation)
        form.addRow("Rotation", self._rotation_row)
        self._shape = _popup(section.body, SHAPES, "elementShape")
        self._shape.setAccessibleName("Shape")
        self._shape.currentIndexChanged.connect(self._edit_shape)
        self._shape_label = QLabel("Shape", section.body)
        form.addRow(self._shape_label, self._shape)
        self._form = form
        return section

    def _text_section(self) -> InspectorSection:
        self._text_section_widget = section = InspectorSection("Text", self, name="textSection")
        form = _form(section.body)
        self._text_font = _popup(section.body, FONTS, "textFont")
        self._text_font.setAccessibleName("Font")
        self._text_font.currentIndexChanged.connect(
            lambda: self._edit_readout("font", self._text_font.currentData(), "Change Font"),
        )
        form.addRow("Font", self._text_font)
        self._text_family = TextField(section.body, limit=96, name="textFamily")
        self._text_family.setPlaceholderText("Face Font")
        self._text_family.setAccessibleName("Font family")
        self._text_family.setToolTip("A font family installed on this computer, such as Menlo")
        completer = QCompleter(QFontDatabase.families(), self._text_family)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._text_family.setCompleter(completer)
        self._text_family.committed.connect(self._edit_family)
        form.addRow("Family", self._text_family)
        self._text_size = NumberField(section.body, 6, 36, name="textSize")
        self._text_size.setAccessibleName("Text size")
        self._text_size.valueChanged.connect(self._edit_text_size)
        form.addRow("Size", self._text_size)
        self._text_style = SegmentedButtons(section.body, list(TEXT_STYLES), exclusive=False)
        self._text_style.toggled.connect(
            lambda key, checked: self._edit_readout(key, checked, "Change Text Style"),
        )
        form.addRow("Style", self._text_style)
        self._text_align = SegmentedButtons(section.body, list(ALIGNMENTS), exclusive=True)
        self._text_align.toggled.connect(
            lambda key, _checked: self._edit_readout("align", key, "Change Alignment"),
        )
        form.addRow("Alignment", self._text_align)
        color_row = QWidget(section.body)
        colors = QHBoxLayout(color_row)
        colors.setContentsMargins(0, 0, 0, 0)
        self._text_color = ColorWell("Text", color_row)
        self._text_color.setObjectName("textColor")
        self._text_color.picked.connect(
            lambda color, session: self._edit_readout(
                "color", color.name(), "Change Text Color", session,
            ),
        )
        colors.addWidget(self._text_color)
        colors.addStretch(1)
        form.addRow("Color", color_row)
        self._reset_text = QPushButton("Use Face Defaults", section.body)
        self._reset_text.setObjectName("resetText")
        self._reset_text.clicked.connect(self._reset_readout)
        form.addRow("", self._reset_text)
        return section

    def _artwork_section(self) -> InspectorSection:
        self._artwork_section_widget = section = InspectorSection(
            "Artwork", self, name="artworkSection",
        )
        layout = QVBoxLayout(section.body)
        layout.setContentsMargins(10, 0, 10, 4)
        self._states = QListWidget(section.body)
        self._states.setObjectName("artworkStates")
        self._states.setAccessibleName("Artwork states")
        self._states.setIconSize(THUMBNAIL)
        self._states.setUniformItemSizes(True)
        self._states.itemActivated.connect(lambda _item: self._command(
            InspectorCommand.IMPORT_ARTWORK,
        ))
        self._states.currentRowChanged.connect(lambda _row: self._update_artwork_buttons())
        layout.addWidget(self._states)
        buttons = QHBoxLayout()
        self._import_artwork = QPushButton("Import…", section.body)
        self._import_artwork.setObjectName("importArtwork")
        self._import_artwork.setToolTip("Choose a PNG for the selected state")
        self._import_artwork.clicked.connect(
            lambda: self._command(InspectorCommand.IMPORT_ARTWORK),
        )
        self._remove_artwork = QPushButton("Remove", section.body)
        self._remove_artwork.setObjectName("removeArtwork")
        self._remove_artwork.clicked.connect(
            lambda: self._command(InspectorCommand.REMOVE_ARTWORK),
        )
        buttons.addWidget(self._import_artwork)
        buttons.addWidget(self._remove_artwork)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        hint = caption("Import Normal first. Other states fall back to it.", section.body)
        hint.setAlignment(Qt.AlignmentFlag.AlignLeft)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return section

    # --------------------------------------------------------------- sync
    @property
    def element(self) -> str:
        return self._name

    @property
    def artwork_state(self) -> str:
        item = self._states.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else "normal"

    def sync(self, data: dict, name: str, artwork: FaceArtwork | None) -> None:
        changed_element = name != self._name
        self._name = name
        self._syncing = True
        try:
            self._sync_header(name)
            self._sync_layout(data, name)
            readout = name in READOUT_CONTROLS
            self._text_section_widget.setVisible(readout)
            if readout:
                self._sync_text(data, name)
            artwork_capable = face_elements.can_hold_artwork(
                name, data.get("sliderStyle", "classic"),
            )
            self._artwork_section_widget.setVisible(artwork_capable)
            if artwork_capable:
                self._sync_artwork(data, name, artwork, reset=changed_element)
        finally:
            self._syncing = False

    def _sync_header(self, name: str) -> None:
        self._title.setText(face_elements.LABELS[name])
        self._kind.setText(face_elements.KINDS[name])
        icon = symbol_icon(face_elements.SYMBOLS[name])
        self._icon.setPixmap(icon.pixmap(QSize(20, 20)) if not icon.isNull() else QPixmap())

    def _sync_layout(self, data: dict, name: str) -> None:
        rect = data["drag"] if name == face_elements.DRAG else data["controls"][name]
        for field, value in zip(self._rect_fields, rect, strict=True):
            field.setValue(value)
        is_drag = name == face_elements.DRAG
        self._rotation.setEnabled(not is_drag)
        self._reset_rotation.setEnabled(not is_drag)
        self._rotation.setValue(data.get("controlRotations", {}).get(name, 0))
        shaped = face_elements.has_shape(name)
        self._shape.setVisible(shaped)
        self._shape_label.setVisible(shaped)
        if shaped:
            _select_data(self._shape, data.get("controlShapes", {}).get(name, "rectangle"))

    def _sync_text(self, data: dict, name: str) -> None:
        style = data.get("readoutStyles", {}).get(name, {})
        _select_data(
            self._text_font,
            style.get("font", "mono" if name == "time" else data.get("font", "sans")),
        )
        self._text_size.setValue(
            style.get("size", data.get("timeSize", 24) if name == "time" else 12),
        )
        self._text_style.set_checked("bold", style.get("bold", name == "title"))
        self._text_style.set_checked("italic", style.get("italic", False))
        self._text_align.set_current(style.get("align", "left"))
        self._text_family.show_model_value(style.get("fontFamily", ""))
        palette = data["palette"]
        default = palette["muted"] if name == "status" else palette["readout"]
        self._text_color.set_color(style.get("color", default))
        self._reset_text.setEnabled(bool(style))

    def _sync_artwork(
        self, data: dict, name: str, artwork: FaceArtwork | None, *, reset: bool,
    ) -> None:
        states = list(STATES) + (list(PLAYING_STATES) if name == "play" else [])
        current = "normal" if reset else self.artwork_state
        sprites = data.get("buttons", {}).get(name, {})
        pixmaps = artwork.buttons.get(name, {}) if artwork is not None else {}
        with QSignalBlocker(self._states):
            self._states.clear()
            for state in states:
                path = sprites.get(state)
                if path:
                    detail = path
                elif state == "normal":
                    detail = "Drawn with the face colors"
                else:
                    detail = "Uses Normal"
                item = QListWidgetItem(f"{STATE_LABELS[state]}\n{detail}")
                item.setData(Qt.ItemDataRole.UserRole, state)
                pixmap = pixmaps.get(state)
                if pixmap is not None and not pixmap.isNull():
                    item.setIcon(pixmap.scaled(
                        THUMBNAIL, Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
                self._states.addItem(item)
            self._states.setCurrentRow(states.index(current) if current in states else 0)
        rows = min(len(states), 6)
        self._states.setFixedHeight(
            rows * max(self._states.sizeHintForRow(0), THUMBNAIL.height() + 4) + 6,
        )
        self._sprites = sprites
        self._update_artwork_buttons()

    def _update_artwork_buttons(self) -> None:
        state = self.artwork_state
        sprites = getattr(self, "_sprites", {})
        self._remove_artwork.setEnabled(state in sprites)
        self._import_artwork.setEnabled(state == "normal" or "normal" in sprites)

    # -------------------------------------------------------------- edits
    def _emit(self, path, value, label, coalesce=None) -> None:
        if not self._syncing:
            self.edited.emit(InspectorEdit(path, value, label, coalesce))

    def _command(self, command: InspectorCommand) -> None:
        if not self._syncing:
            self.command.emit(command, self.artwork_state)

    def _edit_rect(self, index: int) -> None:
        if self._syncing:
            return
        field = self._rect_fields[index]
        path = ("drag",) if self._name == face_elements.DRAG else ("controls", self._name)
        label = "Move" if index < 2 else "Resize"
        coalesce = self._steps.key(f"{self._name}:{index}") if field.stepping else None
        self._emit(path, [item.value() for item in self._rect_fields], label, coalesce)

    def _edit_rotation(self, degrees: float) -> None:
        if self._syncing:
            return
        coalesce = self._steps.key(f"{self._name}:rotation") if self._rotation.stepping else None
        self._emit(("controlRotations", self._name), degrees, "Rotate", coalesce)

    def _edit_shape(self) -> None:
        self._emit(("controlShapes", self._name), self._shape.currentData(), "Change Shape")

    def _edit_readout(self, key: str, value, label: str, coalesce=None) -> None:
        if self._name in READOUT_CONTROLS:
            self._emit(("readoutStyles", self._name, key), value, label, coalesce)

    def _edit_text_size(self, size: int) -> None:
        coalesce = self._steps.key(f"{self._name}:size") if self._text_size.stepping else None
        self._edit_readout("size", size, "Change Text Size", coalesce)

    def _edit_family(self, text: str) -> None:
        self._edit_readout("fontFamily", text.strip() or None, "Change Font Family")

    def _reset_readout(self) -> None:
        self._emit(("readoutStyles", self._name), None, "Use Face Text Defaults")

    def commit_pending(self) -> None:
        """Commit typing that has not lost focus yet, e.g. before a save."""
        if self._name in READOUT_CONTROLS and self._text_family.has_pending_edit():
            self._edit_family(self._text_family.text())
        for field in (*self._rect_fields, self._rotation, self._text_size):
            field.interpretText()

    def focus_first_field(self) -> None:
        self._rect_fields[0].setFocus(Qt.FocusReason.TabFocusReason)


class FaceInspector(QWidget):
    edited = Signal(object)  # InspectorEdit
    command = Signal(object, str)  # InspectorCommand, unused argument

    def __init__(self, palette_keys, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("faceInspector")
        self._syncing = False
        self._steps = _StepSessions()
        self._undo_filter = UndoPassthrough(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(4)
        layout.addWidget(self._identity_section())
        layout.addWidget(self._layout_section())
        layout.addWidget(self._background_section())
        layout.addWidget(self._colors_section(palette_keys))
        layout.addWidget(self._credits_section())
        layout.addStretch(1)
        for field in self.findChildren(QWidget):
            if isinstance(field, (NumberField, TextField)):
                field.installEventFilter(self._undo_filter)

    def _identity_section(self) -> InspectorSection:
        section = InspectorSection("Identity", self, name="identitySection")
        form = _form(section.body)
        self._metadata: dict[str, TextField] = {}
        for key, label, limit in IDENTITY_FIELDS:
            field = TextField(section.body, limit=limit, name=f"face{key.title()}")
            field.setAccessibleName(label)
            field.committed.connect(lambda text, key=key: self._emit(
                (key,), text, f"Change {METADATA_LABELS[key]}",
            ))
            self._metadata[key] = field
            form.addRow(label, field)
        self._metadata["id"].setToolTip(
            "Identifies the face in the player. Installed faces need unique IDs."
        )
        return section

    def _layout_section(self) -> InspectorSection:
        section = InspectorSection("Layout", self, name="faceLayoutSection")
        form = _form(section.body)
        self._face_size = [
            NumberField(section.body, 1, MAX_DRAFT_GEOMETRY, name="faceWidth"),
            NumberField(section.body, 1, MAX_DRAFT_GEOMETRY, name="faceHeight"),
        ]
        for field, label in zip(self._face_size, ("Face width", "Face height"), strict=True):
            field.setAccessibleName(label)
            field.valueChanged.connect(self._edit_size)
        form.addRow("Size", _pair(section.body, self._face_size, ("Width", "Height")))
        self._radius = NumberField(section.body, 0, 24, name="faceRadius")
        self._radius.setAccessibleName("Corner radius")
        self._radius.valueChanged.connect(lambda value: self._emit(
            ("radius",), value, "Change Corner Radius",
            self._steps.key("radius") if self._radius.stepping else None,
        ))
        form.addRow("Corners", self._radius)
        self._face_font = _popup(section.body, FONTS, "faceFont")
        self._face_font.setAccessibleName("Default font")
        self._face_font.currentIndexChanged.connect(lambda: self._emit(
            ("font",), self._face_font.currentData(), "Change Font",
        ))
        form.addRow("Font", self._face_font)
        self._slider_style = _popup(section.body, SLIDER_STYLES, "sliderStyle")
        self._slider_style.setAccessibleName("Slider style")
        self._slider_style.currentIndexChanged.connect(lambda: self._emit(
            ("sliderStyle",), self._slider_style.currentData(), "Change Slider Style",
        ))
        form.addRow("Sliders", self._slider_style)
        self._glass = QCheckBox("Reflection over album artwork", section.body)
        self._glass.setObjectName("coverGlass")
        self._glass.toggled.connect(lambda value: self._emit(
            ("coverGlass",), value, "Change Artwork Reflection",
        ))
        form.addRow("", self._glass)
        self._sprite_labels = QCheckBox("Labels over button artwork", section.body)
        self._sprite_labels.setObjectName("spriteLabels")
        self._sprite_labels.toggled.connect(lambda value: self._emit(
            ("spriteLabels",), value, "Change Button Labels",
        ))
        form.addRow("", self._sprite_labels)
        return section

    def _background_section(self) -> InspectorSection:
        section = InspectorSection("Background", self, name="backgroundSection")
        form = _form(section.body)
        self._background_preview = QLabel(section.body)
        self._background_preview.setObjectName("backgroundPreview")
        self._background_preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._background_preview.setFixedHeight(BACKGROUND_PREVIEW_HEIGHT)
        self._background_preview.setFrameShape(QFrame.Shape.StyledPanel)
        form.addRow(self._background_preview)
        self._background_name = caption("", section.body)
        self._background_name.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow(self._background_name)
        import_background = QPushButton("Import Image…", section.body)
        import_background.setObjectName("importBackground")
        import_background.clicked.connect(
            lambda: self.command.emit(InspectorCommand.IMPORT_BACKGROUND, ""),
        )
        form.addRow("Image", import_background)
        self._adopt_background = QCheckBox("Resize face to fit the image", section.body)
        self._adopt_background.setObjectName("adoptBackgroundSize")
        self._adopt_background.setToolTip(
            "When off, the image must match the face size at 1x or 2x."
        )
        form.addRow("", self._adopt_background)
        mask_row = QWidget(section.body)
        mask = QHBoxLayout(mask_row)
        mask.setContentsMargins(0, 0, 0, 0)
        self._mask_import = QPushButton("Import…", mask_row)
        self._mask_import.setObjectName("importMask")
        self._mask_import.clicked.connect(
            lambda: self.command.emit(InspectorCommand.IMPORT_MASK, ""),
        )
        self._mask_remove = QPushButton("Remove", mask_row)
        self._mask_remove.setObjectName("removeMask")
        self._mask_remove.clicked.connect(
            lambda: self.command.emit(InspectorCommand.REMOVE_MASK, ""),
        )
        mask.addWidget(self._mask_import)
        mask.addWidget(self._mask_remove)
        mask.addStretch(1)
        form.addRow("Window Mask", mask_row)
        self._mask_name = caption("", section.body)
        self._mask_name.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._mask_name.setWordWrap(True)
        self._mask_name.setTextFormat(Qt.TextFormat.PlainText)
        form.addRow("", self._mask_name)
        return section

    def _colors_section(self, palette_keys) -> InspectorSection:
        section = InspectorSection("Colors", self, name="colorsSection")
        grid = QGridLayout(section.body)
        grid.setContentsMargins(10, 0, 10, 4)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self._colors: dict[str, ColorWell] = {}
        for index, key in enumerate(palette_keys):
            label = PALETTE_LABELS.get(key, key)
            well = ColorWell(label, section.body)
            well.setObjectName(f"color-{key}")
            well.picked.connect(lambda color, session, key=key, label=label: self._emit(
                ("palette", key), color.name(), f"Change {label} Color", session,
            ))
            self._colors[key] = well
            row, column = divmod(index, 2)
            text = QLabel(label, section.body)
            text.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            text.setBuddy(well)
            grid.addWidget(text, row, column * 2)
            grid.addWidget(well, row, column * 2 + 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        return section

    def _credits_section(self) -> InspectorSection:
        self._credits_section_widget = section = InspectorSection(
            "Original Credits", self, name="creditsSection",
        )
        layout = QVBoxLayout(section.body)
        layout.setContentsMargins(10, 0, 10, 4)
        self._source_credit = QPlainTextEdit(section.body)
        self._source_credit.setReadOnly(True)
        self._source_credit.setAccessibleName("Original face credits")
        self._source_credit.setMaximumHeight(120)
        self._source_credit.setTabChangesFocus(True)
        layout.addWidget(self._source_credit)
        return section

    @property
    def adopt_background_size(self) -> bool:
        return self._adopt_background.isChecked()

    def sync(self, data: dict, artwork: FaceArtwork | None) -> None:
        self._syncing = True
        try:
            for key, field in self._metadata.items():
                field.show_model_value(data[key])
            for field, value in zip(self._face_size, data["size"], strict=True):
                field.setValue(value)
            self._radius.setValue(data.get("radius", 4))
            _select_data(self._face_font, data.get("font", "sans"))
            _select_data(self._slider_style, data.get("sliderStyle", "classic"))
            with QSignalBlocker(self._glass):
                self._glass.setChecked(data.get("coverGlass", False))
            with QSignalBlocker(self._sprite_labels):
                self._sprite_labels.setChecked(data.get("spriteLabels", True))
            self._background_name.setText(data["background"])
            if artwork is not None and not artwork.background.isNull():
                self._background_preview.setPixmap(artwork.background.scaled(
                    QSize(240, BACKGROUND_PREVIEW_HEIGHT - 8), Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ))
            mask = data.get("alphaMask")
            self._mask_name.setText(mask or "None. The background's transparency shapes the face.")
            self._mask_remove.setEnabled(mask is not None)
            for key, well in self._colors.items():
                well.set_color(QColor(data["palette"][key]))
            credit = data.get("sourceCredit", "")
            if self._source_credit.toPlainText() != credit:
                self._source_credit.setPlainText(credit)
            self._credits_section_widget.setVisible(bool(credit))
        finally:
            self._syncing = False

    def _emit(self, path, value, label, coalesce=None) -> None:
        if not self._syncing:
            self.edited.emit(InspectorEdit(path, value, label, coalesce))

    def _edit_size(self) -> None:
        if self._syncing:
            return
        stepping = any(field.stepping for field in self._face_size)
        self._emit(
            ("size",), [field.value() for field in self._face_size], "Resize Face",
            self._steps.key("size") if stepping else None,
        )

    def commit_pending(self) -> None:
        for key, field in self._metadata.items():
            if field.has_pending_edit():
                self._emit((key,), field.text(), f"Change {METADATA_LABELS[key]}")
        for field in (*self._face_size, self._radius):
            field.interpretText()


class Inspector(QWidget):
    """The Element/Face segmented control over the two scrolling panes."""

    paneChanged = Signal(object)  # InspectorPane

    def __init__(self, palette_keys, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("inspector")
        self.element = ElementInspector()
        self.face = FaceInspector(palette_keys)
        self._tabs = QTabBar(self)
        self._tabs.setObjectName("inspectorTabs")
        self._tabs.setExpanding(False)
        self._tabs.setDrawBase(False)
        self._tabs.addTab("Element")
        self._tabs.addTab("Face")
        self._tabs.setAccessibleName("Inspector pane")
        self._stack = QStackedWidget(self)
        self._stack.addWidget(_scrolling(self.element))
        self._stack.addWidget(_scrolling(self.face))
        self._tabs.currentChanged.connect(self._show_pane)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._tabs, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._stack, 1)

    @property
    def pane(self) -> InspectorPane:
        return InspectorPane(self._tabs.currentIndex())

    def show_pane(self, pane: InspectorPane) -> None:
        self._tabs.setCurrentIndex(pane.value)

    def _show_pane(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.paneChanged.emit(InspectorPane(index))

    def commit_pending(self) -> None:
        self.face.commit_pending()
        self.element.commit_pending()
