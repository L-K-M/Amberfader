"""Qt-free face editing, bounded PNG snapshots and transactional folder saves.

The document owns every byte used by its preview. Editing never writes into the
source pack; only an explicit save publishes a fully validated portable folder.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from amberfader import face_library
from amberfader.face_library import (
    BUILTIN_DIRECTORY,
    FACE_FORMAT_VERSION,
    MAX_IMAGE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PACK_BYTES,
    PACK_LIMIT_ERROR,
    Face,
    FaceError,
)

MAX_HISTORY_STEPS = 100
MAX_HISTORY_BYTES = 64 * 1024 * 1024
BUTTONS = frozenset({
    "previous", "play", "next", "like", "search", "show", "hide", "menu", "minimize", "close",
})
READOUTS = frozenset({"title", "artists", "time", "playback", "status"})
CONTROLS = BUTTONS | READOUTS | {"art", "seek", "volume"}
PALETTE_KEYS = frozenset({
    "window", "panel", "display", "text", "muted", "readout", "accent", "border",
    "buttonTop", "buttonBottom", "danger",
})
SIMPLE_FIELDS = frozenset({
    "id", "name", "author", "description", "size", "drag", "font", "timeSize", "radius",
    "coverGlass", "sliderStyle",
})
OPTIONAL_FIELDS = frozenset({"font", "timeSize", "radius", "coverGlass", "sliderStyle"})
VERSION_TWO_FIELDS = frozenset({
    "coverGlass", "sliderStyle", "controlShapes", "controlRotations", "readoutStyles",
})
BUTTON_STATES = frozenset({"normal", "hover", "pressed", "disabled"})


@dataclass(frozen=True)
class _Snapshot:
    manifest: bytes
    assets: Mapping[str, bytes]

    def data(self) -> dict[str, Any]:
        return json.loads(self.manifest)


def _declared_names(data: dict[str, Any]) -> set[str]:
    names = {data["background"]}
    for states in data.get("buttons", {}).values():
        names.update(states.values())
    return names


def _snapshot(data: dict[str, Any], assets: Mapping[str, bytes]) -> _Snapshot:
    try:
        manifest = json.dumps(data, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    except (TypeError, ValueError, RecursionError) as exc:
        raise FaceError("Face edits must contain finite JSON values") from exc
    if len(manifest) > MAX_MANIFEST_BYTES:
        raise FaceError("Face manifest exceeds the 64 KiB limit")
    selected = {name: assets[name] for name in _declared_names(data) if name in assets}
    if sum(map(len, selected.values())) > MAX_PACK_BYTES:
        raise FaceError(PACK_LIMIT_ERROR)
    return _Snapshot(manifest, MappingProxyType(selected))


def _read_snapshot(source: Path) -> _Snapshot:
    data = face_library._manifest(source)
    assets = {}
    total = 0
    for name in sorted(_declared_names(data)):
        assets[name] = face_library._image(source, name)[0]
        total += len(assets[name])
        if total > MAX_PACK_BYTES:
            raise FaceError(PACK_LIMIT_ERROR)
    snapshot = _snapshot(data, assets)
    face_library.load_face_snapshot(data, snapshot.assets, source)
    return snapshot


class FaceDocument:
    """An editable face with undoable commands and a saved checkpoint.

    Bounded layout mistakes remain editable and can be rendered as draft previews.
    Saves always use strict validation, even while a gesture is active.
    """

    def __init__(self, snapshot: _Snapshot, path: Path | None = None) -> None:
        self._current = snapshot
        self._saved = snapshot if path is not None else None
        self._disk_snapshot = snapshot if path is not None else None
        self._path = path
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._gesture: _Snapshot | None = None

    @classmethod
    def open(cls, folder: Path) -> FaceDocument:
        """Load a validated snapshot; opening a bundled pack makes a custom copy."""
        source = Path(folder).resolve()
        if source.is_relative_to(BUILTIN_DIRECTORY.resolve()):
            return cls.from_template(source)
        try:
            return cls(_read_snapshot(source), source)
        except (OSError, ValueError) as exc:
            raise FaceError(f"Cannot open face: {exc}") from exc

    @classmethod
    def from_template(
        cls, folder: Path, *, face_id: str | None = None, name: str | None = None,
    ) -> FaceDocument:
        """Clone a pack as an unsaved version 2 face with a custom identity."""
        source = Path(folder).resolve()
        try:
            snapshot = _read_snapshot(source)
            data = snapshot.data()
            data["formatVersion"] = FACE_FORMAT_VERSION
            data["id"] = (
                face_id if face_id is not None
                else data["id"][:31] + "-custom-" + uuid4().hex[:8]
            )
            data["name"] = name if name is not None else data["name"][:57] + " Custom"
            document = cls(_snapshot(data, snapshot.assets))
            document.preview(validate_layout=True)
            return document
        except (OSError, ValueError) as exc:
            raise FaceError(f"Cannot create face: {exc}") from exc

    @property
    def manifest(self) -> dict[str, Any]:
        return self._current.data()

    @property
    def assets(self) -> Mapping[str, bytes]:
        return self._current.assets

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def dirty(self) -> bool:
        return self._current != self._saved

    @property
    def can_undo(self) -> bool:
        return bool(self._undo) or self._gesture_changed()

    @property
    def can_redo(self) -> bool:
        return bool(self._redo) and not self._gesture_changed()

    def _gesture_changed(self) -> bool:
        return self._gesture is not None and self._gesture != self._current

    def set_value(self, path: tuple[str, ...], value: Any) -> None:
        """Edit a presentation field. None removes an optional override."""
        self._check_edit_path(path, value)
        data = self.manifest
        target = data
        for part in path[:-1]:
            if value is None and part not in target:
                return
            target = target.setdefault(part, {})
        if value is None:
            target.pop(path[-1], None)
        else:
            target[path[-1]] = value
        if path[0] in VERSION_TWO_FIELDS:
            data["formatVersion"] = FACE_FORMAT_VERSION
        self._apply(_snapshot(data, self.assets))

    @staticmethod
    def _check_edit_path(path: tuple[str, ...], value: Any) -> None:
        allowed = len(path) == 1 and path[0] in SIMPLE_FIELDS
        if len(path) == 2:
            group, key = path
            allowed = (
                (group == "controls" and key in CONTROLS)
                or (group == "palette" and key in PALETTE_KEYS)
                or (group == "controlShapes" and key in BUTTONS | {"art"})
                or (group == "controlRotations" and key in CONTROLS)
                or (group == "readoutStyles" and key in READOUTS and value is None)
            )
        elif len(path) == 3:
            group, control, key = path
            allowed = (
                group == "readoutStyles" and control in READOUTS
                and key in {"align", "font", "size", "bold"}
            )
        if not allowed:
            raise FaceError("This field cannot be edited directly; import PNG assets instead")
        if value is None and (
            path[0] in {"controls", "palette"}
            or (len(path) == 1 and path[0] not in OPTIONAL_FIELDS)
        ):
            raise FaceError("Required face fields cannot be removed")

    def set_rect(self, name: str, rect: Sequence[int]) -> None:
        path = ("drag",) if name == "drag" else ("controls", name)
        self.set_value(path, list(rect))

    def set_rotation(self, name: str, degrees: float) -> None:
        self.set_value(("controlRotations", name), degrees)

    def _apply(self, snapshot: _Snapshot) -> None:
        if snapshot == self._current:
            return
        if self._gesture is None:
            self._undo.append(self._current)
            self._redo.clear()
        self._current = snapshot
        self._trim_history()

    def _trim_history(self) -> None:
        del self._undo[:-MAX_HISTORY_STEPS]
        while self._undo or self._redo:
            unique_assets = {}
            snapshots = [self._current, self._saved, self._gesture, *self._undo, *self._redo]
            for snapshot in snapshots:
                if snapshot is not None:
                    unique_assets.update({id(asset): asset for asset in snapshot.assets.values()})
            if sum(map(len, unique_assets.values())) <= MAX_HISTORY_BYTES:
                return
            if self._undo:
                self._undo.pop(0)
            else:
                self._redo.pop(0)

    def begin_gesture(self) -> None:
        if self._gesture is not None:
            raise FaceError("Finish the current gesture before starting another")
        self._gesture = self._current

    def end_gesture(self) -> None:
        if self._gesture is None:
            return
        before = self._gesture
        self._gesture = None
        if before != self._current:
            self._undo.append(before)
            self._redo.clear()
            self._trim_history()

    def cancel_gesture(self) -> None:
        if self._gesture is not None:
            self._current = self._gesture
            self._gesture = None

    def undo(self) -> bool:
        self.end_gesture()
        if not self._undo:
            return False
        self._redo.append(self._current)
        self._current = self._undo.pop()
        return True

    def redo(self) -> bool:
        self.end_gesture()
        if not self._redo:
            return False
        self._undo.append(self._current)
        self._current = self._redo.pop()
        return True

    def _import_image(self, source: Path, prefix: str) -> tuple[str, bytes, tuple[int, int]]:
        try:
            data = face_library._read_bounded(Path(source), MAX_IMAGE_BYTES)
            dimensions = face_library._png_dimensions(data, Path(source).name)
            name = prefix + "-" + hashlib.sha256(data).hexdigest()[:20] + ".png"
            return name, data, dimensions
        except (OSError, ValueError) as exc:
            raise FaceError(f"Cannot import PNG: {exc}") from exc

    def import_background(self, source: Path, *, adopt_size: bool = False) -> None:
        """Snapshot a PNG, preserving the canvas unless adopt_size is requested."""
        name, image, dimensions = self._import_image(source, "background")
        data = self.manifest
        if adopt_size:
            data["size"] = list(dimensions)
        else:
            face_library._check_background_size(data["size"], dimensions)
        data["background"] = name
        self._apply(_snapshot(data, {**self.assets, name: image}))

    def import_button(self, control: str, state: str, source: Path) -> None:
        if control not in BUTTONS or state not in BUTTON_STATES:
            raise FaceError("Choose a supported button and sprite state")
        data = self.manifest
        states = data.setdefault("buttons", {}).setdefault(control, {})
        if state != "normal" and "normal" not in states:
            raise FaceError("Import the normal button sprite before its other states")
        name, image, _ = self._import_image(source, control + "-" + state)
        states[state] = name
        self._apply(_snapshot(data, {**self.assets, name: image}))

    def preview(self, *, validate_layout: bool = False) -> Face:
        validation = (
            face_library.FaceValidation.STRICT if validate_layout
            else face_library.FaceValidation.DRAFT
        )
        source = self._path or BUILTIN_DIRECTORY
        return face_library.load_face_snapshot(
            self.manifest, self.assets, source, validation=validation,
        )

    def validate(self) -> tuple[str, ...]:
        try:
            self.preview(validate_layout=True)
        except FaceError as exc:
            return (str(exc),)
        return ()

    def save(self, path: Path | None = None) -> Path:
        """Save to the opened folder, or Save As to an absent/empty folder."""
        if path is None:
            if self._path is None:
                raise FaceError("Choose a folder to save this custom face")
            path = self._path
        target = self._publish(Path(path), allow_current=True)
        self._path = target
        self._saved = self._current
        self._disk_snapshot = self._current
        return target

    def export(self, path: Path) -> Path:
        """Write a portable folder without moving the working document checkpoint."""
        return self._publish(Path(path), allow_current=False)

    def _publish(self, chosen: Path, *, allow_current: bool) -> Path:
        self.preview(validate_layout=True)
        if chosen.is_symlink():
            raise FaceError("A face destination cannot be a symbolic link")
        target = chosen.resolve()
        if target.is_relative_to(BUILTIN_DIRECTORY.resolve()):
            raise FaceError("Save custom faces outside the bundled face folder")
        replace_current = allow_current and target == self._path
        try:
            if target.exists():
                if not target.is_dir():
                    raise FaceError("Choose an empty folder for the face")
                if replace_current:
                    self._check_source_unchanged(target)
                elif any(target.iterdir()):
                    raise FaceError("Choose a new or empty folder; existing files are protected")
            if not target.parent.is_dir():
                raise FaceError("The parent folder does not exist")
            root = Path(mkdtemp(prefix=".face-edit-", dir=target.parent))
            preserve_recovery = False
            try:
                staging = root / "snapshot"
                staging.mkdir()
                (staging / "face.json").write_bytes(self._current.manifest)
                for name, asset in self.assets.items():
                    (staging / name).write_bytes(asset)
                # Validate the immutable bytes actually staged for publication.
                face_library.load_face(staging)
                backup = root / "previous"
                existed = target.exists()
                if target.is_symlink():
                    raise FaceError("The face destination became a symbolic link")
                if existed:
                    if replace_current:
                        self._check_source_unchanged(target)
                    elif any(target.iterdir()):
                        raise FaceError("The destination changed; choose a new or empty folder")
                    target.replace(backup)
                try:
                    if existed:
                        # Check the folder actually renamed, not just the path
                        # observed before replacement. A concurrent writer may
                        # have added or changed files immediately before rename.
                        if backup.is_symlink() or not backup.is_dir():
                            raise FaceError("The destination changed during publication")
                        if replace_current:
                            self._check_source_unchanged(backup)
                        elif any(backup.iterdir()):
                            raise FaceError("The destination changed during publication")
                    staging.replace(target)
                except (OSError, FaceError) as publish_error:
                    if existed:
                        try:
                            backup.replace(target)
                        except OSError as restore_error:
                            preserve_recovery = True
                            raise FaceError(
                                f"Publication failed: {publish_error}. The original face is "
                                f"preserved at {backup}; restoration failed: {restore_error}"
                            ) from restore_error
                    raise
            finally:
                # A failed rollback must retain the original bytes for recovery.
                if not preserve_recovery:
                    shutil.rmtree(root, ignore_errors=True)
        except (OSError, ValueError) as exc:
            raise FaceError(f"Cannot save face: {exc}") from exc
        return target

    def _check_source_unchanged(self, target: Path) -> None:
        assert self._disk_snapshot is not None
        expected_names = {"face.json", *self._disk_snapshot.assets}
        actual_files = list(target.iterdir())
        if (
            {file.name for file in actual_files} != expected_names
            or any(not file.is_file() or file.is_symlink() for file in actual_files)
            or _read_snapshot(target) != self._disk_snapshot
        ):
            raise FaceError("The face folder changed outside this editor; reopen it or use Save As")
