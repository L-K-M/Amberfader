"""Rotation validates physical footprints and retains actual Qt widget input."""
import json
from types import MappingProxyType

import pytest
from test_faces import make_pack

from amberfader.face_library import FaceError, load_face


@pytest.fixture()
def rotating_pack(tmp_path):
    directory, data = make_pack(tmp_path)
    data["formatVersion"] = 2
    # A wide canvas with separate rows leaves space for rotated controls.
    data["size"] = [640, 560]
    data["drag"] = [20, 4, 100, 18]
    rows = {
        "art": [20, 35, 64, 64], "title": [110, 35, 160, 20],
        "artists": [110, 65, 180, 20], "time": [110, 95, 160, 24],
        "playback": [310, 65, 100, 20], "status": [310, 95, 180, 20],
        "previous": [40, 150, 34, 24], "play": [130, 150, 70, 24],
        "next": [250, 150, 34, 24], "like": [340, 150, 46, 24],
        "seek": [80, 250, 200, 24], "volume": [370, 250, 100, 24],
        "search": [40, 350, 80, 24], "show": [170, 350, 80, 24],
        "hide": [310, 350, 80, 24], "menu": [430, 350, 30, 24],
        "minimize": [40, 450, 30, 24], "close": [130, 450, 30, 24],
    }
    data["controls"] = rows
    from test_faces import png
    (directory / "background.png").write_bytes(png(*data["size"]))
    return directory, data


def save_pack(pack):
    directory, data = pack
    (directory / "face.json").write_text(json.dumps(data))
    return directory


def test_rotation_accepts_every_control_and_is_immutable(rotating_pack):
    _, data = rotating_pack
    data["controlRotations"] = dict.fromkeys(data["controls"], 8.5)
    face = load_face(save_pack(rotating_pack))
    assert dict(face.control_rotations) == data["controlRotations"]
    assert isinstance(face.control_rotations, MappingProxyType)
    with pytest.raises(TypeError):
        face.control_rotations["play"] = 0


def test_missing_rotations_preserve_zero_angle_layout(rotating_pack):
    face = load_face(save_pack(rotating_pack))
    assert not face.control_rotations


@pytest.mark.parametrize("rotation", [True, "30", None, -181, 181, float("nan"), float("inf")])
def test_invalid_rotation_is_rejected(rotating_pack, rotation):
    rotating_pack[1]["controlRotations"] = {"play": rotation}
    with pytest.raises(FaceError):
        load_face(save_pack(rotating_pack))


@pytest.mark.parametrize("change", [
    lambda data: data.update(formatVersion=1, controlRotations={"play": 0}),
    lambda data: data.update(controlRotations={"drag": 10}),
    lambda data: data.update(controlRotations={"untrusted": 10}),
])
def test_rotation_is_constrained_to_v2_controls(rotating_pack, change):
    change(rotating_pack[1])
    with pytest.raises(FaceError):
        load_face(save_pack(rotating_pack))


def test_rotated_bounds_are_checked(rotating_pack):
    data = rotating_pack[1]
    data["controls"]["play"] = [0, 150, 70, 24]
    data["controls"]["previous"] = [120, 150, 34, 24]
    data["controlRotations"] = {"play": 25}
    with pytest.raises(FaceError, match="play must fit"):
        load_face(save_pack(rotating_pack))


def test_rotation_cannot_turn_separate_rectangles_into_overlaps(rotating_pack):
    data = rotating_pack[1]
    data["controls"]["play"] = [130, 160, 70, 24]
    data["controls"]["next"] = [188, 195, 34, 24]
    data["controlRotations"] = {"play": 45}
    with pytest.raises(FaceError, match="overlaps"):
        load_face(save_pack(rotating_pack))


@pytest.fixture()
def rotated_window(rotating_pack, qapp, tmp_path):
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from test_gui_features import _state

    from amberfader.face_library import FaceLibrary
    from amberfader.ui.main_window import MainWindow

    rotating_pack[1]["controlRotations"] = {"play": 30, "seek": 25, "volume": -35, "art": 15}
    library = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json")
    info = library.install(save_pack(rotating_pack))
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    window.select_face(info.id)
    window.apply_state(_state(capabilities=["play", "pause", "seek", "volume", "next", "previous"]))
    window._tick.stop()
    window._status_timer.stop()
    window.show()
    qapp.processEvents()
    yield window, sent
    window.close()
    window.deleteLater()
    qapp.processEvents()


def proxy_position(wrapper, point):
    from PySide6.QtCore import QPointF
    return wrapper.mapFromScene(wrapper._proxy.mapToScene(QPointF(point)))


def test_rotated_button_hits_visual_surface_and_preserves_pending_guard(rotated_window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    window, sent = rotated_window
    wrapper = window._surface._rotated["play"]
    center = proxy_position(wrapper, window._play.rect().center())
    QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert sent == [("player.play", {})]
    assert window._pending_transport
    assert not window._play.isEnabled()
    QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=center)
    assert len(sent) == 1
    window.command_settled()
    sent.clear()
    # The empty corner of its axis-aligned bounding box cannot trigger play.
    QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(1, 1))
    assert sent == []


def test_rotated_button_receives_native_keyboard_activation(rotated_window, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, sent = rotated_window
    wrapper = window._surface._rotated["play"]
    wrapper.setFocus()
    wrapper._proxy.setFocus()
    window._play.setFocus()
    qapp.processEvents()
    QTest.keyClick(wrapper.viewport(), Qt.Key.Key_Space)
    assert sent == [("player.play", {})]


@pytest.mark.parametrize("name,method", [("seek", "player.seek"), ("volume", "player.setVolume")])
def test_rotated_slider_drag_keeps_native_signals_and_command_mapping(rotated_window, name, method):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    window, sent = rotated_window
    slider = window._controls[name]
    wrapper = window._surface._rotated[name]
    slider.setValue(slider.maximum() // 4)
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider,
    )
    pressed = QSignalSpy(slider.sliderPressed)
    moved = QSignalSpy(slider.sliderMoved)
    released = QSignalSpy(slider.sliderReleased)
    start = proxy_position(wrapper, handle.center())
    end = proxy_position(wrapper, QPoint(3 * slider.width() // 4, slider.height() // 2))
    QTest.mousePress(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=start)
    assert slider.isSliderDown()
    QTest.mouseMove(wrapper.viewport(), end)
    QTest.mouseRelease(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert pressed.count() == released.count() == 1
    assert moved.count() > 0
    assert slider.value() > slider.maximum() // 2
    assert sent[0][0] == method
    assert len(sent) == 1


def test_rotation_switch_preserves_control_identity_and_pending_state(rotated_window, qapp):
    window, sent = rotated_window
    original = dict(window._controls)
    window._play.click()
    sent.clear()
    for face_id in ("amber-classic", "my-face", "moonstone", "my-face"):
        window.select_face(face_id)
        qapp.processEvents()
        assert window._controls == original
        assert window._pending_transport
        assert not window._play.isEnabled()
        assert sent == []
    assert not window._surface.grab().isNull()


def test_rotated_opaque_mask_uses_transformed_footprint(rotating_pack, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage

    from amberfader.ui.face_surface import prepare_face

    data = rotating_pack[1]
    data["controlRotations"] = {"play": 45}
    face = load_face(save_pack(rotating_pack))
    image = QImage.fromData(face.background)
    # This point lies outside the old rect, inside the rotated upper tip.
    image.setPixelColor(151, 136, Qt.GlobalColor.transparent)
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    from dataclasses import replace
    face = replace(face, background=bytes(raw))
    with pytest.raises(FaceError, match="play must sit"):
        prepare_face(face)


@pytest.mark.parametrize("name", ["seek", "volume"])
def test_rotated_slider_keeps_native_keyboard_navigation(rotated_window, qapp, name):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, sent = rotated_window
    slider = window._controls[name]
    wrapper = window._surface._rotated[name]
    wrapper.setFocus()
    wrapper._proxy.setFocus()
    slider.setFocus()
    qapp.processEvents()
    QTest.keyClick(wrapper.viewport(), Qt.Key.Key_Home)
    assert slider.value() == slider.minimum()
    QTest.keyClick(wrapper.viewport(), Qt.Key.Key_Right)
    assert slider.value() == slider.singleStep()
    QTest.keyClick(wrapper.viewport(), Qt.Key.Key_End)
    assert slider.value() == slider.maximum()
    assert sent == []


@pytest.mark.parametrize("name", ["seek", "volume"])
@pytest.mark.parametrize("from_rotation", [False, True])
def test_rehosting_a_drag_cancels_without_committing_partial_command(
    rotated_window, qapp, name, from_rotation,
):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    window, sent = rotated_window
    slider = window._controls[name]
    if not from_rotation:
        window.select_face("amber-classic")
    slider.setValue(slider.maximum() // 4)
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    handle = slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider,
    )
    if from_rotation:
        wrapper = window._surface._rotated[name]
        QTest.mousePress(
            wrapper.viewport(), Qt.MouseButton.LeftButton,
            pos=proxy_position(wrapper, handle.center()),
        )
    else:
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=handle.center())
    assert slider.isSliderDown()
    window.select_face("amber-classic" if from_rotation else "my-face")
    qapp.processEvents()
    assert not slider.isSliderDown()
    assert not window._seeking
    assert window._seek_occ is None
    assert sent == []


def test_native_rotated_cover_receives_pointer_activation(rotated_window):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, sent = rotated_window
    wrapper = window._surface._rotated["art"]
    QTest.mouseClick(
        wrapper.viewport(), Qt.MouseButton.LeftButton,
        pos=proxy_position(wrapper, window._art.rect().center()),
    )
    assert window._cover_window.isVisible()
    assert sent == []


def test_shared_preview_rotates_sprite_and_restores_painter_transform(rotating_pack, qapp):
    from dataclasses import replace

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPixmap, QTransform

    from amberfader.ui.face_surface import draw_face_preview, prepare_face

    data = rotating_pack[1]
    data["controlRotations"] = {"play": 90}
    face = load_face(save_pack(rotating_pack))
    artwork = prepare_face(face)
    sprite = QPixmap(70, 24)
    sprite.fill(QColor("#0000ff"))
    artwork = replace(artwork, buttons={"play": {"normal": sprite}})
    image = QImage(*face.size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    original = QTransform(painter.worldTransform())
    draw_face_preview(painter, face, artwork, QPixmap())
    assert painter.worldTransform() == original
    painter.end()
    # The transformed blue surface extends above its unrotated position.
    assert image.pixelColor(165, 132) == QColor("#0000ff")
    assert image.pixelColor(135, 162) == QColor("#706050")


def test_snapshot_draft_skips_only_geometry_and_retains_strict_load(rotating_pack):
    from amberfader.face_library import FaceValidation, load_face_snapshot

    directory, data = rotating_pack
    data["controlRotations"] = {"play": 25}
    data["controls"]["play"] = [0, 150, 70, 24]
    images = {"background.png": (directory / "background.png").read_bytes()}
    draft = load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)
    assert draft.control_rotations["play"] == 25
    with pytest.raises(FaceError, match="must fit"):
        load_face_snapshot(data, images, directory)
    data["controlRotations"]["play"] = 900
    with pytest.raises(FaceError, match="maximum"):
        load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)


def test_snapshot_is_independent_of_later_manifest_edits(rotating_pack):
    from amberfader.face_library import load_face_snapshot

    directory, data = rotating_pack
    data["controlRotations"] = {"play": 30}
    data["readoutStyles"] = {"title": {"align": "center"}}
    face = load_face_snapshot(data, {"background.png": (directory / "background.png").read_bytes()},
                              directory)
    data["controlRotations"]["play"] = 80
    data["palette"]["text"] = "#123456"
    data["controls"]["play"][0] = 0
    data["readoutStyles"]["title"]["align"] = "right"
    assert face.control_rotations["play"] == 30
    assert face.palette["text"] != "#123456"
    assert face.controls["play"][0] == 130
    assert face.readout_styles["title"]["align"] == "center"


def test_overlap_uses_polygons_rather_than_rotated_bounding_boxes(rotating_pack):
    from amberfader.face_library import control_bounds

    data = rotating_pack[1]
    data["controls"]["play"] = [130, 160, 70, 24]
    data["controls"]["next"] = [110, 194, 70, 24]
    data["controlRotations"] = {"play": 30, "next": 30}
    play = control_bounds(tuple(data["controls"]["play"]), 30)
    following = control_bounds(tuple(data["controls"]["next"]), 30)
    assert play[0] < following[0] + following[2]
    assert following[1] < play[1] + play[3]
    assert load_face(save_pack(rotating_pack)).control_rotations["next"] == 30


@pytest.mark.parametrize("rotation", [-180, -90, -12.5, 0, 12.5, 90, 180])
def test_control_polygon_center_and_clockwise_rotation(rotation):
    from math import cos, radians, sin

    from amberfader.face_library import control_polygon

    corners = control_polygon((100, 100, 80, 24), rotation)
    assert sum(point[0] for point in corners) / 4 == pytest.approx(140)
    assert sum(point[1] for point in corners) / 4 == pytest.approx(112)
    # Top-left follows Qt's clockwise convention in screen coordinates.
    assert corners[0] == pytest.approx((
        140 - 40 * cos(radians(rotation)) + 12 * sin(radians(rotation)),
        112 - 40 * sin(radians(rotation)) - 12 * cos(radians(rotation)),
    ))


@pytest.mark.parametrize("scale", [1.0, 1.5, 2.0])
def test_scaled_rotation_maps_buttons_to_their_actual_visual_centers(
    rotating_pack, qapp, tmp_path, scale,
):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_gui_features import _state

    from amberfader.face_library import FaceLibrary
    from amberfader.ui.main_window import MainWindow

    rotating_pack[1]["controlRotations"] = {"play": 90}
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(save_pack(rotating_pack))
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), scale=scale,
                        faces=library)
    try:
        window.select_face(info.id)
        window.apply_state(_state(capabilities=["play", "pause"]))
        window.show()
        qapp.processEvents()
        wrapper = window._surface._rotated["play"]
        center = proxy_position(wrapper, window._play.rect().center())
        scene_center = wrapper._proxy.mapToScene(window._play.rect().center())
        assert window.rect().contains(wrapper.geometry())
        assert center.x() == pytest.approx(scene_center.x(), abs=1)
        assert center.y() == pytest.approx(scene_center.y(), abs=1)
        QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=center)
        assert sent == [("player.play", {})]
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_rotated_round_button_has_native_contour_and_keyboard_focus(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QWidget

    from amberfader.ui.face_surface import FaceButton, RotatedControl

    shell = QWidget()
    shell.resize(200, 140)
    button = FaceButton("Search", shell)
    button.resize(80, 32)
    button.set_shape("ellipse", 0)
    wrapper = RotatedControl(button, shell)
    wrapper.apply_geometry((50, 50, 80, 32), 35)
    spy = QSignalSpy(button.clicked)
    shell.show()
    qapp.processEvents()
    try:
        QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton,
                         pos=proxy_position(wrapper, QPoint(2, 2)))
        assert spy.count() == 0
        QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton,
                         pos=proxy_position(wrapper, button.rect().center()))
        assert spy.count() == 1
        wrapper.setFocus()
        wrapper._proxy.setFocus()
        button.setFocus()
        qapp.processEvents()
        assert button.hasFocus()
        QTest.keyClick(wrapper.viewport(), Qt.Key.Key_Space)
        assert spy.count() == 2
        wrapper.detach(shell)
        qapp.processEvents()
        assert button.parentWidget() is shell
        assert button.isVisible()
    finally:
        shell.close()
        shell.deleteLater()
        qapp.processEvents()


def test_snapshot_draft_previews_unfinished_canvas_size(rotating_pack):
    from amberfader.face_library import FaceValidation, load_face_snapshot

    directory, data = rotating_pack
    images = {"background.png": (directory / "background.png").read_bytes()}
    data["size"] = [700, 600]
    draft = load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)
    assert draft.size == (700, 600)
    with pytest.raises(FaceError, match="Background must match"):
        load_face_snapshot(data, images, directory)
    images["background.png"] = b"not an image"
    with pytest.raises(FaceError, match="not a PNG"):
        load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)


def test_proxy_tab_navigation_can_return_to_native_siblings(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QPushButton, QWidget

    from amberfader.ui.face_surface import FaceButton, RotatedControl

    shell = QWidget()
    shell.resize(300, 150)
    button = FaceButton("Rotated", shell)
    button.resize(80, 32)
    wrapper = RotatedControl(button, shell)
    wrapper.apply_geometry((30, 40, 80, 32), 30)
    sibling = QPushButton("Native", shell)
    sibling.setGeometry(170, 40, 80, 32)
    QWidget.setTabOrder(wrapper, sibling)
    shell.show()
    try:
        wrapper.setFocus()
        wrapper._proxy.setFocus()
        button.setFocus()
        qapp.processEvents()
        QTest.keyClick(wrapper.viewport(), Qt.Key.Key_Tab)
        qapp.processEvents()
        assert sibling.hasFocus()
        QTest.keyClick(sibling, Qt.Key.Key_Backtab)
        qapp.processEvents()
        assert button.hasFocus()
    finally:
        shell.close()
        shell.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("name", ["play", "drag"])
@pytest.mark.parametrize("rect", [
    [-12, 150, 70, 24], [130, -12, 70, 24], [-2048, 2048, 2048, 2048],
    [130, 150, 1500, 24], [130, 150, 70, 1500],
])
def test_snapshot_draft_renders_bounded_unfinished_rectangle(rotating_pack, name, rect):
    from amberfader.face_library import FaceValidation, load_face_snapshot

    directory, data = rotating_pack
    if name == "drag":
        data["drag"] = rect
    else:
        data["controls"][name] = rect
    images = {"background.png": (directory / "background.png").read_bytes()}
    draft = load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)
    actual = draft.drag if name == "drag" else draft.controls[name]
    assert actual == tuple(rect)
    with pytest.raises(FaceError):
        load_face_snapshot(data, images, directory)


@pytest.mark.parametrize("rect", [
    [-2049, 150, 70, 24], [2049, 150, 70, 24], [130, -2049, 70, 24],
    [130, 2049, 70, 24], [130, 150, 2049, 24], [130, 150, 70, 2049],
    [130, 150, 0, 24], [130, 150, -1, 24], [130, 150, 70, 0],
    [130, 150, 70, -1], [130.5, 150, 70, 24], [130, True, 70, 24],
    [130, 150, 70.5, 24], [130, 150, 70, 24, 5], [130, 150, 70],
])
def test_snapshot_draft_geometry_stays_bounded_and_structural(rotating_pack, rect):
    from amberfader.face_library import FaceValidation, load_face_snapshot

    directory, data = rotating_pack
    data["controls"]["play"] = rect
    images = {"background.png": (directory / "background.png").read_bytes()}
    with pytest.raises(FaceError):
        load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)


@pytest.mark.parametrize("change", [
    lambda data: data.update(font="malformed"),
    lambda data: data.update(name=""),
    lambda data: data.update(controlRotations={"play": 181}),
    lambda data: data.update(background="../outside.png"),
    lambda data: data["controls"].pop("play"),
    lambda data: data.update(size=[350, 560]),
    lambda data: data.update(controlShapes={"play": "malformed"}),
])
def test_snapshot_draft_geometry_relaxation_preserves_other_constraints(rotating_pack, change):
    from amberfader.face_library import FaceValidation, load_face_snapshot

    directory, data = rotating_pack
    data["controls"]["play"][0] = -12
    change(data)
    images = {"background.png": (directory / "background.png").read_bytes()}
    with pytest.raises(FaceError):
        load_face_snapshot(data, images, directory, validation=FaceValidation.DRAFT)
