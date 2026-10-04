"""Face pack boundaries, installation and preference recovery without Qt."""
import json
import struct
import zlib

import pytest

import amberfader.face_library as face_module
from amberfader.face_library import (
    BUILTIN_DIRECTORY,
    DEFAULT_FACE_ID,
    MAX_IMAGE_BYTES,
    MAX_IMAGE_DIMENSION,
    MAX_MANIFEST_BYTES,
    PNG_HEADER_BYTES,
    PNG_SIGNATURE,
    FaceError,
    FaceLibrary,
    load_face,
)

BUNDLED_IDS = {
    "amber-classic", "midnight-rack", "moonstone", "copper-reel", "paper-signal",
    "memphis-93", "arcade-clear", "rave-grid",
    "orbit-99", "manta-ray", "jellyfish-fm", "boom-bot",
    "tangent", "keystone", "switchback", "vane",
    "aureole", "viridian",
}


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
    data.update(id="my-face", name="My Face", formatVersion=1)
    # This fixture exercises a minimal pack; sprite tests add their own assets.
    data.pop("buttons", None)
    for key in ("controlShapes", "coverGlass", "readoutStyles", "sliderStyle"):
        data.pop(key, None)
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


@pytest.mark.parametrize("face_id", sorted(BUNDLED_IDS))
def test_bundled_shared_sprites_fit_one_button_size(face_id):
    # A sprite stretches to each control, so a shared surface needs one size
    # and shape or its corners, rims and capsule ends distort on some buttons.
    data = json.loads((BUILTIN_DIRECTORY / face_id / "face.json").read_text())
    shapes = data.get("controlShapes", {})
    members = {}
    for name, images in data["buttons"].items():
        outline = (tuple(data["controls"][name][2:]), shapes.get(name, "rectangle"))
        members.setdefault(images["normal"], {})[name] = outline
    for sprite, outlines in members.items():
        assert len(set(outlines.values())) == 1, (face_id, sprite, outlines)


@pytest.mark.parametrize("change", [
    lambda d: d.update(formatVersion=3),
    lambda d: d.update(code="plugin.py"),
    lambda d: d.update(background="../outside.png"),
    lambda d: d["palette"].update(accent="red; background: url(https://example.org)"),
    lambda d: d["controls"].pop("like"),
    lambda d: d["controls"].update(extra=[0, 0, 30, 30]),
    lambda d: d.update(font="unknown"),
    lambda d: d.update(buttons={"play": {"hover": "background.png"}}),
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


def test_legacy_manifest_retains_default_presentation(pack):
    face = load_face(pack[0])
    assert not face.control_shapes
    assert face.cover_glass is False
    assert face.controls["art"] == tuple(pack[1]["controls"]["art"])


@pytest.mark.parametrize("metadata", [
    {"controlShapes": {"art": "ellipse"}}, {"controlShapes": {}}, {"coverGlass": False},
])
def test_legacy_version_rejects_new_presentation_fields(pack, metadata):
    pack[1].update(metadata)
    write_manifest(pack)
    with pytest.raises(FaceError):
        load_face(pack[0])


@pytest.mark.parametrize("width,height", [(48, 48), (48, 80), (96, 48)])
def test_format_two_accepts_circular_and_oval_cover_apertures(pack, width, height):
    pack[1].update(formatVersion=2, controlShapes={"art": "ellipse"})
    pack[1]["controls"]["art"] = [28, 64, width, height]
    write_manifest(pack)
    face = load_face(pack[0])
    assert face.controls["art"] == (28, 64, width, height)
    assert face.control_shapes["art"] == "ellipse"


@pytest.mark.parametrize("rectangle,error", [
    ([28, 64, 47, 48], "too small"), ([28, 64, 48, 47], "too small"),
    ([530, 64, 48, 48], "fit inside"), ([84, 192, 48, 48], "overlaps"),
])
def test_format_two_curved_cover_keeps_size_and_layout_bounds(pack, rectangle, error):
    pack[1].update(formatVersion=2, controlShapes={"art": "ellipse"})
    pack[1]["controls"]["art"] = rectangle
    write_manifest(pack)
    with pytest.raises(FaceError, match=error):
        load_face(pack[0])


@pytest.mark.parametrize("shape", ["rectangle", "rounded", "capsule"])
def test_format_two_other_cover_shapes_keep_legacy_size_bounds(pack, shape):
    pack[1].update(formatVersion=2, controlShapes={"art": shape})
    pack[1]["controls"]["art"] = [28, 64, 64, 64]
    write_manifest(pack)
    assert load_face(pack[0]).control_shapes["art"] == shape
    for width, height, error in [(48, 48, "too small"), (64, 80, "square")]:
        pack[1]["controls"]["art"] = [28, 64, width, height]
        write_manifest(pack)
        with pytest.raises(FaceError, match=error):
            load_face(pack[0])


@pytest.mark.parametrize("metadata", [
    {"controlShapes": {"seek": "ellipse"}},
    {"controlShapes": {"play": "triangle"}},
    {"controlShapes": {"play": {"path": "M0,0"}}},
    {"coverGlass": "true"},
])
def test_format_two_presentation_remains_constrained_data(pack, metadata):
    pack[1].update(formatVersion=2, **metadata)
    write_manifest(pack)
    with pytest.raises(FaceError):
        load_face(pack[0])


def test_install_and_restart_preserve_format_two_presentation(pack, library, tmp_path):
    shapes = {"art": "ellipse", "play": "ellipse", "search": "capsule", "menu": "rounded"}
    pack[1].update(formatVersion=2, controlShapes=shapes, coverGlass=True)
    pack[1]["controls"]["art"] = [28, 64, 48, 80]
    write_manifest(pack)
    info = library.install(pack[0])
    installed = json.loads((info.source / "face.json").read_text())
    assert installed["formatVersion"] == 2
    assert installed["controlShapes"] == shapes
    assert installed["coverGlass"] is True
    restarted = FaceLibrary(library.ensure_directory(), tmp_path / "appearance.json")
    face = restarted.load(info.id)
    assert dict(face.control_shapes) == shapes
    assert face.cover_glass is True
    assert face.controls["art"] == (28, 64, 48, 80)


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


def test_missing_builtin_directory_has_an_actionable_domain_error(monkeypatch, tmp_path):
    monkeypatch.setattr(face_module, "BUILTIN_DIRECTORY", tmp_path / "missing")
    with pytest.raises(FaceError, match="Reinstall Amberfader"):
        FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")


def test_manifest_changed_during_install_is_reported_and_not_published(pack, library, monkeypatch):
    original = face_module._manifest
    reads = 0

    def changing_manifest(directory):
        nonlocal reads
        if directory == pack[0]:
            reads += 1
            if reads == 2:
                (directory / "face.json").write_text("not json")
        return original(directory)

    monkeypatch.setattr(face_module, "_manifest", changing_manifest)
    with pytest.raises(FaceError):
        library.install(pack[0])
    assert not library.ensure_directory().joinpath("my-face").exists()


def test_install_directory_read_error_stays_inside_domain_contract(pack, library, monkeypatch):
    root = library.ensure_directory()
    original = type(root).iterdir

    def fail_scan(path):
        if path == root:
            raise OSError("Face folder became unreadable")
        return original(path)

    monkeypatch.setattr(type(root), "iterdir", fail_scan)
    with pytest.raises(FaceError, match="unreadable"):
        library.install(pack[0])


def test_discovery_reads_headers_instead_of_image_payloads(pack, library, monkeypatch):
    library.install(pack[0])
    original_open = type(pack[0]).open
    image_reads = []

    class CountedImage:
        def __init__(self, stream):
            self._stream = stream

        def __enter__(self):
            self._stream.__enter__()
            return self

        def __exit__(self, *args):
            return self._stream.__exit__(*args)

        def fileno(self):
            return self._stream.fileno()

        def read(self, size=-1):
            data = self._stream.read(size)
            image_reads.append(len(data))
            return data

    def counted_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return CountedImage(stream) if path.suffix == ".png" else stream

    monkeypatch.setattr(type(pack[0]), "open", counted_open)
    library.refresh()
    assert image_reads
    assert max(image_reads) <= PNG_HEADER_BYTES
    assert "my-face" in {face.id for face in library.faces}


def test_disappearing_installed_manifest_reports_domain_error(pack, library, monkeypatch):
    original = library.refresh
    target = library.ensure_directory() / "my-face"

    def refreshing():
        if target.exists():
            (target / "face.json").unlink()
        original()

    monkeypatch.setattr(library, "refresh", refreshing)
    with pytest.raises(FaceError, match="Installed face"):
        library.install(pack[0])


def test_header_only_discovery_still_rejects_image_budget_violations(pack, library):
    info = library.install(pack[0])
    with (info.source / "background.png").open("r+b") as stream:
        stream.truncate(MAX_IMAGE_BYTES + 1)
    library.refresh()
    assert "my-face" not in {face.id for face in library.faces}
    assert any("limit" in problem for problem in library.problems)
