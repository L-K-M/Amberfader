"""The player's faces, listed in the editor so you can pick one to edit.

    Faces panel
    ├─ Installed (n)   your faces folder; Save writes back to the face
    └─ Built-in (n)    shipped with Amberfader; opens as an unsaved copy
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QLineEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..face_library import BUILTIN_DIRECTORY, FaceError, FaceInfo, FaceLibrary

MAX_SHOWN_PROBLEMS = 3
SOURCE_ROLE = Qt.ItemDataRole.UserRole


class FaceLibraryPanel(QWidget):
    """Requests edits only; the editor decides how to open each face."""

    editRequested = Signal(Path)

    def __init__(self, library: FaceLibrary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._library = library
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter faces by name")
        self._filter.setAccessibleName("Filter faces")
        self._filter.setClearButtonEnabled(True)
        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setAccessibleName("Installed and built-in faces")
        self._installed = QTreeWidgetItem(self._tree)
        self._bundled = QTreeWidgetItem(self._tree)
        for group in (self._installed, self._bundled):
            group.setFlags(Qt.ItemFlag.ItemIsEnabled)
            group.setExpanded(True)
        self._edit = QPushButton("Edit face", self)
        self._edit.setEnabled(False)
        hint = QLabel(
            "Installed faces save in place. Built-in faces open as a copy.", self,
        )
        hint.setWordWrap(True)
        self._problems = QLabel(self)
        self._problems.setTextFormat(Qt.TextFormat.PlainText)
        self._problems.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(self._filter)
        layout.addWidget(self._tree, 1)
        layout.addWidget(self._edit)
        layout.addWidget(hint)
        layout.addWidget(self._problems)

        self._filter.textChanged.connect(self._apply_filter)
        self._tree.currentItemChanged.connect(self._selection_changed)
        self._tree.itemActivated.connect(self._request_edit)
        self._edit.clicked.connect(lambda: self._request_edit(self._tree.currentItem()))
        self._populate()

    def reload(self, current: Path | None = None) -> None:
        """Rescan the faces folder, e.g. after an import or a save.

        A failed rescan keeps the previous list and shows why.
        """
        try:
            self._library.refresh()
        except FaceError as exc:
            self._problems.setText(str(exc))
            self._problems.setVisible(True)
            return
        self._populate()
        self.select(current)

    def select(self, source: Path | None) -> bool:
        """Select the listed face stored at `source`, if there is one."""
        if source is None:
            return False
        source = source.resolve()
        for group in (self._installed, self._bundled):
            for index in range(group.childCount()):
                item = group.child(index)
                if item.data(0, SOURCE_ROLE) == source and not item.isHidden():
                    self._tree.setCurrentItem(item)
                    return True
        return False

    def _populate(self) -> None:
        bundled_root = BUILTIN_DIRECTORY.resolve()
        installed: list[FaceInfo] = []
        bundled: list[FaceInfo] = []
        for info in self._library.faces:
            (bundled if info.source.is_relative_to(bundled_root) else installed).append(info)

        for group, faces in ((self._installed, installed), (self._bundled, bundled)):
            group.takeChildren()
            for info in sorted(faces, key=lambda face: (face.name.casefold(), face.id)):
                item = QTreeWidgetItem(group, [info.name])
                item.setData(0, SOURCE_ROLE, info.source)
                item.setToolTip(0, f"{info.name} · {info.author}\n{info.description}\n{info.id}")
        self._installed.setText(0, f"Installed ({len(installed)})")
        self._bundled.setText(0, f"Built-in ({len(bundled)})")

        problems = self._library.problems
        hidden = len(problems) - MAX_SHOWN_PROBLEMS
        lines = list(problems[:MAX_SHOWN_PROBLEMS])
        if hidden > 0:
            lines.append(f"…and {hidden} more problems")
        self._problems.setText("\n".join(lines))
        self._problems.setVisible(bool(lines))
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._filter.text().casefold().strip()
        for group in (self._installed, self._bundled):
            shown = 0
            for index in range(group.childCount()):
                item = group.child(index)
                item.setHidden(query not in item.text(0).casefold())
                shown += not item.isHidden()
            group.setHidden(group.childCount() > 0 and shown == 0)

        # Edit face must never act on a face the filter hides.
        current = self._tree.currentItem()
        if current is not None and current.isHidden():
            self._tree.setCurrentItem(None)

    def _selection_changed(self, item: QTreeWidgetItem | None, previous=None) -> None:
        self._edit.setEnabled(item is not None and item.data(0, SOURCE_ROLE) is not None)

    def _request_edit(self, item: QTreeWidgetItem | None, column: int = 0) -> None:
        if item is None:
            return
        source = item.data(0, SOURCE_ROLE)
        if source is not None:
            self.editRequested.emit(source)
