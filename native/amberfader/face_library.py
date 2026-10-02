"""Versioned, data-only face plugins and local appearance preferences.

Faces describe presentation, never commands. Only declared, bounded PNG files
are installed; executable plugins and stylesheet imports are not part of v1.
This module has no Qt dependency.
"""
from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

DEFAULT_FACE_ID = "amber-classic"
FACE_FORMAT_VERSION = 1
MAX_MANIFEST_BYTES = 64 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PACK_BYTES = 16 * 1024 * 1024
MAX_IMAGE_DIMENSION = 2048
MAX_USER_FACES = 64
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
BUILTIN_DIRECTORY = Path(__file__).with_name("faces")
Rect = tuple[int, int, int, int]


class FaceError(ValueError):
    """A face cannot be loaded, installed, or saved."""


@dataclass(frozen=True)
class FaceInfo:
    id: str
    name: str
    author: str
    description: str
    source: Path


@dataclass(frozen=True)
class Face:
    info: FaceInfo
    size: tuple[int, int]
    drag: Rect
    controls: MappingProxyType[str, Rect]
    palette: MappingProxyType[str, str]
    font: str
    time_size: int
    radius: int
    background: bytes
    buttons: MappingProxyType[str, MappingProxyType[str, bytes]]


def _read_bounded(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise FaceError(f"{path.name} exceeds its {limit // 1024} KiB limit")
    return data


def _manifest(directory: Path) -> dict[str, Any]:
    path = directory / "face.json"
    if not path.resolve().is_relative_to(directory):
        raise FaceError("face.json must stay inside the face folder")
    data = json.loads(_read_bounded(path, MAX_MANIFEST_BYTES))
    schema = json.loads((BUILTIN_DIRECTORY / "schema.json").read_text(encoding="utf-8"))
    problem = next(Draft202012Validator(schema).iter_errors(data), None)
    if problem is not None:
        location = ".".join(str(part) for part in problem.absolute_path) or "face.json"
        # Do not echo potentially huge or malformed field values into the UI.
        raise FaceError(f"Invalid {location}: {problem.validator} constraint")
    return data


def _image(directory: Path, name: str) -> tuple[bytes, tuple[int, int]]:
    path = (directory / name).resolve()
    if not path.is_relative_to(directory):
        raise FaceError(f"{name} must stay inside the face folder")
    data = _read_bounded(path, MAX_IMAGE_BYTES)
    if len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise FaceError(f"{name} is not a PNG image")
    width, height = struct.unpack(">II", data[16:24])
    if not (0 < width <= MAX_IMAGE_DIMENSION and 0 < height <= MAX_IMAGE_DIMENSION):
        raise FaceError(f"{name} exceeds the {MAX_IMAGE_DIMENSION} px image limit")
    return data, (width, height)


def _intersects(left: Rect, right: Rect) -> bool:
    x, y, width, height = left
    rx, ry, rw, rh = right
    return x < rx + rw and rx < x + width and y < ry + rh and ry < y + height


def _check_layout(data: dict) -> None:
    width, height = data["size"]
    regions = {**data["controls"], "drag": data["drag"]}
    for name, (x, y, w, h) in regions.items():
        if not w or not h or x + w > width or y + h > height:
            raise FaceError(f"{name} must fit inside the face")
        minimum = (22, 22)
        if name == "art":
            minimum = (64, 64)
            if w != h:
                raise FaceError("art must be square")
        elif name in ("title", "artists", "time", "playback", "status", "drag"):
            minimum = (64, 18)
        elif name in ("seek", "volume"):
            minimum = (80, 18)
        if w < minimum[0] or h < minimum[1]:
            raise FaceError(f"{name} is too small to use")

    names = list(regions)
    for index, name in enumerate(names):
        for other in names[index + 1:]:
            if _intersects(tuple(regions[name]), tuple(regions[other])):
                raise FaceError(f"{name} overlaps {other}")


def load_face(directory: Path) -> Face:
    """Validate a pack again on use, including file confinement and budgets."""
    try:
        directory = directory.resolve()
        data = _manifest(directory)
        _check_layout(data)
        names = {data["background"]}
        for states in data.get("buttons", {}).values():
            names.update(states.values())
        images = {}
        total_bytes = 0
        for name in sorted(names):
            images[name] = _image(directory, name)
            total_bytes += len(images[name][0])
            if total_bytes > MAX_PACK_BYTES:
                raise FaceError("Face images exceed the 16 MiB pack limit")
        size = tuple(data["size"])
        image_size = images[data["background"]][1]
        if image_size not in (size, (size[0] * 2, size[1] * 2)):
            raise FaceError("Background must match the face size at 1x or 2x")

        return Face(
            info=FaceInfo(data["id"], data["name"], data["author"], data["description"], directory),
            size=size,
            drag=tuple(data["drag"]),
            controls=MappingProxyType({
                name: tuple(rect) for name, rect in data["controls"].items()
            }),
            palette=MappingProxyType(data["palette"]),
            font=data.get("font", "sans"),
            time_size=data.get("timeSize", 24),
            radius=data.get("radius", 4),
            background=images[data["background"]][0],
            buttons=MappingProxyType({
                control: MappingProxyType({
                    state: images[name][0] for state, name in states.items()
                })
                for control, states in data.get("buttons", {}).items()
            }),
        )
    except (OSError, ValueError, RecursionError, struct.error) as exc:
        raise FaceError(str(exc)) from exc


def _xdg_path(variable: str, fallback: str) -> Path:
    configured = os.environ.get(variable, "")
    if configured and Path(configured).is_absolute():
        return Path(configured) / "amberfader"
    return Path.home() / fallback / "amberfader"


class FaceLibrary:
    """Discover, install and remember faces independently of player state."""

    def __init__(self, directory: Path | None = None, preferences: Path | None = None) -> None:
        self._directory = directory or _xdg_path("XDG_DATA_HOME", ".local/share") / "faces"
        self._preferences = preferences or (
            _xdg_path("XDG_CONFIG_HOME", ".config") / "appearance.json"
        )
        self._catalog: dict[str, FaceInfo] = {}
        self._problems: list[str] = []
        self._preference_problem: str | None = None
        self.refresh()

    @property
    def problems(self) -> tuple[str, ...]:
        preference = (self._preference_problem,) if self._preference_problem else ()
        return tuple(self._problems) + preference

    @property
    def faces(self) -> tuple[FaceInfo, ...]:
        return tuple(self._catalog.values())

    def refresh(self) -> None:
        self._catalog.clear()
        self._problems.clear()
        for directory in sorted(BUILTIN_DIRECTORY.iterdir()):
            if directory.is_dir():
                self._discover(directory)
        if not self._directory.exists():
            return
        try:
            # The limit applies before loading image data, including invalid packs.
            count = 0
            for directory in sorted(self._directory.iterdir()):
                if not directory.is_dir() or directory.name.startswith("."):
                    continue
                count += 1
                if count > MAX_USER_FACES:
                    self._problems.append(
                        f"Only the first {MAX_USER_FACES} installed face folders are loaded"
                    )
                    break
                self._discover(directory)
        except OSError as exc:
            self._problems.append(f"Cannot read faces folder: {exc}")

    def _discover(self, directory: Path) -> None:
        try:
            info = load_face(directory).info
            if info.id in self._catalog:
                raise FaceError(f"Duplicate face ID: {info.id}")
            self._catalog[info.id] = info
        except FaceError as exc:
            self._problems.append(f"{directory.name}: {exc}")

    def load(self, face_id: str) -> Face:
        info = self._catalog.get(face_id)
        if info is None:
            raise FaceError(f"Face not found: {face_id}")
        return load_face(info.source)

    def preferred_id(self) -> str:
        if not self._preferences.exists():
            self._preference_problem = None
            return DEFAULT_FACE_ID
        try:
            data = json.loads(_read_bounded(self._preferences, MAX_MANIFEST_BYTES))
            face_id = data.get("face") if isinstance(data, dict) else None
            if isinstance(face_id, str) and face_id in self._catalog:
                self._preference_problem = None
                return face_id
        except (OSError, ValueError, RecursionError):
            pass
        self._preference_problem = "Saved face is unavailable. Using Amber Classic"
        return DEFAULT_FACE_ID

    def remember(self, face_id: str) -> None:
        if face_id not in self._catalog:
            raise FaceError(f"Face not found: {face_id}")
        try:
            self._preferences.parent.mkdir(parents=True, exist_ok=True)
            # Replace one complete preference document; never leave a partial JSON file.
            with TemporaryDirectory(prefix=".appearance-", dir=self._preferences.parent) as temp:
                path = Path(temp) / "appearance.json"
                path.write_text(json.dumps({"face": face_id}) + "\n", encoding="utf-8")
                path.replace(self._preferences)
            self._preference_problem = None
        except OSError as exc:
            raise FaceError(f"Cannot save appearance: {exc}") from exc

    def ensure_directory(self) -> Path:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            return self._directory
        except OSError as exc:
            raise FaceError(f"Cannot create faces folder: {exc}") from exc

    def install(self, source: Path) -> FaceInfo:
        face = load_face(source)
        self.refresh()
        if face.info.id in self._catalog:
            raise FaceError(f"Face ID already installed: {face.info.id}")
        root = self.ensure_directory()
        target = root / face.info.id
        if target.exists() or target.is_symlink():
            raise FaceError(f"Face folder already exists: {face.info.id}")
        if sum(p.is_dir() and not p.name.startswith(".") for p in root.iterdir()) >= MAX_USER_FACES:
            raise FaceError(
                f"Remove an installed face before adding another ({MAX_USER_FACES}-face limit)"
            )
        try:
            with TemporaryDirectory(prefix=".install-", dir=root) as temp:
                staging = Path(temp) / face.info.id
                staging.mkdir()
                data = _manifest(face.info.source)
                (staging / "face.json").write_text(
                    json.dumps(data, indent=2) + "\n", encoding="utf-8"
                )
                names = {data["background"]}
                for states in data.get("buttons", {}).values():
                    names.update(states.values())
                for name in names:
                    (staging / name).write_bytes(_image(face.info.source, name)[0])
                # Validate the staged snapshot, not a source that may have changed.
                installed = load_face(staging)
                if installed.info.id != face.info.id:
                    raise FaceError("Face changed during installation; try again")
                staging.rename(target)
        except OSError as exc:
            raise FaceError(f"Cannot install face: {exc}") from exc
        self.refresh()
        return self._catalog[face.info.id]
