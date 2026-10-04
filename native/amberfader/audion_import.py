"""Import Panic's preserved Audion JSON/PNG faces as editable local drafts.

Archives are read in place, never extracted. Only the selected face's bounded,
declared artwork enters the document; the source and its credits stay intact.
"""
from __future__ import annotations

import json
import os
import re
import stat
import struct
import sys
import zlib
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter

from .face_document import FaceDocument
from .face_library import (
    MAX_DECODED_PIXELS,
    MAX_IMAGE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PACK_BYTES,
    FaceError,
    _png_dimensions,
)

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 150_000
MAX_ARCHIVE_METADATA_BYTES = 32 * 1024 * 1024
MAX_AUDION_FACES = 2048
MAX_FOLDER_ENTRIES = 8192
MAX_ARCHIVE_PATH = 512
ZIP_END = struct.Struct("<4s4H2IH")
ZIP64_LOCATOR = struct.Struct("<4sIQI")
ZIP64_END = struct.Struct("<4sQ2H2I4Q")
ZIP_CENTRAL = struct.Struct("<4s6H3I5H2I")
ZIP_MAX_COMMENT = 65535
SUPPORTED_ZIP_METHODS = frozenset({ZIP_STORED, ZIP_DEFLATED})
ZIP_COMPRESSION_ERROR = "Audion ZIP members must use stored or deflate compression"
SOURCE_HELP = (
    "Choose a converted Audion face folder or a ZIP from Panic's preserved collection. "
    "Classic resource-fork/PICT faces must be converted first."
)


@dataclass(frozen=True)
class AudionFaceSource:
    source: Path
    prefix: str
    name: str


@dataclass(frozen=True)
class AudionImportResult:
    document: FaceDocument
    warnings: tuple[str, ...]


@contextmanager
def _regular_stream(path: Path):
    # Nonblocking open lets fstat reject a FIFO without waiting for a writer.
    # Inspect the opened descriptor so a replacement between stat/open is safe.
    descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(descriptor, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise FaceError(f"Audion asset {path.name} must be a regular file")
        yield stream


@contextmanager
def _archive(path: Path):
    with _regular_stream(path) as stream:
        if os.fstat(stream.fileno()).st_size > MAX_ARCHIVE_BYTES:
            raise FaceError("Audion ZIP exceeds the 512 MiB archive limit")
        _preflight_archive(stream, os.fstat(stream.fileno()).st_size)
        with ZipFile(stream) as archive:
            if len(archive.infolist()) > MAX_ARCHIVE_ENTRIES:
                raise FaceError("Audion ZIP contains too many files")
            yield archive


def _zip_record(stream: BinaryIO, offset: int, record: struct.Struct) -> tuple:
    if offset < 0:
        raise FaceError("Invalid Audion ZIP central directory")
    stream.seek(offset)
    data = stream.read(record.size)
    if len(data) != record.size:
        raise FaceError("Invalid Audion ZIP central directory")
    return record.unpack(data)


def _zip_directory(stream: BinaryIO, size: int) -> tuple[int, int, int]:
    # APPNOTE 4.3.12-16: inspect only the bounded footer before ZipFile builds
    # its index. Match its physical directory placement, including SFX prefixes.
    stream.seek(max(0, size - ZIP_MAX_COMMENT - ZIP_END.size))
    tail = stream.read(ZIP_MAX_COMMENT + ZIP_END.size)
    end = len(tail) - ZIP_END.size
    if end < 0 or tail[end:end + 4] != b"PK\x05\x06" or tail[-2:] != b"\0\0":
        end = tail.rfind(b"PK\x05\x06")
    if end < 0 or end + ZIP_END.size > len(tail):
        raise FaceError("Invalid Audion ZIP end record")
    footer = ZIP_END.unpack_from(tail, end)
    if end + ZIP_END.size + footer[-1] != len(tail):
        raise FaceError("Invalid Audion ZIP comment span")
    _, disk, directory_disk, disk_count, count, directory_size, offset, _ = footer
    end_offset = size - len(tail) + end
    directory_end = end_offset
    if end_offset >= ZIP64_LOCATOR.size:
        locator = _zip_record(stream, end_offset - ZIP64_LOCATOR.size, ZIP64_LOCATOR)
        if locator[0] == b"PK\x06\x07":
            physical64 = end_offset - ZIP64_LOCATOR.size - ZIP64_END.size
            record = _zip_record(stream, physical64, ZIP64_END)
            if record[0] != b"PK\x06\x06" or record[1] != ZIP64_END.size - 12:
                raise FaceError("Unsupported Audion ZIP64 end record")
            if locator[1] != 0 or locator[3] != 1 or locator[2] > physical64:
                raise FaceError("Audion ZIP must be a single-disk archive")
            _, _, _, _, disk, directory_disk, disk_count, count, directory_size, offset = record
            directory_end = physical64
            if physical64 - locator[2] != directory_end - directory_size - offset:
                raise FaceError("Invalid Audion ZIP64 directory offset")
    if disk or directory_disk or disk_count != count:
        raise FaceError("Audion ZIP must be a single-disk archive")
    if count > MAX_ARCHIVE_ENTRIES:
        raise FaceError("Audion ZIP contains too many files")
    if directory_size > MAX_ARCHIVE_METADATA_BYTES:
        raise FaceError("Audion ZIP exceeds the 32 MiB metadata limit")
    start = directory_end - directory_size
    if start < 0 or offset > start:
        raise FaceError("Invalid Audion ZIP central directory span")
    return start, directory_size, count


def _preflight_archive(stream: BinaryIO, size: int) -> None:
    start, directory_size, declared_count = _zip_directory(stream, size)
    end = start + directory_size
    position, count = start, 0
    while position < end:
        if end - position < ZIP_CENTRAL.size:
            raise FaceError("Invalid Audion ZIP central directory")
        entry = _zip_record(stream, position, ZIP_CENTRAL)
        if entry[0] != b"PK\x01\x02":
            raise FaceError("Invalid Audion ZIP central directory")
        count += 1
        if count > MAX_ARCHIVE_ENTRIES:
            raise FaceError("Audion ZIP contains too many files")
        name_size, extra_size, comment_size = entry[10:13]
        following = position + ZIP_CENTRAL.size + name_size + extra_size + comment_size
        if following > end or name_size > MAX_ARCHIVE_PATH * 4:
            raise FaceError("Invalid Audion ZIP member span")
        flags = entry[3]
        if flags & (1 | (1 << 6) | (1 << 13)):
            raise FaceError("Audion ZIP members must be unencrypted")
        # Other stdlib codecs allocate dictionaries or unbounded intermediate
        # output before ZipExtFile applies the requested read length.
        if entry[4] not in SUPPORTED_ZIP_METHODS:
            raise FaceError(ZIP_COMPRESSION_ERROR)
        if entry[13] != 0:
            raise FaceError("Audion ZIP must be a single-disk archive")
        try:
            name = stream.read(name_size).decode("utf-8" if flags & (1 << 11) else "cp437")
        except UnicodeError as exc:
            raise FaceError("Invalid Audion ZIP member name") from exc
        _member_path(name)
        mode = stat.S_IFMT(entry[15] >> 16)
        if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or (
            mode == stat.S_IFDIR and not name.endswith("/")
        ):
            raise FaceError("Audion ZIP members must be regular files or directories")
        position = following
    if count != declared_count:
        raise FaceError("Invalid Audion ZIP entry count")
    stream.seek(0)


def _regular_zip_entry(entry) -> bool:
    mode = stat.S_IFMT(entry.external_attr >> 16)
    return not entry.is_dir() and mode in (0, stat.S_IFREG)


def _member_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        len(name) > MAX_ARCHIVE_PATH or path.is_absolute() or "\\" in name
        or any(part in ("..", ".") for part in name.split("/"))
        or len(path.parts) > 8 or "\x00" in name
    ):
        raise FaceError("Audion ZIP contains an unsafe face path")
    return path


def list_audion_faces(source: Path) -> tuple[AudionFaceSource, ...]:
    """Discover one pack or a collection without decoding all its artwork."""
    try:
        path = Path(source).resolve()
        if path.is_file() and path.name == "index.json":
            path = path.parent
        if path.is_dir():
            if (path / "index.json").is_file():
                return (AudionFaceSource(path, "", path.name),)
            faces = []
            for count, child in enumerate(path.iterdir(), start=1):
                if count > MAX_FOLDER_ENTRIES:
                    raise FaceError("Audion collection contains too many folder entries")
                if child.is_dir() and (child / "index.json").is_file():
                    if not child.resolve().is_relative_to(path):
                        raise FaceError("Audion faces must stay inside the selected folder")
                    faces.append(AudionFaceSource(child, "", child.name))
                    if len(faces) > MAX_AUDION_FACES:
                        raise FaceError("Audion collection contains too many faces")
        elif path.is_file() and path.suffix.lower() == ".zip":
            faces = []
            with _archive(path) as archive:
                seen = set()
                for entry in archive.infolist():
                    if entry.filename.startswith("__MACOSX/"):
                        continue
                    if PurePosixPath(entry.filename).name != "index.json":
                        continue
                    member = _member_path(entry.filename)
                    if not _regular_zip_entry(entry):
                        raise FaceError("Audion ZIP face indexes must be regular files")
                    if entry.filename in seen:
                        raise FaceError("Audion ZIP contains duplicate face indexes")
                    seen.add(entry.filename)
                    prefix = str(member.parent)
                    prefix = "" if prefix == "." else prefix + "/"
                    name = member.parent.name or path.stem
                    faces.append(AudionFaceSource(path, prefix, name))
                    if len(faces) > MAX_AUDION_FACES:
                        raise FaceError("Audion collection contains too many faces")
        else:
            raise FaceError(SOURCE_HELP)
        if not faces:
            raise FaceError("No converted Audion faces containing index.json were found. "
                            + SOURCE_HELP)
        return tuple(sorted(faces, key=lambda face: (face.name.casefold(), face.prefix)))
    except (OSError, BadZipFile, RuntimeError) as exc:
        raise FaceError(f"Cannot read Audion collection: {exc}") from exc


class _SourceReader:
    def __init__(self, source: AudionFaceSource) -> None:
        self._source = source
        self._root = source.source.resolve()
        self._resources = ExitStack()
        self._archive = (
            self._resources.enter_context(_archive(self._root)) if self._root.is_file() else None
        )
        self._total = 0
        self._cache: dict[str, bytes] = {}
        self._decoded_names: set[str] = set()
        self._decoded_pixels = 0
        self._entries = {}
        if self._archive is not None:
            for entry in self._archive.infolist():
                if entry.filename.startswith(source.prefix):
                    if entry.filename in self._entries:
                        self.close()
                        raise FaceError("Audion ZIP contains duplicate artwork paths")
                    self._entries[entry.filename] = entry

    def close(self) -> None:
        self._resources.close()

    def read(self, name: str, *, optional: bool = False) -> bytes | None:
        if name in self._cache:
            return self._cache[name]
        limit = MAX_MANIFEST_BYTES if name == "index.json" else MAX_IMAGE_BYTES
        if self._archive is None:
            path = (self._root / name).resolve()
            if not path.is_relative_to(self._root):
                raise FaceError(f"Audion asset {name} must stay inside the face folder")
            if optional and not path.exists():
                return None
            with _regular_stream(path) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise FaceError(f"Audion asset {name} exceeds its size limit")
        else:
            member = self._source.prefix + name
            _member_path(member)
            entry = self._entries.get(member)
            if entry is None:
                if optional:
                    return None
                raise FaceError(f"Missing Audion asset: {name}")
            if (
                not _regular_zip_entry(entry) or entry.flag_bits & 1
            ):
                raise FaceError(f"Audion asset {name} must be an unencrypted regular file")
            # Recheck the parsed member if the archive changed after preflight.
            if entry.compress_type not in SUPPORTED_ZIP_METHODS:
                raise FaceError(ZIP_COMPRESSION_ERROR)
            if entry.file_size > limit:
                raise FaceError(f"Audion asset {name} exceeds its size limit")
            with self._archive.open(entry) as stream:
                data = stream.read(limit + 1)
            if len(data) > limit:
                raise FaceError(f"Audion asset {name} exceeds its size limit")
        self._total += len(data)
        if self._total > MAX_PACK_BYTES:
            raise FaceError("Selected Audion artwork exceeds the 16 MiB pack limit")
        self._cache[name] = data
        return data

    def image(self, name: str, *, optional: bool = False) -> QImage | None:
        data = self.read(name, optional=optional)
        if data is None:
            return None
        width, height = _png_dimensions(data, name)
        if name not in self._decoded_names:
            self._decoded_pixels += width * height
            if self._decoded_pixels > MAX_DECODED_PIXELS:
                raise FaceError("Selected Audion images exceed the 128 MiB decoded image limit")
            self._decoded_names.add(name)
        image = QImage.fromData(data, "PNG")
        if image.isNull():
            raise FaceError(f"Cannot decode Audion PNG: {name}")
        return image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


def _png(image: QImage) -> bytes:
    encoded = QByteArray()
    buffer = QBuffer(encoded)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
        raise FaceError("Cannot encode the imported Audion artwork")
    data = bytes(encoded)
    if len(data) > MAX_IMAGE_BYTES:
        raise FaceError("Converted Audion PNG exceeds the 4 MiB image limit")
    return data


def _origin(index: dict, key: str) -> tuple[int, int] | None:
    value = index.get(key)
    if value is None:
        return None
    if not isinstance(value, dict) or any(
        not isinstance(value.get(edge), int) or isinstance(value.get(edge), bool)
        for edge in ("left", "top", "right", "bottom")
    ):
        raise FaceError(f"Invalid Audion layout field: {key}")
    if abs(value["left"]) > 2048 or abs(value["top"]) > 2048:
        raise FaceError(f"Audion layout field {key} is outside the canvas limit")
    if value["right"] - value["left"] <= 1 and value["bottom"] - value["top"] <= 1:
        return None
    return value["left"], value["top"]


def _rectangle(index: dict, key: str, size: tuple[int, int]) -> list[int] | None:
    origin = _origin(index, key)
    if origin is None:
        return None
    value = index[key]
    left, top = max(0, origin[0]), max(0, origin[1])
    right, bottom = min(size[0], value["right"]), min(size[1], value["bottom"])
    return [left, top, right - left, bottom - top] if right > left and bottom > top else None


class _Converter:
    def __init__(self, source: AudionFaceSource, reader: _SourceReader, index: dict) -> None:
        self._reader, self._index = reader, index
        self._background = reader.image("base.png")
        self._size = self._background.width(), self._background.height()
        self._mask = reader.image("base-alpha.png", optional=True)
        if self._mask is not None and self._mask.size() != self._background.size():
            self._mask = self._mask.scaled(
                self._background.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        self.assets: dict[str, bytes] = {}
        self.controls: dict[str, list[int]] = {}
        self.buttons: dict[str, dict[str, str]] = {}
        self.warnings: list[str] = []
        info = index.get("faceInfo", [])
        if not isinstance(info, list) or any(not isinstance(line, str) for line in info):
            raise FaceError("Audion faceInfo must contain text credits")
        credit = "\n".join(info)
        if len(credit) > 4096:
            raise FaceError("Audion credits exceed the 4096-character limit")
        slug = re.sub(r"[^a-z0-9]+", "-", source.name.lower()).strip("-")[:28]
        self.manifest: dict[str, Any] = {
            "formatVersion": 3, "id": "audion-" + (slug or "face") + "-" + uuid4().hex[:8],
            "name": source.name[:64] or "Audion face", "author": (info[0] if info else
            "Original Audion face author")[:96] or "Original Audion face author",
            "description": "Imported from Panic's preserved Audion face collection.",
            "sourceCredit": credit, "size": list(self._size), "background": "background.png",
            "drag": [0, 0, *self._size], "controls": self.controls, "buttons": self.buttons,
            "spriteLabels": False, "sliderStyle": "popup", "font": "sans", "radius": 0,
            "palette": {
                "window": "#202020", "panel": "#303030", "display": "#151515",
                "text": "#f0f0f0", "muted": "#a0a0a0", "readout": "#f0f0f0",
                "accent": "#e9ae42", "border": "#555555", "buttonTop": "#555555",
                "buttonBottom": "#252525", "danger": "#e87070",
            },
        }

    def _paint(self, image: QImage, origin: tuple[int, int]) -> None:
        painter = QPainter(self._background)
        painter.drawImage(*origin, image)
        painter.end()

    def button(self, prefix: str, field: str, control: str) -> None:
        origin = _origin(self._index, field)
        if origin is None:
            return
        normal = self._reader.image(prefix + ".png", optional=True)
        if normal is None:
            self.warnings.append(f"Missing {prefix}.png; its button was not imported.")
            return
        images = {"normal": normal}
        for suffix, state in (("hover", "hover"), ("active", "pressed"),
                              ("disabled", "disabled")):
            image = self._reader.image(f"{prefix}-{suffix}.png", optional=True)
            if image is not None:
                images[state] = image
        if control == "play":
            for suffix, state in (("", "playing"), ("-hover", "playing-hover"),
                                  ("-active", "playing-pressed"),
                                  ("-disabled", "playing-disabled")):
                image = self._reader.image("pause" + suffix + ".png", optional=True)
                if image is not None:
                    images[state] = image
        width = max(image.width() for image in images.values())
        height = max(image.height() for image in images.values())
        x, y = origin
        left, top = max(0, x), max(0, y)
        right, bottom = min(self._size[0], x + width), min(self._size[1], y + height)
        if right <= left or bottom <= top:
            self.warnings.append(f"The {prefix} button lies outside its original canvas.")
            return
        self.controls[control] = [left, top, right - left, bottom - top]
        self.buttons[control] = {}
        for state, image in images.items():
            padded = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
            padded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(padded)
            painter.drawImage(0, 0, image)
            painter.end()
            visible = padded.copy(left - x, top - y, right - left, bottom - top)
            name = f"{control}-{state}.png"
            self.assets[name] = _png(visible)
            self.buttons[control][state] = name

    def decoration(self, name: str, field: str, *, disabled: bool = False) -> None:
        origin = _origin(self._index, field)
        if origin is None:
            return
        image = self._reader.image(name + "-disabled.png", optional=True) if disabled else None
        if image is None:
            image = self._reader.image(name + ".png", optional=True)
        if image is not None:
            self._paint(image, origin)

    def text(self, prefix: str, control: str) -> None:
        rect = _rectangle(self._index, prefix + "DisplayRect", self._size)
        if rect is None:
            return
        size = self._index.get(prefix + "FontSize", 12)
        if not isinstance(size, int) or isinstance(size, bool) or not 0 <= size <= 200:
            raise FaceError(f"Invalid Audion {prefix}FontSize")
        size = min(36, max(6, size or 12))
        style: dict[str, Any] = {"font": "sans", "size": size, "align": "left",
                                 "bold": bool(self._index.get(prefix + "Bold", False)),
                                 "italic": bool(self._index.get(prefix + "Italic", False))}
        family = self._index.get(prefix + "DisplayFontName")
        if family is not None:
            if not isinstance(family, str) or len(family) > 96 or any(
                ord(character) < 32 for character in family
            ):
                raise FaceError(f"Invalid Audion {prefix}DisplayFontName")
            if family:
                style["fontFamily"] = family
        for suffix in ("FromTxtr", "FromFace"):
            color = self._index.get(prefix + "DisplayTextFaceColor" + suffix)
            if color is None:
                continue
            if not isinstance(color, dict) or any(
                not isinstance(color.get(channel), int) or isinstance(color.get(channel), bool)
                or not 0 <= color[channel] <= 255 for channel in ("red", "green", "blue")
            ):
                raise FaceError(f"Invalid Audion {prefix} text color")
            style["color"] = "#{red:02x}{green:02x}{blue:02x}".format(**color)
            break
        self.controls[control] = rect
        self.manifest.setdefault("readoutStyles", {})[control] = style

    def digits(self) -> None:
        digits = []
        for number in range(1, 5):
            field = f"timeDigit{number}"
            rect = _rectangle(self._index, field + "Rect", self._size)
            first = self._index.get(field + "FirstPICTID")
            if rect is None or first is None:
                continue
            if not isinstance(first, int) or isinstance(first, bool) or not 0 <= first <= 32757:
                raise FaceError(f"Invalid Audion {field}FirstPICTID")
            names = []
            for value in range(10):
                image = self._reader.image(str(first + value) + ".png")
                image = image.scaled(rect[2], rect[3], Qt.AspectRatioMode.IgnoreAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
                name = f"time-{number}-{value}.png"
                self.assets[name] = _png(image)
                names.append(name)
            digits.append({"rect": rect, "images": names})
        if len(digits) != 4:
            if digits:
                self.warnings.append("Incomplete time digit graphics; time display was omitted.")
            return
        left, top = min(d["rect"][0] for d in digits), min(d["rect"][1] for d in digits)
        right = max(d["rect"][0] + d["rect"][2] for d in digits)
        bottom = max(d["rect"][1] + d["rect"][3] for d in digits)
        self.controls["time"] = [left, top, right - left, bottom - top]
        self.controls["seek"] = list(self.controls["time"])
        self.manifest["timeDigits"] = digits

    def _prune_invisible_controls(self) -> None:
        if self._mask is None:
            return  # Maskless originals compose their sprites into the visible shell.
        bits = self._mask.constBits()
        stride = self._mask.bytesPerLine()
        # SourceReader normalizes to native ARGB32 premultiplied pixels.
        alpha_offset = 3 if sys.byteorder == "little" else 0

        def visible(rect: list[int]) -> bool:
            left, top, width, height = rect
            for y in range(top, top + height):
                start = y * stride + left * 4 + alpha_offset
                if any(bits[start:start + width * 4:4]):
                    return True
            return False

        if not visible(self.manifest["drag"]):
            raise FaceError("Audion face has no visible pixels in its drag region")
        for name, rect in list(self.controls.items()):
            if visible(rect):
                continue
            del self.controls[name]
            self.buttons.pop(name, None)
            self.manifest.get("readoutStyles", {}).pop(name, None)
            self.warnings.append(
                f"The original {name} control is fully transparent and was omitted.",
            )
        if "time" not in self.controls:
            self.manifest.pop("timeDigits", None)
            self.controls.pop("seek", None)

    def convert(self) -> AudionImportResult:
        for prefix, field, control in (
            ("rw", "rewindButtonRect", "previous"), ("play", "playButtonRect", "play"),
            ("ff", "fastForwardButtonRect", "next"),
            ("menu", "playlistButtonRect", "menu"), ("close", "closeButtonRect", "close"),
            ("volume", "volumeButtonRect", "volume"),
        ):
            self.button(prefix, field, control)
        for prefix, field in (
            ("stop", "stopButtonRect"), ("eject", "ejectButtonRect"),
            ("info", "infoButtonRect"), ("music", "modeButtonRect"),
        ):
            self.decoration(prefix, field, disabled=True)
        for prefix, field in (
            ("mp3", "MP3IndicatorRect"), ("cd", "CDIndicatorRect"),
            ("net", "netIndicatorRect"), ("cddb", "CDDBIndicatorRect"),
        ):
            self.decoration(prefix, field)
        for number in (1, 2):
            first = self._index.get(f"trackDigit{number}FirstPICTID")
            if isinstance(first, int) and not isinstance(first, bool) and 0 <= first <= 32757:
                self.decoration(str(first + 10), f"trackDigit{number}Rect")
        self.text("artist", "title")
        self.text("album", "artists")
        self.digits()
        self._prune_invisible_controls()
        self.assets["background.png"] = _png(self._background)
        if self._mask is not None:
            self.assets["alpha-mask.png"] = _png(self._mask)
            self.manifest["alphaMask"] = "alpha-mask.png"
        self.warnings.extend((
            "Audion file/CD buttons and track-number indicators are decorative; "
            "animated indicators are not imported.",
            "Legacy text fonts use installed equivalents when unavailable. "
            "The bitmap clock shows elapsed minutes and seconds.",
            "Use the face menu or right-click for Amberfader features absent from the original.",
        ))
        document = FaceDocument.from_snapshot(self.manifest, self.assets)
        return AudionImportResult(document, tuple(self.warnings))


def import_audion_face(source: AudionFaceSource) -> AudionImportResult:
    """Snapshot and convert one selected face, without writing to its source."""
    reader = None
    try:
        reader = _SourceReader(source)
        index = json.loads(reader.read("index.json"))
        if not isinstance(index, dict):
            raise FaceError("Audion index.json must contain an object")
        return _Converter(source, reader, index).convert()
    except (
        OSError, ValueError, RecursionError, BadZipFile, RuntimeError, EOFError, zlib.error,
    ) as exc:
        if isinstance(exc, FaceError):
            raise
        reason = (
            "ZIP ended unexpectedly while reading the face" if isinstance(exc, EOFError) else exc
        )
        raise FaceError(f"Cannot import Audion face: {reason}") from exc
    finally:
        if reader is not None:
            reader.close()
