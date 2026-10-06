"""Versioned, data-only face plugins and local appearance preferences.

Faces describe presentation, never commands. Only declared, bounded PNG files
are installed; executable plugins and stylesheet imports are unsupported.
This module has no Qt dependency.
"""
from __future__ import annotations

import json
import os
import stat
import struct
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import lru_cache
from math import cos, isfinite, radians, sin
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

from . import __version__
from .paths import app_dirs

DEFAULT_FACE_ID = "amber-classic"
BUNDLED_FACE_ERROR = "Bundled faces are unavailable. Reinstall Amberfader."
FACE_FORMAT_VERSION = 2
IMPORT_FACE_FORMAT_VERSION = 3
MAX_MANIFEST_BYTES = 64 * 1024
MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_PACK_BYTES = 16 * 1024 * 1024
MAX_IMAGE_DIMENSION = 2048
MAX_DECODED_PIXELS = 32 * 1024 * 1024
MAX_DRAFT_GEOMETRY = 2048
# Panic's three Audion collection ZIPs hold 883 faces together.
MAX_USER_FACES = 1024
CATALOG_CACHE = ".catalog.json"
MAX_CATALOG_CACHE_BYTES = 16 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_HEADER = struct.Struct(">8sI4sII5BI")
PNG_HEADER_BYTES = PNG_HEADER.size
PNG_HEADER_CHUNK = b"IHDR"
PNG_HEADER_DATA_BYTES = 13
PACK_LIMIT_ERROR = "Face images exceed the 16 MiB pack limit"
DECODED_LIMIT_ERROR = "Face images exceed the 128 MiB decoded image limit"
BUILTIN_DIRECTORY = Path(__file__).with_name("faces")
Rect = tuple[int, int, int, int]
Polygon = tuple[tuple[float, float], ...]
INFO_FIELDS = ("id", "name", "author", "description")


class FaceValidation(Enum):
    STRICT = "strict"
    DRAFT = "draft"


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
class TimeDigit:
    rect: Rect
    images: tuple[bytes, ...]


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
    control_shapes: MappingProxyType[str, str] = field(default_factory=lambda: MappingProxyType({}))
    cover_glass: bool = False
    readout_styles: MappingProxyType[str, MappingProxyType[str, Any]] = field(
        default_factory=lambda: MappingProxyType({}),
    )
    slider_style: str = "classic"
    control_rotations: MappingProxyType[str, float] = field(
        default_factory=lambda: MappingProxyType({}),
    )
    format_version: int = FACE_FORMAT_VERSION
    source_credit: str = ""
    sprite_labels: bool = True
    time_digits: tuple[TimeDigit, ...] = ()
    alpha_mask: bytes | None = None


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
    try:
        data = json.loads(_read_bounded(path, MAX_MANIFEST_BYTES))
    except (ValueError, RecursionError) as exc:
        raise FaceError(f"Invalid face.json: {exc}") from exc
    _validate_manifest(data)
    return data


def _validate_manifest(
    data: dict[str, Any], validation: FaceValidation = FaceValidation.STRICT,
) -> None:
    validator = _validator(BUILTIN_DIRECTORY / "schema.json", validation)
    problem = next(validator.iter_errors(data), None)
    if problem is not None:
        location = ".".join(str(part) for part in problem.absolute_path) or "face.json"
        # Do not echo potentially huge or malformed field values into the UI.
        raise FaceError(f"Invalid {location}: {problem.validator} constraint")
    for name, rotation in data.get("controlRotations", {}).items():
        if not isfinite(rotation):
            raise FaceError(f"Invalid controlRotations.{name}: rotation must be finite")


@lru_cache(maxsize=2)
def _validator(
    path: Path, validation: FaceValidation = FaceValidation.STRICT,
) -> Draft202012Validator:
    # The schema is a bundled program resource, not part of an editable pack.
    schema = json.loads(path.read_text(encoding="utf-8"))
    if validation is FaceValidation.DRAFT:
        # Dragging can temporarily put a control outside the shell. Its bounds
        # remain finite and typed; the production schema stays unchanged.
        origin = {
            "type": "integer", "minimum": -MAX_DRAFT_GEOMETRY,
            "maximum": MAX_DRAFT_GEOMETRY,
        }
        extent = {"type": "integer", "minimum": 1, "maximum": MAX_DRAFT_GEOMETRY}
        draft_rect = {
            "type": "array", "prefixItems": [origin, origin, extent, extent],
            "items": False, "minItems": 4, "maxItems": 4,
        }
        schema["$defs"]["rect"] = draft_rect
        schema["$defs"]["legacyRect"] = draft_rect
    return Draft202012Validator(schema)


def _image_path(directory: Path, name: str) -> Path:
    path = (directory / name).resolve()
    if not path.is_relative_to(directory):
        raise FaceError(f"{name} must stay inside the face folder")
    return path


def _png_dimensions(data: bytes, name: str) -> tuple[int, int]:
    if len(data) < PNG_HEADER_BYTES:
        raise FaceError(f"{name} is not a PNG image")
    signature, length, kind, width, height, *_ = PNG_HEADER.unpack_from(data)
    if signature != PNG_SIGNATURE or kind != PNG_HEADER_CHUNK or length != PNG_HEADER_DATA_BYTES:
        raise FaceError(f"{name} is not a PNG image")
    if not (0 < width <= MAX_IMAGE_DIMENSION and 0 < height <= MAX_IMAGE_DIMENSION):
        raise FaceError(f"{name} exceeds the {MAX_IMAGE_DIMENSION} px image limit")
    return width, height


def _image(directory: Path, name: str) -> tuple[bytes, tuple[int, int]]:
    data = _read_bounded(_image_path(directory, name), MAX_IMAGE_BYTES)
    width, height = _png_dimensions(data, name)
    return data, (width, height)


def control_polygon(rect: Rect, rotation: float = 0.0) -> Polygon:
    """Clockwise screen-space corners around the unrotated rectangle's center."""
    x, y, width, height = rect
    cx, cy = x + width / 2, y + height / 2
    angle = radians(rotation)
    cosine, sine = cos(angle), sin(angle)
    return tuple(
        (cx + dx * cosine - dy * sine, cy + dx * sine + dy * cosine)
        for dx, dy in (
            (-width / 2, -height / 2), (width / 2, -height / 2),
            (width / 2, height / 2), (-width / 2, height / 2),
        )
    )


def control_bounds(rect: Rect, rotation: float = 0.0) -> tuple[float, float, float, float]:
    polygon = control_polygon(rect, rotation)
    left, right = min(x for x, _ in polygon), max(x for x, _ in polygon)
    top, bottom = min(y for _, y in polygon), max(y for _, y in polygon)
    return left, top, right - left, bottom - top


def _intersects(left: Polygon, right: Polygon) -> bool:
    # Separating axes keep angled controls independent even when their bounding
    # boxes overlap. Touching edges are allowed, as in the original layout rules.
    for polygon in (left, right):
        for index, point in enumerate(polygon):
            following = polygon[(index + 1) % len(polygon)]
            axis = (point[1] - following[1], following[0] - point[0])
            projections = [
                [x * axis[0] + y * axis[1] for x, y in corners]
                for corners in (left, right)
            ]
            if (
                max(projections[0]) <= min(projections[1]) + 1e-7
                or max(projections[1]) <= min(projections[0]) + 1e-7
            ):
                return False
    return True


def _check_layout(data: dict) -> None:
    width, height = data["size"]
    regions = {**data["controls"], "drag": data["drag"]}
    imported = data["formatVersion"] == IMPORT_FACE_FORMAT_VERSION
    if imported:
        regions.update({
            f"timeDigits.{index}": digit["rect"]
            for index, digit in enumerate(data.get("timeDigits", []))
        })
    rotations = data.get("controlRotations", {})
    polygons = {
        name: control_polygon(tuple(rect), rotations.get(name, 0))
        for name, rect in regions.items()
    }
    for name, (_x, _y, w, h) in regions.items():
        if not w or not h or any(
            px < -1e-7 or py < -1e-7 or px > width + 1e-7 or py > height + 1e-7
            for px, py in polygons[name]
        ):
            raise FaceError(f"{name} must fit inside the face")
        if imported:
            continue
        minimum = (22, 22)
        if name == "art":
            curved = data.get("controlShapes", {}).get("art") == "ellipse"
            minimum = (48, 48) if curved else (64, 64)
            if w != h and not curved:
                raise FaceError("art must be square")
        elif name in ("title", "artists", "time", "playback", "status", "drag"):
            minimum = (64, 18)
        elif name in ("seek", "volume"):
            minimum = (80, 18)
        if w < minimum[0] or h < minimum[1]:
            raise FaceError(f"{name} is too small to use")

    if imported:
        return  # Audion's original hit regions and drag masks can overlap.
    names = list(regions)
    for index, name in enumerate(names):
        for other in names[index + 1:]:
            if _intersects(polygons[name], polygons[other]):
                raise FaceError(f"{name} overlaps {other}")


def declared_image_names(data: Mapping[str, Any]) -> set[str]:
    """Collect assets from a schema-controlled face or editor snapshot."""
    names = {data["background"]}
    if "alphaMask" in data:
        names.add(data["alphaMask"])
    for states in data.get("buttons", {}).values():
        names.update(states.values())
    for digit in data.get("timeDigits", []):
        names.update(digit["images"])
    return names


def _pack_manifest(directory: Path) -> tuple[dict[str, Any], list[str]]:
    data = _manifest(directory)
    _check_layout(data)
    return data, sorted(declared_image_names(data))


def _check_background_size(
    size: list[int], image_size: tuple[int, int], *, name: str = "Background",
) -> None:
    if image_size not in (tuple(size), (size[0] * 2, size[1] * 2)):
        raise FaceError(f"{name} must match the face size at 1x or 2x")


def _probe_face(directory: Path) -> tuple[FaceInfo, list[list[Any]]]:
    """List validated metadata without buffering discarded PNG payloads.

    Also returns the signature of the files as they were before being read
    (see _signature): if a file changes during the probe, the signature no
    longer matches it afterwards.
    """
    try:
        directory = directory.resolve()
        seen = [_identity("face.json", os.lstat(directory / "face.json"))]
        data, names = _pack_manifest(directory)
        total_bytes = 0
        decoded_pixels = 0
        dimensions = {}
        for name in names:
            with _image_path(directory, name).open("rb") as stream:
                status = os.fstat(stream.fileno())
                seen.append(_identity(name, status))
                size = status.st_size
                if size > MAX_IMAGE_BYTES:
                    raise FaceError(f"{name} exceeds its {MAX_IMAGE_BYTES // 1024} KiB limit")
                total_bytes += size
                if total_bytes > MAX_PACK_BYTES:
                    raise FaceError(PACK_LIMIT_ERROR)
                dimensions[name] = _png_dimensions(stream.read(PNG_HEADER_BYTES), name)
                decoded_pixels += dimensions[name][0] * dimensions[name][1]
                if decoded_pixels > MAX_DECODED_PIXELS:
                    raise FaceError(DECODED_LIMIT_ERROR)
        _check_background_size(data["size"], dimensions[data["background"]])
        if "alphaMask" in data:
            _check_background_size(data["size"], dimensions[data["alphaMask"]], name="Alpha mask")
        info = FaceInfo(data["id"], data["name"], data["author"], data["description"], directory)
        return info, seen
    except (OSError, ValueError, RecursionError, struct.error) as exc:
        raise FaceError(str(exc)) from exc


def _identity(name: str, status: os.stat_result) -> list[Any]:
    return [
        name, status.st_dev, status.st_ino, status.st_size,
        status.st_mtime_ns, status.st_ctime_ns,
    ]


def _signature(directory: Path, names: Iterable[str]) -> list[list[Any]] | None:
    """Identify a face's files by lstat; None when one is not a plain file.

    Every write or rename updates ctime, and ctime cannot be set back, so an
    unchanged signature means unchanged bytes. Faces with symbolic links are
    never cached.
    """
    signature = []
    folder = os.fspath(directory)  # Plain strings: pathlib dominates 60,000 lstat calls.
    for name in ("face.json", *sorted(names)):
        status = os.lstat(os.path.join(folder, name))
        if not stat.S_ISREG(status.st_mode):
            return None
        signature.append(_identity(name, status))
    return signature


def _unchanged(directory: Path, signature: list[list[Any]]) -> bool:
    """Whether a face's files still match a signature."""
    try:
        return _signature(directory, [file[0] for file in signature[1:]]) == signature
    except OSError:
        return False


def _catalog_entry(info: FaceInfo, signature: list[list[Any]]) -> dict[str, Any]:
    return {
        "signature": signature,
        "info": [info.id, info.name, info.author, info.description],
    }


def _cached_info(directory: Path, entry: Any) -> FaceInfo | None:
    """Reuse the probe of a face whose files are unchanged.

    The cache only lists a face: load() validates it in full again.
    """
    try:
        signature, fields = entry["signature"], entry["info"]
        source = directory.resolve()
        if not _unchanged(source, signature):
            return None
        if len(fields) != len(INFO_FIELDS) or not all(isinstance(f, str) for f in fields):
            return None
        return FaceInfo(*fields, source)
    except (OSError, TypeError, KeyError, IndexError, ValueError):
        return None


def load_face_snapshot(
    manifest: dict[str, Any], images: Mapping[str, bytes], source: Path,
    *, validation: FaceValidation = FaceValidation.STRICT,
) -> Face:
    """Build a bounded data-only face from an editor's in-memory snapshot.

    DRAFT permits bounded unfinished rectangles for editing. Other schema and
    image constraints still apply; install and player paths use STRICT.
    """
    try:
        encoded = json.dumps(manifest).encode("utf-8")
        if len(encoded) > MAX_MANIFEST_BYTES:
            raise FaceError("face.json exceeds its 64 KiB limit")
        _validate_manifest(manifest, validation)
        if validation is FaceValidation.STRICT:
            _check_layout(manifest)
        elif validation is not FaceValidation.DRAFT:
            raise FaceError("Unknown face validation mode")
        names = declared_image_names(manifest)
        validated = {}
        total_bytes = 0
        decoded_pixels = 0
        for name in sorted(names):
            image = images.get(name)
            if not isinstance(image, bytes):
                raise FaceError(f"Missing PNG image: {name}")
            if len(image) > MAX_IMAGE_BYTES:
                raise FaceError(f"{name} exceeds its {MAX_IMAGE_BYTES // 1024} KiB limit")
            total_bytes += len(image)
            if total_bytes > MAX_PACK_BYTES:
                raise FaceError(PACK_LIMIT_ERROR)
            dimensions = _png_dimensions(image, name)
            decoded_pixels += dimensions[0] * dimensions[1]
            if decoded_pixels > MAX_DECODED_PIXELS:
                raise FaceError(DECODED_LIMIT_ERROR)
            validated[name] = image, dimensions
        if validation is FaceValidation.STRICT:
            _check_background_size(manifest["size"], validated[manifest["background"]][1])
            if "alphaMask" in manifest:
                _check_background_size(
                    manifest["size"], validated[manifest["alphaMask"]][1], name="Alpha mask",
                )
        return Face(
            info=FaceInfo(
                manifest["id"], manifest["name"], manifest["author"],
                manifest["description"], source,
            ),
            size=tuple(manifest["size"]),
            drag=tuple(manifest["drag"]),
            controls=MappingProxyType({
                name: tuple(rect) for name, rect in manifest["controls"].items()
            }),
            palette=MappingProxyType(dict(manifest["palette"])),
            font=manifest.get("font", "sans"),
            time_size=manifest.get("timeSize", 24),
            radius=manifest.get("radius", 4),
            background=validated[manifest["background"]][0],
            buttons=MappingProxyType({
                control: MappingProxyType({
                    state: validated[name][0] for state, name in states.items()
                })
                for control, states in manifest.get("buttons", {}).items()
            }),
            control_shapes=MappingProxyType(dict(manifest.get("controlShapes", {}))),
            cover_glass=manifest.get("coverGlass", False),
            readout_styles=MappingProxyType({
                name: MappingProxyType(dict(style))
                for name, style in manifest.get("readoutStyles", {}).items()
            }),
            slider_style=manifest.get("sliderStyle", "classic"),
            control_rotations=MappingProxyType(dict(manifest.get("controlRotations", {}))),
            format_version=manifest["formatVersion"],
            source_credit=manifest.get("sourceCredit", ""),
            sprite_labels=manifest.get("spriteLabels", True),
            time_digits=tuple(
                TimeDigit(tuple(digit["rect"]), tuple(
                    validated[name][0] for name in digit["images"]
                )) for digit in manifest.get("timeDigits", [])
            ),
            alpha_mask=(validated[manifest["alphaMask"]][0] if "alphaMask" in manifest else None),
        )
    except (TypeError, ValueError, RecursionError, struct.error) as exc:
        raise FaceError(str(exc)) from exc


def load_face(directory: Path) -> Face:
    """Validate a pack again on use, including file confinement and budgets."""
    try:
        directory = directory.resolve()
        data, names = _pack_manifest(directory)
        images = {}
        total_bytes = 0
        for name in names:
            image = _image(directory, name)[0]
            total_bytes += len(image)
            if total_bytes > MAX_PACK_BYTES:
                raise FaceError(PACK_LIMIT_ERROR)
            images[name] = image
        return load_face_snapshot(data, images, directory)
    except (OSError, ValueError, RecursionError, struct.error) as exc:
        raise FaceError(str(exc)) from exc


class FaceLibrary:
    """Discover, install and remember faces independently of player state."""

    def __init__(self, directory: Path | None = None, preferences: Path | None = None) -> None:
        dirs = app_dirs()
        self._directory = directory or dirs.data / "faces"
        self._preferences = preferences or dirs.config / "appearance.json"
        self._catalog: dict[str, FaceInfo] = {}
        self._problems: list[str] = []
        self._preference_problem: str | None = None
        # Cache entries of faces installed since the last refresh().
        self._installed_entries: dict[str, Any] = {}
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
        try:
            for directory in sorted(BUILTIN_DIRECTORY.iterdir()):
                if directory.is_dir():
                    self._discover(directory)
        except OSError as exc:
            raise FaceError(BUNDLED_FACE_ERROR) from exc
        known = self._installed_entries
        self._installed_entries = {}
        if not self._directory.exists():
            return

        # Probing validates every image header, about 5 ms for an imported
        # Audion face. The cache skips faces whose files did not change, so a
        # library of 900 faces lists in a fraction of a second.
        stored = self._read_cache()
        known = {**stored, **known}
        entries = {}
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
                entry = self._discover(directory, known.get(directory.name))
                if entry is not None:
                    entries[directory.name] = entry
        except OSError as exc:
            self._problems.append(f"Cannot read faces folder: {exc}")
            return
        if entries != stored:
            self._write_cache(entries)

    def _discover(self, directory: Path, cached: Any = None) -> dict[str, Any] | None:
        """Catalog a valid face. Returns its cache entry, if it can have one."""
        info = _cached_info(directory, cached) if cached is not None else None
        entry = cached
        if info is None:
            try:
                info, seen = _probe_face(directory)
            except FaceError as exc:
                self._problems.append(f"{directory.name}: {exc}")
                return None
            # Files that changed while being probed are probed again next time.
            entry = _catalog_entry(info, seen) if _unchanged(info.source, seen) else None
        if info.id in self._catalog:
            self._problems.append(f"{directory.name}: Duplicate face ID: {info.id}")
        else:
            self._catalog[info.id] = info
        return entry

    def _read_cache(self) -> dict[str, Any]:
        """A missing, stale or unreadable cache only costs a full probe."""
        try:
            data = json.loads(
                _read_bounded(self._directory / CATALOG_CACHE, MAX_CATALOG_CACHE_BYTES)
            )
        except (OSError, ValueError, RecursionError):
            return {}
        # Validation rules can change between releases.
        if not isinstance(data, dict) or data.get("version") != __version__:
            return {}
        faces = data.get("faces")
        return faces if isinstance(faces, dict) else {}

    def _write_cache(self, entries: dict[str, Any]) -> None:
        try:
            with TemporaryDirectory(prefix=".catalog-", dir=self._directory) as temp:
                staged = Path(temp) / CATALOG_CACHE
                staged.write_text(
                    json.dumps({"version": __version__, "faces": entries}, separators=(",", ":")),
                    encoding="utf-8",
                )
                staged.replace(self._directory / CATALOG_CACHE)
        except OSError:
            pass  # Listing works without the cache; the next refresh tries again.

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

        def copy(staging: Path) -> None:
            data = _manifest(face.info.source)
            (staging / "face.json").write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            for name in declared_image_names(data):
                (staging / name).write_bytes(_image(face.info.source, name)[0])

        self._install(face.info.id, copy)
        self.refresh()
        info = self._catalog.get(face.info.id)
        if info is None:
            raise FaceError(f"Installed face failed to load: {face.info.id}")
        return info

    def install_snapshot(
        self, manifest: Mapping[str, Any], images: Mapping[str, bytes],
    ) -> FaceInfo:
        """Install an in-memory face, such as a converted Audion face.

        IDs are checked against the catalog of the last refresh() plus the
        faces installed since, so a batch of N faces probes N folders instead
        of rescanning the library N times.
        """
        data = dict(manifest)
        face = load_face_snapshot(data, images, self._directory)

        def write(staging: Path) -> None:
            (staging / "face.json").write_text(
                json.dumps(data, indent=2) + "\n", encoding="utf-8"
            )
            for name in declared_image_names(data):
                (staging / name).write_bytes(images[name])

        # _install validated the staged files that now form the target.
        info = replace(face.info, source=self._install(face.info.id, write).resolve())
        self._catalog[info.id] = info
        try:
            signature = _signature(info.source, declared_image_names(data))
        except OSError:
            signature = None
        if signature is not None:
            self._installed_entries[info.source.name] = _catalog_entry(info, signature)
        return info

    def _install(self, face_id: str, write: Callable[[Path], None]) -> Path:
        """Stage the files `write` creates, validate them, then publish the
        folder under the face ID in one rename."""
        if face_id in self._catalog:
            raise FaceError(f"Face ID already installed: {face_id}")
        root = self.ensure_directory()
        target = root / face_id
        if target.exists() or target.is_symlink():
            raise FaceError(f"Face folder already exists: {face_id}")
        try:
            count = sum(p.is_dir() and not p.name.startswith(".") for p in root.iterdir())
            if count >= MAX_USER_FACES:
                raise FaceError(
                    f"Remove an installed face before adding another ({MAX_USER_FACES}-face limit)"
                )
            with TemporaryDirectory(prefix=".install-", dir=root) as temp:
                staging = Path(temp) / face_id
                staging.mkdir()
                write(staging)
                # Validate the staged snapshot, not a source that may have changed.
                installed = load_face(staging)
                if installed.info.id != face_id:
                    raise FaceError("Face changed during installation; try again")
                staging.rename(target)
        except (OSError, ValueError, RecursionError, struct.error) as exc:
            raise FaceError(f"Cannot install face: {exc}") from exc
        return target
