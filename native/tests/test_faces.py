"""Face pack boundaries, installation and preference recovery without Qt."""
import json
import struct
import zlib

import pytest

from amberfader.face_library import (
    BUILTIN_DIRECTORY,
    DEFAULT_FACE_ID,
    MAX_IMAGE_DIMENSION,
    MAX_MANIFEST_BYTES,
    PNG_SIGNATURE,
    FaceError,
    FaceLibrary,
    load_face,
)

BUNDLED_IDS = {"amber-classic", "midnight-rack", "moonstone", "copper-reel", "paper-signal"}


def png(width, height, rgba=b"\x70\x60\x50\xff"):
    def chunk(kind, data):
        checksum = struct.pack(">I", zlib.crc32(kind + data))
        return struct.pack(">I", len(data)) + kind + data + checksum

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    pixels = (b"\0" + rgba * width) * height
    return (
        PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels))
        + chunk(b"IEND", b"")
    )


def make_pack(tmp_path):
    directory = tmp_path / "source"
    directory.mkdir()
    data = json.loads((BUILTIN_DIRECTORY / DEFAULT_FACE_ID / "face.json").read_text())
    data.update(id="my-face", name="My Face")
    (directory / "face.json").write_text(json.dumps(data))
    (directory / "background.png").write_bytes(png(*data["size"]))
    return directory, data


@pytest.fixture()
def pack(tmp_path):
    return make_pack(tmp_path)


@pytest.fixture()
def library(tmp_path):
    return FaceLibrary(tmp_path / "installed", tmp_path / "config" / "appearance.json")


def write_manifest(pack):
    directory, data = pack
    (directory / "face.json").write_text(json.dumps(data))


def test_bundled_catalog_is_complete_and_valid(library):
    assert {face.id for face in library.faces} == BUNDLED_IDS
    assert not library.problems
    assert library.preferred_id() == DEFAULT_FACE_ID
    for info in library.faces:
        face = library.load(info.id)
        assert face.background.startswith(PNG_SIGNATURE)
        assert "like" in face.controls
        assert "art" in face.controls


@pytest.mark.parametrize("change", [
    lambda d: d.update(formatVersion=2),
    lambda d: d.update(code="plugin.py"),
    lambda d: d.update(background="../outside.png"),
    lambda d: d["palette"].update(accent="red; background: url(https://example.org)"),
    lambda d: d["controls"].pop("like"),
    lambda d: d["controls"].update(extra=[0, 0, 30, 30]),
    lambda d: d["controls"].update(like=[600, 100, 30, 30]),
    lambda d: d["controls"].update(art=[18, 52, 20, 20]),
    lambda d: d["controls"].update(like=d["controls"]["play"]),
    lambda d: d.update(drag=d["controls"]["menu"]),
])
def test_invalid_pack_is_rejected(pack, change):
    change(pack[1])
    write_manifest(pack)
    with pytest.raises(FaceError):
        load_face(pack[0])


def test_manifest_size_is_bounded(pack):
    path = pack[0] / "face.json"
    path.write_bytes(b" " * (MAX_MANIFEST_BYTES + 1))
    with pytest.raises(FaceError, match="limit"):
        load_face(pack[0])


def test_symlink_asset_cannot_escape_pack(pack, tmp_path):
    directory, _ = pack
    outside = tmp_path / "outside.png"
    (directory / "background.png").rename(outside)
    (directory / "background.png").symlink_to(outside)
    with pytest.raises(FaceError, match="inside"):
        load_face(directory)


def test_symlink_manifest_cannot_escape_pack(pack, tmp_path):
    directory, _ = pack
    outside = tmp_path / "outside.json"
    (directory / "face.json").rename(outside)
    (directory / "face.json").symlink_to(outside)
    with pytest.raises(FaceError, match="inside"):
        load_face(directory)


def test_image_dimensions_checked_before_qt_decoding(pack):
    directory, _ = pack
    oversized = bytearray((directory / "background.png").read_bytes())
    oversized[16:20] = struct.pack(">I", MAX_IMAGE_DIMENSION + 1)
    (directory / "background.png").write_bytes(oversized)
    with pytest.raises(FaceError, match="image limit"):
        load_face(directory)


def test_background_must_match_logical_canvas(pack):
    (pack[0] / "background.png").write_bytes(png(64, 64))
    with pytest.raises(FaceError, match="match the face size"):
        load_face(pack[0])


def test_install_copies_only_declared_data_and_never_overwrites(pack, library):
    directory, _ = pack
    (directory / "plugin.py").write_text("raise RuntimeError('must never run')")
    info = library.install(directory)
    assert {p.name for p in info.source.iterdir()} == {"face.json", "background.png"}
    original = (info.source / "face.json").read_bytes()
    with pytest.raises(FaceError, match="already installed"):
        library.install(directory)
    assert (info.source / "face.json").read_bytes() == original


def test_install_missing_image_does_not_leave_a_partial_pack(pack, library):
    (pack[0] / "background.png").unlink()
    with pytest.raises(FaceError):
        library.install(pack[0])
    assert "my-face" not in {info.id for info in library.faces}
    assert not library.ensure_directory().joinpath("my-face").exists()


def test_external_pack_cannot_shadow_builtin(pack, library):
    pack[1]["id"] = DEFAULT_FACE_ID
    write_manifest(pack)
    with pytest.raises(FaceError, match="already installed"):
        library.install(pack[0])
    assert library.load(DEFAULT_FACE_ID).info.source.is_relative_to(BUILTIN_DIRECTORY)


def test_selection_survives_restart_without_writing_on_read(pack, library, tmp_path):
    preferences = tmp_path / "config" / "appearance.json"
    assert not preferences.exists()
    library.install(pack[0])
    assert not preferences.exists()
    library.remember("my-face")
    restarted = FaceLibrary(library.ensure_directory(), preferences)
    assert restarted.preferred_id() == "my-face"


@pytest.mark.parametrize("contents", ["not json", '{"face": "missing"}', "[]"])
def test_bad_preference_has_explicit_fallback(library, tmp_path, contents):
    preferences = tmp_path / "config" / "appearance.json"
    preferences.parent.mkdir()
    preferences.write_text(contents)
    assert library.preferred_id() == DEFAULT_FACE_ID
    assert any("Saved face is unavailable" in problem for problem in library.problems)


def test_bad_user_pack_does_not_break_builtins(library):
    bad = library.ensure_directory() / "broken"
    bad.mkdir()
    (bad / "face.json").write_text("{}")
    library.refresh()
    assert {face.id for face in library.faces} == BUNDLED_IDS
    assert library.problems


def test_unknown_face_cannot_change_preferences(library, tmp_path):
    library.remember(DEFAULT_FACE_ID)
    path = tmp_path / "config" / "appearance.json"
    original = path.read_bytes()
    with pytest.raises(FaceError, match="not found"):
        library.remember("unknown")
    assert path.read_bytes() == original


def test_xdg_locations_are_respected(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    library = FaceLibrary()
    assert library.ensure_directory() == tmp_path / "data" / "amberfader" / "faces"
    library.remember(DEFAULT_FACE_ID)
    assert (tmp_path / "config" / "amberfader" / "appearance.json").exists()
