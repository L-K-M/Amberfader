"""Native editor gestures and file actions remain reversible and data-only."""

from __future__ import annotations

import pytest

from amberfader.face_document import FaceDocument
from amberfader.face_library import BUILTIN_DIRECTORY, load_face


@pytest.fixture()
def editor(qapp):
    from amberfader.ui.face_editor import FaceEditorWindow

    window = FaceEditorWindow()
    # Pointer tests need a canvas near actual size; the offscreen screen is small.
    window.resize(1440, 900)
    window.show()
    qapp.processEvents()
    yield window
    # Teardown cannot open the unsaved-changes prompt of an intentionally unsaved draft.
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def _commit(field, text):
    """Type a value and press Return, as a user commits an inspector field."""
    field.setText(text)
    field.editingFinished.emit()


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
    names = set(editor._sidebar.element_names())
    assert names == {*editor.document.manifest["controls"], "drag"}
    assert editor._canvas.selected == "play"
    assert editor._save_action.isEnabled()
    assert editor.validation_problem is None
    assert not editor._issue.isVisible()
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

    editor._snap_action.setChecked(True)
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
    inspector = editor._inspector.element
    inspector._rotation.setValue(-30)
    assert editor.document.manifest["controlRotations"]["play"] == -30
    assert editor._canvas._item.face.control_rotations["play"] == -30
    editor._canvas.select("title")
    inspector._text_font.setCurrentIndex(inspector._text_font.findData("mono"))
    inspector._text_size.setValue(19)
    inspector._text_align.button("center").click()
    inspector._text_style.button("bold").click()
    assert editor.document.manifest["readoutStyles"]["title"] == {
        "font": "mono",
        "size": 19,
        "align": "center",
        "bold": False,
    }
    assert editor._canvas._item.face.readout_styles["title"]["align"] == "center"
    assert editor._undo_action.text() == "Undo Change Text Style"
    inspector._reset_text.click()
    assert "title" not in editor.document.manifest.get("readoutStyles", {})
    editor._canvas.select("drag")
    assert not inspector._rotation.isEnabled()


def test_invalid_geometry_remains_visible_but_blocks_save_and_recovers_on_undo(
    editor, tmp_path, monkeypatch,
):
    errors = []
    monkeypatch.setattr(editor, "_show_error", lambda title, error: errors.append(str(error)))
    original = editor.document.manifest["controls"]["play"]
    editor._inspector.element._rect_fields[0].setValue(1000)
    assert editor.validation_problem == "play must fit inside the face"
    assert editor._issue.text() == "Can't save: Play / Pause must fit inside the face"
    assert editor._canvas._item.face.controls["play"][0] == 1000
    # Save stays available and explains why it cannot write the face.
    assert editor._save_action.isEnabled()
    assert not editor._save_to(tmp_path / "invalid")
    assert errors == ["play must fit inside the face"]
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor.validation_problem is None


def test_issue_button_selects_the_element_it_names(editor):
    editor._canvas.select("title")
    editor.document.set_rect("play", [1000, 0, 60, 48])
    editor._changed()
    editor._issue.click()
    assert editor._canvas.selected == "play"


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


def test_unedited_copy_switches_and_closes_without_asking(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: pytest.fail("nothing to save"))
    assert not editor.isWindowModified()
    incoming = tmp_path / "incoming"
    FaceDocument.from_template(BUILTIN_DIRECTORY / "viridian").save(incoming)
    assert editor.open_face(incoming)
    assert editor.new_from_template(BUILTIN_DIRECTORY / "viridian")
    assert editor.close()


def test_open_cancel_keeps_dirty_current_document(editor, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    incoming = tmp_path / "incoming"
    FaceDocument.from_template(BUILTIN_DIRECTORY / "viridian").save(incoming)
    original = editor.document
    original.set_rotation("play", 10)
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


def test_close_prompt_names_the_face_and_includes_uncommitted_metadata_text(
    editor, monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    editor._inspector.face._metadata["name"].setText("A name still being typed")
    prompts = []

    def cancel(parent, title, text, *args):
        prompts.append(text)
        return QMessageBox.StandardButton.Cancel

    monkeypatch.setattr(QMessageBox, "warning", cancel)
    assert not editor._confirm_discard()
    assert editor.document.manifest["name"] == "A name still being typed"
    assert prompts == [
        "Do you want to save the changes you made to “A name still being typed”?",
    ]


def test_save_shortcut_commits_metadata_without_requiring_focus_change(editor, tmp_path):
    destination = tmp_path / "saved"
    assert editor._save_to(destination)
    editor._inspector.face._metadata["name"].setText("Shortcut saved")
    assert editor.save()
    assert load_face(destination).info.name == "Shortcut saved"


def _drop_png(editor, filename, scene_point):
    from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(filename))])
    event = QDropEvent(
        QPointF(editor._canvas.mapFromScene(scene_point)),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._canvas.dropEvent(event)
    return event


def test_png_drop_on_a_button_imports_its_normal_sprite(editor, qapp, tmp_path):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage

    image = QImage(60, 48, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.magenta)
    filename = tmp_path / "replacement.png"
    assert image.save(str(filename))
    original = editor.document.assets
    editor._canvas.select("title")
    target = QRectF(*editor.document.manifest["controls"]["next"]).center()
    assert _drop_png(editor, filename, target).isAccepted()
    name = editor.document.manifest["buttons"]["next"]["normal"]
    assert editor.document.assets[name] == filename.read_bytes()
    assert editor._canvas.selected == "next"
    assert editor._undo_action.text() == "Undo Import Artwork"
    editor._undo()
    assert editor.document.assets == original


def test_png_drop_on_readout_changes_background_not_control(editor, tmp_path):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage

    width, height = editor.document.manifest["size"]
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.darkCyan)
    filename = tmp_path / "background.png"
    assert image.save(str(filename))
    target = QRectF(*editor.document.manifest["controls"]["title"]).center()
    assert _drop_png(editor, filename, target).isAccepted()
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
    editor._inspector.face._metadata["name"].setText("Unsaved exported copy")
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
    original.set_rotation("play", 10)
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

    editor._inspector.element._rotation.setValue(30)
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
    editor._inspector.face._face_size[0].setValue(width + 20)
    assert editor._canvas._item.face.size[0] == width + 20
    assert editor.validation_problem == "Background must match the face size at 1x or 2x"


def test_undo_metadata_updates_focused_field_so_save_does_not_reapply_edit(editor, tmp_path):
    original = editor.document.manifest["name"]
    field = editor._inspector.face._metadata["name"]
    field.setFocus()
    _commit(field, "Undo this name")
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

    _commit(editor._inspector.face._metadata["name"], "Previously committed edit")
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
    _commit(editor._inspector.face._metadata["name"], "Abandoned name")
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
    assert moved != original
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


@pytest.mark.parametrize("index", [0, 1])
def test_negative_position_draft_renders_at_same_geometry_as_selection(editor, index):
    original = editor.document.manifest["controls"]["play"]
    editor._inspector.element._rect_fields[index].setValue(-12)
    draft = editor.document.manifest["controls"]["play"]
    assert draft[index] == -12
    assert editor._issue.text() == "Can't save: Play / Pause must fit inside the face"
    assert editor._canvas._item.face.controls["play"] == tuple(draft)
    assert editor._canvas._geometry("play")[0].getRect() == tuple(draft)
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor.validation_problem is None


def test_oversized_draft_control_is_rendered_and_expands_scrollable_scene(editor):
    editor._inspector.element._rect_fields[2].setValue(1500)
    draft = editor.document.manifest["controls"]["play"]
    assert editor._canvas._item.face.controls["play"] == tuple(draft)
    assert editor._canvas._item.boundingRect().right() >= draft[0] + draft[2]
    assert editor._canvas.sceneRect().right() > draft[0] + draft[2]
    assert editor.validation_problem is not None


def test_negative_draft_control_expands_item_bounds_without_changing_face_size(editor):
    face_size = editor._canvas._item.face_rect().size()
    editor._inspector.element._rect_fields[0].setValue(-120)
    assert editor._canvas._item.boundingRect().left() <= -120
    assert editor._canvas.sceneRect().left() < -120
    assert editor._canvas._item.face_rect().size() == face_size
    assert editor.validation_problem is not None


def test_nudges_stop_at_shared_draft_bounds_and_keep_preview_current(editor, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from amberfader.face_library import MAX_DRAFT_GEOMETRY

    editor._inspector.element._rect_fields[0].setValue(MAX_DRAFT_GEOMETRY)
    QTest.keyClick(editor._canvas, Qt.Key.Key_Right, Qt.KeyboardModifier.ShiftModifier)
    draft = editor.document.manifest["controls"]["play"]
    assert draft[0] == MAX_DRAFT_GEOMETRY
    assert editor._canvas._item.face.controls["play"] == tuple(draft)
    editor._inspector.element._rect_fields[1].setValue(-MAX_DRAFT_GEOMETRY)
    QTest.keyClick(editor._canvas, Qt.Key.Key_Up, Qt.KeyboardModifier.ShiftModifier)
    draft = editor.document.manifest["controls"]["play"]
    assert draft[1] == -MAX_DRAFT_GEOMETRY
    assert editor._canvas._item.face.controls["play"] == tuple(draft)
    fields = editor._inspector.element._rect_fields
    assert fields[0].maximum() == fields[2].maximum()


def test_undo_while_typing_undoes_the_typing_first_then_the_document(editor, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    from amberfader.ui.face_inspector import InspectorPane

    original_x = editor.document.manifest["controls"]["play"][0]
    editor._inspector.element._rect_fields[0].setValue(original_x + 1)
    editor._inspector.show_pane(InspectorPane.FACE)
    field = editor._inspector.face._metadata["name"]
    field.setFocus()
    qapp.processEvents()
    committed = field.text()
    QTest.keyClicks(field, " still being typed")
    editor._update_edit_actions()
    assert editor._undo_action.text() == "Undo Typing"
    editor._undo_action.trigger()
    assert field.text() == committed
    assert editor.document.manifest["controls"]["play"][0] == original_x + 1
    assert editor._undo_action.text() == "Undo Move"
    editor._undo_action.trigger()
    assert editor.document.manifest["controls"]["play"][0] == original_x
    assert field.hasFocus()
    # With nothing left to undo, the field releases ⌘Z to the menu.
    QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert editor.document.manifest["controls"]["play"][0] == original_x


@pytest.mark.parametrize("button_name", ["RightButton", "MiddleButton"])
def test_non_left_release_keeps_left_drag_active(editor, qapp, button_name):
    from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
    from PySide6.QtGui import QMouseEvent

    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(5, 0), release=False)
    event = QMouseEvent(
        QEvent.Type.MouseButtonRelease,
        QPointF(editor._canvas.mapFromScene(start)),
        QPointF(editor._canvas.viewport().mapToGlobal(editor._canvas.mapFromScene(start))),
        getattr(Qt.MouseButton, button_name),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    editor._canvas.mouseReleaseEvent(event)
    assert editor._canvas._gesture is not None
    editor._canvas.cancel_gesture()
    assert editor.document.manifest["controls"]["play"] == original
    assert not editor.document.can_undo


def test_replacing_document_with_focused_metadata_keeps_incoming_identity_and_history(
    editor,
    qapp,
    monkeypatch,
):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox

    from amberfader.ui.face_inspector import InspectorPane

    editor._inspector.show_pane(InspectorPane.FACE)
    editor._inspector.face._metadata["name"].setFocus()
    QTest.keyClicks(editor._inspector.face._metadata["name"], " from the old document")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    assert editor.new_from_template(BUILTIN_DIRECTORY / "viridian")
    qapp.processEvents()
    assert editor.document.manifest["name"] == "Viridian Custom"
    assert editor._inspector.face._metadata["name"].text() == "Viridian Custom"
    assert editor._canvas.selected == "play"
    fields = editor._inspector.element._rect_fields
    assert [field.value() for field in fields] == editor.document.manifest["controls"]["play"]
    assert not editor.document.can_undo


def test_save_in_close_prompt_preserves_active_drag_and_pending_metadata(
    editor,
    qapp,
    tmp_path,
    monkeypatch,
):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtWidgets import QMessageBox

    destination = tmp_path / "closing-drag"
    assert editor._save_to(destination)
    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(1, 0), release=False)
    moved = editor.document.manifest["controls"]["play"]
    assert moved != original
    editor._inspector.face._metadata["name"].setText("Pending name at close")
    prompts = []

    def save_choice(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.Save

    monkeypatch.setattr(QMessageBox, "warning", save_choice)
    assert editor._confirm_discard()
    saved = load_face(destination)
    assert len(prompts) == 1
    assert saved.controls["play"] == tuple(moved)
    assert saved.info.name == "Pending name at close"
    assert editor.document.manifest["controls"]["play"] == moved
    assert editor._canvas._gesture is None
    assert not editor.document.dirty


def test_cancel_in_close_prompt_preserves_current_active_drag(editor, qapp, monkeypatch):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtWidgets import QMessageBox

    _commit(editor._inspector.face._metadata["name"], "An earlier committed edit")
    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(1, 0), release=False)
    moved = editor.document.manifest["controls"]["play"]
    assert moved != original
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not editor._confirm_discard()
    assert editor.document.manifest["controls"]["play"] == moved
    assert editor.document.manifest["name"] == "An earlier committed edit"
    assert editor._canvas._gesture is None
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert editor.document.manifest["name"] == "An earlier committed edit"


def test_save_during_active_drag_keeps_numeric_inspector_text_not_yet_committed(
    editor,
    qapp,
    tmp_path,
):
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtTest import QTest

    destination = tmp_path / "drag-numeric-edit"
    assert editor._save_to(destination)
    original = editor.document.manifest["controls"]["play"]
    start = QRectF(*original).center()
    _drag(qapp, editor._canvas, start, start + QPointF(1, 0), release=False)
    field = editor._inspector.element._rect_fields[0]
    field.setFocus()
    field.lineEdit().selectAll()
    QTest.keyClicks(field.lineEdit(), str(original[0] + 3))
    assert field.value() == original[0] + 1
    assert field.lineEdit().text().startswith(str(original[0] + 3))
    assert editor.save()
    assert load_face(destination).controls["play"][0] == original[0] + 3
    assert editor.document.manifest["controls"]["play"][0] == original[0] + 3
    assert editor._canvas._gesture is None


def test_shift_constrains_a_move_to_one_axis(editor, qapp):
    from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest

    canvas = editor._canvas
    original = editor.document.manifest["controls"]["play"]
    start = canvas.mapFromScene(QRectF(*original).center())
    finish = canvas.mapFromScene(QRectF(*original).center() + QPointF(30, 6))
    QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    move = QMouseEvent(
        QEvent.Type.MouseMove, QPointF(finish), QPointF(canvas.viewport().mapToGlobal(finish)),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
    )
    canvas.mouseMoveEvent(move)
    QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=finish)
    moved = editor.document.manifest["controls"]["play"]
    assert moved[1] == original[1]
    assert abs(moved[0] - original[0] - 30) <= 1


def test_held_arrow_key_is_one_undo_step(editor):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    original = editor.document.manifest["controls"]["play"]
    for repeat in (False, True, True, True):
        event = QKeyEvent(
            QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier,
            "", repeat,
        )
        editor._canvas.keyPressEvent(event)
    assert editor.document.manifest["controls"]["play"][0] == original[0] + 4
    assert editor._undo_action.text() == "Undo Move"
    editor._undo()
    assert editor.document.manifest["controls"]["play"] == original
    assert not editor.document.can_undo


def test_delete_key_removes_the_selected_element_with_a_named_undo(editor, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    editor._canvas.setFocus()
    editor._canvas.select("like")
    QTest.keyClick(editor._canvas, Qt.Key.Key_Backspace)
    assert "like" not in editor.document.manifest["controls"]
    assert "like" not in editor._sidebar.element_names()
    assert editor._undo_action.text() == "Undo Remove Like"
    editor._undo()
    assert "like" in editor.document.manifest["controls"]
    editor._canvas.select("drag")
    QTest.keyClick(editor._canvas, Qt.Key.Key_Delete)
    assert editor._canvas.selected == "drag"  # The drag region is required.


def test_space_drag_pans_and_releasing_space_restores_editing(editor):
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QGraphicsView

    canvas = editor._canvas
    press = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
    canvas.keyPressEvent(press)
    assert canvas.dragMode() == QGraphicsView.DragMode.ScrollHandDrag
    release = QKeyEvent(
        QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier,
    )
    canvas.keyReleaseEvent(release)
    assert canvas.dragMode() == QGraphicsView.DragMode.NoDrag


def test_context_menu_targets_the_element_under_the_pointer(editor):
    from PySide6.QtCore import QPoint, QRectF
    from PySide6.QtGui import QContextMenuEvent

    requests = []
    editor._canvas.contextMenuRequested.disconnect()
    editor._canvas.contextMenuRequested.connect(lambda name, _pos: requests.append(name))
    center = editor._canvas.mapFromScene(
        QRectF(*editor.document.manifest["controls"]["next"]).center(),
    )
    editor._canvas.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, center, QPoint(0, 0)),
    )
    editor._canvas.contextMenuEvent(
        QContextMenuEvent(QContextMenuEvent.Reason.Mouse, QPoint(2, 2), QPoint(0, 0)),
    )
    assert requests == ["next", ""]
    assert editor._canvas.selected == "next"


def test_dragging_a_png_highlights_what_it_will_replace(editor, tmp_path):
    from PySide6.QtCore import QMimeData, QRectF, Qt, QUrl
    from PySide6.QtGui import QDragMoveEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(tmp_path / "art.png"))])

    def move_over(name):
        point = editor._canvas.mapFromScene(
            QRectF(*editor.document.manifest["controls"][name]).center(),
        )
        event = QDragMoveEvent(
            point, Qt.DropAction.CopyAction, mime, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        editor._canvas.dragMoveEvent(event)
        return event

    assert move_over("play").isAccepted()
    assert editor._canvas._drop_target == "play"
    move_over("title")
    assert editor._canvas._drop_target == ""  # Screen text takes no artwork: background.
    editor._canvas.dragLeaveEvent(None)
    assert editor._canvas._drop_target is None


def test_zoom_steps_through_standard_percentages(editor):
    editor._canvas.set_zoom(1)
    editor._zoom_in_action.trigger()
    assert editor._canvas.zoom == pytest.approx(1.25)
    assert editor._zoom_button_action.text() == "125%"
    editor._zoom_out_action.trigger()
    editor._zoom_out_action.trigger()
    assert editor._canvas.zoom == pytest.approx(0.75)


def test_edit_commands_follow_keyboard_focus(editor, qapp):
    from amberfader.ui.face_inspector import InspectorPane

    editor._canvas.setFocus()
    qapp.processEvents()
    editor._update_edit_actions()
    assert editor._delete_action.isEnabled()
    assert not editor._copy_action.isEnabled()
    assert not editor._select_all_action.isEnabled()

    editor._inspector.show_pane(InspectorPane.FACE)
    field = editor._inspector.face._metadata["name"]
    field.setFocus()
    qapp.processEvents()
    field.selectAll()
    assert editor._cut_action.isEnabled() and editor._copy_action.isEnabled()
    assert editor._select_all_action.isEnabled()
    editor._delete_action.trigger()
    assert field.text() == ""
    assert editor.document.manifest["name"] != ""  # Deleting text is not a document edit.


def test_zoomed_canvas_pans_with_scrolling_and_fitting_is_stable(editor, qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    canvas = editor._canvas
    canvas.set_zoom(3)
    before = canvas.horizontalScrollBar().value()
    event = QWheelEvent(
        QPointF(20, 20), QPointF(canvas.viewport().mapToGlobal(QPoint(20, 20))),
        QPoint(-60, 0), QPoint(-120, 0), Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    canvas.wheelEvent(event)
    assert canvas.horizontalScrollBar().value() != before
    # Hiding a panel refits once; the view never toggles scroll bars and refits again.
    canvas.fit_face()
    zooms = []
    canvas.zoomChanged.connect(zooms.append)
    editor._toggle_sidebar()
    qapp.processEvents()
    editor._toggle_inspector()
    qapp.processEvents()
    assert 1 <= len(zooms) <= 4
    assert not canvas.horizontalScrollBar().isVisible()
