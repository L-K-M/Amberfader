"""Portable face editing without Qt, with bounded assets and transactional saves."""
import json
from pathlib import Path

import pytest

import amberfader.face_document as document_module
from amberfader.face_document import FaceDocument
from amberfader.face_library import (
    BUILTIN_DIRECTORY,
    DEFAULT_FACE_ID,
    MAX_MANIFEST_BYTES,
    MAX_PACK_BYTES,
    FaceError,
    load_face,
)

TEMPLATE = BUILTIN_DIRECTORY / DEFAULT_FACE_ID


def test_template_is_an_unsaved_custom_copy(tmp_path):
    original = (TEMPLATE / "face.json").read_bytes()
    document = FaceDocument.from_template(TEMPLATE)
    assert document.path is None
    assert document.dirty
    assert document.manifest["id"] != DEFAULT_FACE_ID
    assert document.manifest["formatVersion"] == 2
    document.set_value(("name",), "My player")
    document.save(tmp_path / "custom")
    assert (TEMPLATE / "face.json").read_bytes() == original
    assert not document.dirty


def test_save_reopen_and_assets_match_in_memory_snapshot(tmp_path):
    document = FaceDocument.from_template(TEMPLATE, face_id="studio", name="Studio")
    target = document.save(tmp_path / "studio")
    reopened = FaceDocument.open(target)
    assert reopened.manifest == document.manifest
    assert reopened.assets == document.assets
    assert not reopened.dirty
    assert load_face(target).info.id == "studio"


def test_unedited_template_copy_has_no_work_to_lose(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    assert document.dirty and not document.needs_save
    document.set_rotation("play", 10)
    assert document.needs_save
    document.undo()
    assert not document.needs_save
    # An import exists only in memory, so it always has work to lose.
    assert FaceDocument.from_snapshot(document.manifest, document.assets).needs_save
    reopened = FaceDocument.open(document.save(tmp_path / "saved"))
    assert not reopened.needs_save
    reopened.set_rotation("play", 5)
    assert reopened.needs_save


def test_saved_copy_asks_even_when_undone_to_the_template(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_rotation("play", 10)
    document.save(tmp_path / "saved")
    document.undo()
    # The folder holds the rotation; closing now would silently keep it.
    assert document.needs_save


def test_returned_manifest_and_assets_cannot_mutate_document():
    document = FaceDocument.from_template(TEMPLATE)
    returned = document.manifest
    returned["controls"]["play"][0] = 888
    assert document.manifest["controls"]["play"][0] != 888
    with pytest.raises(TypeError):
        document.assets["background.png"] = b"bad"


def test_edit_undo_redo_and_saved_checkpoint(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    document.save(tmp_path / "custom")
    document.set_value(("name",), "Changed")
    assert document.dirty and document.can_undo
    assert document.undo()
    assert not document.dirty and document.can_redo
    assert document.redo()
    assert document.manifest["name"] == "Changed"
    document.save()
    assert not document.dirty
    document.undo()
    assert document.dirty


def test_gesture_coalesces_moves_and_cancel_restores_exact_snapshot():
    document = FaceDocument.from_template(TEMPLATE)
    original = document.manifest
    document.begin_gesture()
    for x in range(85, 93):
        document.set_rect("play", (x, 192, 60, 48))
    document.end_gesture()
    assert document.undo()
    assert document.manifest == original
    assert not document.can_undo
    document.begin_gesture()
    document.set_value(("name",), "Cancelled")
    document.cancel_gesture()
    assert document.manifest == original


def test_invalid_layout_stays_editable_but_cannot_save(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_rect("play", document.manifest["controls"]["next"])
    assert any("overlaps" in problem for problem in document.validate())
    assert document.preview().controls["play"] == document.preview().controls["next"]
    with pytest.raises(FaceError, match="overlaps"):
        document.save(tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_export_does_not_change_document_path_or_checkpoint(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    document.save(tmp_path / "working")
    document.set_value(("name",), "Unsaved change")
    exported = document.export(tmp_path / "portable")
    assert document.path == tmp_path / "working"
    assert document.dirty
    assert load_face(exported).info.name == "Unsaved change"
    assert load_face(document.path).info.name != "Unsaved change"


def test_save_as_refuses_existing_pack_and_builtin_destination(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    existing = tmp_path / "exists"
    existing.mkdir()
    (existing / "precious.txt").write_text("Keep me")
    with pytest.raises(FaceError, match="empty"):
        document.save(existing)
    assert (existing / "precious.txt").read_text() == "Keep me"
    with pytest.raises(FaceError, match="bundled"):
        document.save(TEMPLATE)


def test_save_failure_restores_original_pack(tmp_path, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    before = {file.name: file.read_bytes() for file in target.iterdir()}
    document.set_value(("name",), "Failed write")
    replace = Path.replace

    def fail_publish(source, destination):
        if source.name == "snapshot":
            raise OSError("Simulated publication failure")
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_publish)
    with pytest.raises(FaceError, match="publication failure"):
        document.save()
    assert {file.name: file.read_bytes() for file in target.iterdir()} == before
    assert document.dirty
    assert not any(file.name.startswith(".face-edit-") for file in tmp_path.iterdir())


def test_external_change_cannot_be_overwritten(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    external = json.loads((target / "face.json").read_text())
    external["name"] = "Someone else's work"
    (target / "face.json").write_text(json.dumps(external))
    document.set_value(("name",), "My work")
    with pytest.raises(FaceError, match="changed"):
        document.save()
    assert load_face(target).info.name == "Someone else's work"


def test_png_import_is_undoable_and_snapshot_survives_source_removal(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    source = tmp_path / "renamed sprite.png"
    source.write_bytes(document.preview().buttons["play"]["normal"])
    document.import_button("next", "normal", source)
    imported_name = document.manifest["buttons"]["next"]["normal"]
    source.unlink()
    assert imported_name.startswith("next-normal-")
    document.save(tmp_path / "saved")
    assert document.undo()
    assert imported_name not in document.assets


def test_background_import_requires_matching_size(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    source = tmp_path / "sprite.png"
    source.write_bytes(document.preview().buttons["play"]["normal"])
    original = document.manifest
    with pytest.raises(FaceError, match="match"):
        document.import_background(source)
    assert document.manifest == original


def test_import_rejects_non_png_and_png_byte_limit(tmp_path, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    source = tmp_path / "bad.png"
    source.write_bytes(b"not png")
    with pytest.raises(FaceError, match="PNG"):
        document.import_button("play", "normal", source)
    monkeypatch.setattr(document_module, "MAX_IMAGE_BYTES", 8)
    with pytest.raises(FaceError, match="limit"):
        document.import_button("play", "normal", TEMPLATE / "background.png")


@pytest.mark.parametrize("path", [
    ("__class__",), ("background",), ("buttons", "play", "normal"),
    ("controls", "imaginary"),
])
def test_general_edits_cannot_invent_assets_or_controls(path):
    document = FaceDocument.from_template(TEMPLATE)
    with pytest.raises(FaceError):
        document.set_value(path, "../../outside.png")


def test_exported_folder_contains_declared_assets_only(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.export(tmp_path / "portable")
    assert {item.name for item in target.iterdir()} == {"face.json", *document.assets}
    assert all(item.is_file() and not item.is_symlink() for item in target.iterdir())


def test_symbolic_destination_cannot_replace_another_folder(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    outside = tmp_path / "outside"
    outside.mkdir()
    destination = tmp_path / "link"
    destination.symlink_to(outside, target_is_directory=True)
    with pytest.raises(FaceError, match="symbolic"):
        document.save(destination)
    assert destination.is_symlink()


def test_opening_a_builtin_clones_it_instead_of_enabling_save():
    document = FaceDocument.open(TEMPLATE)
    assert document.path is None
    assert document.manifest["id"] != DEFAULT_FACE_ID
    with pytest.raises(FaceError, match="folder"):
        document.save()


def test_template_copies_get_independent_custom_identifiers():
    first = FaceDocument.from_template(TEMPLATE)
    second = FaceDocument.from_template(TEMPLATE)
    assert first.manifest["id"] != second.manifest["id"]
    assert len(first.manifest["id"]) <= 48


def test_readout_override_can_be_removed_as_a_group():
    document = FaceDocument.from_template(TEMPLATE)
    document.set_value(("readoutStyles", "title", "align"), "center")
    document.set_value(("readoutStyles", "title"), None)
    assert "title" not in document.manifest["readoutStyles"]
    document.undo()
    assert document.manifest["readoutStyles"]["title"]["align"] == "center"


def test_removing_an_absent_override_does_not_add_history():
    document = FaceDocument.from_template(TEMPLATE)
    original = document.manifest
    document.set_value(("readoutStyles", "title", "align"), None)
    assert document.manifest == original
    assert not document.can_undo


def test_rotated_face_save_reopen_matches_snapshot(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    # A near-square window button keeps its footprint through a quarter turn,
    # so the rotated draft stays valid whatever the template's row spacing.
    document.set_rotation("close", -90)
    assert not document.validate()
    target = document.save(tmp_path / "rotated")
    reopened = FaceDocument.open(target)
    assert reopened.preview().control_rotations["close"] == -90


def test_rotation_overlap_blocks_save_but_retains_draft(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_rotation("time", 90)
    assert document.validate()
    assert document.preview().control_rotations["time"] == 90
    with pytest.raises(FaceError):
        document.save(tmp_path / "bad")


def test_open_rejects_asset_path_traversal(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "source")
    data = document.manifest
    data["background"] = "../outside.png"
    (target / "face.json").write_text(json.dumps(data))
    with pytest.raises(FaceError):
        FaceDocument.open(target)


def test_open_rejects_manifest_symlink_escape(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "source")
    (target / "face.json").rename(tmp_path / "outside.json")
    (target / "face.json").symlink_to(tmp_path / "outside.json")
    with pytest.raises(FaceError, match="inside"):
        FaceDocument.open(target)


def test_save_refuses_foreign_files_added_to_opened_pack(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    (target / "precious.txt").write_text("Do not remove")
    with pytest.raises(FaceError, match="changed"):
        document.save()
    assert (target / "precious.txt").read_text() == "Do not remove"


def test_failed_rollback_preserves_original_in_recovery_folder(tmp_path, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    original = (target / "face.json").read_bytes()
    document.set_value(("name",), "Failed write")
    replace = Path.replace

    def fail_publish_and_restore(source, destination):
        if source.name in {"snapshot", "previous"}:
            raise OSError("Simulated failure")
        return replace(source, destination)

    monkeypatch.setattr(Path, "replace", fail_publish_and_restore)
    with pytest.raises(FaceError, match="preserved at"):
        document.save()
    backups = list(tmp_path.glob(".face-edit-*/previous/face.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert document.dirty


def test_manifest_byte_limit_is_enforced_before_state_changes():
    document = FaceDocument.from_template(TEMPLATE)
    original = document.manifest
    with pytest.raises(FaceError, match="64 KiB"):
        document.set_value(("description",), "x" * MAX_MANIFEST_BYTES)
    assert document.manifest == original


def test_asset_import_pack_budget_failure_keeps_previous_snapshot(tmp_path, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    original = document.manifest
    source = tmp_path / "background.png"
    source.write_bytes(document.preview().background)
    monkeypatch.setattr(document_module, "MAX_PACK_BYTES", 1)
    with pytest.raises(FaceError, match="pack limit"):
        document.import_background(source)
    assert document.manifest == original
    assert sum(map(len, document.assets.values())) <= MAX_PACK_BYTES


def test_history_step_limit_discards_oldest_commands(monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    monkeypatch.setattr(document_module, "MAX_HISTORY_STEPS", 3)
    for index in range(5):
        document.set_value(("name",), f"Edit {index}")
    assert sum(document.undo() for _ in range(5)) == 3
    assert document.manifest["name"] == "Edit 1"


def test_import_history_png_bytes_are_bounded_and_checkpoint_survives(
    tmp_path, monkeypatch,
):
    document = FaceDocument.from_template(TEMPLATE)
    document.save(tmp_path / "working")
    base_bytes = sum(map(len, document.assets.values()))
    sprite = document.preview().buttons["play"]["normal"]
    monkeypatch.setattr(document_module, "MAX_HISTORY_BYTES", base_bytes + 2 * (len(sprite) + 1))
    source = tmp_path / "sprite.png"
    for index in range(6):
        source.write_bytes(sprite + bytes([index]))
        document.import_button("play", "normal", source)
    assert document.dirty
    assert sum(document.undo() for _ in range(6)) == 1
    assert document.dirty
    document.save()
    assert not document.dirty


def test_template_asset_replacement_does_not_change_loaded_document(tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "source")
    reopened = FaceDocument.open(target)
    original = reopened.preview().background
    (target / reopened.manifest["background"]).write_bytes(b"changed externally")
    assert reopened.preview().background == original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), object()])
def test_non_json_edits_fail_without_mutating_state(value):
    document = FaceDocument.from_template(TEMPLATE)
    original = document.manifest
    with pytest.raises(FaceError, match="finite JSON"):
        document.set_rotation("play", value)
    assert document.manifest == original


@pytest.mark.parametrize("destination", ["working", "empty-save-as", "empty-export"])
def test_rename_race_preserves_files_added_to_actual_replaced_folder(
    tmp_path, monkeypatch, destination,
):
    document = FaceDocument.from_template(TEMPLATE)
    working = document.save(tmp_path / "working")
    document.set_value(("name",), "Changed")
    target = working if destination == "working" else tmp_path / "empty"
    if target != working:
        target.mkdir()
    previous_manifest = (working / "face.json").read_bytes()
    replace = Path.replace

    def add_foreign_file_during_rename(source, renamed):
        if source == target:
            (source / "precious.txt").write_text("Concurrent work")
        return replace(source, renamed)

    monkeypatch.setattr(Path, "replace", add_foreign_file_during_rename)
    operation = document.export if destination == "empty-export" else document.save
    with pytest.raises(FaceError, match="changed"):
        operation(target)
    assert (target / "precious.txt").read_text() == "Concurrent work"
    assert (working / "face.json").read_bytes() == previous_manifest
    assert document.dirty
    assert not list(tmp_path.glob(".face-edit-*"))


def test_active_gesture_is_undoable_and_invalidates_redo():
    document = FaceDocument.from_template(TEMPLATE)
    document.set_value(("name",), "Older edit")
    document.undo()
    assert document.can_redo
    original = document.manifest
    document.begin_gesture()
    document.set_rect("play", (88, 192, 60, 48))
    assert document.can_undo
    assert not document.can_redo
    assert document.undo()
    assert document.manifest == original
    assert document.redo()
    assert document.manifest["controls"]["play"][0] == 88


def test_rename_race_preserves_changed_manifest_bytes(tmp_path, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    document.set_value(("name",), "My edit")
    foreign = document.manifest
    foreign["name"] = "Concurrent edit"
    foreign_bytes = json.dumps(foreign).encode()
    replace = Path.replace

    def change_manifest_during_rename(source, renamed):
        if source == target:
            (source / "face.json").write_bytes(foreign_bytes)
        return replace(source, renamed)

    monkeypatch.setattr(Path, "replace", change_manifest_during_rename)
    with pytest.raises(FaceError, match="changed"):
        document.save()
    assert (target / "face.json").read_bytes() == foreign_bytes
    assert document.dirty


def test_rename_race_failed_restore_retains_concurrent_file(tmp_path, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    replace = Path.replace

    def add_file_and_block_restore(source, renamed):
        if source == target:
            (source / "precious.txt").write_text("Concurrent work")
        elif source.name == "previous":
            raise OSError("Restore unavailable")
        return replace(source, renamed)

    monkeypatch.setattr(Path, "replace", add_file_and_block_restore)
    with pytest.raises(FaceError, match="preserved at"):
        document.save()
    backups = list(tmp_path.glob(".face-edit-*/previous/precious.txt"))
    assert len(backups) == 1
    assert backups[0].read_text() == "Concurrent work"


@pytest.mark.parametrize("rectangle", [(-8, 192, 60, 48), (84, -8, 60, 48)])
def test_negative_coordinate_draft_is_visible_but_not_savable_and_undo_restores(
    tmp_path, rectangle,
):
    document = FaceDocument.from_template(TEMPLATE)
    target = document.save(tmp_path / "working")
    original = document.manifest["controls"]["play"]
    saved_bytes = (target / "face.json").read_bytes()
    document.set_rect("play", rectangle)
    assert document.preview().controls["play"] == rectangle
    assert document.validate()
    with pytest.raises(FaceError):
        document.save()
    assert (target / "face.json").read_bytes() == saved_bytes
    assert document.undo()
    assert document.preview().controls["play"] == tuple(original)
    assert not document.dirty
    assert not document.validate()


@pytest.fixture()
def temporary_bundle(tmp_path, monkeypatch):
    directory = tmp_path / "bundled-faces"
    directory.mkdir()
    source = FaceDocument.from_template(TEMPLATE).export(directory / "template")
    monkeypatch.setattr(document_module, "BUILTIN_DIRECTORY", directory)
    return directory, source


def case_alias(directory):
    alias = directory.with_name(directory.name.upper())
    if not alias.exists() or not alias.samefile(directory):
        pytest.skip("The temporary filesystem is case sensitive")
    return alias


def test_open_physical_case_alias_of_bundle_creates_custom_copy(temporary_bundle):
    directory, source = temporary_bundle
    alias_source = case_alias(directory) / source.name
    original = (source / "face.json").read_bytes()
    document = FaceDocument.open(alias_source)
    assert document.path is None
    assert document.manifest["id"] != json.loads(original)["id"]
    assert (source / "face.json").read_bytes() == original


def test_save_cannot_overwrite_bundle_through_case_alias(temporary_bundle):
    directory, source = temporary_bundle
    alias_source = case_alias(directory) / source.name
    original = (source / "face.json").read_bytes()
    document = FaceDocument.open(alias_source)
    document.set_value(("name",), "Edited copy")
    with pytest.raises(FaceError, match="bundled"):
        document.save(alias_source)
    assert (source / "face.json").read_bytes() == original


@pytest.mark.parametrize("operation", ["save", "export"])
def test_absent_destination_under_case_alias_of_bundle_is_protected(
    temporary_bundle, operation,
):
    directory, source = temporary_bundle
    target = case_alias(directory) / "new-face"
    document = FaceDocument.from_template(source)
    with pytest.raises(FaceError, match="bundled"):
        getattr(document, operation)(target)
    assert not target.exists()


def test_case_sensitive_distinct_directory_remains_a_valid_destination(temporary_bundle):
    directory, source = temporary_bundle
    distinct = directory.with_name(directory.name.upper())
    if distinct.exists():
        pytest.skip("The temporary filesystem is case insensitive")
    distinct.mkdir()
    document = FaceDocument.from_template(source)
    target = document.save(distinct / "custom")
    assert load_face(target).info.id == document.manifest["id"]
    assert not distinct.samefile(directory)


@pytest.mark.parametrize("operation", ["open", "save"])
def test_bundle_identity_inspection_error_never_bypasses_protection(
    tmp_path, monkeypatch, operation,
):
    document = FaceDocument.from_template(TEMPLATE)
    existing = document.save(tmp_path / "working")
    original = (existing / "face.json").read_bytes()

    def unreadable_identity(path, other):
        raise PermissionError("Folder identity cannot be read")

    monkeypatch.setattr(Path, "samefile", unreadable_identity)
    with pytest.raises(FaceError, match="Cannot inspect face folder"):
        if operation == "open":
            FaceDocument.open(existing)
        else:
            document.save(tmp_path / "new")
    assert (existing / "face.json").read_bytes() == original
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("operation", ["save", "export"])
@pytest.mark.parametrize("aliased", [False, True])
def test_destination_inside_working_pack_is_rejected_before_it_changes_source(
    tmp_path, operation, aliased,
):
    document = FaceDocument.from_template(TEMPLATE)
    working = document.save(tmp_path / "working")
    original = {file.name: file.read_bytes() for file in working.iterdir()}
    parent = case_alias(working) if aliased else working
    target = parent / "copy"
    document.set_value(("name",), "Unsaved edit")
    with pytest.raises(FaceError, match="outside the working face folder"):
        getattr(document, operation)(target)
    assert not target.exists()
    assert {file.name: file.read_bytes() for file in working.iterdir()} == original
    assert document.path == working
    assert document.dirty
    document.save()
    assert not document.dirty
