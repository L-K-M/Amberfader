"""Audion imports remain previewable, editable and independent of playback."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

from amberfader.face_document import FaceDocument
from amberfader.face_library import BUILTIN_DIRECTORY, DEFAULT_FACE_ID


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


def _imported_document():
    template = FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
    manifest = template.manifest
    manifest["formatVersion"] = 3
    manifest["controls"] = {"title": manifest["controls"]["title"]}
    manifest["sourceCredit"] = "Original face: <FishFace>\nAuthor: Rob Gentle"
    return FaceDocument.from_snapshot(manifest, template.assets)


def test_editor_file_menu_offers_audion_import(editor):
    file_menu = editor.menuBar().actions()[0].menu()
    texts = [action.text() for action in file_menu.actions()]
    assert "Import Audion Face…" in texts
    assert "Import Audion Collection…" in texts


def test_sparse_import_can_select_add_remove_and_undo_elements(editor, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    document = _imported_document()
    result = SimpleNamespace(document=document, warnings=("Some controls were omitted.",))
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    assert editor.import_audion_result(result)
    assert editor.document is document and document.path is None and document.dirty
    assert editor._canvas.selected == "title"
    assert editor._sidebar.element_names() == ["title", "drag"]
    credits = editor._inspector.face._source_credit
    assert credits.toPlainText() == document.manifest["sourceCredit"]
    assert editor._canvas._item.face.controls.keys() == {"title"}

    editor._fill_add_menu()
    labels = [action.text() for action in editor._add_menu.actions() if not action.isSeparator()]
    assert "Play / Pause" in labels and "Track Title" not in labels
    actions = editor._add_menu.actions()
    next(action for action in actions if action.text() == "Play / Pause").trigger()
    assert editor._canvas.selected == "play"
    assert editor._undo_action.text() == "Undo Add Play / Pause"
    assert "play" in document.manifest["controls"]
    editor._remove_element()
    assert "play" not in document.manifest["controls"]
    assert editor._canvas.selected == "title"
    editor._undo()
    assert "play" in document.manifest["controls"]
    editor._canvas.select("play")
    editor._remove_element()
    editor._remove_element()
    assert editor._canvas.selected == "drag"
    assert not document.manifest["controls"]
    assert not editor._remove_element_action.isEnabled()
    qapp.processEvents()


def test_cancelled_import_keeps_current_document_and_pending_text(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    previous = editor.document
    editor._inspector.face._metadata["name"].setText("Keep my pending name")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    result = SimpleNamespace(document=_imported_document(), warnings=())
    assert not editor.import_audion_result(result)
    assert editor.document is previous
    assert previous.manifest["name"] == "Keep my pending name"


def test_failed_import_does_not_prompt_or_replace_current_document(editor, monkeypatch):
    from amberfader.face_library import FaceError

    previous = editor.document
    errors = []
    monkeypatch.setattr(editor, "_show_error", lambda *args: errors.append(args))
    monkeypatch.setattr(editor, "_confirm_discard", lambda: pytest.fail("Invalid import prompted"))
    invalid = SimpleNamespace(preview=lambda **kwargs: (_ for _ in ()).throw(FaceError("Bad PNG")))
    assert not editor.import_audion_result(SimpleNamespace(document=invalid, warnings=()))
    assert editor.document is previous
    assert errors == [("The Audion face could not be imported.", errors[0][1])]
    assert str(errors[0][1]) == "Bad PNG"


def test_import_dialog_previews_one_selection_and_keeps_credits_plain_text(qapp, monkeypatch):
    from amberfader.ui import audion_import_dialog as module

    first = SimpleNamespace(source=Path("/first"), prefix="", name="FishFace")
    second = SimpleNamespace(source=Path("/second"), prefix="", name="Gizmo")
    converted = []

    def convert(candidate):
        converted.append(candidate.name)
        return SimpleNamespace(document=_imported_document(), warnings=("<Unsupported> resource",))

    monkeypatch.setattr(module, "_list_faces", lambda source: (first, second))
    monkeypatch.setattr(module, "_convert_face", convert)
    dialog = module.AudionImportDialog()
    try:
        assert dialog.load_source(Path("/faces"))
        assert converted == ["FishFace"]
        assert not dialog._preview.pixmap().isNull()
        assert "<FishFace>" in dialog._details.toPlainText()
        assert "<Unsupported> resource" in dialog._details.toPlainText()
        dialog._filter.setText("Gizmo")
        assert converted == ["FishFace", "Gizmo"]
        assert dialog._faces.currentItem().text() == "Gizmo"
        assert dialog.import_result is not None
        dialog.accept()
        assert converted == ["FishFace", "Gizmo"]
        assert dialog.result() == module.QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_failed_source_cannot_import_a_previous_cached_selection(qapp, monkeypatch):
    from amberfader.face_library import FaceError
    from amberfader.ui import audion_import_dialog as module

    candidate = SimpleNamespace(source=Path("/first"), prefix="", name="FishFace")

    def sources(path):
        if path == Path("/bad"):
            raise FaceError("Missing index.json")
        return (candidate,)

    monkeypatch.setattr(module, "_list_faces", sources)
    monkeypatch.setattr(module, "_convert_face", lambda source: SimpleNamespace(
        document=_imported_document(), warnings=(),
    ))
    dialog = module.AudionImportDialog()
    try:
        assert dialog.load_source(Path("/good"))
        assert dialog.import_result is not None
        assert not dialog.load_source(Path("/bad"))
        assert dialog.import_result is None
        assert not dialog._import_button.isEnabled()
        assert "Missing index.json" in dialog._details.toPlainText()
        dialog.accept()
        assert dialog.result() != module.QDialog.DialogCode.Accepted
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_imported_typography_and_small_canvas_survive_inspector_refresh(editor, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    document = _imported_document()
    document.set_value(("readoutStyles", "title", "size"), 6)
    document.set_value(("readoutStyles", "title", "fontFamily"), "Courier")
    document.set_value(("readoutStyles", "title", "italic"), True)
    document.set_value(("readoutStyles", "title", "color"), "#123456")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    assert editor.import_audion_result(SimpleNamespace(document=document, warnings=()))
    inspector = editor._inspector.element
    assert inspector._text_size.value() == 6
    assert inspector._text_family.text() == "Courier"
    assert inspector._text_style.button("italic").isChecked()
    assert inspector._text_color.color().name() == "#123456"

    inspector._text_family.setFocus()
    qapp.processEvents()
    inspector._text_family.setText("Still typing a family")
    inspector._rotation.setValue(5)
    assert inspector._text_family.text() == "Still typing a family"
    editor._flush_inspector()
    assert document.manifest["readoutStyles"]["title"]["fontFamily"] == "Still typing a family"


def test_native_browse_actions_use_portal_compatible_folder_and_zip_dialogs(qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from amberfader.ui import audion_import_dialog as module

    dialog = module.AudionImportDialog()
    loaded = []
    choices = []

    def folder(*args):
        choices.append(("folder", args))
        return "/face collection"

    def archive(*args):
        choices.append(("zip", args))
        return "/faces.zip", "ZIP archives (*.zip)"

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", folder)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", archive)
    monkeypatch.setattr(dialog, "load_source", lambda source: loaded.append(source))
    try:
        dialog._browse_folder()
        dialog._browse_zip()
        assert loaded == [Path("/face collection"), Path("/faces.zip")]
        assert len(choices[0][1]) == 3
        assert len(choices[1][1]) == 4
        assert choices[1][1][-1] == "ZIP archives (*.zip)"
    finally:
        dialog.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("source_kind", ["folder", "archive"])
def test_failed_source_browse_retries_in_the_selected_location(
    qapp, tmp_path, monkeypatch, source_kind,
):
    from PySide6.QtWidgets import QFileDialog

    from amberfader.ui.audion_import_dialog import AudionImportDialog

    location = tmp_path / "selected location"
    location.mkdir()
    source = location
    if source_kind == "archive":
        source = location / "broken.zip"
        source.write_bytes(b"This is not a ZIP archive")
    starts = []
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args: (
        starts.append(args[2]) or ""
    ))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args: (
        starts.append(args[2]) or "", ""
    ))
    dialog = AudionImportDialog()
    try:
        assert not dialog.load_source(source)
        assert "Could not read Audion faces" in dialog._details.toPlainText()
        assert not dialog._import_button.isEnabled()
        if source_kind == "folder":
            dialog._browse_folder()
        else:
            dialog._browse_zip()
        assert starts == [str(location)]
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_inaccessible_source_shows_an_inline_read_error(qapp, tmp_path, monkeypatch):
    from amberfader.ui.audion_import_dialog import AudionImportDialog

    dialog = AudionImportDialog()

    def inaccessible(path):
        raise PermissionError("The source folder is inaccessible")

    monkeypatch.setattr(Path, "is_dir", inaccessible)
    try:
        assert not dialog.load_source(tmp_path / "inaccessible")
        assert "The source folder is inaccessible" in dialog._details.toPlainText()
        assert dialog.import_result is None
        assert not dialog._import_button.isEnabled()
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_removing_bitmap_clock_discards_cached_digit_artwork(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    template = FaceDocument.from_template(BUILTIN_DIRECTORY / DEFAULT_FACE_ID)
    manifest = template.manifest
    manifest["formatVersion"] = 3
    manifest["controls"] = {"time": [20, 40, 40, 10]}
    manifest["timeDigits"] = [
        {"rect": [20 + index * 10, 40, 10, 10], "images": ["background.png"] * 10}
        for index in range(4)
    ]
    document = FaceDocument.from_snapshot(manifest, template.assets)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    assert editor.import_audion_result(SimpleNamespace(document=document, warnings=()))
    assert len(editor._artwork.time_digits) == 4
    editor._remove_element()
    assert "timeDigits" not in document.manifest
    document.set_rect("time", [20, 40, 40, 10])
    editor._changed()
    assert not editor._artwork.time_digits


@pytest.mark.parametrize("source_kind", ["folder", "zip"])
def test_real_import_dialog_to_editor_save_and_reopen_is_portable(
    editor, qapp, tmp_path, monkeypatch, source_kind,
):
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtWidgets import QMessageBox

    from amberfader.ui.audion_import_dialog import AudionImportDialog

    source = tmp_path / "Imported Fixture"
    source.mkdir()
    for name, size, color in (
        ("base.png", (180, 120), "#203040"),
        ("play.png", (18, 18), "#60b080"),
    ):
        image = QImage(*size, QImage.Format.Format_ARGB32)
        image.fill(QColor(color))
        assert image.save(str(source / name), "PNG")
    (source / "index.json").write_text(json.dumps({
        "playButtonRect": {"left": 20, "top": 80, "right": 38, "bottom": 98},
        "artistDisplayRect": {"left": 20, "top": 20, "right": 160, "bottom": 38},
        "artistDisplayFontName": "Courier", "artistFontSize": 9,
        "faceInfo": ["Original Fixture by Test Artist", "<Preserved credits>"],
    }))
    before = {path.name: path.read_bytes() for path in source.iterdir()}
    selected = source
    if source_kind == "zip":
        selected = tmp_path / "Faces.zip"
        with ZipFile(selected, "w") as archive:
            for path in source.iterdir():
                archive.write(path, source.name + "/" + path.name)
    dialog = AudionImportDialog(editor)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)
    try:
        assert dialog.load_source(selected)
        result = dialog.import_result
        assert result is not None
        assert result.document.manifest["size"] == [180, 120]
        assert not dialog._preview.pixmap().isNull()
        assert "<Preserved credits>" in dialog._details.toPlainText()
        assert editor.import_audion_result(result)
        assert editor.document.path is None and editor.document.dirty
        face = editor._inspector.face
        assert [field.value() for field in face._face_size] == [180, 120]
        assert not face._sprite_labels.isChecked()
        assert face._slider_style.currentData() == "popup"
        assert set(editor.document.manifest["controls"]) == {"play", "title"}
        saved = tmp_path / "Converted"
        assert editor._save_to(saved)
        assert {path.name: path.read_bytes() for path in source.iterdir()} == before
        manifest, assets = editor.document.manifest, dict(editor.document.assets)
        for path in source.iterdir():
            path.unlink()
        source.rmdir()
        if source_kind == "zip":
            selected.unlink()
        assert editor.open_face(saved)
        assert editor.document.manifest == manifest
        assert dict(editor.document.assets) == assets
        assert not editor.document.dirty
        assert editor._canvas._item.face.source_credit == "\n".join([
            "Original Fixture by Test Artist", "<Preserved credits>",
        ])
    finally:
        dialog.deleteLater()
        qapp.processEvents()


def test_import_dialog_is_released_after_cancel(editor, qapp, monkeypatch):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QDialog

    from amberfader.ui import audion_import_dialog as module

    destroyed = []

    def cancel(dialog):
        dialog.destroyed.connect(lambda: destroyed.append(True))
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(module.AudionImportDialog, "exec", cancel)
    editor._import_audion()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    assert destroyed == [True]


def test_alpha_mask_import_refreshes_preview_and_can_be_cleared(editor, tmp_path, monkeypatch):
    from PySide6.QtGui import QImage

    width, height = editor.document.manifest["size"]
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(0xffffffff)
    path = tmp_path / "mask.png"
    assert image.save(str(path), "PNG")
    previous_artwork = editor._artwork
    monkeypatch.setattr(editor, "_choose_png", lambda caption: path)
    editor._import_alpha_mask()
    assert editor.document.preview().alpha_mask is not None
    assert editor._artwork is not previous_artwork
    face = editor._inspector.face
    assert face._mask_name.text() == editor.document.manifest["alphaMask"]
    assert face._mask_remove.isEnabled() and editor._remove_mask_action.isEnabled()
    face._mask_remove.click()
    assert "alphaMask" not in editor.document.manifest
    assert editor.document.preview().alpha_mask is None
    assert not face._mask_remove.isEnabled()
    assert editor._undo_action.text() == "Undo Remove Window Mask"
    editor._undo()
    assert editor.document.preview().alpha_mask is not None
