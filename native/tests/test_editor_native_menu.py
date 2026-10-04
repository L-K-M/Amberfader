"""Native menu preference and editor action wiring, independent of desktop export."""

from __future__ import annotations

import pytest


@pytest.fixture()
def editor(qapp):
    from amberfader.ui.face_editor import FaceEditorWindow

    window = FaceEditorWindow()
    window.show()
    qapp.processEvents()
    yield window
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def test_editor_explicitly_requests_native_menus(qapp, monkeypatch):
    from PySide6.QtWidgets import QMenuBar

    from amberfader.ui.face_editor import FaceEditorWindow

    requests = []
    original = QMenuBar.setNativeMenuBar

    def record_request(menu_bar, enabled):
        requests.append((menu_bar, enabled))
        original(menu_bar, enabled)

    monkeypatch.setattr(QMenuBar, "setNativeMenuBar", record_request)
    window = FaceEditorWindow()
    try:
        # Offscreen Qt has no native exporter. Assert the requested preference,
        # rather than claiming that this platform exported a global menu.
        assert requests == [(window.menuBar(), True)]
    finally:
        window.deleteLater()
        qapp.processEvents()


def test_native_editor_menus_share_toolbar_actions_and_undo_state(editor):
    from PySide6.QtWidgets import QToolBar

    menus = [action.menu() for action in editor.menuBar().actions()]
    assert [menu.title() for menu in menus] == ["&File", "&Edit", "&View"]
    file_menu, edit_menu, view_menu = menus
    toolbar = editor.findChild(QToolBar)
    for action in (editor._new_action, editor._open_action, editor._save_action):
        assert action in file_menu.actions()
        assert action in toolbar.actions()
    for action in (editor._undo_action, editor._redo_action):
        assert action in edit_menu.actions()
        assert action in toolbar.actions()
    assert editor._fit_action in view_menu.actions()
    assert editor._fit_action in toolbar.actions()
    assert not editor._undo_action.isEnabled()
    assert not editor._redo_action.isEnabled()

    original_name = editor.document.manifest["name"]
    editor.document.set_value(("name",), "Edited through shared menu actions")
    editor._changed()
    assert editor._undo_action.isEnabled()
    assert not editor._redo_action.isEnabled()

    edit_menu.actions()[0].trigger()
    assert editor.document.manifest["name"] == original_name
    assert not editor._undo_action.isEnabled()
    assert editor._redo_action.isEnabled()

    edit_menu.actions()[1].trigger()
    assert editor.document.manifest["name"] == "Edited through shared menu actions"
    assert editor._undo_action.isEnabled()
    assert not editor._redo_action.isEnabled()

    editor._canvas.set_zoom(2)
    view_menu.actions()[1].trigger()
    assert editor._canvas.transform().m11() == 1
