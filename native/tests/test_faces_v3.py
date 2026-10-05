"""Native imported geometry and sprites retain the existing pack boundaries."""

import json
from dataclasses import FrozenInstanceError

import pytest
from test_faces import png

import amberfader.face_library as face_module
from amberfader.face_document import FaceDocument
from amberfader.face_library import (
    BUILTIN_DIRECTORY,
    DEFAULT_FACE_ID,
    FaceError,
    FaceLibrary,
    load_face,
    load_face_snapshot,
)


@pytest.fixture()
def imported_snapshot():
    manifest = json.loads((BUILTIN_DIRECTORY / DEFAULT_FACE_ID / "face.json").read_text())
    manifest.update(
        formatVersion=3, id="audion-fixture", name="Original face", size=[24, 11],
        drag=[0, 0, 24, 11], sourceCredit="Original designer\nOriginal release notes",
        spriteLabels=False, sliderStyle="popup",
        controls={"play": [2, 2, 8, 8], "title": [1, 1, 12, 6], "seek": [2, 2, 8, 8]},
        readoutStyles={"title": {
            "fontFamily": "Chicago", "color": "#112233", "italic": True, "size": 6,
        }},
        buttons={
            "play": {"normal": "play.png", "playing": "pause.png"},
            "seek": {"normal": "seek.png"},
        },
        timeDigits=[{"rect": [index * 3, 1, 2, 5], "images": [
            f"digit-{digit}.png" for digit in range(10)
        ]} for index in range(4)],
    )
    manifest.pop("controlShapes", None)
    manifest.pop("coverGlass", None)
    assets = {
        "background.png": png(24, 11), "play.png": png(8, 8), "pause.png": png(8, 8),
        "seek.png": png(8, 8), **{f"digit-{digit}.png": png(2, 5) for digit in range(10)},
    }
    return manifest, assets


def test_imported_geometry_and_assets_are_preserved(imported_snapshot, tmp_path):
    manifest, assets = imported_snapshot
    face = load_face_snapshot(manifest, assets, tmp_path)
    assert face.format_version == 3
    assert face.size == (24, 11)
    assert set(face.controls) == {"play", "title", "seek"}
    assert face.drag == (0, 0, 24, 11)
    assert not face.sprite_labels
    assert face.source_credit == manifest["sourceCredit"]
    assert face.slider_style == "popup"
    assert face.readout_styles["title"]["size"] == 6
    assert face.buttons["play"]["playing"] == assets["pause.png"]
    assert face.buttons["seek"]["normal"] == assets["seek.png"]
    assert face.time_digits[0].rect == (0, 1, 2, 5)
    assert face.time_digits[0].images == tuple(assets[f"digit-{digit}.png"] for digit in range(10))
    with pytest.raises(FrozenInstanceError):
        face.time_digits[0].rect = (1, 1, 2, 5)


def test_snapshot_document_saves_and_installs_all_digit_assets(imported_snapshot, tmp_path):
    manifest, assets = imported_snapshot
    document = FaceDocument.from_snapshot(manifest, assets)
    assert document.path is None and document.dirty and not document.can_undo
    manifest["controls"]["play"][0] = 15
    assets["background.png"] = png(1, 1)
    assert document.preview().controls["play"] == (2, 2, 8, 8)
    target = document.save(tmp_path / "converted")
    assert {entry.name for entry in target.iterdir()} == {"face.json", *document.assets}
    reopened = FaceDocument.open(target)
    assert reopened.manifest == document.manifest
    assert reopened.preview().time_digits == document.preview().time_digits
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(target)
    installed = load_face(info.source)
    assert installed.time_digits == document.preview().time_digits
    assert installed.source_credit == document.manifest["sourceCredit"]
    cloned = FaceDocument.from_template(info.source)
    assert cloned.manifest["formatVersion"] == 3
    cloned.set_rotation("play", 0)
    assert cloned.manifest["formatVersion"] == 3


@pytest.mark.parametrize("rect", [[0, 0, 0, 4], [0, 0, 4, 0], [-1, 0, 4, 4], [23, 0, 2, 4]])
@pytest.mark.parametrize("region", ["play", "digit", "drag"])
def test_imported_regions_still_require_positive_in_canvas_bounds(
    imported_snapshot, tmp_path, rect, region,
):
    manifest, assets = imported_snapshot
    if region == "digit":
        manifest["timeDigits"][0]["rect"] = rect
    elif region == "drag":
        manifest["drag"] = rect
    else:
        manifest["controls"][region] = rect
    with pytest.raises(FaceError):
        load_face_snapshot(manifest, assets, tmp_path)


@pytest.mark.parametrize("change", [
    lambda data: data.update(sourceCredit="x" * 4097),
    lambda data: data["readoutStyles"]["title"].update(fontFamily="x" * 97),
    lambda data: data["readoutStyles"]["title"].update(color="red; url(https://example.org)"),
    lambda data: data["timeDigits"][0]["images"].pop(),
    lambda data: data["timeDigits"].append(data["timeDigits"][0]),
    lambda data: data["timeDigits"][0]["images"].__setitem__(0, "../outside.png"),
    lambda data: data["controls"].update(code=[0, 0, 1, 1]),
])
def test_imported_presentation_is_bounded_data(imported_snapshot, tmp_path, change):
    manifest, assets = imported_snapshot
    change(manifest)
    with pytest.raises(FaceError):
        load_face_snapshot(manifest, assets, tmp_path)


def test_digit_assets_share_existing_image_and_pack_limits(
    imported_snapshot, tmp_path, monkeypatch,
):
    manifest, assets = imported_snapshot
    assets.pop("digit-9.png")
    with pytest.raises(FaceError, match="Missing PNG"):
        FaceDocument.from_snapshot(manifest, assets)
    assets["digit-9.png"] = png(2, 5) + b"x" * 1000
    monkeypatch.setattr(face_module, "MAX_IMAGE_BYTES", len(assets["digit-9.png"]) - 1)
    with pytest.raises(FaceError, match="limit"):
        load_face_snapshot(manifest, assets, tmp_path)
    monkeypatch.undo()
    without_digits = sum(
        len(assets[name]) for name in ("background.png", "play.png", "pause.png", "seek.png")
    )
    monkeypatch.setattr(face_module, "MAX_PACK_BYTES", without_digits)
    with pytest.raises(FaceError, match="pack limit"):
        load_face_snapshot(manifest, assets, tmp_path)


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("extra", [
    {"sourceCredit": "credit"}, {"spriteLabels": True}, {"timeDigits": []},
    {"alphaMask": "background.png"},
    {"sliderStyle": "popup"}, {"readoutStyles": {"title": {"fontFamily": "Chicago"}}},
    {"readoutStyles": {"title": {"italic": False}}},
    {"readoutStyles": {"title": {"color": "#ffffff"}}},
    {"readoutStyles": {"title": {"size": 6}}},
    {"buttons": {"seek": {"normal": "background.png"}}},
    {"buttons": {"play": {"normal": "background.png", "playing": "background.png"}}},
])
def test_legacy_versions_reject_import_only_fields(tmp_path, version, extra):
    manifest = json.loads((BUILTIN_DIRECTORY / DEFAULT_FACE_ID / "face.json").read_text())
    manifest.update(formatVersion=version, **extra)
    manifest.pop("controlShapes", None)
    manifest.pop("coverGlass", None)
    with pytest.raises(FaceError):
        load_face_snapshot(manifest, {"background.png": png(*manifest["size"])}, tmp_path)


def test_removing_controls_prunes_overrides_without_losing_undo(imported_snapshot):
    manifest, assets = imported_snapshot
    manifest["controls"]["time"] = [0, 0, 10, 6]
    document = FaceDocument.from_snapshot(manifest, assets)
    document.set_value(("controls", "play"), None)
    assert "play" not in document.preview().controls
    assert "play" not in document.manifest["buttons"]
    assert "play.png" not in document.assets
    assert document.undo()
    assert "play.png" in document.assets
    document.set_value(("controls", "time"), None)
    assert not document.preview().time_digits
    assert not any(name.startswith("digit-") for name in document.assets)
    assert document.undo()
    document.set_value(("readoutStyles", "title", "fontFamily"), None)
    assert "fontFamily" not in document.manifest["readoutStyles"]["title"]


@pytest.mark.parametrize("path,value", [
    (("sourceCredit",), "Author"), (("spriteLabels",), False),
    (("sliderStyle",), "popup"), (("readoutStyles", "title", "fontFamily"), "Chicago"),
    (("readoutStyles", "title", "size"), 6), (("controls", "like"), None),
])
def test_import_presentation_edits_upgrade_legacy_documents(path, value):
    document = FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
    assert document.manifest["formatVersion"] == 2
    document.set_value(path, value)
    assert document.manifest["formatVersion"] == 3
    assert document.validate() == ()


@pytest.mark.parametrize("control,state", [
    ("seek", "normal"), ("volume", "normal"), ("play", "playing"),
    ("play", "playing-hover"), ("play", "playing-pressed"), ("play", "playing-disabled"),
])
def test_imported_sprite_edits_upgrade_and_survive_save(tmp_path, control, state):
    source = tmp_path / "sprite.png"
    source.write_bytes(png(8, 8))
    document = FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
    if state != "normal":
        document.import_button(control, "normal", source)
        assert document.manifest["formatVersion"] == 2
    document.import_button(control, state, source)
    assert document.manifest["formatVersion"] == 3
    assert document.validate() == ()
    reopened = load_face(document.save(tmp_path / "saved"))
    assert reopened.buttons[control][state] == source.read_bytes()


def test_snapshot_creation_rejects_unvalidated_geometry_and_assets(imported_snapshot):
    manifest, assets = imported_snapshot
    manifest["controls"]["play"] = [-1, 0, 8, 8]
    with pytest.raises(FaceError):
        FaceDocument.from_snapshot(manifest, assets)
    manifest["controls"]["play"] = [0, 0, 8, 8]
    assets["play.png"] = bytearray(assets["play.png"])
    with pytest.raises(FaceError, match="Missing PNG"):
        FaceDocument.from_snapshot(manifest, assets)


@pytest.mark.parametrize("scale", [1, 2])
def test_alpha_mask_is_preserved_through_snapshot_save_install_and_clone(
    imported_snapshot, tmp_path, scale,
):
    manifest, assets = imported_snapshot
    manifest["alphaMask"] = "alpha-mask.png"
    assets["alpha-mask.png"] = png(24 * scale, 11 * scale)
    document = FaceDocument.from_snapshot(manifest, assets)
    assert document.preview().alpha_mask == assets["alpha-mask.png"]
    saved = document.save(tmp_path / "saved")
    assert (saved / "alpha-mask.png").read_bytes() == assets["alpha-mask.png"]
    assert FaceDocument.open(saved).preview().alpha_mask == assets["alpha-mask.png"]
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    installed = library.install(saved)
    assert load_face(installed.source).alpha_mask == assets["alpha-mask.png"]
    assert any(face.id == installed.id for face in library.faces)
    clone = FaceDocument.from_template(installed.source)
    assert clone.preview().alpha_mask == assets["alpha-mask.png"]


@pytest.mark.parametrize("size", [(1, 1), (24, 22), (72, 33)])
def test_alpha_mask_dimensions_require_matching_logical_canvas(imported_snapshot, size):
    manifest, assets = imported_snapshot
    manifest["alphaMask"] = "alpha-mask.png"
    assets["alpha-mask.png"] = png(*size)
    with pytest.raises(FaceError, match="Alpha mask must match"):
        FaceDocument.from_snapshot(manifest, assets)


def test_alpha_mask_import_is_undoable_and_can_be_removed(tmp_path):
    document = FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
    source = tmp_path / "mask.png"
    source.write_bytes(png(*document.manifest["size"]))
    document.import_alpha_mask(source)
    assert document.manifest["formatVersion"] == 3
    assert document.preview().alpha_mask == source.read_bytes()
    assert document.undo()
    assert document.manifest["formatVersion"] == 2
    assert document.preview().alpha_mask is None
    assert document.redo()
    document.import_alpha_mask(None)
    assert document.preview().alpha_mask is None
    assert "alphaMask" not in document.manifest


def test_alpha_mask_is_a_required_bounded_declared_image(imported_snapshot, tmp_path, monkeypatch):
    manifest, assets = imported_snapshot
    manifest["alphaMask"] = "alpha-mask.png"
    with pytest.raises(FaceError, match="Missing PNG"):
        FaceDocument.from_snapshot(manifest, assets)
    assets["alpha-mask.png"] = png(24, 11) + b"x" * 1000
    monkeypatch.setattr(face_module, "MAX_IMAGE_BYTES", len(assets["alpha-mask.png"]) - 1)
    with pytest.raises(FaceError, match=r"alpha-mask\.png exceeds"):
        load_face_snapshot(manifest, assets, tmp_path)
    monkeypatch.undo()
    without_mask = sum(len(data) for name, data in assets.items() if name != "alpha-mask.png")
    monkeypatch.setattr(face_module, "MAX_PACK_BYTES", without_mask)
    with pytest.raises(FaceError, match="pack limit"):
        load_face_snapshot(manifest, assets, tmp_path)


def test_catalog_probe_rejects_wrong_mask_dimensions(imported_snapshot, tmp_path):
    manifest, assets = imported_snapshot
    manifest["alphaMask"] = "alpha-mask.png"
    assets["alpha-mask.png"] = png(24, 11)
    (tmp_path / "faces").mkdir()
    saved = FaceDocument.from_snapshot(manifest, assets).save(tmp_path / "faces" / "fixture")
    (saved / "alpha-mask.png").write_bytes(png(1, 1))
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    assert not any(face.id == "audion-fixture" for face in library.faces)
    assert any("Alpha mask must match" in error for error in library.problems)


def test_aggregate_bitmap_pixels_are_bounded_before_native_decode(imported_snapshot, tmp_path):
    manifest, assets = imported_snapshot
    large = png(2048, 2048)
    for index, digit in enumerate(manifest["timeDigits"]):
        digit["images"] = [f"large-{index}-{value}.png" for value in range(10)]
        assets.update({name: large for name in digit["images"]})
    with pytest.raises(FaceError, match="decoded image limit"):
        load_face_snapshot(manifest, assets, tmp_path)


def test_repeated_asset_references_count_pixels_once(imported_snapshot, tmp_path):
    manifest, assets = imported_snapshot
    assets["large.png"] = png(2048, 2048)
    for digit in manifest["timeDigits"]:
        digit["images"] = ["large.png"] * 10
    face = load_face_snapshot(manifest, assets, tmp_path)
    assert len(face.time_digits) == 4


def test_catalog_probe_checks_the_aggregate_pixel_budget(imported_snapshot, tmp_path, monkeypatch):
    manifest, assets = imported_snapshot
    saved = FaceDocument.from_snapshot(manifest, assets).save(tmp_path / "saved")
    monkeypatch.setattr(face_module, "MAX_DECODED_PIXELS", 24 * 11)
    with pytest.raises(FaceError, match="decoded image limit"):
        face_module._probe_face(saved)


@pytest.mark.parametrize("control", ["close", "volume"])
def test_sprite_import_requires_a_present_control(imported_snapshot, tmp_path, control):
    document = FaceDocument.from_snapshot(*imported_snapshot)
    source = tmp_path / "sprite.png"
    source.write_bytes(png(8, 8))
    before = document.manifest
    assets = dict(document.assets)
    with pytest.raises(FaceError, match=f"Add the {control} control"):
        document.import_button(control, "normal", source)
    assert document.manifest == before and document.assets == assets
    assert not document.can_undo
