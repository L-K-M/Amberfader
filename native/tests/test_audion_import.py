"""Audion conversion, portable snapshots and confined archive/folder reads."""
from __future__ import annotations

import json
import os
import stat
import struct
import zipfile
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor, QImage

from amberfader import audion_import
from amberfader.audion_import import import_audion_face, list_audion_faces
from amberfader.face_document import FaceDocument
from amberfader.face_library import FaceError, load_face


def _image(path: Path, size=(8, 10), color="#d54070", alpha=255):
    image = QImage(*size, QImage.Format.Format_ARGB32)
    rgba = QColor(color)
    rgba.setAlpha(alpha)
    image.fill(rgba)
    assert image.save(str(path), "PNG")


def _rect(x, y, width, height):
    return {"left": x, "top": y, "right": x + width, "bottom": y + height}


@pytest.fixture()
def audion_pack(tmp_path):
    folder = tmp_path / "Chromatic Orb"
    folder.mkdir()
    _image(folder / "base.png", (140, 90), "#102040")
    _image(folder / "base-alpha.png", (140, 90), "#ffffff", 128)
    for name in ("play", "play-active", "play-disabled", "rw", "ff", "menu", "volume"):
        _image(folder / (name + ".png"))
    _image(folder / "pause.png", (9, 11), "#70e0b0")
    index = {
        "playButtonRect": _rect(12, 60, 1, 20),
        "rewindButtonRect": _rect(2, 60, 8, 10),
        "fastForwardButtonRect": _rect(25, 60, 8, 10),
        "playlistButtonRect": _rect(120, 60, 8, 10),
        "volumeButtonRect": _rect(100, 60, 8, 10),
        "closeButtonRect": _rect(0, 0, 1, 1),
        "artistDisplayRect": _rect(20, 12, 100, 12),
        "albumDisplayRect": _rect(20, 25, 100, 12),
        "artistDisplayFontName": "Geneva", "artistFontSize": 9,
        "artistDisplayTextFaceColorFromFace": {"red": 1, "green": 2, "blue": 3},
        "artistDisplayTextFaceColorFromTxtr": {"red": 200, "green": 100, "blue": 50},
        "faceInfo": ["Chromatic Orb by Sample Artist", "https://example.test/credit", "2001"],
    }
    for number in range(1, 5):
        index[f"timeDigit{number}Rect"] = _rect(35 + number * 10, 40, 8, 10)
        index[f"timeDigit{number}FirstPICTID"] = 100 + number * 10
        for value in range(10):
            _image(folder / f"{100 + number * 10 + value}.png", color=f"#{value * 20:02x}6030")
    (folder / "index.json").write_text(json.dumps(index))
    return folder


def _import(folder):
    return import_audion_face(list_audion_faces(folder)[0])


def test_import_preserves_native_layout_sprites_clock_and_credits(audion_pack, qapp):
    result = _import(audion_pack)
    doc = result.document
    data = doc.manifest
    assert doc.path is None and doc.dirty and not doc.can_undo
    assert data["formatVersion"] == 3 and data["size"] == [140, 90]
    # Audion buttons use the image size, not the index's right/bottom edges.
    assert data["controls"]["play"] == [12, 60, 9, 11]
    assert "close" not in data["controls"] and "art" not in data["controls"]
    assert "like" not in data["controls"] and "show" not in data["controls"]
    assert not data["spriteLabels"] and data["sliderStyle"] == "popup"
    assert "playing" in data["buttons"]["play"]
    assert data["readoutStyles"]["title"]["color"] == "#c86432"
    assert data["readoutStyles"]["title"]["fontFamily"] == "Geneva"
    assert "https://example.test/credit" in data["sourceCredit"]
    assert len(data["timeDigits"]) == 4
    assert all(len(digit["images"]) == 10 for digit in data["timeDigits"])
    assert data["controls"]["time"] == data["controls"]["seek"]
    assert doc.validate() == () and result.warnings


def test_import_retains_global_mask_and_pads_variant_without_stretch(audion_pack, qapp):
    doc = _import(audion_pack).document
    background = QImage.fromData(doc.assets["background.png"])
    normal = QImage.fromData(doc.assets[doc.manifest["buttons"]["play"]["normal"]])
    mask = QImage.fromData(doc.assets[doc.manifest["alphaMask"]])
    assert background.pixelColor(0, 0).alpha() == 255
    assert mask.pixelColor(0, 0).alpha() == 128
    assert normal.size().width() == 9 and normal.size().height() == 11
    assert normal.pixelColor(0, 0).alpha() == 255
    assert normal.pixelColor(8, 10).alpha() == 0


def test_face_preview_applies_global_alpha_once_after_control_layers(audion_pack, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter, QPixmap

    from amberfader.ui.face_surface import draw_face_preview, prepare_face_preview

    face = _import(audion_pack).document.preview(validate_layout=True)
    image = QImage(*face.size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_face_preview(painter, face, prepare_face_preview(face), QPixmap())
    painter.end()
    assert image.pixelColor(13, 61).alpha() == 128


def test_import_save_reopen_and_install_are_portable_without_source(audion_pack, tmp_path, qapp):
    before = {path.name: path.read_bytes() for path in audion_pack.iterdir()}
    doc = _import(audion_pack).document
    target = doc.save(tmp_path / "Converted")
    assert {path.name: path.read_bytes() for path in audion_pack.iterdir()} == before
    for path in audion_pack.iterdir():
        path.unlink()
    audion_pack.rmdir()
    reopened = FaceDocument.open(target)
    assert reopened.manifest == doc.manifest and reopened.assets == doc.assets
    from amberfader.face_library import FaceLibrary

    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    installed = library.install(target)
    assert library.load(installed.id).time_digits == load_face(target).time_digits


def test_collection_zip_import_reads_selected_pack_without_extraction(audion_pack, tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        for path in audion_pack.iterdir():
            writer.write(path, "Faces/Chromatic Orb/" + path.name)
        writer.writestr("__MACOSX/Faces/._index.json", b"irrelevant")
    before = {path.name for path in tmp_path.iterdir()}
    candidates = list_audion_faces(archive)
    assert len(candidates) == 1 and candidates[0].name == "Chromatic Orb"
    converted = import_audion_face(candidates[0]).document
    assert converted.manifest["controls"]["play"] == [12, 60, 9, 11]
    assert {path.name for path in tmp_path.iterdir()} == before


def test_collection_discovery_accepts_folder_and_index(audion_pack):
    assert list_audion_faces(audion_pack) == list_audion_faces(audion_pack / "index.json")
    assert list_audion_faces(audion_pack.parent)[0].source == audion_pack


@pytest.mark.parametrize("member", ["../Orb/index.json", "/Orb/index.json",
                                    "Orb\\index.json", "Orb/../index.json"])
def test_zip_rejects_escaping_index_paths(tmp_path, member):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        writer.writestr(member, "{}")
    with pytest.raises(FaceError):
        list_audion_faces(archive)


def test_folder_rejects_artwork_symlink_outside_pack(audion_pack, tmp_path, qapp):
    outside = tmp_path / "outside.png"
    _image(outside, (140, 90))
    (audion_pack / "base.png").unlink()
    (audion_pack / "base.png").symlink_to(outside)
    with pytest.raises(FaceError, match="stay inside"):
        _import(audion_pack)


def test_zip_rejects_symlink_artwork(tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    link = ZipInfo("Orb/base.png")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive, "w") as writer:
        writer.writestr("Orb/index.json", "{}")
        writer.writestr(link, "../outside.png")
    with pytest.raises(FaceError, match="regular file"):
        import_audion_face(list_audion_faces(archive)[0])


def test_folder_rejects_fifo_artwork_without_waiting_for_writer(audion_pack, qapp):
    path = audion_pack / "base.png"
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(FaceError, match="regular file"):
        _import(audion_pack)


def test_folder_discovery_is_bounded_even_without_faces(tmp_path, monkeypatch):
    monkeypatch.setattr(audion_import, "MAX_FOLDER_ENTRIES", 2)
    for number in range(3):
        (tmp_path / str(number)).touch()
    with pytest.raises(FaceError, match="folder entries"):
        list_audion_faces(tmp_path)


def test_zip_rejects_special_file_mode(tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    fifo = ZipInfo("Orb/base.png")
    fifo.create_system = 3
    fifo.external_attr = (stat.S_IFIFO | 0o600) << 16
    with ZipFile(archive, "w") as writer:
        writer.writestr("Orb/index.json", "{}")
        writer.writestr(fifo, b"not a regular image")
    with pytest.raises(FaceError, match="regular file"):
        import_audion_face(list_audion_faces(archive)[0])


def test_zip_rejects_duplicate_selected_assets(tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        writer.writestr("Orb/index.json", "{}")
        with pytest.warns(UserWarning, match="Duplicate name"):
            writer.writestr("Orb/index.json", "{}")
    with pytest.raises(FaceError, match="duplicate"):
        list_audion_faces(archive)


def test_corrupt_png_and_missing_digits_report_conversion_errors(audion_pack, qapp):
    original = (audion_pack / "base.png").read_bytes()
    (audion_pack / "base.png").write_bytes(original[:33])
    with pytest.raises(FaceError, match="Cannot decode"):
        _import(audion_pack)
    (audion_pack / "base.png").write_bytes(original)
    (audion_pack / "111.png").unlink()
    with pytest.raises(FaceError, match=r"111\.png"):
        _import(audion_pack)


def test_selected_pack_budget_is_enforced(audion_pack, monkeypatch, qapp):
    monkeypatch.setattr(audion_import, "MAX_PACK_BYTES", 100)
    with pytest.raises(FaceError, match="pack limit"):
        _import(audion_pack)


@pytest.mark.parametrize("field,value", [("artistFontSize", True),
                                        ("artistDisplayFontName", "Geneva\nInjected"),
                                        ("faceInfo", ["Credit", 42])])
def test_malformed_metadata_is_rejected(audion_pack, field, value, qapp):
    path = audion_pack / "index.json"
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(FaceError, match="Audion"):
        _import(audion_pack)


def test_classic_resource_file_has_actionable_format_message(tmp_path):
    classic = tmp_path / "Orb.face"
    classic.write_bytes(b"old resource fork")
    with pytest.raises(FaceError, match="converted first"):
        list_audion_faces(classic)


def _forbid_unbounded_zip_reader(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("ZipFile allocated the directory before its bounds were checked")
    monkeypatch.setattr(audion_import, "ZipFile", forbidden)


def test_zip_counts_actual_records_before_zipfile_even_when_count_is_forged(tmp_path, monkeypatch):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        for number in range(3):
            writer.writestr(f"junk/{number}", b"")
    data = bytearray(archive.read_bytes())
    # The EOCD total can lie. zipfile parses the whole directory regardless.
    struct.pack_into("<HH", data, len(data) - 14, 1, 1)
    archive.write_bytes(data)
    monkeypatch.setattr(audion_import, "MAX_ARCHIVE_ENTRIES", 2)
    _forbid_unbounded_zip_reader(monkeypatch)
    with pytest.raises(FaceError, match="too many files"):
        list_audion_faces(archive)


def test_zip64_forged_count_is_rejected_before_zipfile(tmp_path, monkeypatch):
    archive = tmp_path / "Faces.zip"
    with monkeypatch.context() as writing:
        writing.setattr(zipfile, "ZIP_FILECOUNT_LIMIT", 1)
        with ZipFile(archive, "w") as writer:
            for number in range(3):
                writer.writestr(f"junk/{number}", b"")
    data = bytearray(archive.read_bytes())
    zip64_end = len(data) - 22 - 20 - 56
    assert data[zip64_end:zip64_end + 4] == b"PK\x06\x06"
    struct.pack_into("<QQ", data, zip64_end + 24, 1, 1)
    archive.write_bytes(data)
    monkeypatch.setattr(audion_import, "MAX_ARCHIVE_ENTRIES", 2)
    _forbid_unbounded_zip_reader(monkeypatch)
    with pytest.raises(FaceError, match="too many files"):
        list_audion_faces(archive)


def test_duplicate_selected_artwork_is_rejected(audion_pack, tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        for path in audion_pack.iterdir():
            writer.write(path, "Orb/" + path.name)
        with pytest.warns(UserWarning, match="Duplicate name"):
            writer.write(audion_pack / "base.png", "Orb/base.png")
    with pytest.raises(FaceError, match="duplicate artwork"):
        import_audion_face(list_audion_faces(archive)[0])


def test_zip_rejects_large_metadata_before_zipfile(tmp_path, monkeypatch):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        entry = ZipInfo("Orb/index.json")
        entry.comment = b"x" * 1000
        writer.writestr(entry, "{}")
    monkeypatch.setattr(audion_import, "MAX_ARCHIVE_METADATA_BYTES", 100, raising=False)
    _forbid_unbounded_zip_reader(monkeypatch)
    with pytest.raises(FaceError, match="metadata limit"):
        list_audion_faces(archive)


def test_zip64_collection_over_65535_entries_is_supported(audion_pack, tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w", allowZip64=True) as writer:
        for path in audion_pack.iterdir():
            writer.write(path, "Faces/Chromatic Orb/" + path.name)
        for number in range(65536):
            writer.writestr(f"misc/{number}", b"")
        writer.comment = b"Preserved faces"
    # A prepended stub remains supported; directory offsets are archive-relative.
    archive.write_bytes(b"stub prefix" + archive.read_bytes())
    sources = list_audion_faces(archive)
    assert len(sources) == 1
    assert import_audion_face(sources[0]).document.validate() == ()


@pytest.mark.parametrize("change", [
    lambda data, central: data.__setitem__(slice(central, central + 4), b"bad!"),
    lambda data, central: struct.pack_into("<H", data, central + 28, 65535),
    lambda data, central: struct.pack_into("<H", data, central + 8, 1),
    lambda data, central: struct.pack_into("<I", data, len(data) - 10, len(data) + 1),
    lambda data, central: struct.pack_into("<HH", data, len(data) - 14, 0, 0),
    lambda data, central: struct.pack_into("<H", data, len(data) - 2, 65535),
])
def test_malformed_or_encrypted_metadata_is_rejected_before_zipfile(tmp_path, monkeypatch, change):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        writer.writestr("Orb/index.json", "{}")
    data = bytearray(archive.read_bytes())
    central = struct.unpack_from("<I", data, len(data) - 6)[0]
    change(data, central)
    archive.write_bytes(data)
    _forbid_unbounded_zip_reader(monkeypatch)
    with pytest.raises(FaceError, match="Audion ZIP"):
        list_audion_faces(archive)


def _clear_mask_region(folder, rect):
    path = folder / "base-alpha.png"
    image = QImage(str(path))
    left, top, width, height = rect
    for y in range(top, top + height):
        for x in range(left, left + width):
            image.setPixelColor(x, y, QColor(0, 0, 0, 0))
    assert image.save(str(path), "PNG")


def test_fully_transparent_original_button_is_omitted_with_warning(audion_pack, qapp):
    _clear_mask_region(audion_pack, (2, 60, 8, 10))
    result = _import(audion_pack)
    assert "previous" not in result.document.manifest["controls"]
    assert "previous" not in result.document.manifest["buttons"]
    assert any("previous" in warning and "transparent" in warning for warning in result.warnings)


def test_transparent_bitmap_clock_removes_digit_assets_and_seek(audion_pack, qapp):
    _clear_mask_region(audion_pack, (45, 40, 38, 10))
    document = _import(audion_pack).document
    assert not ({"time", "seek"} & document.manifest["controls"].keys())
    assert "timeDigits" not in document.manifest
    assert not any(name.startswith("time-") for name in document.assets)


def test_translucent_original_text_remains_imported(audion_pack, qapp):
    _image(audion_pack / "base-alpha.png", (140, 90), "#ffffff", 1)
    assert "title" in _import(audion_pack).document.manifest["controls"]


def test_fully_transparent_original_shell_is_rejected(audion_pack, qapp):
    _image(audion_pack / "base-alpha.png", (140, 90), "#ffffff", 0)
    with pytest.raises(FaceError, match=r"no visible.*drag"):
        _import(audion_pack)


def test_source_image_pixels_are_bounded_before_conversion(audion_pack, qapp):
    _image(audion_pack / "110.png", (2048, 2048))
    large = (audion_pack / "110.png").read_bytes()
    for first in (110, 120, 130, 140):
        for digit in range(10):
            (audion_pack / f"{first + digit}.png").write_bytes(large)
    with pytest.raises(FaceError, match="decoded image limit"):
        _import(audion_pack)


def test_repeated_source_images_count_pixels_once(audion_pack, monkeypatch, qapp):
    monkeypatch.setattr(audion_import, "MAX_DECODED_PIXELS", 140 * 90)
    reader = audion_import._SourceReader(list_audion_faces(audion_pack)[0])
    try:
        for _number in range(3):
            assert reader.image("base.png") is not None
        with pytest.raises(FaceError, match="decoded image limit"):
            reader.image("play.png")
    finally:
        reader.close()


@pytest.mark.parametrize("method", [zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2])
def test_unsafe_compression_is_rejected_before_decoder_creation(tmp_path, monkeypatch, method):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w", compression=method) as writer:
        writer.writestr("Orb/index.json", "{}")
    if method == zipfile.ZIP_LZMA:
        data = bytearray(archive.read_bytes())
        name_size, extra_size = struct.unpack_from("<HH", data, 26)
        # LZMA's ZIP properties can request an arbitrary dictionary allocation.
        dictionary_offset = 30 + name_size + extra_size + 5
        struct.pack_into("<I", data, dictionary_offset, 2**31)
        archive.write_bytes(data)

    def forbidden(*_args, **_kwargs):
        pytest.fail("The unsafe compression decoder was created")

    monkeypatch.setattr(zipfile, "_get_decompressor", forbidden)
    with pytest.raises(FaceError, match="stored or deflate"):
        import_audion_face(list_audion_faces(archive)[0])


def test_deflated_collection_import_remains_supported(audion_pack, tmp_path, qapp):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as writer:
        for path in audion_pack.iterdir():
            writer.write(path, "Orb/" + path.name)
    document = import_audion_face(list_audion_faces(archive)[0]).document
    assert document.validate() == ()


def test_corrupt_deflate_payload_reports_face_error(tmp_path):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as writer:
        writer.writestr("Orb/index.json", "{}")
    data = bytearray(archive.read_bytes())
    name_size, extra_size = struct.unpack_from("<HH", data, 26)
    data[30 + name_size + extra_size] = 0x07  # Reserved DEFLATE block type.
    archive.write_bytes(data)
    with pytest.raises(FaceError, match="Cannot import Audion face"):
        import_audion_face(list_audion_faces(archive)[0])


def test_truncated_member_reports_face_error(tmp_path, monkeypatch):
    archive = tmp_path / "Faces.zip"
    with ZipFile(archive, "w") as writer:
        writer.writestr("Orb/index.json", "{}")
    original_open = ZipFile.open

    def truncate_after_header(self, *args, **kwargs):
        member = original_open(self, *args, **kwargs)
        archive.write_bytes(b"")
        self.fp.seek(0, os.SEEK_END)  # Invalidate buffered bytes from the previous file.
        return member

    monkeypatch.setattr(ZipFile, "open", truncate_after_header)
    with pytest.raises(FaceError, match="Cannot import Audion face: ZIP ended unexpectedly"):
        import_audion_face(list_audion_faces(archive)[0])
