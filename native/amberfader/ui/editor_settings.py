"""The face editor's own preferences: recent faces, window layout, toolbar.

Stored as an INI file next to the player's settings (see paths.py), so a
test or a second profile never touches the user's real preferences.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from ..paths import app_dirs

SETTINGS_FILE = "face-editor.ini"
MAX_RECENT_FACES = 10


class ToolbarStyle(Enum):
    ICON_ONLY = "icon"
    ICON_AND_TEXT = "icon-text"
    TEXT_ONLY = "text"


class EditorSettings:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path or app_dirs().config / SETTINGS_FILE
        self._settings = QSettings(str(self._path), QSettings.Format.IniFormat)

    # Recent faces, newest first.
    def recent_faces(self) -> list[Path]:
        value = self._settings.value("recent/faces", [])
        paths = [value] if isinstance(value, str) else list(value or [])
        return [Path(path) for path in paths if isinstance(path, str) and path]

    def note_recent(self, path: Path) -> None:
        path = Path(path)
        recent = [path, *(item for item in self.recent_faces() if item != path)]
        self._settings.setValue(
            "recent/faces", [str(item) for item in recent[:MAX_RECENT_FACES]],
        )

    def clear_recent(self) -> None:
        self._settings.remove("recent/faces")

    def forget_recent(self, path: Path) -> None:
        self._settings.setValue(
            "recent/faces", [str(item) for item in self.recent_faces() if item != Path(path)],
        )

    # Window layout shared by new windows.
    def window_geometry(self) -> QByteArray | None:
        value = self._settings.value("window/geometry")
        return value if isinstance(value, QByteArray) else None

    def set_window_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)

    def panel_visible(self, panel: str, default: bool = True) -> bool:
        value = self._settings.value(f"window/{panel}Visible", default)
        return value in (True, "true", "1", 1)

    def set_panel_visible(self, panel: str, visible: bool) -> None:
        self._settings.setValue(f"window/{panel}Visible", visible)

    def toolbar_style(self, default: ToolbarStyle) -> ToolbarStyle:
        try:
            return ToolbarStyle(self._settings.value("toolbar/style", default.value))
        except ValueError:
            return default

    def set_toolbar_style(self, style: ToolbarStyle) -> None:
        self._settings.setValue("toolbar/style", style.value)

    def last_folder(self) -> Path:
        """Where Open and Save panels start: the last folder used, else Documents."""
        documents = Path.home() / "Documents"
        default = documents if documents.is_dir() else Path.home()
        value = self._settings.value("panels/folder", "")
        folder = Path(value) if isinstance(value, str) and value else default
        return folder if folder.is_dir() else default

    def set_last_folder(self, folder: Path) -> None:
        self._settings.setValue("panels/folder", str(folder))

    # Faces open at the last quit, for window restoration.
    def session_faces(self) -> list[Path]:
        value = self._settings.value("session/faces", [])
        paths = [value] if isinstance(value, str) else list(value or [])
        return [Path(path) for path in paths if isinstance(path, str) and path]

    def set_session_faces(self, paths: list[Path]) -> None:
        self._settings.setValue("session/faces", [str(path) for path in paths])

    def sync(self) -> None:
        self._settings.sync()
