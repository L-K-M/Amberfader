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
    assert [menu.title() for menu in menus] == [
        "&File", "&Edit", "&View", "E&lement", "F&ace", "&Window", "&Help",
    ]
    file_menu, edit_menu, view_menu = menus[:3]
    toolbar = editor.findChild(QToolBar)
    for action in (editor._new_action, editor._open_action, editor._save_action):
        assert action in file_menu.actions()
    for action in (
        editor._toggle_sidebar_action, editor._toggle_inspector_action, editor._snap_action,
        editor._guides_action, editor._add_element_action,
    ):
        assert action in toolbar.actions()
    for action in (editor._toggle_sidebar_action, editor._snap_action, editor._fit_action):
        assert action in view_menu.actions()
    for action in (editor._undo_action, editor._redo_action):
        assert action in edit_menu.actions()
    assert not editor._undo_action.isEnabled()
    assert not editor._redo_action.isEnabled()

    original_name = editor.document.manifest["name"]
    editor.document.set_value(("name",), "Edited through shared menu actions", label="Change Name")
    editor._changed()
    assert editor._undo_action.isEnabled()
    assert editor._undo_action.text() == "Undo Change Name"
    assert not editor._redo_action.isEnabled()

    edit_menu.actions()[0].trigger()
    assert editor.document.manifest["name"] == original_name
    assert not editor._undo_action.isEnabled()
    assert editor._redo_action.isEnabled()
    assert editor._redo_action.text() == "Redo Change Name"

    edit_menu.actions()[1].trigger()
    assert editor.document.manifest["name"] == "Edited through shared menu actions"
    assert editor._undo_action.isEnabled()
    assert not editor._redo_action.isEnabled()

    editor._canvas.set_zoom(2)
    editor._actual_action.trigger()
    assert editor._canvas.transform().m11() == 1


def test_standard_shortcuts_follow_mac_conventions(editor):
    from PySide6.QtGui import QKeySequence

    shortcuts = {
        editor._new_action: QKeySequence.StandardKey.New,
        editor._open_action: QKeySequence.StandardKey.Open,
        editor._close_action: QKeySequence.StandardKey.Close,
        editor._save_action: QKeySequence.StandardKey.Save,
        editor._save_as_action: QKeySequence.StandardKey.SaveAs,
        editor._undo_action: QKeySequence.StandardKey.Undo,
        editor._redo_action: QKeySequence.StandardKey.Redo,
        editor._select_all_action: QKeySequence.StandardKey.SelectAll,
    }
    for action, standard in shortcuts.items():
        assert action.shortcut() in QKeySequence.keyBindings(standard), action.text()
    assert editor._actual_action.shortcut() == QKeySequence("Ctrl+0")
    assert editor._fit_action.shortcut() == QKeySequence("Ctrl+9")
    assert editor._toggle_sidebar_action.shortcut() == QKeySequence("Ctrl+Meta+S")
    assert editor._toggle_inspector_action.shortcut() == QKeySequence("Ctrl+Alt+I")
    # No bare letter shortcuts: typing in a field must never trigger a command.
    for action in editor.actions():
        for shortcut in action.shortcuts():
            assert shortcut.toString().count("+") or not shortcut.toString(), action.text()


def test_view_toggles_rename_themselves_like_mac_menus(editor):
    assert editor._toggle_sidebar_action.text() == "Hide Sidebar"
    editor._toggle_sidebar_action.trigger()
    assert not editor._sidebar.isVisible()
    assert editor._toggle_sidebar_action.text() == "Show Sidebar"
    editor._toggle_sidebar_action.trigger()
    assert editor._sidebar.isVisible()
    editor._face_pane_action.trigger()
    from amberfader.ui.face_inspector import InspectorPane

    assert editor._inspector.pane is InspectorPane.FACE
