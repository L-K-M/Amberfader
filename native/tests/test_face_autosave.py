"""Crash recovery snapshots stay outside face folders and never overwrite newer work."""
from __future__ import annotations

import pytest

from amberfader.face_autosave import AutosaveStore
from amberfader.face_document import FaceDocument
from amberfader.face_library import BUILTIN_DIRECTORY, DEFAULT_FACE_ID, FaceError

TEMPLATE = BUILTIN_DIRECTORY / DEFAULT_FACE_ID
TOKEN = "0123abcd"


@pytest.fixture()
def store(tmp_path):
    return AutosaveStore(tmp_path / "autosave")


def test_untitled_draft_round_trips_as_unsaved_work(store):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_rect("play", [-40, 10, 60, 48], label="Move")  # A draft outside the face.
    store.write(TOKEN, document)
    faces, problems = store.recover()
    assert problems == []
    [face] = faces
    assert face.token == TOKEN
    assert face.document.path is None
    assert face.document.needs_save
    assert face.document.manifest == document.manifest
    assert dict(face.document.assets) == dict(document.assets)


def test_saved_face_recovers_attached_and_undo_returns_to_disk(store, tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    folder = document.save(tmp_path / "saved")
    document.set_rotation("play", 12, label="Rotate")
    store.write(TOKEN, document)
    [face], _ = store.recover()
    recovered = face.document
    assert recovered.path == folder
    assert recovered.manifest["controlRotations"]["play"] == 12
    assert recovered.undo_label == "Recover Changes"
    recovered.undo()
    assert not recovered.dirty
    recovered.redo()
    recovered.save()
    assert FaceDocument.open(folder).manifest["controlRotations"]["play"] == 12


def test_changed_folder_recovers_untitled_so_save_cannot_overwrite_it(store, tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    folder = document.save(tmp_path / "saved")
    document.set_rotation("play", 12)
    store.write(TOKEN, document)
    newer = FaceDocument.open(folder)
    newer.set_value(("name",), "Edited elsewhere")
    newer.save()
    [face], _ = store.recover()
    assert face.document.path is None
    assert face.document.manifest["controlRotations"]["play"] == 12


def test_rewrite_replaces_and_remove_deletes_the_snapshot(store):
    document = FaceDocument.from_template(TEMPLATE)
    store.write(TOKEN, document)
    document.set_value(("name",), "Second")
    store.write(TOKEN, document)
    [face], _ = store.recover()
    assert face.document.manifest["name"] == "Second"
    assert sorted(path.name for path in store.root.iterdir()) == [TOKEN]
    store.remove(TOKEN)
    assert store.recover() == ([], [])


def test_unreadable_snapshot_is_reported_and_kept(store):
    document = FaceDocument.from_template(TEMPLATE)
    store.write(TOKEN, document)
    (store.root / TOKEN / "face.json").write_text("{not json")
    faces, problems = store.recover()
    assert faces == []
    assert len(problems) == 1 and problems[0].startswith(TOKEN)
    assert (store.root / TOKEN).is_dir()


def test_interrupted_writes_are_cleaned_and_tokens_are_checked(store):
    store.root.mkdir(parents=True)
    (store.root / ".0123abcd-partial").mkdir()
    assert store.recover() == ([], [])
    assert not (store.root / ".0123abcd-partial").exists()
    with pytest.raises(FaceError):
        store.write("../escape", FaceDocument.from_template(TEMPLATE))
