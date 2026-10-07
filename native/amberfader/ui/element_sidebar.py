"""The source list of face elements, grouped like the face itself.

    PLAYBACK
      ⏮ Previous Track
      ⏯ Play / Pause      ← selection follows the canvas
    SCREEN
      …
    [+ ▾] [-]             add a missing element, remove the selected one

The sidebar only reports intent; the window applies edits and owns undo.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QMenu,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import face_elements
from .editor_widgets import secondary_color, symbol_icon

NAME_ROLE = Qt.ItemDataRole.UserRole


class _ElementTree(QTreeWidget):
    """Arrow keys skip group headers; Delete asks to remove the element."""

    removeRequested = Signal()

    def moveCursor(self, action, modifiers):
        index = super().moveCursor(action, modifiers)
        item = self.itemFromIndex(index)
        if item is None or item.data(0, NAME_ROLE) is not None:
            return index
        # A header: continue to its first element, or the previous group's last.
        moving_up = action in (
            QAbstractItemView.CursorAction.MoveUp, QAbstractItemView.CursorAction.MovePageUp,
            QAbstractItemView.CursorAction.MovePrevious,
        )
        if moving_up:
            above = self.itemAbove(item)
            return self.indexFromItem(above) if above is not None else self.currentIndex()
        return self.indexFromItem(item.child(0)) if item.childCount() else self.currentIndex()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            self.removeRequested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ElementSidebar(QWidget):
    selected = Signal(str)
    removeRequested = Signal()
    contextMenuRequested = Signal(str, object)  # element, global QPoint

    def __init__(self, add_menu: QMenu, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("elementSidebar")
        self._tree = _ElementTree(self)
        self._tree.setObjectName("elementList")
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.setIndentation(8)
        self._tree.setFrameShape(QFrame.Shape.NoFrame)
        self._tree.setIconSize(QSize(16, 16))
        self._tree.setAccessibleName("Face elements")
        self._tree.setUniformRowHeights(True)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._context_menu)
        self._tree.currentItemChanged.connect(self._current_changed)
        self._tree.removeRequested.connect(self.removeRequested)
        self._names: list[str] = []

        self._add = QToolButton(self)
        self._add.setObjectName("addElementButton")
        self._add.setIcon(symbol_icon("plus", "list-add"))
        self._add.setText("+")
        self._add.setToolTip("Add an element")
        self._add.setAccessibleName("Add Element")
        self._add.setMenu(add_menu)
        self._add.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._add.setAutoRaise(True)
        self._remove = QToolButton(self)
        self._remove.setObjectName("removeElementButton")
        self._remove.setIcon(symbol_icon("minus", "list-remove"))
        self._remove.setText("-")
        self._remove.setToolTip("Remove the selected element")
        self._remove.setAccessibleName("Remove Element")
        self._remove.setAutoRaise(True)
        self._remove.clicked.connect(self.removeRequested)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 2, 6, 4)
        bar.setSpacing(2)
        bar.addWidget(self._add)
        bar.addWidget(self._remove)
        bar.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._tree, 1)
        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setForegroundRole(QPalette.ColorRole.Mid)
        layout.addWidget(line)
        layout.addLayout(bar)
        self._style_tree()

    def _style_tree(self) -> None:
        # A source list sits on the window background, not a white field.
        palette = self._tree.palette()
        palette.setColor(QPalette.ColorRole.Base, palette.color(QPalette.ColorRole.Window))
        self._tree.setPalette(palette)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == event.Type.PaletteChange:
            self._style_tree()
            self._restyle_headers()

    @property
    def tree(self) -> QTreeWidget:
        return self._tree

    def element_names(self) -> list[str]:
        """The listed elements in display order."""
        return [
            self._tree.topLevelItem(group).child(index).data(0, NAME_ROLE)
            for group in range(self._tree.topLevelItemCount())
            for index in range(self._tree.topLevelItem(group).childCount())
        ]

    def set_elements(self, names: list[str], selected: str) -> None:
        names = face_elements.ordered(names)
        if names != self._names:
            self._names = names
            self._tree.blockSignals(True)
            self._tree.clear()
            present = set(names)
            for title, group in face_elements.GROUPS:
                members = [name for name in group if name in present]
                if not members:
                    continue
                header = QTreeWidgetItem(self._tree, [title.upper()])
                header.setFlags(Qt.ItemFlag.ItemIsEnabled)
                header.setData(0, NAME_ROLE, None)
                for name in members:
                    item = QTreeWidgetItem(header, [face_elements.LABELS[name]])
                    item.setData(0, NAME_ROLE, name)
                    item.setIcon(0, symbol_icon(face_elements.SYMBOLS[name]))
                    item.setToolTip(0, face_elements.KINDS[name])
                header.setExpanded(True)
            self._restyle_headers()
            self._tree.blockSignals(False)
        self.select(selected)
        self._remove.setEnabled(selected != face_elements.DRAG)

    def _restyle_headers(self) -> None:
        color = secondary_color(self._tree.palette())
        for index in range(self._tree.topLevelItemCount()):
            header = self._tree.topLevelItem(index)
            font = QFont(self._tree.font())
            font.setBold(True)
            font.setPointSizeF(max(8.0, font.pointSizeF() - 2))
            header.setFont(0, font)
            header.setForeground(0, color)

    def select(self, name: str) -> None:
        item = self._item(name)
        if item is not None and item is not self._tree.currentItem():
            self._tree.blockSignals(True)
            self._tree.setCurrentItem(item)
            self._tree.blockSignals(False)
        self._remove.setEnabled(name != face_elements.DRAG)

    def set_can_add(self, can_add: bool) -> None:
        self._add.setEnabled(can_add)

    def _item(self, name: str) -> QTreeWidgetItem | None:
        for index in range(self._tree.topLevelItemCount()):
            header = self._tree.topLevelItem(index)
            for child in range(header.childCount()):
                item = header.child(child)
                if item.data(0, NAME_ROLE) == name:
                    return item
        return None

    def _current_changed(self, item: QTreeWidgetItem | None, _previous=None) -> None:
        name = item.data(0, NAME_ROLE) if item is not None else None
        if name is not None:
            self.selected.emit(name)

    def _context_menu(self, position) -> None:
        item = self._tree.itemAt(position)
        name = item.data(0, NAME_ROLE) if item is not None else None
        if name is None:
            return
        self._tree.setCurrentItem(item)
        self.contextMenuRequested.emit(name, self._tree.viewport().mapToGlobal(position))
