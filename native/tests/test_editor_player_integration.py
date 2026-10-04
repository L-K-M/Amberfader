"""Authoring from player menus does not change playback or the installed face."""
import pytest

from amberfader.face_library import FaceLibrary


@pytest.fixture()
def player(qapp, tmp_path):
    from amberfader.ui.main_window import MainWindow

    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    window.show()
    qapp.processEvents()
    yield window, library, sent
    if window._face_editor is not None:
        window._face_editor.hide()
        window._face_editor.deleteLater()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def test_player_editor_uses_copy_and_reuses_visible_window(player, qapp):
    window, library, sent = player
    face_id = window._face_id
    source = library.load(face_id)
    window.open_face_editor()
    editor = window._face_editor
    assert editor is not None and editor.isVisible()
    assert editor.document.path is None
    assert editor.document.manifest["id"] != face_id
    assert editor.document.assets[editor.document.manifest["background"]] == source.background

    editor.document.set_rotation("play", 15)
    window.open_face_editor()
    qapp.processEvents()
    assert window._face_editor is editor
    assert editor.document.manifest["controlRotations"]["play"] == 15
    assert window._face_id == face_id
    assert library.load(face_id).control_rotations == {}
    assert sent == []


def test_picker_edit_copy_respects_unsaved_editor_cancellation(player, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    window, _, sent = player
    window.open_faces()
    picker = window._faces_window
    for index in range(picker._list.count()):
        item = picker._list.item(index)
        if item.data(256) == "viridian":
            picker._list.setCurrentItem(item)
            break
    picker._edit_button.click()
    qapp.processEvents()
    editor = window._face_editor
    assert editor.document.manifest["name"] == "Viridian Custom"
    document = editor.document

    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel,
    )
    window.open_face_editor("aureole")
    assert editor.document is document
    assert window._face_id == "amber-classic"
    assert sent == []
