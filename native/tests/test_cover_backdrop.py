"""The album cover lies beneath every control, and a face may use it as its backdrop."""
import json
from dataclasses import replace
from types import MappingProxyType

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QBuffer, QIODevice, QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QRegion
from PySide6.QtTest import QTest
from test_faces import make_pack, png
from test_gui_features import _state

from amberfader.face_library import FaceLibrary, load_face
from amberfader.ui.face_surface import draw_face_preview, prepare_face, prepare_face_preview
from amberfader.ui.main_window import MainWindow

RED = QColor("#ff0000")
SHELL = QColor("#404040")
SMOKE = QColor(0, 0, 0, 128)
# Logical points on the bare cover, above and inside the smoked band, and on the shell.
CLEAR_POINT, BAND_POINT, SHELL_POINT = QPointF(50, 120), QPointF(300, 300), QPointF(500, 300)


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


def _png_bytes(image):
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(buffer.data())


def backdrop_pack(tmp_path, face_id="backdrop"):
    """A format 2 face whose cover lies under most controls.

    The 2x background is an opaque shell. Inside the cover it is clear above
    y 185 and smoked with 50% black below, so the cover shows through both.
    """
    root = tmp_path / face_id
    root.mkdir()
    directory, data = make_pack(root)
    data.update(
        id=face_id, formatVersion=2, coverBackdrop=True, size=[640, 560], drag=[20, 4, 100, 18],
    )
    data["controls"] = {
        "art": [20, 35, 300, 300], "title": [110, 35, 160, 20],
        "artists": [110, 65, 180, 20], "time": [110, 95, 160, 24],
        "playback": [310, 65, 100, 20], "status": [310, 95, 180, 20],
        "previous": [40, 150, 34, 24], "play": [130, 150, 70, 24],
        "next": [250, 150, 34, 24], "like": [340, 150, 46, 24],
        "seek": [80, 250, 200, 24], "volume": [370, 250, 100, 24],
        "search": [40, 350, 80, 24], "show": [170, 350, 80, 24],
        "hide": [310, 350, 80, 24], "menu": [430, 350, 30, 24],
        "minimize": [40, 450, 30, 24], "close": [130, 450, 30, 24],
    }
    background = QImage(640 * 2, 560 * 2, QImage.Format.Format_ARGB32)
    background.fill(SHELL)
    painter = QPainter(background)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    painter.scale(2, 2)
    painter.fillRect(QRectF(20, 35, 300, 150), Qt.GlobalColor.transparent)
    painter.fillRect(QRectF(20, 185, 300, 150), SMOKE)
    painter.end()
    write_manifest(directory, data)
    (directory / "background.png").write_bytes(_png_bytes(background))
    return directory, data


@pytest.fixture()
def backdrop_window(qapp, tmp_path, request):
    """The player on the backdrop face with a white cover; parametrize the scale."""
    directory, _ = backdrop_pack(tmp_path)
    library = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json")
    info = library.install(directory)
    sent = []
    window = MainWindow(
        lambda method, params: sent.append(method),
        scale=getattr(request, "param", 1.0), faces=library,
    )
    window.select_face(info.id)
    window.show()
    white = QPixmap(64, 64)
    white.fill(QColor("#ffffff"))
    window._cover = white
    window._render_cover()
    qapp.processEvents()
    sent.clear()
    yield window, load_face(directory), sent
    if window._cover_window is not None:
        window._cover_window.close()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _at(window, point, face_width=640):
    """A face point in the surface's logical pixels at the window's effective scale."""
    scale = window._surface.width() / face_width
    return QPoint(round(point.x() * scale), round(point.y() * scale))


def _click(window, point, button=Qt.MouseButton.LeftButton):
    """Click through the window, so Qt routes the press as it would a real one."""
    QTest.mouseClick(
        window.windowHandle(), button, Qt.KeyboardModifier.NoModifier,
        window._surface.mapTo(window, point),
    )


def _close(left, right, tolerance):
    return all(abs(a - b) <= tolerance for a, b in zip(left, right, strict=True))


@pytest.mark.parametrize("backdrop_window", [1.0, 1.5], indirect=True)
def test_backdrop_layers_background_over_cover(backdrop_window, qapp):
    window, face, _ = backdrop_window
    window._art.clearFocus()
    qapp.processEvents()
    grab = window._surface.grab().toImage()
    preview = QImage(grab.size(), QImage.Format.Format_ARGB32_Premultiplied)
    preview.fill(Qt.GlobalColor.transparent)
    painter = QPainter(preview)
    painter.scale(grab.width() / face.size[0], grab.height() / face.size[1])
    draw_face_preview(painter, face, prepare_face(face), window._cover)
    painter.end()
    # The grab and the preview are in device pixels; map face points with
    # their scale, not the surface's logical size.
    scale = grab.width() / face.size[0]
    white, smoked = (255,) * 3, (round(255 * (1 - SMOKE.alphaF())),) * 3
    for point, expected in [
        (CLEAR_POINT, white), (BAND_POINT, smoked), (SHELL_POINT, (64, 64, 64)),
        # Beside the band edge and the art's corner, a shifted or rescaled
        # overlay shows the wrong part of the background.
        (QPointF(100, 190), smoked), (QPointF(25, 40), white),
    ]:
        pixel = QPoint(round(point.x() * scale), round(point.y() * scale))
        actual = grab.pixelColor(pixel).getRgb()[:3]
        assert _close(actual, expected, 2), (point, actual)
        assert _close(preview.pixelColor(pixel).getRgb()[:3], actual, 1), point


def test_backdrop_mask_counts_the_aperture(qapp, tmp_path):
    face = load_face(backdrop_pack(tmp_path)[0])
    # A format 2 face needs opaque footprints; the clear glass under the
    # title shows the cover, which always fills its aperture.
    artwork = prepare_face(face)
    for scale in (1.0, 1.5, 2.0):
        mask = artwork.scaled_mask(tuple(round(value * scale) for value in face.size))
        for name, rect in {**face.controls, "drag": face.drag}.items():
            footprint = QRegion(QRect(*(round(value * scale) for value in rect)))
            assert footprint.subtracted(mask).isEmpty(), (scale, name)


def test_backdrop_draft_without_art_still_previews(qapp, tmp_path):
    # The editor keeps unfinished drafts paintable; the strict layout check
    # reports the missing art.
    face = load_face(backdrop_pack(tmp_path)[0])
    controls = {name: rect for name, rect in face.controls.items() if name != "art"}
    draft = replace(face, controls=MappingProxyType(controls))
    artwork = prepare_face_preview(draft)
    assert not artwork.mask.contains(QPoint(50, 120))  # The clear glass stays a hole.


def test_bare_cover_moves_window(backdrop_window, qapp):
    window, _, sent = backdrop_window
    surface = window._surface
    point = _at(window, CLEAR_POINT)
    assert surface.childAt(point) is None
    before = window.pos()
    # Offscreen Qt cannot start a system move, so the surface moves the window.
    QTest.mousePress(surface, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(surface, point + QPoint(30, 20))
    QTest.mouseRelease(
        surface, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point + QPoint(30, 20),
    )
    qapp.processEvents()
    assert window.pos() != before
    assert window._cover_window is None
    assert not sent


def test_rotated_readout_on_backdrop_moves_window(qapp, tmp_path):
    # A rotated readout lives in a graphics view. Offscreen Qt cannot start a
    # system move, so the surface needs every move and the release of a press
    # no control took, as it gets them through a flat label.
    directory, data = backdrop_pack(tmp_path)
    data["controlRotations"] = {"title": 5}
    write_manifest(directory, data)
    library = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json")
    info = library.install(directory)
    window = MainWindow(lambda method, params: None, faces=library)
    window.select_face(info.id)
    window.show()
    qapp.processEvents()
    try:
        wrapper = window._surface._rotated["title"]
        start = window._surface.mapTo(window, wrapper.geometry().center())
        assert window.childAt(start) is wrapper.viewport()
        before = window.pos()
        handle = window.windowHandle()
        QTest.mousePress(handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        QTest.mouseMove(handle, start + QPoint(30, 20))
        QTest.mouseRelease(
            handle, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
            start + QPoint(30, 20),
        )
        qapp.processEvents()
        assert window.pos() != before
        assert window._surface._drag_offset is None
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_controls_on_backdrop_keep_their_commands(backdrop_window, qapp):
    window, _, sent = backdrop_window
    window.apply_state(_state(capabilities=["play", "pause"]))
    sent.clear()
    point = _at(window, QPointF(165, 162))
    assert window._surface.childAt(point) is window._play
    _click(window, point)
    qapp.processEvents()
    assert sent == ["player.play"]
    assert window._cover_window is None


def test_backdrop_keeps_menu_and_keyboard_cover_view(backdrop_window, qapp):
    window, _, sent = backdrop_window
    menus = []
    window._surface.menuRequested.connect(menus.append)
    _click(window, _at(window, CLEAR_POINT), Qt.MouseButton.RightButton)
    qapp.processEvents()
    assert len(menus) == 1
    window._face_menu.hide()
    assert window._cover_window is None

    window._art.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(window._art, Qt.Key.Key_Return)
    assert window._cover_window is not None and window._cover_window.isVisible()
    window._cover_window.close()
    cover_view = next(action for action in window._menu.actions() if action.text() == "Cover view")
    cover_view.trigger()
    assert window._cover_window.isVisible()
    assert not sent


def test_normal_face_after_backdrop_restores_cover_click(backdrop_window, qapp):
    window, _, _ = backdrop_window
    assert window._art.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    window.select_face("amber-classic")
    qapp.processEvents()
    assert not window._art.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    drag = window._faces.load("amber-classic").drag
    scale = window._surface.width() / window._faces.load("amber-classic").size[0]
    assert window._surface._drag == QRegion(QRect(*(round(value * scale) for value in drag)))
    centre = window._art.geometry().center()
    assert window._surface.childAt(centre) is window._art
    _click(window, centre)
    qapp.processEvents()
    assert window._cover_window is not None and window._cover_window.isVisible()


def test_full_canvas_drag_without_backdrop_keeps_cover_click(qapp, tmp_path):
    # Imported faces may drag from anywhere, cover included; without the
    # backdrop flag a click on their cover still opens Cover view.
    directory, data = v3_overlap_pack(tmp_path, "full-drag")
    data["drag"] = [0, 0, *data["size"]]
    write_manifest(directory, data)
    library = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json")
    info = library.install(directory)
    window = MainWindow(lambda method, params: None, faces=library)
    window.select_face(info.id)
    window.show()
    qapp.processEvents()
    try:
        point = _at(window, QPointF(60, 200))
        assert window._surface.childAt(point) is window._art
        _click(window, point)
        qapp.processEvents()
        assert window._cover_window is not None and window._cover_window.isVisible()
    finally:
        if window._cover_window is not None:
            window._cover_window.close()
        window.close()
        window.deleteLater()
        qapp.processEvents()
