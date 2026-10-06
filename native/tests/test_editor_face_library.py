"""The editor lists the player's faces and installs whole Audion collections."""

from __future__ import annotations

import json
from zipfile import ZipFile

import pytest

from amberfader.face_document import FaceDocument
from amberfader.face_library import BUILTIN_DIRECTORY, FaceLibrary


@pytest.fixture()
def library(tmp_path):
    return FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")


@pytest.fixture()
def installed(library, tmp_path):
    document = FaceDocument.from_template(
        BUILTIN_DIRECTORY / "viridian", face_id="my-viridian", name="My Viridian",
    )
    return library.install(document.export(tmp_path / "export"))


@pytest.fixture(autouse=True)
def discard_unsaved_copies(monkeypatch):
    """The editor starts with an unsaved template copy; switching asks first."""
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Discard)


@pytest.fixture()
def editor(qapp, library, installed):
    from amberfader.ui.face_editor import FaceEditorWindow

    window = FaceEditorWindow(library=library)
    window.show()
    qapp.processEvents()
    yield window
    window.hide()
    window.deleteLater()
    qapp.processEvents()


def _faces(editor, group: int) -> list[str]:
    item = editor._faces_panel._tree.topLevelItem(group)
    return [item.child(index).text(0) for index in range(item.childCount())]


def _item(editor, name: str):
    tree = editor._faces_panel._tree
    for group in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(group)
        for index in range(item.childCount()):
            if item.child(index).text(0) == name:
                return item.child(index)
    raise AssertionError(f"{name} is not listed")


def _edit(editor, name: str) -> None:
    editor._faces_panel._tree.setCurrentItem(_item(editor, name))
    editor._faces_panel._edit.click()


def _audion_zip(tmp_path, names=("Chromatic Orb", "Amber Orb")):
    from PySide6.QtGui import QColor, QImage

    archive = tmp_path / "Faces.zip"
    source = tmp_path / "audion"
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
        "faceInfo": ["Original Fixture by Test Artist"],
    }))
    with ZipFile(archive, "w") as writer:
        for name in names:
            for path in source.iterdir():
                writer.write(path, f"Faces/{name}/{path.name}")
    return archive


@pytest.fixture()
def messages(monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    shown = []

    def record(box):
        shown.append((box.text(), box.detailedText()))
        return QMessageBox.StandardButton.Ok

    def warn(parent, title, text, *args):
        shown.append((title, str(text)))
        return QMessageBox.StandardButton.Discard

    monkeypatch.setattr(QMessageBox, "exec", record)
    monkeypatch.setattr(QMessageBox, "warning", warn)
    return shown


def test_editor_opens_with_installed_and_builtin_faces_listed(editor):
    from PySide6.QtWidgets import QDockWidget

    dock = editor.findChild(QDockWidget, "facesDock")
    assert dock is not None and dock.isVisible()
    tree = editor._faces_panel._tree
    assert tree.topLevelItem(0).text(0) == "Installed (1)"
    assert tree.topLevelItem(1).text(0) == "Built-in (18)"
    assert _faces(editor, 0) == ["My Viridian"]
    assert "Amber Classic" in _faces(editor, 1)
    view_menu = editor.menuBar().actions()[2].menu()
    assert dock.toggleViewAction() in view_menu.actions()


def test_installed_face_is_edited_in_place_and_relisted(editor, installed, library):
    _edit(editor, "My Viridian")
    assert editor.document.path == installed.source
    assert editor.document.manifest["id"] == "my-viridian"
    assert not editor.document.dirty

    editor._metadata["name"].setText("Viridian Night")
    editor._edit_metadata("name")
    assert editor.save()
    assert library.load("my-viridian").info.name == "Viridian Night"
    assert _faces(editor, 0) == ["Viridian Night"]
    assert editor._faces_panel._tree.currentItem().text(0) == "Viridian Night"


def test_builtin_face_opens_as_an_unsaved_copy(editor):
    before = (BUILTIN_DIRECTORY / "viridian" / "face.json").read_bytes()
    _edit(editor, "Viridian")
    assert editor.document.path is None
    assert editor.document.manifest["id"].startswith("viridian-custom-")
    assert (BUILTIN_DIRECTORY / "viridian" / "face.json").read_bytes() == before


def test_cancelled_switch_keeps_unsaved_work(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    editor.document.set_rotation("play", 12)
    original = editor.document
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    _edit(editor, "My Viridian")
    assert editor.document is original
    assert editor.document.manifest["controlRotations"]["play"] == 12


def test_filter_hides_faces_by_name(editor):
    editor._faces_panel._filter.setText("viridian")
    shown = [
        item.text(0) for group in range(2)
        for item in [editor._faces_panel._tree.topLevelItem(group)]
        for item in [item.child(index) for index in range(item.childCount())]
        if not item.isHidden()
    ]
    assert shown == ["My Viridian", "Viridian"]


def test_file_menu_offers_importing_a_whole_audion_zip(editor):
    file_menu = editor.menuBar().actions()[0].menu()
    assert "Import all Audion faces from ZIP…" in [action.text() for action in file_menu.actions()]


def test_audion_zip_import_installs_and_lists_every_face(
    editor, library, tmp_path, messages, qapp,
):
    archive = _audion_zip(tmp_path)
    document = editor.document
    assert editor.import_audion_archive(archive)
    assert editor.document is document
    assert _faces(editor, 0) == ["Amber Orb", "Chromatic Orb", "My Viridian"]
    assert editor._faces_panel._tree.currentItem().text(0) == "Amber Orb"
    assert messages[-1][0].splitlines()[0] == "Installed 2 of 2 Audion faces."
    imported = [face for face in library.faces if face.id.startswith("audion-")]
    assert sorted(face.name for face in imported) == ["Amber Orb", "Chromatic Orb"]

    editor._faces_panel._edit.click()
    assert editor.document.path in {face.source for face in imported}
    assert editor.document.manifest["sourceCredit"] == "Original Fixture by Test Artist"

    assert editor.import_audion_archive(archive)
    assert "2 were already installed." in messages[-1][0]
    assert len(_faces(editor, 0)) == 3


def test_audion_zip_import_can_stop_early(editor, library, tmp_path, messages, monkeypatch):
    from PySide6.QtWidgets import QProgressDialog

    checks = []

    def stop_after_first_face(dialog):
        checks.append(dialog)
        return len(checks) > 1

    monkeypatch.setattr(QProgressDialog, "wasCanceled", stop_after_first_face)
    assert editor.import_audion_archive(_audion_zip(tmp_path))
    text = messages[-1][0]
    assert text.startswith("Installed 1 of 2 Audion faces.")
    assert "Import stopped." in text
    assert len(_faces(editor, 0)) == 2


def test_audion_zip_import_reports_unreadable_archives(editor, tmp_path, messages):
    archive = tmp_path / "Broken.zip"
    archive.write_text("not a ZIP")
    document = editor.document
    assert not editor.import_audion_archive(archive)
    assert messages[-1][0] == "Could not import Audion faces"
    assert editor.document is document
    assert _faces(editor, 0) == ["My Viridian"]


def test_failed_faces_are_listed_in_the_details(editor, tmp_path, messages):
    archive = _audion_zip(tmp_path, ("Chromatic Orb",))
    with ZipFile(archive, "a") as writer:
        writer.writestr("Faces/Broken/index.json", "{}")
    assert editor.import_audion_archive(archive)
    text, details = messages[-1]
    assert "1 could not be imported." in text
    assert details.startswith("Broken: ") and "base.png" in details
