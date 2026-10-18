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
    """Switching away from edited work asks first; these tests discard it."""
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


def _gallery(editor, source=None):
    from amberfader.ui.face_gallery import GallerySource

    editor._workspace.show_gallery(source or GallerySource.INSTALLED, editor)
    return editor._workspace._gallery


def _faces(gallery, *, shown_only=True) -> list[str]:
    grid = gallery._grid
    return [
        grid.item(index).text() for index in range(grid.count())
        if not (shown_only and grid.item(index).isHidden())
    ]


def _choose(gallery, name: str) -> None:
    grid = gallery._grid
    item = next(grid.item(i) for i in range(grid.count()) if grid.item(i).text() == name)
    grid.setCurrentItem(item)
    gallery._primary.click()


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


def test_gallery_lists_installed_and_builtin_faces(editor):
    from amberfader.ui.face_gallery import GallerySource

    gallery = _gallery(editor, GallerySource.BUILT_IN)
    assert gallery.isVisible()
    bundled = sum((folder / "face.json").is_file() for folder in BUILTIN_DIRECTORY.iterdir())
    assert gallery._sources.item(0).text() == f"Built-in  {bundled}"
    assert gallery._sources.item(1).text() == "Installed  1"
    assert "Amber Classic" in _faces(gallery)
    assert gallery._primary.text() == "Create"
    gallery.show_source(GallerySource.INSTALLED)
    assert _faces(gallery) == ["My Viridian"]
    assert gallery._primary.text() == "Open"
    window_menu = editor.menuBar().actions()[5].menu()
    assert window_menu.title() == "&Window"
    assert editor._gallery_action in window_menu.actions()


def test_installed_face_is_edited_in_place_and_relisted(editor, installed, library):
    gallery = _gallery(editor)
    _choose(gallery, "My Viridian")
    assert editor.document.path == installed.source
    assert editor.document.manifest["id"] == "my-viridian"
    assert not editor.document.dirty
    assert not gallery.isVisible()

    field = editor._inspector.face._metadata["name"]
    field.setText("Viridian Night")
    field.editingFinished.emit()
    assert editor.save()
    assert library.load("my-viridian").info.name == "Viridian Night"
    assert _faces(gallery) == ["Viridian Night"]
    assert gallery.selected_source() == installed.source


def test_builtin_face_opens_as_an_unsaved_copy(editor):
    from amberfader.ui.face_gallery import GallerySource

    before = (BUILTIN_DIRECTORY / "viridian" / "face.json").read_bytes()
    _choose(_gallery(editor, GallerySource.BUILT_IN), "Viridian")
    assert editor.document.path is None
    assert editor.document.manifest["id"].startswith("viridian-custom-")
    assert (BUILTIN_DIRECTORY / "viridian" / "face.json").read_bytes() == before


def test_cancelled_switch_keeps_unsaved_work(editor, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    editor.document.set_rotation("play", 12)
    original = editor.document
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Cancel)
    gallery = _gallery(editor)
    _choose(gallery, "My Viridian")
    assert editor.document is original
    assert editor.document.manifest["controlRotations"]["play"] == 12
    assert gallery.isVisible()


def test_search_filters_faces_and_explains_empty_results(editor):
    from amberfader.ui.face_gallery import GallerySource

    gallery = _gallery(editor, GallerySource.BUILT_IN)
    gallery._search.setText("viridian")
    assert _faces(gallery) == ["Viridian"]
    gallery._search.setText("no such face")
    assert _faces(gallery) == []
    assert gallery._content.currentWidget() is gallery._empty
    assert "no such face" in gallery._empty.text()
    assert gallery.selected_source() is None
    assert not gallery._primary.isEnabled()


def test_empty_installed_library_explains_where_faces_come_from(qapp, tmp_path):
    from amberfader.ui.face_editor import FaceEditorWindow

    window = FaceEditorWindow(library=FaceLibrary(tmp_path / "none", tmp_path / "a.json"))
    try:
        gallery = _gallery(window)
        assert _faces(gallery) == []
        assert gallery._empty.text().startswith("No Installed Faces")
    finally:
        window.hide()
        window.deleteLater()


def test_file_menu_offers_importing_a_whole_audion_zip(editor):
    file_menu = editor.menuBar().actions()[0].menu()
    assert "Import Audion Collection…" in [action.text() for action in file_menu.actions()]


def test_audion_zip_import_installs_and_lists_every_face(
    editor, library, tmp_path, messages, qapp,
):
    archive = _audion_zip(tmp_path)
    document = editor.document
    assert editor.import_audion_archive(archive)
    assert editor.document is document
    gallery = editor._workspace._gallery
    assert gallery.isVisible()
    assert _faces(gallery) == ["Amber Orb", "Chromatic Orb", "My Viridian"]
    assert gallery._grid.currentItem().text() == "Amber Orb"
    assert messages[-1][0].splitlines()[0] == "Installed 2 of 2 Audion faces."
    imported = [face for face in library.faces if face.id.startswith("audion-")]
    assert sorted(face.name for face in imported) == ["Amber Orb", "Chromatic Orb"]

    gallery._primary.click()
    assert editor.document.path in {face.source for face in imported}
    assert editor.document.manifest["sourceCredit"] == "Original Fixture by Test Artist"

    assert editor.import_audion_archive(archive)
    assert "2 were already installed." in messages[-1][0]
    assert len(_faces(gallery)) == 3


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
    assert len(_faces(editor._workspace._gallery)) == 2


def test_audion_zip_import_reports_unreadable_archives(editor, library, tmp_path, messages):
    archive = tmp_path / "Broken.zip"
    archive.write_text("not a ZIP")
    document = editor.document
    assert not editor.import_audion_archive(archive)
    assert messages[-1][0] == "The Audion collection could not be imported."
    assert editor.document is document
    assert [face.name for face in library.faces if face.id == "my-viridian"] == ["My Viridian"]


def test_failed_faces_are_listed_in_the_details(editor, tmp_path, messages):
    archive = _audion_zip(tmp_path, ("Chromatic Orb",))
    with ZipFile(archive, "a") as writer:
        writer.writestr("Faces/Broken/index.json", "{}")
    assert editor.import_audion_archive(archive)
    text, details = messages[-1]
    assert "1 could not be imported." in text
    assert details.startswith("Broken: ") and "base.png" in details


def test_failed_rescan_after_save_keeps_the_list_and_reports_it(
    editor, installed, library, monkeypatch,
):
    from amberfader.face_library import FaceError

    gallery = _gallery(editor)
    _choose(gallery, "My Viridian")
    field = editor._inspector.face._metadata["name"]
    field.setText("Viridian Night")
    field.editingFinished.emit()

    def broken_refresh():
        raise FaceError("Bundled faces are unavailable. Reinstall Amberfader.")

    monkeypatch.setattr(library, "refresh", broken_refresh)
    assert editor.save()
    assert _faces(gallery) == ["My Viridian"]
    assert gallery._problem_list == ("Bundled faces are unavailable. Reinstall Amberfader.",)
    assert gallery._problems.text() == "1 face folder could not be loaded"


def test_search_never_opens_a_hidden_face(editor):
    gallery = _gallery(editor)
    assert gallery.selected_source() is not None
    gallery._search.setText("amber")
    assert gallery.selected_source() is None
    gallery._primary.click()
    assert editor.document.path is None


def test_progress_names_each_face_before_it_is_imported(editor, tmp_path, messages, monkeypatch):
    from PySide6.QtWidgets import QProgressDialog

    from amberfader.audion_import import AudionArchive

    seen = []
    original = AudionArchive.install

    def install(archive, face, library, check):
        [progress] = editor.findChildren(QProgressDialog)
        seen.append((face.name, progress.isVisible(), progress.labelText()))
        return original(archive, face, library, check)

    monkeypatch.setattr(AudionArchive, "install", install)
    assert editor.import_audion_archive(_audion_zip(tmp_path))
    assert seen == [
        ("Amber Orb", True, "Importing Amber Orb…"),
        ("Chromatic Orb", True, "Importing Chromatic Orb…"),
    ]


def test_default_libraries_live_in_the_private_test_home(private_app_dirs):
    assert FaceLibrary().ensure_directory().is_relative_to(private_app_dirs)
