"""The standalone editor manages one window per face, like a Mac document app."""
from __future__ import annotations

import pytest

from amberfader.face_autosave import AutosaveStore
from amberfader.face_document import FaceDocument
from amberfader.face_library import BUILTIN_DIRECTORY, FaceLibrary


@pytest.fixture()
def saved_face(tmp_path):
    document = FaceDocument.from_template(BUILTIN_DIRECTORY / "viridian", name="Saved Viridian")
    return document.save(tmp_path / "Saved Viridian")


@pytest.fixture()
def make_editor(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from amberfader.ui.editor_application import FaceEditorApplication
    from amberfader.ui.editor_settings import EditorSettings

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    created = []

    def make():
        editor = FaceEditorApplication(
            qapp,
            library=FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json"),
            settings=EditorSettings(tmp_path / "editor.ini"),
            autosave=AutosaveStore(tmp_path / "autosave"),
        )
        created.append(editor)
        return editor

    yield make
    for editor in created:
        for window in list(editor._windows):
            window.close()
        if editor._gallery is not None:
            editor._gallery.close()
            editor._gallery.deleteLater()
        editor.setParent(None)
        editor.deleteLater()
    qapp.processEvents()


def _create(editor, template="amber-classic"):
    gallery = editor._gallery
    editor._create_from_template(BUILTIN_DIRECTORY / template)
    return gallery


def test_launch_shows_the_gallery_and_a_template_opens_a_window(make_editor):
    editor = make_editor()
    editor.start([])
    assert editor._gallery.isVisible()
    assert editor.windows() == []
    _create(editor)
    [window] = editor.windows()
    assert window.document.path is None
    assert not editor._gallery.isVisible()


def test_untouched_untitled_window_is_reused_for_the_next_face(make_editor, saved_face):
    editor = make_editor()
    editor.start([])
    _create(editor)
    [window] = editor.windows()
    assert editor.open_face(saved_face, window)
    assert editor.windows() == [window]
    assert window.document.path == saved_face


def test_edited_window_is_kept_and_the_face_opens_beside_it(make_editor, saved_face):
    editor = make_editor()
    editor.start([])
    _create(editor)
    [window] = editor.windows()
    window.document.set_rotation("play", 5)
    window._changed()
    assert editor.open_face(saved_face, window)
    assert len(editor.windows()) == 2
    assert window.document.manifest["controlRotations"]["play"] == 5


def test_opening_an_open_face_brings_its_window_forward(make_editor, saved_face):
    editor = make_editor()
    editor.start([FaceDocument.open(saved_face)])
    assert len(editor.windows()) == 1
    assert editor.open_face(saved_face / "face.json", None)
    assert len(editor.windows()) == 1


def test_recent_faces_follow_opens_and_feed_every_menu(make_editor, saved_face):
    editor = make_editor()
    editor.start([])
    _create(editor)
    [window] = editor.windows()
    editor.open_face(saved_face, None)
    assert editor.recent_faces() == [saved_face]
    titles = [action.text() for action in window._recent_menu.actions()]
    assert titles[0] == "Saved Viridian"
    assert titles[-1] == "Clear Menu"
    editor.clear_recent()
    assert editor.recent_faces() == []
    assert [action.text() for action in window._recent_menu.actions()] == ["Clear Menu"]


def test_finder_file_open_event_opens_the_face_and_closes_the_launch_gallery(
    make_editor, saved_face, qapp,
):
    from PySide6.QtGui import QFileOpenEvent

    editor = make_editor()
    editor.start([])
    assert editor._gallery.isVisible()
    qapp.sendEvent(qapp, QFileOpenEvent(str(saved_face)))
    [window] = editor.windows()
    assert window.document.path == saved_face
    assert not editor._gallery.isVisible()


def test_unsaved_work_is_autosaved_and_recovered_after_a_crash(make_editor, saved_face):
    editor = make_editor()
    editor.start([FaceDocument.open(saved_face)])
    [window] = editor.windows()
    window.document.set_rotation("play", 21, label="Rotate")
    window._changed()
    editor.autosave_now()
    assert (editor._autosave.root / window.autosave_token).is_dir()
    # While this editor runs, another one leaves its work alone.
    bystander = make_editor()
    bystander.start([])
    assert bystander.windows() == []

    # A second process after a crash: the window returns, attached to its folder.
    editor._autosave.close()  # The crashed editor's session ends.
    recovered = make_editor()
    recovered.start([])
    [again] = recovered.windows()
    assert again.document.path == saved_face
    assert again.document.manifest["controlRotations"]["play"] == 21
    assert again._undo_action.text() == "Undo Recover Changes"
    assert (recovered._autosave.root / again.autosave_token).is_dir()
    assert not (recovered._autosave.root / window.autosave_token).exists()
    assert recovered._gallery is None

    # Discarding the recovered work removes its snapshot.
    again.close()
    assert not (recovered._autosave.root / again.autosave_token).exists()


def test_saving_removes_the_autosave(make_editor, saved_face):
    editor = make_editor()
    editor.start([FaceDocument.open(saved_face)])
    [window] = editor.windows()
    window.document.set_rotation("play", 3)
    window._changed()
    editor.autosave_now()
    assert window.save()
    editor.autosave_now()
    assert not (editor._autosave.root / window.autosave_token).exists()


def test_dock_reopen_shows_the_gallery_when_no_window_is_open(make_editor, monkeypatch):
    from PySide6.QtCore import Qt

    from amberfader.ui import editor_application

    editor = make_editor()
    # Only the reopen rule is macOS-specific; the Dock menu needs real macOS.
    monkeypatch.setattr(editor_application, "MACOS", True)
    editor._state = Qt.ApplicationState.ApplicationActive
    editor._state_changed(Qt.ApplicationState.ApplicationActive)
    assert editor._gallery is not None and editor._gallery.isVisible()


def test_a_recovered_face_is_not_opened_twice_from_the_command_line(make_editor, saved_face):
    editor = make_editor()
    editor.start([FaceDocument.open(saved_face)])
    [window] = editor.windows()
    window.document.set_rotation("play", 4)
    window._changed()
    editor.autosave_now()
    editor._autosave.close()
    recovered = make_editor()
    recovered.start([FaceDocument.open(saved_face)])
    [again] = recovered.windows()
    assert again.document.manifest["controlRotations"]["play"] == 4


def test_quitting_remembers_open_faces_for_window_restoration(
    make_editor, saved_face, qapp, monkeypatch,
):
    from PySide6.QtCore import QEvent

    from amberfader.ui import editor_application

    editor = make_editor()
    editor.start([FaceDocument.open(saved_face)])
    _create(editor)  # Untitled windows have nothing to reopen.
    # The app's filter sees Quit before any window closes.
    assert editor.eventFilter(qapp, QEvent(QEvent.Type.Quit)) is False
    assert editor._settings.session_faces() == [saved_face]

    for window in list(editor._windows):
        window.close()
    monkeypatch.setattr(editor_application, "_system_keeps_windows", lambda: True)
    restored = make_editor()
    restored._settings = editor._settings
    restored.start([])
    assert [window.document.path for window in restored.windows()] == [saved_face]
    assert restored._gallery is None


def test_continuous_editing_does_not_postpone_the_autosave(make_editor, saved_face):
    import time

    editor = make_editor()
    editor.start([FaceDocument.open(saved_face)])
    [window] = editor.windows()
    window.document.set_rotation("play", 1)
    window._changed()
    first_deadline = editor._autosave_timer.remainingTime()
    time.sleep(0.05)
    window.document.set_rotation("play", 2)
    window._changed()
    assert editor._autosave_timer.isActive()
    assert editor._autosave_timer.remainingTime() < first_deadline


def test_the_editor_inside_the_player_leaves_quit_to_the_player(qapp, make_editor):
    from PySide6.QtGui import QKeySequence

    from amberfader.ui.face_editor import FaceEditorWindow

    embedded = FaceEditorWindow()
    try:
        assert embedded._quit_action.shortcut().isEmpty()
        assert embedded._about_action not in embedded.menuBar().actions()[-1].menu().actions()
    finally:
        embedded.deleteLater()
    editor = make_editor()
    editor.start([FaceDocument.from_template(BUILTIN_DIRECTORY / "viridian")])
    [standalone] = editor.windows()
    assert standalone._quit_action.shortcut() == QKeySequence("Ctrl+Q")
