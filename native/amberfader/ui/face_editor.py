"""Native visual editing of portable, data-only face packs."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QLinearGradient, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from ..face_document import SPRITE_CONTROLS, FaceDocument
from ..face_library import (
    BUILTIN_DIRECTORY,
    DEFAULT_FACE_ID,
    MAX_DRAFT_GEOMETRY,
    FaceError,
    FaceLibrary,
)
from .face_editor_canvas import FaceEditorCanvas
from .face_surface import READOUT_CONTROLS, FaceArtwork, prepare_face, prepare_face_preview

if TYPE_CHECKING:
    from ..audion_import import AudionImportResult

BUTTON_CONTROLS = frozenset(
    (
        "previous",
        "play",
        "next",
        "like",
        "search",
        "show",
        "hide",
        "menu",
        "minimize",
        "close",
    )
)
CONTROL_LABELS = {
    "art": "Album artwork",
    "title": "Track title",
    "artists": "Artist / album",
    "time": "Playback time",
    "playback": "Playback state",
    "status": "Connection status",
    "previous": "Previous track",
    "play": "Play / pause",
    "next": "Next track",
    "like": "Like",
    "seek": "Seek slider",
    "volume": "Volume slider",
    "search": "Search",
    "show": "Show YouTube Music",
    "hide": "Hide YouTube Music",
    "menu": "Menu",
    "minimize": "Minimize window",
    "close": "Close window",
    "drag": "Window drag region",
}


class FaceEditorWindow(QMainWindow):
    """A modeless editor; its canvas never sends commands to the music player."""

    def __init__(
        self,
        parent: QWidget | None = None,
        document: FaceDocument | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("faceEditorWindow")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(1220, 780)
        self.setMinimumSize(940, 600)
        self._document = document or FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
        self._syncing = False
        self._metadata_model_values: dict[str, str] = {}
        self._readout_family_model: tuple[str, str] | None = None
        self._artwork: FaceArtwork | None = None
        self._artwork_key = None
        self._cover = self._sample_cover()
        self._canvas = FaceEditorCanvas(self)
        self._canvas.set_document(self._document)
        self._layers = QListWidget(self)
        self._layers.setAccessibleName("Face elements")
        self._layers.setMinimumWidth(180)
        self._layers.setMaximumWidth(250)
        self._validation = QLabel(self)
        self._validation.setTextFormat(Qt.TextFormat.PlainText)
        self._validation.setWordWrap(True)
        self._validation.setObjectName("faceValidation")
        self._validation.setMargin(8)
        self._validation.setMaximumHeight(108)
        self._actions()
        self._build_layout()
        self._layers.currentItemChanged.connect(self._select_layer)
        self._canvas.selectionChanged.connect(self._select_canvas)
        self._canvas.documentChanged.connect(self._changed)
        self._canvas.zoomChanged.connect(self._zoom_changed)
        self._canvas.imageDropped.connect(self._drop_image)
        self._set_document(self._document)

    @property
    def document(self) -> FaceDocument:
        return self._document

    @staticmethod
    def _sample_cover() -> QPixmap:
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

    def _action(self, text: str, shortcut, slot) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _actions(self) -> None:
        self.menuBar().setNativeMenuBar(True)
        self._new_action = self._action(
            "New from template…", QKeySequence.StandardKey.New, self._new
        )
        self._open_action = self._action(
            "Open face folder…", QKeySequence.StandardKey.Open, self._open
        )
        self._audion_import_action = self._action("Import Audion face…", None, self._import_audion)
        self._save_action = self._action("Save", QKeySequence.StandardKey.Save, self.save)
        self._save_as_action = self._action(
            "Save as…", QKeySequence.StandardKey.SaveAs, self.save_as
        )
        self._export_action = self._action("Export copy…", None, self.export)
        self._undo_action = self._action("Undo", QKeySequence.StandardKey.Undo, self._undo)
        self._redo_action = self._action("Redo", QKeySequence.StandardKey.Redo, self._redo)
        self._fit_action = self._action("Fit face", QKeySequence("F"), self._canvas.fit_face)
        self._actual_action = self._action(
            "Actual size", QKeySequence("Ctrl+0"), lambda: self._canvas.set_zoom(1)
        )
        self._add_element_action = self._action("Add element…", None, self._add_element)
        self._remove_element_action = self._action("Remove element", None, self._remove_element)
        file_menu = self.menuBar().addMenu("&File")
        for action in (
            self._new_action,
            self._open_action,
            self._audion_import_action,
            self._save_action,
            self._save_as_action,
            self._export_action,
        ):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(
            self._action("Close editor", QKeySequence.StandardKey.Close, self.close)
        )
        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self._undo_action)
        edit_menu.addAction(self._redo_action)
        edit_menu.addSeparator()
        edit_menu.addAction(self._add_element_action)
        edit_menu.addAction(self._remove_element_action)
        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self._fit_action)
        view_menu.addAction(self._actual_action)
        toolbar = QToolBar("Face editing", self)
        toolbar.setMovable(False)
        for action in (self._new_action, self._open_action, self._save_action):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self._undo_action)
        toolbar.addAction(self._redo_action)
        toolbar.addSeparator()
        toolbar.addAction(self._fit_action)
        self._zoom = QComboBox(toolbar)
        self._zoom.setAccessibleName("Canvas zoom")
        for percent in (25, 50, 75, 100, 125, 150, 200, 300, 400):
            self._zoom.addItem(f"{percent}%", percent / 100)
        self._zoom.activated.connect(
            lambda index: self._canvas.set_zoom(self._zoom.itemData(index))
        )
        toolbar.addWidget(self._zoom)
        self._snap = QCheckBox("Snap to 8 px", toolbar)
        self._snap.setToolTip(
            "Snap move and resize gestures. Hold Option / Alt to bypass snapping."
        )
        self._snap.toggled.connect(self._snap_changed)
        toolbar.addWidget(self._snap)
        self._guides = QCheckBox("Guides", toolbar)
        self._guides.setChecked(True)
        self._guides.toggled.connect(self._canvas.set_guides)
        toolbar.addWidget(self._guides)
        self.addToolBar(toolbar)

    def _build_layout(self) -> None:
        central = QWidget(self)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 8, 12, 8)
        hint = QLabel(
            "Drag elements to move them. Use a corner to resize or the round handle to rotate.",
            central,
        )
        hint.setWordWrap(True)
        root.addWidget(hint)
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        layers_panel = QWidget(splitter)
        left = QVBoxLayout(layers_panel)
        left.setContentsMargins(0, 0, 0, 0)
        title = QLabel("Elements", layers_panel)
        title.setStyleSheet("font-weight: bold;")
        left.addWidget(title)
        left.addWidget(self._layers)
        self._add_element_button = QPushButton("Add element…", layers_panel)
        self._add_element_button.clicked.connect(self._add_element)
        left.addWidget(self._add_element_button)
        self._remove_element_button = QPushButton("Remove element", layers_panel)
        self._remove_element_button.clicked.connect(self._remove_element)
        left.addWidget(self._remove_element_button)
        left.addWidget(
            QLabel("Arrow keys: 1 px\nShift + arrows: 10 px\nShift + rotate: 15°", layers_panel)
        )
        splitter.addWidget(layers_panel)
        splitter.addWidget(self._canvas)
        self._inspector = QTabWidget(splitter)
        self._inspector.setMinimumWidth(280)
        self._inspector.setMaximumWidth(350)
        self._inspector.addTab(self._element_panel(), "Element")
        self._inspector.addTab(self._face_panel(), "Face")
        splitter.addWidget(self._inspector)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([190, 670, 290])
        root.addWidget(splitter, 1)
        root.addWidget(self._validation)
        self.setCentralWidget(central)
        self.statusBar().showMessage(
            "Drop a PNG for the background, or for the selected button's normal sprite."
        )

    def _element_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        self._element_name = QLabel(panel)
        self._element_name.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._element_name)
        geometry = QFormLayout()
        self._rect_fields: list[QSpinBox] = []
        for index, label in enumerate(("X", "Y", "Width", "Height")):
            field = QSpinBox(panel)
            field.setObjectName(f"element{label}")
            field.setRange(-MAX_DRAFT_GEOMETRY if index < 2 else 1, MAX_DRAFT_GEOMETRY)
            field.setKeyboardTracking(False)
            field.setSuffix(" px")
            field.valueChanged.connect(self._edit_rect)
            self._rect_fields.append(field)
            geometry.addRow(label, field)
        self._rotation = QDoubleSpinBox(panel)
        self._rotation.setObjectName("elementRotation")
        self._rotation.setRange(-180, 180)
        self._rotation.setDecimals(1)
        self._rotation.setSuffix("°")
        self._rotation.setKeyboardTracking(False)
        self._rotation.valueChanged.connect(self._edit_rotation)
        geometry.addRow("Rotation", self._rotation)
        layout.addLayout(geometry)
        self._shape_group = QGroupBox("Contour", panel)
        shape_layout = QFormLayout(self._shape_group)
        self._shape = QComboBox(self._shape_group)
        self._shape.addItems(["rectangle", "rounded", "capsule", "ellipse"])
        self._shape.currentTextChanged.connect(self._edit_shape)
        shape_layout.addRow("Shape", self._shape)
        layout.addWidget(self._shape_group)
        self._readout_group = QGroupBox("Screen typography", panel)
        text_layout = QFormLayout(self._readout_group)
        self._text_font = QComboBox(self._readout_group)
        self._text_font.addItems(["sans", "mono", "serif"])
        self._text_font.currentTextChanged.connect(lambda value: self._edit_readout("font", value))
        text_layout.addRow("Font", self._text_font)
        self._text_size = QSpinBox(self._readout_group)
        self._text_size.setRange(6, 36)
        self._text_size.setSuffix(" px")
        self._text_size.setKeyboardTracking(False)
        self._text_size.valueChanged.connect(lambda value: self._edit_readout("size", value))
        text_layout.addRow("Size", self._text_size)
        self._text_align = QComboBox(self._readout_group)
        self._text_align.addItems(["left", "center", "right"])
        self._text_align.currentTextChanged.connect(
            lambda value: self._edit_readout("align", value)
        )
        text_layout.addRow("Alignment", self._text_align)
        self._text_bold = QCheckBox("Bold", self._readout_group)
        self._text_bold.toggled.connect(lambda value: self._edit_readout("bold", value))
        text_layout.addRow(self._text_bold)
        self._text_family = QLineEdit(self._readout_group)
        self._text_family.setMaxLength(96)
        self._text_family.setPlaceholderText("Use the face font")
        self._text_family.editingFinished.connect(self._edit_font_family)
        text_layout.addRow("Font family", self._text_family)
        self._text_italic = QCheckBox("Italic", self._readout_group)
        self._text_italic.toggled.connect(lambda value: self._edit_readout("italic", value))
        text_layout.addRow(self._text_italic)
        self._text_color = QPushButton(self._readout_group)
        self._text_color.clicked.connect(self._pick_readout_color)
        text_layout.addRow("Text color", self._text_color)
        reset = QPushButton("Use face defaults", self._readout_group)
        reset.clicked.connect(self._reset_readout)
        text_layout.addRow(reset)
        layout.addWidget(self._readout_group)
        self._sprite_group = QGroupBox("Button artwork", panel)
        sprite_layout = QVBoxLayout(self._sprite_group)
        self._sprite_state = QComboBox(self._sprite_group)
        self._sprite_state.addItems(["normal", "hover", "pressed", "disabled"])
        self._sprite_state.currentTextChanged.connect(self._sprite_description)
        sprite_layout.addWidget(self._sprite_state)
        self._sprite_info = QLabel(self._sprite_group)
        self._sprite_info.setTextFormat(Qt.TextFormat.PlainText)
        self._sprite_info.setWordWrap(True)
        sprite_layout.addWidget(self._sprite_info)
        sprite_import = QPushButton("Import PNG…", self._sprite_group)
        sprite_import.clicked.connect(self._import_sprite)
        sprite_layout.addWidget(sprite_import)
        layout.addWidget(self._sprite_group)
        layout.addStretch(1)
        return self._scroll(panel)

    @staticmethod
    def _scroll(panel: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(panel)
        return scroll

    def _face_panel(self) -> QWidget:
        panel = QWidget(self)
        layout = QVBoxLayout(panel)
        metadata = QFormLayout()
        self._metadata: dict[str, QLineEdit] = {}
        for key, label, limit in (
            ("name", "Name", 64),
            ("id", "Pack ID", 48),
            ("author", "Author", 96),
            ("description", "Description", 240),
        ):
            field = QLineEdit(panel)
            field.setMaxLength(limit)
            field.setObjectName(f"face{key.title()}")
            field.editingFinished.connect(lambda key=key: self._edit_metadata(key))
            self._metadata[key] = field
            metadata.addRow(label, field)
        self._face_size: list[QSpinBox] = []
        for label, minimum, maximum in (
            ("Face width", 360, 1024),
            ("Face height", 180, 768),
        ):
            field = QSpinBox(panel)
            field.setRange(minimum, maximum)
            field.setSuffix(" px")
            field.setKeyboardTracking(False)
            field.valueChanged.connect(self._edit_size)
            self._face_size.append(field)
            metadata.addRow(label, field)
        self._face_font = QComboBox(panel)
        self._face_font.addItems(["sans", "mono", "serif"])
        self._face_font.currentTextChanged.connect(lambda value: self._edit_value(("font",), value))
        metadata.addRow("Default font", self._face_font)
        self._radius = QSpinBox(panel)
        self._radius.setRange(0, 24)
        self._radius.setKeyboardTracking(False)
        self._radius.valueChanged.connect(lambda value: self._edit_value(("radius",), value))
        metadata.addRow("Corner radius", self._radius)
        self._slider_style = QComboBox(panel)
        self._slider_style.addItems(["classic", "inset", "popup"])
        self._slider_style.currentTextChanged.connect(
            lambda value: self._edit_value(("sliderStyle",), value),
        )
        metadata.addRow("Slider style", self._slider_style)
        self._glass = QCheckBox("Reflection over album artwork", panel)
        self._glass.toggled.connect(lambda value: self._edit_value(("coverGlass",), value))
        metadata.addRow(self._glass)
        self._sprite_labels = QCheckBox("Draw labels over button artwork", panel)
        self._sprite_labels.toggled.connect(
            lambda value: self._edit_value(("spriteLabels",), value),
        )
        metadata.addRow(self._sprite_labels)
        layout.addLayout(metadata)
        self._source_credit = QPlainTextEdit(panel)
        self._source_credit.setReadOnly(True)
        self._source_credit.setAccessibleName("Original face credits")
        self._source_credit.setMaximumHeight(140)
        layout.addWidget(self._source_credit)
        background_group = QGroupBox("Background", panel)
        background_layout = QVBoxLayout(background_group)
        self._background_name = QLabel(background_group)
        self._background_name.setTextFormat(Qt.TextFormat.PlainText)
        background_layout.addWidget(self._background_name)
        background_import = QPushButton("Import background PNG…", background_group)
        background_import.clicked.connect(self._import_background)
        background_layout.addWidget(background_import)
        self._adopt_background = QCheckBox(
            "Use imported PNG dimensions as face size", background_group
        )
        self._adopt_background.setToolTip(
            "When unchecked, the PNG must match the face at 1x or 2x."
        )
        background_layout.addWidget(self._adopt_background)
        self._alpha_mask_name = QLabel(background_group)
        self._alpha_mask_name.setTextFormat(Qt.TextFormat.PlainText)
        self._alpha_mask_name.setWordWrap(True)
        background_layout.addWidget(self._alpha_mask_name)
        mask_import = QPushButton("Import window mask PNG…", background_group)
        mask_import.clicked.connect(self._import_alpha_mask)
        background_layout.addWidget(mask_import)
        self._clear_alpha_mask_button = QPushButton("Remove window mask", background_group)
        self._clear_alpha_mask_button.clicked.connect(self._clear_alpha_mask)
        background_layout.addWidget(self._clear_alpha_mask_button)
        layout.addWidget(background_group)
        palette_group = QGroupBox("Palette", panel)
        palette_layout = QFormLayout(palette_group)
        self._colors: dict[str, QPushButton] = {}
        for key in self._document.manifest["palette"]:
            button = QPushButton(palette_group)
            button.clicked.connect(lambda checked=False, key=key: self._pick_color(key))
            self._colors[key] = button
            palette_layout.addRow(key, button)
        layout.addWidget(palette_group)
        layout.addStretch(1)
        return self._scroll(panel)

    def _set_document(self, document: FaceDocument) -> None:
        for field in self._metadata.values():
            field.clearFocus()
        self._document = document
        self._canvas.set_document(document)
        self._artwork_key = None
        self._artwork = None
        self._refresh_layers()
        self._changed()
        self._canvas.fit_face()

    def _refresh_layers(self) -> None:
        names = [*self._document.manifest["controls"], "drag"]
        selected = self._canvas.selected
        if selected not in names:
            selected = "play" if "play" in names else names[0]
            self._canvas.select(selected)
        existing = [
            self._layers.item(index).data(Qt.ItemDataRole.UserRole)
            for index in range(self._layers.count())
        ]
        blocker = QSignalBlocker(self._layers)
        if existing != names:
            self._layers.clear()
            for name in names:
                item = QListWidgetItem(CONTROL_LABELS[name])
                item.setData(Qt.ItemDataRole.UserRole, name)
                self._layers.addItem(item)
        for index, name in enumerate(names):
            if name == selected:
                self._layers.setCurrentRow(index)
                break
        del blocker

    def _select_layer(self, item: QListWidgetItem | None, previous=None) -> None:
        if item is None:
            return
        self._canvas.select(item.data(Qt.ItemDataRole.UserRole))
        self._sync_inspector()

    def _select_canvas(self, name: str) -> None:
        for index in range(self._layers.count()):
            item = self._layers.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                self._layers.setCurrentItem(item)
                break
        self._sync_inspector()

    def _sync_inspector(self) -> None:
        self._syncing = True
        try:
            data = self._document.manifest
            name = self._canvas.selected
            rect = data["drag"] if name == "drag" else data["controls"][name]
            self._element_name.setText(CONTROL_LABELS[name])
            for field, value in zip(self._rect_fields, rect, strict=True):
                field.setValue(value)
            self._rotation.setEnabled(name != "drag")
            self._rotation.setValue(data.get("controlRotations", {}).get(name, 0))
            self._shape_group.setVisible(name in BUTTON_CONTROLS or name == "art")
            self._shape.setCurrentText(data.get("controlShapes", {}).get(name, "rectangle"))
            self._readout_group.setVisible(name in READOUT_CONTROLS)
            if name in READOUT_CONTROLS:
                style = data.get("readoutStyles", {}).get(name, {})
                self._text_font.setCurrentText(
                    style.get("font", "mono" if name == "time" else data.get("font", "sans"))
                )
                self._text_size.setValue(
                    style.get("size", data.get("timeSize", 24) if name == "time" else 12)
                )
                self._text_align.setCurrentText(style.get("align", "left"))
                self._text_bold.setChecked(style.get("bold", name == "title"))
                family = style.get("fontFamily", "")
                if not self._text_family.hasFocus() or self._readout_family_model != (name, family):
                    self._text_family.setText(family)
                self._readout_family_model = (name, family)
                self._text_italic.setChecked(style.get("italic", False))
                self._text_color.setText(style.get("color", "Use face color"))
            self._sprite_group.setVisible(self._uses_button_artwork(name))
            states = ["normal", "hover", "pressed", "disabled"]
            if name == "play":
                states += ["playing", "playing-hover", "playing-pressed", "playing-disabled"]
            current_states = [
                self._sprite_state.itemText(index) for index in range(self._sprite_state.count())
            ]
            if states != current_states:
                state = self._sprite_state.currentText()
                self._sprite_state.clear()
                self._sprite_state.addItems(states)
                self._sprite_state.setCurrentText(state if state in states else "normal")
            self._sprite_description()
            for key, field in self._metadata.items():
                value = data[key]
                # Preserve text still being typed during unrelated layout refreshes.
                # Undo and document replacement still update a focused field when
                # its committed model value changes.
                if not field.hasFocus() or self._metadata_model_values.get(key) != value:
                    field.setText(value)
                self._metadata_model_values[key] = value
            compact = data["formatVersion"] >= 3
            for index, (field, value) in enumerate(zip(self._face_size, data["size"], strict=True)):
                if compact:
                    field.setRange(1, MAX_DRAFT_GEOMETRY)
                else:
                    field.setRange(360 if index == 0 else 180, 1024 if index == 0 else 768)
                field.setValue(value)
            self._face_font.setCurrentText(data.get("font", "sans"))
            self._radius.setValue(data.get("radius", 4))
            self._slider_style.setCurrentText(data.get("sliderStyle", "classic"))
            self._glass.setChecked(data.get("coverGlass", False))
            self._sprite_labels.setChecked(data.get("spriteLabels", True))
            self._source_credit.setPlainText(data.get("sourceCredit", ""))
            self._source_credit.setVisible(bool(data.get("sourceCredit")))
            self._remove_element_action.setEnabled(name != "drag")
            self._remove_element_button.setEnabled(name != "drag")
            can_add = any(
                control not in data["controls"] for control in CONTROL_LABELS if control != "drag"
            )
            self._add_element_action.setEnabled(can_add)
            self._add_element_button.setEnabled(can_add)
            self._background_name.setText(data["background"])
            self._alpha_mask_name.setText(data.get("alphaMask", "No separate window mask"))
            self._clear_alpha_mask_button.setEnabled("alphaMask" in data)
            for key, button in self._colors.items():
                color = data["palette"][key]
                button.setText(color)
                foreground = "#ffffff" if QColor(color).lightnessF() < 0.5 else "#15191f"
                button.setStyleSheet(f"background-color: {color}; color: {foreground};")
        finally:
            self._syncing = False

    def _changed(self) -> None:
        self._refresh_layers()
        problems = list(self._document.validate())
        try:
            face = self._document.preview()
            key = (
                face.background,
                face.alpha_mask,
                tuple((name, tuple(images.items())) for name, images in face.buttons.items()),
                face.time_digits,
            )
            if key != self._artwork_key or self._artwork is None:
                self._artwork = prepare_face_preview(face)
                self._artwork_key = key
            self._canvas.set_preview(face, self._artwork, self._cover)
            if not problems:
                try:
                    prepare_face(face)
                except FaceError as exc:
                    problems.append(str(exc))
        except (FaceError, OSError, ValueError) as exc:
            if str(exc) not in problems:
                problems.append(str(exc))
        if problems:
            self._validation.setText("Cannot save yet: " + "\n".join(problems[:4]))
            self._validation.setStyleSheet(
                "background: #fff0da; color: #673d08; border-radius: 5px;"
            )
        else:
            self._validation.setText(
                "Ready to save. The pack includes its manifest and all declared PNG assets."
            )
            self._validation.setStyleSheet(
                "background: #e3f0e9; color: #205337; border-radius: 5px;"
            )
        self._save_action.setEnabled(not problems)
        self._save_as_action.setEnabled(not problems)
        self._export_action.setEnabled(not problems)
        self._undo_action.setEnabled(self._document.can_undo)
        self._redo_action.setEnabled(self._document.can_redo)
        self._sync_inspector()
        data = self._document.manifest
        self.setWindowTitle(f"{data['name']}[*] · Amberfader Face Editor")
        self.setWindowModified(self._document.dirty)
        self.setWindowFilePath(str(self._document.path) if self._document.path is not None else "")

    def _edit_rect(self) -> None:
        if self._syncing:
            return
        self._document.set_rect(
            self._canvas.selected, [field.value() for field in self._rect_fields]
        )
        self._changed()

    def _edit_rotation(self, degrees: float) -> None:
        if self._syncing:
            return
        self._document.set_rotation(self._canvas.selected, degrees)
        self._changed()

    def _edit_shape(self, shape: str) -> None:
        self._edit_value(("controlShapes", self._canvas.selected), shape)

    def _edit_readout(self, key: str, value) -> None:
        self._edit_value(("readoutStyles", self._canvas.selected, key), value)

    def _reset_readout(self) -> None:
        self._edit_value(("readoutStyles", self._canvas.selected), None)

    def _edit_font_family(self) -> None:
        if self._syncing or self._canvas.selected not in READOUT_CONTROLS:
            return
        self._edit_readout("fontFamily", self._text_family.text().strip() or None)

    def _pick_readout_color(self) -> None:
        data = self._document.manifest
        style = data.get("readoutStyles", {}).get(self._canvas.selected, {})
        color = QColorDialog.getColor(
            QColor(style.get("color", data["palette"]["readout"])),
            self, "Choose screen text color",
        )
        if color.isValid():
            self._edit_readout("color", color.name())

    def _edit_metadata(self, key: str) -> None:
        self._edit_value((key,), self._metadata[key].text())

    def _edit_size(self) -> None:
        self._edit_value(("size",), [field.value() for field in self._face_size])

    def _edit_value(self, path: tuple[str, ...], value) -> None:
        if self._syncing:
            return
        self._document.set_value(path, value)
        self._changed()

    def _undo(self) -> None:
        self._canvas.finish_gesture()
        self._document.undo()
        self._changed()

    def _redo(self) -> None:
        self._canvas.finish_gesture()
        self._document.redo()
        self._changed()

    def _add_element(self) -> None:
        missing = [
            name for name in CONTROL_LABELS
            if name != "drag" and name not in self._document.manifest["controls"]
        ]
        if not missing:
            return
        labels = [CONTROL_LABELS[name] for name in missing]
        label, accepted = QInputDialog.getItem(
            self, "Add element", "Choose a playback control or readout", labels, 0, False,
        )
        if not accepted:
            return
        name = missing[labels.index(label)]
        self._flush_inspector()
        self._canvas.finish_gesture()
        width, height = self._document.manifest["size"]
        if name in BUTTON_CONTROLS:
            control_width, control_height = 48, 32
        elif name == "art":
            control_width, control_height = 64, 64
        elif name in ("seek", "volume"):
            control_width, control_height = 120, 16
        else:
            control_width, control_height = 160, 28
        control_width, control_height = min(control_width, width), min(control_height, height)
        self._document.set_rect(name, [
            (width - control_width) // 2, (height - control_height) // 2,
            control_width, control_height,
        ])
        self._canvas.select(name)
        self._changed()

    def _remove_element(self) -> None:
        name = self._canvas.selected
        if name == "drag":
            return
        self._flush_inspector()
        self._canvas.finish_gesture()
        self._document.set_value(("controls", name), None)
        self._changed()

    def _zoom_changed(self, scale: float) -> None:
        self._zoom.setPlaceholderText(f"{round(scale * 100)}%")
        matching = next(
            (
                index
                for index in range(self._zoom.count())
                if abs(self._zoom.itemData(index) - scale) < 0.001
            ),
            -1,
        )
        self._zoom.setCurrentIndex(matching)

    def _snap_changed(self, enabled: bool) -> None:
        self._canvas.snap = enabled
        self._canvas.viewport().update()

    def _pick_color(self, key: str) -> None:
        color = QColorDialog.getColor(
            QColor(self._document.manifest["palette"][key]), self, f"Choose {key} color"
        )
        if color.isValid():
            self._edit_value(("palette", key), color.name())

    def _sprite_description(self) -> None:
        if not hasattr(self, "_sprite_info"):
            return
        state = self._sprite_state.currentText()
        path = self._document.manifest.get("buttons", {}).get(self._canvas.selected, {}).get(state)
        self._sprite_info.setText(
            path or ("Uses the normal sprite." if state != "normal" else "Uses the face palette.")
        )

    def _choose_png(self, caption: str) -> Path | None:
        path, _ = QFileDialog.getOpenFileName(self, caption, "", "PNG images (*.png)")
        return Path(path) if path else None

    def _import_background(self) -> None:
        path = self._choose_png("Import background PNG")
        if path is not None:
            self._apply_import(path)

    def _import_alpha_mask(self) -> None:
        path = self._choose_png("Import window mask PNG")
        if path is None:
            return
        try:
            self._document.import_alpha_mask(path)
        except (FaceError, OSError) as exc:
            self._show_error("Could not import window mask", exc)
            return
        self._changed()

    def _clear_alpha_mask(self) -> None:
        self._document.import_alpha_mask(None)
        self._changed()

    def _import_sprite(self) -> None:
        path = self._choose_png("Import button PNG")
        if path is not None:
            self._apply_import(path, self._canvas.selected, self._sprite_state.currentText())

    def _drop_image(self, filename: str, control: str) -> None:
        self._apply_import(Path(filename), control if self._uses_button_artwork(control) else None)

    def _uses_button_artwork(self, name: str) -> bool:
        return name in BUTTON_CONTROLS or (
            name in SPRITE_CONTROLS and self._document.manifest.get("sliderStyle") == "popup"
        )

    def _apply_import(self, path: Path, control: str | None = None, state: str = "normal") -> None:
        try:
            if control is None:
                self._document.import_background(
                    path, adopt_size=self._adopt_background.isChecked()
                )
            else:
                self._document.import_button(control, state, path)
        except (FaceError, OSError) as exc:
            self._show_error("Could not import PNG", exc)
            return
        self._changed()

    def _show_error(self, title: str, error: Exception | str) -> None:
        QMessageBox.warning(self, title, str(error))

    def _flush_inspector(self) -> None:
        # Shortcut saves and window closes need text that has not lost focus yet.
        for key, field in self._metadata.items():
            if field.text() != self._document.manifest[key]:
                self._document.set_value((key,), field.text())
        name = self._canvas.selected
        if name in READOUT_CONTROLS:
            family = self._text_family.text().strip() or None
            style = self._document.manifest.get("readoutStyles", {}).get(name, {})
            if family != style.get("fontFamily"):
                self._document.set_value(("readoutStyles", name, "fontFamily"), family)
        for field in [
            *self._rect_fields,
            self._rotation,
            *self._face_size,
            self._radius,
            self._text_size,
        ]:
            field.interpretText()
        self._changed()

    def _confirm_discard(self) -> bool:
        # Flush before finishing: its refresh must not erase pending inspector text.
        # Save and Cancel preserve the current visible edit, including a drag.
        self._flush_inspector()
        self._canvas.finish_gesture()
        if not self._document.dirty:
            return True
        choice = QMessageBox.warning(
            self,
            "Save your face?",
            "This face has unsaved changes.",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        return self.save() if choice == QMessageBox.StandardButton.Save else True

    def _new(self) -> None:
        library = FaceLibrary()
        templates = list(library.faces)
        names = [face.name for face in templates]
        labels = [
            f"{face.name} ({face.id})" if names.count(face.name) > 1 else face.name
            for face in templates
        ]
        name, accepted = QInputDialog.getItem(
            self, "New face", "Start from a template", labels, 0, False
        )
        if not accepted:
            return
        self.new_from_template(templates[labels.index(name)].source)

    def new_from_template(self, directory: Path) -> bool:
        """Start an independent copy without modifying its original pack."""
        try:
            document = FaceDocument.from_template(Path(directory))
        except (FaceError, OSError) as exc:
            self._show_error("Could not create face", exc)
            return False
        if not self._confirm_discard():
            return False
        self._set_document(document)
        return True

    def _open(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Open face folder")
        if directory:
            self.open_face(Path(directory))

    def _import_audion(self) -> None:
        from .audion_import_dialog import AudionImportDialog

        dialog = AudionImportDialog(self)
        try:
            if dialog.exec() == dialog.DialogCode.Accepted and dialog.import_result is not None:
                self.import_audion_result(dialog.import_result)
        finally:
            dialog.deleteLater()

    def import_audion_result(self, result: AudionImportResult) -> bool:
        """Apply a prepared conversion only after preserving the current working face."""
        try:
            prepare_face(result.document.preview(validate_layout=True))
        except (FaceError, OSError, ValueError) as exc:
            self._show_error("Could not import Audion face", exc)
            return False
        if not self._confirm_discard():
            return False
        self._set_document(result.document)
        self.statusBar().showMessage(
            "Imported an editable copy. Save it to a new folder before installing it.", 10000,
        )
        return True

    def open_face(self, directory: Path) -> bool:
        """Open a pack safely, preserving the current document on any failure."""
        try:
            document = FaceDocument.open(Path(directory))
        except (FaceError, OSError) as exc:
            self._show_error("Could not open face", exc)
            return False
        if not self._confirm_discard():
            return False
        self._set_document(document)
        return True

    def save(self) -> bool:
        self._flush_inspector()
        self._canvas.finish_gesture()
        if self._document.path is None:
            return self.save_as()
        return self._save_to(self._document.path)

    def _destination_folder(self, caption: str) -> Path | None:
        initial = str(self._document.path.parent if self._document.path else Path.home())
        directory = QFileDialog.getExistingDirectory(
            self,
            f"{caption}: choose a new or empty folder",
            initial,
        )
        return Path(directory) if directory else None

    def save_as(self) -> bool:
        self._flush_inspector()
        self._canvas.finish_gesture()
        destination = self._destination_folder("Save face")
        return self._save_to(destination) if destination is not None else False

    def export(self) -> bool:
        """Write a portable copy while preserving the editable working document."""
        self._flush_inspector()
        self._canvas.finish_gesture()
        destination = self._destination_folder("Export face copy")
        if destination is None:
            return False
        try:
            prepare_face(self._document.preview(validate_layout=True))
            exported = self._document.export(destination)
        except (FaceError, OSError, ValueError) as exc:
            self._show_error("Could not export face", exc)
            return False
        self.statusBar().showMessage(f"Exported portable face pack to {exported}", 8000)
        return True

    def _save_to(self, path: Path) -> bool:
        self._canvas.finish_gesture()
        try:
            prepare_face(self._document.preview(validate_layout=True))
            saved = self._document.save(path)
        except (FaceError, OSError, ValueError) as exc:
            self._show_error("Could not save face", exc)
            return False
        self._changed()
        self.statusBar().showMessage(f"Saved portable face pack to {saved}", 8000)
        return True

    def closeEvent(self, event) -> None:
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
