"""The album cover lies beneath every control, in the player and in previews."""
import json

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from test_faces import make_pack, png

from amberfader.face_library import FaceLibrary, load_face
from amberfader.ui.face_surface import draw_face_preview, prepare_face
from amberfader.ui.main_window import MainWindow

RED = QColor("#ff0000")


def v3_overlap_pack(tmp_path, face_id, *, rotate_art=False):
    """An imported-format face whose cover lies under the title, as format 3 allows."""
    root = tmp_path / face_id
    root.mkdir()
    directory, data = make_pack(root)
    data.update(id=face_id, formatVersion=3, size=[640, 560], drag=[20, 4, 100, 18])
    data["controls"] = {
        "art": [40, 50, 260, 260], "title": [80, 80, 160, 20],
        "artists": [400, 65, 180, 20], "time": [400, 95, 160, 24],
        "playback": [400, 125, 100, 20], "status": [400, 155, 180, 20],
        "previous": [40, 400, 34, 24], "play": [130, 400, 70, 24],
        "next": [250, 400, 34, 24], "like": [340, 400, 46, 24],
        "seek": [380, 250, 200, 24], "volume": [370, 300, 100, 24],
        "search": [40, 450, 80, 24], "show": [170, 450, 80, 24],
        "hide": [310, 450, 80, 24], "menu": [430, 450, 30, 24],
        "minimize": [40, 500, 30, 24], "close": [130, 500, 30, 24],
    }
    if rotate_art:
        data["controlRotations"] = {"art": 10}
    write_manifest(directory, data)
    (directory / "background.png").write_bytes(png(*data["size"]))
    return directory, data


def write_manifest(directory, data):
    (directory / "face.json").write_text(json.dumps(data))


def render_preview(face, cover):
    image = QImage(*face.size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_face_preview(painter, face, prepare_face(face), cover)
    painter.end()
    return image


def test_cover_stays_beneath_controls_after_rotated_art(qapp, tmp_path):
    library = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json")
    flat = library.install(v3_overlap_pack(tmp_path, "flat")[0])
    rotated = library.install(v3_overlap_pack(tmp_path, "rotated", rotate_art=True)[0])
    window = MainWindow(lambda method, params: None, faces=library)
    window.show()
    qapp.processEvents()
    try:
        # Rehosting art in a rotation wrapper, and back, must not lift the
        # cover above controls placed on it.
        for info in (flat, rotated, flat):
            window.select_face(info.id)
            qapp.processEvents()
            checked = set()
            for name, widget in window._controls.items():
                if name == "art" or not widget.isVisible():
                    continue
                hit = window._surface.childAt(widget.geometry().center())
                assert hit is widget, f"{info.id}: {name} is covered by {hit!r}"
                checked.add(name)
            assert "title" in checked
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_preview_paints_cover_before_other_controls(qapp, tmp_path):
    directory, data = v3_overlap_pack(tmp_path, "order")
    data["controls"]["play"] = [100, 200, 70, 24]
    write_manifest(directory, data)
    art_first = load_face(directory)
    art = data["controls"].pop("art")
    data["controls"]["art"] = art
    write_manifest(directory, data)
    art_last = load_face(directory)
    assert list(art_last.controls)[-1] == "art"

    cover = QPixmap(64, 64)
    cover.fill(RED)
    expected, actual = render_preview(art_first, cover), render_preview(art_last, cover)
    play = QPoint(135, 212)
    assert expected.pixelColor(play) != RED
    assert actual.pixelColor(play) == expected.pixelColor(play)
    assert actual == expected
