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
    store = AutosaveStore(tmp_path / "autosave")
    yield store
    store.close()


def _after_crash(store):
    """The next editor, once the writer's session has ended without cleanup."""
    store.close()
    return AutosaveStore(store.root)


def _snapshots(root):
    return sorted(path.name for path in root.iterdir() if not path.name.startswith("."))


def test_untitled_draft_round_trips_as_unsaved_work(store):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_rect("play", [-40, 10, 60, 48], label="Move")  # A draft outside the face.
    store.write(TOKEN, document)
    faces, problems = _after_crash(store).recover()
    assert problems == []
    [face] = faces
    assert face.token != TOKEN  # The recovering editor owns it now.
    assert _snapshots(store.root) == [face.token]
    assert face.document.path is None
    assert face.document.needs_save
    assert face.document.manifest == document.manifest
    assert dict(face.document.assets) == dict(document.assets)


def test_saved_face_recovers_attached_and_undo_returns_to_disk(store, tmp_path):
    document = FaceDocument.from_template(TEMPLATE)
    folder = document.save(tmp_path / "saved")
    document.set_rotation("play", 12, label="Rotate")
    store.write(TOKEN, document)
    [face], _ = _after_crash(store).recover()
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
    [face], _ = _after_crash(store).recover()
    assert face.document.path is None
    assert face.document.manifest["controlRotations"]["play"] == 12


def test_rewrite_replaces_and_remove_deletes_the_snapshot(store):
    document = FaceDocument.from_template(TEMPLATE)
    store.write(TOKEN, document)
    document.set_value(("name",), "Second")
    store.write(TOKEN, document)
    assert _snapshots(store.root) == [TOKEN]
    store.remove(TOKEN)
    assert _after_crash(store).recover() == ([], [])


def test_rewrite_keeps_only_the_latest_snapshot(store):
    document = FaceDocument.from_template(TEMPLATE)
    store.write(TOKEN, document)
    document.set_value(("name",), "Second")
    store.write(TOKEN, document)
    [face], _ = _after_crash(store).recover()
    assert face.document.manifest["name"] == "Second"


def test_a_running_editors_snapshots_are_never_recovered_by_another(store):
    store.write(TOKEN, FaceDocument.from_template(TEMPLATE))
    other = AutosaveStore(store.root)
    try:
        assert other.recover() == ([], [])
        assert _snapshots(store.root) == [TOKEN]
    finally:
        other.close()


def test_only_one_editor_claims_a_crashed_snapshot(store):
    store.write(TOKEN, FaceDocument.from_template(TEMPLATE))
    first = _after_crash(store)
    second = AutosaveStore(store.root)
    try:
        claimed, _ = first.recover()
        assert len(claimed) == 1
        assert second.recover() == ([], [])  # It is first's live work now.
    finally:
        first.close()
        second.close()


def test_unreadable_snapshot_is_reported_and_kept(store):
    document = FaceDocument.from_template(TEMPLATE)
    store.write(TOKEN, document)
    (store.root / TOKEN / "face.json").write_text("{not json")
    faces, problems = _after_crash(store).recover()
    assert faces == []
    assert len(problems) == 1 and problems[0].startswith(TOKEN)
    assert (store.root / TOKEN).is_dir()


@pytest.mark.parametrize("stage", ["moved-aside", "renamed-new"])
def test_an_interrupted_rewrite_still_recovers_a_complete_snapshot(store, stage, monkeypatch):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_value(("name",), "First")
    store.write(TOKEN, document)
    document.set_value(("name",), "Second")
    real_replace = type(store.root).replace
    calls = []

    def crash(path, target):
        calls.append(path.name)
        # Crash before the second rename, or right after renaming ~new.
        if stage == "moved-aside" and len(calls) == 2:
            raise OSError("power lost")
        result = real_replace(path, target)
        if stage == "renamed-new" and len(calls) == 2:
            raise OSError("power lost")
        return result

    monkeypatch.setattr(type(store.root), "replace", crash)
    with pytest.raises(FaceError):
        store.write(TOKEN, document)
    monkeypatch.undo()
    next_editor = _after_crash(store)
    [face], problems = next_editor.recover()
    assert problems == []
    assert face.document.manifest["name"] == "Second"
    assert _snapshots(store.root) == [face.token]
    next_editor.remove(face.token)
    next_editor.close()
    assert list(store.root.iterdir()) == []


def test_an_incomplete_new_snapshot_falls_back_to_the_previous_one(store):
    document = FaceDocument.from_template(TEMPLATE)
    document.set_value(("name",), "Kept")
    store.write(TOKEN, document)
    (store.root / f"{TOKEN}~new").mkdir()  # A write that never finished.
    [face], _ = _after_crash(store).recover()
    assert face.document.manifest["name"] == "Kept"


def test_tokens_are_checked(store):
    with pytest.raises(FaceError):
        store.write("../escape", FaceDocument.from_template(TEMPLATE))


def test_recovery_works_through_a_symlinked_state_folder(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked"
    link.symlink_to(real)
    store = AutosaveStore(link / "autosave")
    store.write(TOKEN, FaceDocument.from_template(TEMPLATE))
    next_editor = _after_crash(store)
    try:
        faces, problems = next_editor.recover()
        assert problems == [] and len(faces) == 1
    finally:
        next_editor.close()


def test_a_claim_left_by_an_editor_that_crashed_while_recovering_is_recovered(store):
    store.write(TOKEN, FaceDocument.from_template(TEMPLATE))
    store.close()
    # The claimer died between its rename and rewriting the snapshot.
    (store.root / TOKEN).rename(store.root / f"{TOKEN}~claim-deadbeef")
    later = AutosaveStore(store.root)
    try:
        [face], problems = later.recover()
        assert problems == []
        assert _snapshots(store.root) == [face.token]
        locks = [path.name for path in store.root.glob(".session-*.lock")]
        assert locks == [f".session-{later._session}.lock"]  # The dead one is gone.
    finally:
        later.close()


def test_a_claim_in_progress_by_a_running_editor_is_left_alone(store):
    store.write(TOKEN, FaceDocument.from_template(TEMPLATE))
    store.close()
    claimer = AutosaveStore(store.root)
    other = AutosaveStore(store.root)
    try:
        claimer.write("ffff", FaceDocument.from_template(TEMPLATE))  # Holds its session.
        session = claimer._session
        (store.root / TOKEN).rename(store.root / f"{TOKEN}~claim-{session}")
        assert other.recover() == ([], [])
        assert (store.root / f"{TOKEN}~claim-{session}").is_dir()
        assert (store.root / "ffff").is_dir()
    finally:
        claimer.close()
        other.close()


def test_checking_a_dead_session_creates_no_lock_file(store):
    from amberfader.face_autosave import _session_alive

    missing = store.root / ".session-0000.lock"
    assert not _session_alive(missing)
    assert not missing.exists()
