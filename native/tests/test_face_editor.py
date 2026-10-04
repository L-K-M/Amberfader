"""Native editor gestures and file actions remain reversible and data-only."""

from __future__ import annotations

import pytest

from amberfader.face_document import FaceDocument
from amberfader.face_library import BUILTIN_DIRECTORY, load_face


@pytest.fixture()
def editor(qapp):
    from amberfader.ui.face_editor import FaceEditorWindow

    window = FaceEditorWindow()
    window.show()
    qapp.processEvents()
    yield window
    # Teardown cannot open the unsaved-changes prompt of an intentionally unsaved draft.
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def _drag(qapp, canvas, start, finish, *, release=True, modifiers=None):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    modifiers = modifiers or Qt.KeyboardModifier.NoModifier
    start, finish = canvas.mapFromScene(start), canvas.mapFromScene(finish)
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, modifiers, start)
    QTest.mouseMove(canvas.viewport(), finish)
    qapp.processEvents()
    if release:
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, modifiers, finish)
        qapp.processEvents()


def test_editor_lists_semantic_controls_and_previews_without_player_commands(editor):
    names = {editor._layers.item(index).data(256) for index in range(editor._layers.count())}
    assert names == {*editor.document.manifest["controls"], "drag"}
    assert editor._canvas.selected == "play"
    assert editor._save_action.isEnabled()
    assert "Ready to save" in editor._validation.text()
    assert editor._canvas._item.face.info.id.startswith("amber-classic-custom-")
    assert editor._canvas._item.artwork.background.size().width() > 0


def test_drag_move_is_one_undo_action_and_redo_restores_final_position(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtTest import QTest

    canvas, document = editor._canvas, editor.document
    original = document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    finish = start + QPointF(17, 9)
    _drag(qapp, canvas, start, finish, release=False)
    QTest.mouseMove(canvas.viewport(), canvas.mapFromScene(start + QPointF(25, 12)))
    QTest.mouseRelease(
        canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        canvas.mapFromScene(start + QPointF(25, 12)),
    )
    qapp.processEvents()
    changed = document.manifest["controls"]["play"]
    assert abs(changed[0] - original[0] - 25) <= 1
    assert abs(changed[1] - original[1] - 12) <= 1
    assert changed[2:] == original[2:]
    assert document.can_undo
    editor._undo()
    assert document.manifest["controls"]["play"] == original
    assert not document.can_undo
    editor._redo()
    assert document.manifest["controls"]["play"] == changed


def test_escape_cancels_an_active_gesture_without_recording_it(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtTest import QTest

    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(40, 30), release=False)
    assert editor.document.manifest["controls"]["play"] != original
    QTest.keyClick(editor._canvas, Qt.Key.Key_Escape)
    assert editor.document.manifest["controls"]["play"] == original
    assert not editor.document.can_undo
    assert editor._canvas._gesture is None


def test_drag_resize_changes_bounds_and_undo_restores_them(editor, qapp):
    from PySide6.QtCore import QPointF

    original = editor.document.manifest["controls"]["play"]
    corner = editor._canvas._handles()[0][2]
    _drag(qapp, editor._canvas, corner, corner + QPointF(16, 8))
    resized = editor.document.manifest["controls"]["play"]
    assert resized[:2] == original[:2]
    assert abs(resized[2] - original[2] - 16) <= 1
    assert abs(resized[3] - original[3] - 8) <= 1
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original


def test_rotation_handle_updates_angle_while_preserving_logical_rectangle(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF

    original = editor.document.manifest["controls"]["play"]
    center = QRectF(*original).center()
    rotation = editor._canvas._handles()[1]
    radius = center.y() - rotation.y()
    _drag(qapp, editor._canvas, rotation, center + QPointF(radius, 0))
    degrees = editor.document.manifest["controlRotations"]["play"]
    assert 89 <= degrees <= 91
    assert editor.document.manifest["controls"]["play"] == original
    editor._undo()
    assert "play" not in editor.document.manifest.get("controlRotations", {})


def test_snap_move_and_keyboard_nudges_use_face_coordinates(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtTest import QTest

    editor._snap.setChecked(True)
    canvas, document = editor._canvas, editor.document
    original = document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, canvas, start, start + QPointF(13, 7))
    moved = document.manifest["controls"]["play"]
    assert moved[0] % 8 == 0 and moved[1] % 8 == 0
    QTest.keyClick(canvas, Qt.Key.Key_Right)
    assert document.manifest["controls"]["play"][0] == moved[0] + 1
    QTest.keyClick(canvas, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
    assert document.manifest["controls"]["play"][1] == moved[1] + 10


def test_inspector_rotation_typography_and_reset_update_preview(editor):
    editor._rotation.setValue(-30)
    assert editor.document.manifest["controlRotations"]["play"] == -30
    assert editor._canvas._item.face.control_rotations["play"] == -30
    editor._canvas.select("title")
    editor._text_font.setCurrentText("mono")
    editor._text_size.setValue(19)
    editor._text_align.setCurrentText("center")
    editor._text_bold.setChecked(False)
    assert editor.document.manifest["readoutStyles"]["title"] == {
        "font": "mono",
        "size": 19,
        "align": "center",
        "bold": False,
    }
    assert editor._canvas._item.face.readout_styles["title"]["align"] == "center"
    editor._reset_readout()
    assert "title" not in editor.document.manifest.get("readoutStyles", {})
    editor._canvas.select("drag")
    assert not editor._rotation.isEnabled()


def test_invalid_geometry_remains_visible_but_blocks_save_and_recovers_on_undo(editor):
    original = editor.document.manifest["controls"]["play"]
    editor._rect_fields[0].setValue(1000)
    assert "Cannot save yet" in editor._validation.text()
    assert not editor._save_action.isEnabled()
    assert not editor._save_as_action.isEnabled()
    assert editor._canvas._item.face.controls["play"][0] == 1000
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor._save_action.isEnabled()


def test_save_as_writes_portable_pack_and_open_preserves_it(editor, tmp_path):
    destination = tmp_path / "my-face"
    assert editor._save_to(destination)
    assert editor.document.path == destination
    assert not editor.document.dirty
    face = load_face(destination)
    assert face.info.id == editor.document.manifest["id"]
    reopened = FaceDocument.open(destination)
    assert reopened.manifest == editor.document.manifest
    assert dict(reopened.assets) == dict(editor.document.assets)


def test_open_cancel_keeps_dirty_current_document(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    incoming = tmp_path / "incoming"
    FaceDocument.from_template(BUILTIN_DIRECTORY / "viridian").save(incoming)
    original = editor.document
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not editor.open_face(incoming)
    assert editor.document is original
    assert editor.document.dirty


def test_open_builtin_clones_instead_of_editing_installed_assets(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    assert editor.open_face(BUILTIN_DIRECTORY / "viridian")
    assert editor.document.path is None
    assert editor.document.manifest["id"].startswith("viridian-custom-")


def test_close_prompt_includes_uncommitted_metadata_text(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    editor._metadata["name"].setText("A name still being typed")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not editor._confirm_discard()
    assert editor.document.manifest["name"] == "A name still being typed"


def test_save_shortcut_commits_metadata_without_requiring_focus_change(editor, tmp_path):
    destination = tmp_path / "saved"
    assert editor._save_to(destination)
    editor._metadata["name"].setText("Shortcut saved")
    assert editor.save()
    assert load_face(destination).info.name == "Shortcut saved"


def test_png_drop_imports_selected_button_normal_sprite(editor, qapp, tmp_path):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent, QImage

    image = QImage(60, 48, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.magenta)
    filename = tmp_path / "replacement.png"
    assert image.save(str(filename))
    original = editor.document.assets
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(filename))])
    event = QDropEvent(
        QPointF(12, 12),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._canvas.dropEvent(event)
    assert event.isAccepted()
    name = editor.document.manifest["buttons"]["play"]["normal"]
    assert editor.document.assets[name] == filename.read_bytes()
    editor._undo()
    assert editor.document.assets == original


def test_png_drop_on_readout_changes_background_not_control(editor, tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    width, height = editor.document.manifest["size"]
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.darkCyan)
    filename = tmp_path / "background.png"
    assert image.save(str(filename))
    editor._canvas.select("title")
    editor._drop_image(str(filename), "title")
    manifest = editor.document.manifest
    assert editor.document.assets[manifest["background"]] == filename.read_bytes()
    assert "title" not in manifest.get("buttons", {})


def test_failed_open_keeps_current_document_and_reports_problem(editor, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(editor, "_show_error", lambda title, error: errors.append(str(error)))
    original = editor.document
    assert not editor.open_face(tmp_path / "missing")
    assert editor.document is original
    assert errors


def test_invalid_pack_cannot_be_saved_via_programmatic_action(editor, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(editor, "_show_error", lambda title, error: errors.append(str(error)))
    editor.document.set_rect("play", [1000, 0, 60, 48])
    editor._changed()
    assert not editor._save_to(tmp_path / "invalid")
    assert not (tmp_path / "invalid").exists()
    assert errors


def test_canvas_zoom_and_fit_keep_elements_in_logical_coordinates(editor):
    before = editor.document.manifest["controls"]
    editor._canvas.set_zoom(2)
    assert editor._canvas.zoom == pytest.approx(2)
    editor._canvas.fit_face()
    assert 0 < editor._canvas.zoom < 4
    assert editor.document.manifest["controls"] == before


def test_export_keeps_working_path_and_unsaved_changes(editor, tmp_path, monkeypatch):
    working = tmp_path / "working"
    exported = tmp_path / "exported"
    assert editor._save_to(working)
    editor._metadata["name"].setText("Unsaved exported copy")
    monkeypatch.setattr(editor, "_destination_folder", lambda caption: exported)
    assert editor.export()
    assert editor.document.path == working
    assert editor.document.dirty
    assert load_face(exported).info.name == "Unsaved exported copy"
    assert load_face(working).info.name != "Unsaved exported copy"
    assert editor._export_action.isEnabled()


def test_cancelled_save_as_preserves_document(editor, monkeypatch):
    monkeypatch.setattr(editor, "_destination_folder", lambda caption: None)
    original = editor.document
    assert not editor.save_as()
    assert editor.document is original
    assert editor.document.path is None
    assert editor.document.dirty


def test_new_template_clones_installed_face_and_preserves_original(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    source = tmp_path / "source"
    FaceDocument.from_template(BUILTIN_DIRECTORY / "viridian").save(source)
    original_id = load_face(source).info.id
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    assert editor.new_from_template(source)
    assert editor.document.path is None
    assert editor.document.manifest["id"] != original_id
    assert load_face(source).info.id == original_id
    assert editor.document.dirty


def test_cancel_new_template_keeps_existing_edits(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    original = editor.document
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not editor.new_from_template(BUILTIN_DIRECTORY / "viridian")
    assert editor.document is original


def test_new_template_error_does_not_replace_current_document(editor, tmp_path, monkeypatch):
    errors = []
    monkeypatch.setattr(editor, "_show_error", lambda title, error: errors.append(str(error)))
    original = editor.document
    assert not editor.new_from_template(tmp_path / "missing")
    assert editor.document is original
    assert errors


def test_resize_corner_cannot_flip_through_opposite_corner(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF

    original = editor.document.manifest["controls"]["play"]
    region = QRectF(*original)
    _drag(qapp, editor._canvas, region.bottomRight(), region.topLeft() - QPointF(15, 15))
    resized = editor.document.manifest["controls"]["play"]
    assert resized[:2] == original[:2]
    assert resized[2:] == [1, 1]


def test_resizing_rotated_control_preserves_opposite_corner(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QTransform

    from amberfader.ui.face_editor_canvas import _control_transform

    editor._rotation.setValue(30)
    original = editor.document.manifest["controls"]["play"]
    region = QRectF(*original)
    transform = _control_transform(region, 30)
    fixed = transform.map(region.topLeft())
    move = QTransform().rotate(30).map(QPointF(18, 10))
    _drag(
        qapp,
        editor._canvas,
        transform.map(region.bottomRight()),
        transform.map(region.bottomRight()) + move,
    )
    resized = QRectF(*editor.document.manifest["controls"]["play"])
    corner = _control_transform(resized, 30).map(resized.topLeft())
    assert abs(corner.x() - fixed.x()) <= 1
    assert abs(corner.y() - fixed.y()) <= 1
    assert resized.width() > region.width()
    assert resized.height() > region.height()


def test_background_size_draft_updates_canvas_and_blocks_save(editor):
    width = editor.document.manifest["size"][0]
    editor._face_size[0].setValue(width + 20)
    assert editor._canvas._item.face.size[0] == width + 20
    assert "Cannot save yet" in editor._validation.text()
    assert not editor._save_action.isEnabled()


def test_undo_metadata_updates_focused_field_so_save_does_not_reapply_edit(editor, tmp_path):
    original = editor.document.manifest["name"]
    field = editor._metadata["name"]
    field.setFocus()
    field.setText("Undo this name")
    editor._edit_metadata("name")
    assert editor.document.manifest["name"] == "Undo this name"
    editor._undo()
    assert field.text() == original
    assert editor._save_to(tmp_path / "undone")
    assert editor.save()
    assert load_face(tmp_path / "undone").info.name == original


def test_changing_selection_cancels_active_drag_without_retargeting_its_geometry(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtTest import QTest

    original = editor.document.manifest["controls"]
    start = QRectF(*original["play"]).center()
    _drag(qapp, editor._canvas, start, start + QPointF(15, 5), release=False)
    assert editor.document.manifest["controls"]["play"] != original["play"]
    editor._canvas.select("title")
    QTest.mouseMove(editor._canvas.viewport(), editor._canvas.mapFromScene(start + QPointF(40, 20)))
    QTest.mouseRelease(
        editor._canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        editor._canvas.mapFromScene(start),
    )
    qapp.processEvents()
    assert editor.document.manifest["controls"] == original
    assert editor._canvas.selected == "title"
    assert editor._canvas._gesture is None
    assert not editor.document.can_undo


def test_undo_active_drag_reverts_only_drag_and_redo_restores_it(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtTest import QTest

    editor._metadata["name"].setText("Previously committed edit")
    editor._edit_metadata("name")
    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(18, 9), release=False)
    moved = editor.document.manifest["controls"]["play"]
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor.document.manifest["name"] == "Previously committed edit"
    assert editor._canvas._gesture is None
    editor._redo()
    assert editor.document.manifest["controls"]["play"] == moved
    assert editor.document.manifest["name"] == "Previously committed edit"
    # Releasing the old pointer press cannot replay the canceled gesture.
    QTest.mouseRelease(
        editor._canvas.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        editor._canvas.mapFromScene(start),
    )
    qapp.processEvents()
    assert editor.document.manifest["controls"]["play"] == moved


def test_undo_is_enabled_during_first_changed_drag(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF

    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(15, 5), release=False)
    assert editor._undo_action.isEnabled()
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor.document.can_redo


def test_new_active_drag_disables_redo_and_cannot_reapply_abandoned_edit(editor, qapp):
    from PySide6.QtCore import QPointF, QRectF

    original_name = editor.document.manifest["name"]
    editor._metadata["name"].setText("Abandoned name")
    editor._edit_metadata("name")
    editor._undo()
    assert editor.document.can_redo
    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(8, 3), release=False)
    moved = editor.document.manifest["controls"]["play"]
    assert not editor._redo_action.isEnabled()
    editor._redo()
    assert editor.document.manifest["name"] == original_name
    assert editor.document.manifest["controls"]["play"] == moved
    assert editor._canvas._gesture is None


def test_saving_active_drag_finishes_it_before_saved_checkpoint(editor, qapp, tmp_path):
    from PySide6.QtCore import QPointF, QRectF

    destination = tmp_path / "held-drag"
    assert editor._save_to(destination)
    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(1, 0), release=False)
    moved = editor.document.manifest["controls"]["play"]
    assert editor.save()
    assert editor._canvas._gesture is None
    assert not editor.document.dirty
    assert load_face(destination).controls["play"] == tuple(moved)
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor.document.dirty
    editor._redo()
    assert editor.document.manifest["controls"]["play"] == moved
    assert not editor.document.dirty
