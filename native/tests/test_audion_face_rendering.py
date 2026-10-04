"""Imported bitmap faces keep their original pixels and real native input."""
from dataclasses import replace
from types import MappingProxyType

import pytest
from test_faces import png

from amberfader.face_library import FaceError, FaceLibrary, TimeDigit


def _frozen(values):
    return MappingProxyType(values)


@pytest.fixture()
def audion_face(qapp, tmp_path):
    from PySide6.QtGui import QFontDatabase, QFontInfo

    face = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json").load("amber-classic")
    family = QFontInfo(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)).family()
    digit_rects = [(40 + index * 8, 45, 6, 8) for index in range(4)]
    digits = tuple(
        TimeDigit(rect, tuple(png(3, 4, bytes((number * 20, 180, 60, 255)))
                             for number in range(10)))
        for rect in digit_rects
    )
    return replace(
        face, info=replace(face.info, id="audion-test"), format_version=3,
        size=(180, 120), drag=(0, 0, 180, 120), radius=0,
        background=png(180, 120, b"\x20\x20\x20\xff"),
        controls=_frozen({
            "title": (45, 10, 120, 10), "artists": (45, 23, 120, 10),
            "play": (10, 40, 20, 20), "time": (40, 45, 30, 8),
            "seek": (40, 45, 30, 8), "volume": (10, 70, 10, 10),
        }),
        buttons=_frozen({
            "play": _frozen({
                "normal": png(20, 20, b"\x10\xe0\x10\xff"),
                "pressed": png(20, 20, b"\x10\x10\xe0\xff"),
                "disabled": png(20, 20, b"\x40\x40\x40\xff"),
                "playing": png(20, 20, b"\xe0\x10\x10\xff"),
                "playing-pressed": png(20, 20, b"\xe0\x10\xe0\xff"),
                "playing-disabled": png(20, 20, b"\x80\x40\x40\xff"),
            }),
            "volume": _frozen({"normal": png(10, 10, b"\x10\x90\xe0\xff")}),
        }),
        control_shapes=_frozen({}), control_rotations=_frozen({}),
        readout_styles=_frozen({"title": _frozen({
            "fontFamily": family, "size": 7, "italic": True,
            "color": "#ff3040", "align": "center",
        })}),
        slider_style="popup", sprite_labels=False, time_digits=digits,
    )


@pytest.fixture()
def audion_player(audion_face, qapp, tmp_path):
    from test_gui_features import _state

    from amberfader.ui.face_surface import prepare_face
    from amberfader.ui.main_window import MainWindow

    library = FaceLibrary(tmp_path / "installed", tmp_path / "preferences.json")
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    artwork = prepare_face(audion_face)
    window._apply_face(audion_face, artwork)
    window.apply_state(_state(
        capabilities=["play", "pause", "seek", "volume"],
        positionSeconds=228, durationSeconds=270,
    ))
    window._tick.stop()
    window._status_timer.stop()
    window.show()
    qapp.processEvents()
    yield window, sent, audion_face, artwork
    for slider in (window._seek, window._vol):
        slider.cancel_popup()
    window._menu.hide()
    window._import_menu.hide()
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _preview(face, artwork, labels=None):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter, QPixmap

    from amberfader.ui.face_surface import draw_face_preview

    image = QImage(*face.size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    draw_face_preview(painter, face, artwork, QPixmap(), labels)
    painter.end()
    return image


def _rgb(image, x, y):
    color = image.pixelColor(x, y)
    return color.red(), color.green(), color.blue()


def _handle(slider):
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    return slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider,
    ).center()


def _open_popup(owner, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    QTest.mouseClick(owner, Qt.MouseButton.LeftButton, pos=owner.rect().center())
    qapp.processEvents()
    assert owner._popup.isVisible()
    return owner._popup_slider


def _start_drag(slider):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=_handle(slider))
    assert slider.isSliderDown()
    end = QPoint(slider.width() // 3, slider.height() // 2)
    QTest.mouseMove(slider, end)
    return end


def test_original_transport_sprite_owns_glyph_and_follows_observed_pause(audion_player, qapp):
    from test_gui_features import _state

    window, sent, face, artwork = audion_player
    window._play.clearFocus()
    native = window._play.grab().toImage()
    # A solid artist sprite would reveal an overlaid generic transport glyph.
    assert {_rgb(native, x, y) for x in range(3, 17) for y in range(3, 17)} == {(16, 224, 16)}
    assert _rgb(_preview(face, artwork), 20, 50) == (16, 224, 16)
    window.apply_state(_state(status="playing", capabilities=["pause", "seek", "volume"]))
    window._play.clearFocus()
    qapp.processEvents()
    assert _rgb(window._play.grab().toImage(), 10, 10) == (224, 16, 16)
    assert _rgb(_preview(face, artwork, {"play": "⏸"}), 20, 50) == (224, 16, 16)
    window._play.click()
    assert sent == [("player.pause", {})]
    assert window._play.property("playing") is True
    assert _rgb(window._play.grab().toImage(), 10, 10) == (128, 64, 64)


def test_pressed_and_playing_pressed_artist_states(audion_player):
    window, _, _, _ = audion_player
    window._play.clearFocus()
    window._play.setDown(True)
    assert _rgb(window._play.grab().toImage(), 10, 10) == (16, 16, 224)
    window._play.setProperty("playing", True)
    assert _rgb(window._play.grab().toImage(), 10, 10) == (224, 16, 224)


def test_bitmap_elapsed_matches_native_and_picker_without_duration_overlay(audion_player):
    window, _, face, artwork = audion_player
    native = window._surface.grab().toImage()
    preview = _preview(face, artwork, {"time": "3:48 / 4:30"})
    for digit, value in zip(face.time_digits, (0, 3, 4, 8), strict=True):
        x, y, width, height = digit.rect
        point = x + width // 2, y + height // 2
        assert _rgb(native, *point) == _rgb(preview, *point) == (value * 20, 180, 60)
    assert window._time.text() == window._time.toolTip() == "3:48 / 4:30"


@pytest.mark.parametrize("elapsed", ["101:05", "–:––"])
def test_bitmap_time_fallback_keeps_truthful_elapsed(audion_player, elapsed, monkeypatch):
    from PySide6.QtGui import QPainter

    window, _, face, artwork = audion_player
    texts = []
    original = QPainter.drawText

    def record_text(painter, *args):
        if isinstance(args[-1], str):
            texts.append(args[-1])
        return original(painter, *args)

    monkeypatch.setattr(QPainter, "drawText", record_text)
    window._time.setText(f"{elapsed} / 120:00")
    window._time.grab()
    assert texts == [elapsed]
    texts.clear()
    _preview(face, artwork, {"time": f"{elapsed} / 120:00"})
    assert elapsed in texts
    assert f"{elapsed} / 120:00" not in texts


def test_custom_tiny_readout_fonts_colors_and_optional_widgets_reset(audion_player, qapp):
    from PySide6.QtCore import Qt

    window, _, face, _ = audion_player
    assert window._title.font().family() == face.readout_styles["title"]["fontFamily"]
    assert window._title.font().pixelSize() == 7
    assert window._title.font().italic()
    assert window._title.property("readoutColor") == "#ff3040"
    assert window._title.alignment() == Qt.AlignmentFlag.AlignCenter
    for name in ("art", "like", "show", "hide", "menu", "previous", "next"):
        assert window._controls[name].isHidden()
    window.select_face("amber-classic")
    qapp.processEvents()
    assert all(not widget.isHidden() for widget in window._controls.values())
    assert not window._time._digits
    assert not window._title.font().italic()
    assert window._title.property("readoutColor") is None


def test_imported_font_name_is_never_interpolated_into_stylesheet(audion_face, qapp):
    from amberfader.ui.face_surface import face_stylesheet, readout_font

    family = 'fake"; color: #abcdef; /*'
    face = replace(audion_face, readout_styles=_frozen({
        "title": _frozen({"fontFamily": family, "size": 7}),
    }))
    assert family not in face_stylesheet(face, 1)
    assert readout_font(face, "title").family() != family


def test_unavailable_imported_font_uses_system_default_without_changing_saved_name(qapp, tmp_path):
    from PySide6.QtGui import QFontDatabase

    from amberfader.face_document import FaceDocument
    from amberfader.face_library import BUILTIN_DIRECTORY, load_face
    from amberfader.ui.face_surface import readout_font

    family = "Amberfader Definitely Unavailable Classic Font"
    assert family not in QFontDatabase.families()
    document = FaceDocument.from_template(BUILTIN_DIRECTORY / "amber-classic")
    document.set_value(("readoutStyles", "title", "fontFamily"), family)
    face = document.preview()
    font = readout_font(face, "title")
    assert font.family() == QFontDatabase.systemFont(QFontDatabase.SystemFont.GeneralFont).family()
    assert face.readout_styles["title"]["fontFamily"] == family
    target = document.save(tmp_path / "saved-font")
    reopened = load_face(target)
    assert reopened.readout_styles["title"]["fontFamily"] == family
    assert readout_font(reopened, "title").family() == font.family()


def test_one_pixel_native_control_has_nonnegative_corner_style(audion_face, qapp):
    from amberfader.ui.face_surface import face_stylesheet

    face = replace(audion_face, controls=_frozen({"play": (10, 40, 1, 1)}))
    assert "QPushButton#play { border-radius: 0px; }" in face_stylesheet(face, 1)


@pytest.mark.parametrize("name,method", [("seek", "player.seek"), ("volume", "player.setVolume")])
def test_popup_drag_uses_original_command_path_once(audion_player, qapp, name, method):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest

    window, sent, _, _ = audion_player
    owner = window._controls[name]
    pressed, moved, released = (
        QSignalSpy(owner.sliderPressed), QSignalSpy(owner.sliderMoved),
        QSignalSpy(owner.sliderReleased),
    )
    slider = _open_popup(owner, qapp)
    assert sent == []
    end = _start_drag(slider)
    assert owner.isSliderDown()
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert pressed.count() == released.count() == 1
    assert moved.count() >= 1
    assert len(sent) == 1 and sent[0][0] == method
    if name == "seek":
        assert sent[0][1] == {
            "occurrenceId": "occ-1", "positionSeconds": 270 * owner.value() / 1000,
        }
    else:
        assert sent[0][1] == {"volume": owner.value() / 100}


@pytest.mark.parametrize("name", ["seek", "volume"])
@pytest.mark.parametrize("cancel", ["escape", "disabled", "face-switch"])
def test_popup_gesture_cancellation_never_commits(audion_player, qapp, name, cancel):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, sent, _, _ = audion_player
    owner = window._controls[name]
    slider = _open_popup(owner, qapp)
    _start_drag(slider)
    if cancel == "escape":
        QTest.keyClick(owner._popup, Qt.Key.Key_Escape)
    elif cancel == "disabled":
        owner.setEnabled(False)
    else:
        window.select_face("amber-classic")
    qapp.processEvents()
    assert not owner._popup.isVisible()
    assert not owner.isSliderDown()
    assert not window._seeking
    assert sent == []


def test_new_occurrence_cancels_popup_seek_commit(audion_player, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_gui_features import _state

    window, sent, _, _ = audion_player
    slider = _open_popup(window._seek, qapp)
    end = _start_drag(slider)
    window.apply_state(_state(
        track={"occurrenceId": "occ-2", "title": "New song"},
        capabilities=["seek", "volume"],
    ))
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert not window._seeking
    assert sent == []


def test_rotated_popup_anchor_and_hidden_proxy_restore(audion_player, qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from test_face_rotation import proxy_position

    from amberfader.ui.face_surface import prepare_face

    window, sent, face, _ = audion_player
    face = replace(face, control_rotations=_frozen({"volume": 25, "play": -20}))
    window._apply_face(face, prepare_face(face))
    qapp.processEvents()
    wrapper = window._surface._rotated["volume"]
    center = proxy_position(wrapper, window._vol.rect().center())
    expected = window._surface.control_global_position(
        "volume", window._vol, QPoint(0, window._vol.height()),
    )
    QTest.mouseClick(wrapper.viewport(), Qt.MouseButton.LeftButton, pos=center)
    qapp.processEvents()
    assert window._vol._popup.isVisible()
    assert window._vol._popup.frameGeometry().topLeft() == expected
    assert sent == []
    absent = replace(face, controls=_frozen({"title": face.controls["title"]}),
                     buttons=_frozen({}), time_digits=(), control_rotations=_frozen({}))
    window._apply_face(absent, prepare_face(absent))
    assert not window._surface._rotated
    assert window._vol.isHidden() and window._play.isHidden()
    assert not window._vol._popup.isVisible()
    window.select_face("amber-classic")
    assert window._vol.parent() is window._surface
    assert not window._vol.isHidden()


def test_right_click_exposes_player_menu_when_original_face_has_no_menu(audion_player, qapp):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication

    window, sent, _, _ = audion_player
    point = QPoint(150, 90)
    event = QContextMenuEvent(
        QContextMenuEvent.Reason.Mouse, point, window._surface.mapToGlobal(point),
    )
    QApplication.sendEvent(window._surface, event)
    qapp.processEvents()
    assert window._btn_menu.isHidden()
    assert window._import_menu.isVisible()
    assert any(action.text() == "Face editor…" for action in window._import_menu.actions())
    assert sent == []


def test_imported_context_menu_restores_missing_like_and_browser_actions(audion_player, qapp):
    from PySide6.QtCore import QPoint
    from test_gui_features import _state

    window, sent, _, _ = audion_player
    window.apply_state(_state(capabilities=["play", "setLiked"], liked=False))
    assert window._like.isHidden() and window._btn_show.isHidden()
    window._popup_menu(window._surface.mapToGlobal(QPoint(100, 90)))
    qapp.processEvents()
    popup = next(menu for menu in window.findChildren(type(window._menu))
                 if menu.isVisible())
    playback = next(action.menu() for action in popup.actions() if action.text() == "Playback")
    like = next(action for action in playback.actions() if action.text() == "Like song")
    assert like is window._playback_actions["like"] and like.isEnabled()
    like.trigger()
    assert sent == [("player.setLiked", {"occurrenceId": "occ-1", "liked": True})]
    assert not like.isEnabled()
    for text, method in [("Show YouTube Music", "browser.showPlayer"),
                         ("Hide YouTube Music", "browser.hidePlayer")]:
        action = next(action for action in popup.actions() if action.text() == text)
        action.trigger()
        assert sent[-1] == (method, {})
    popup.hide()
    window.select_face("amber-classic")
    window._popup_menu(window._surface.mapToGlobal(QPoint(100, 90)))
    assert window._menu.isVisible()
    assert all(action.text() != "Playback" for action in window._menu.actions())


def test_imported_regions_may_cross_alpha_edge_but_cannot_be_invisible(audion_face, qapp):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QImage

    from amberfader.ui.face_surface import prepare_face

    image = QImage.fromData(audion_face.background)
    for x in range(10, 20):
        for y in range(40, 60):
            image.setPixelColor(x, y, Qt.GlobalColor.transparent)
    raw = QByteArray()
    buffer = QBuffer(raw)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    half_visible = replace(audion_face, alpha_mask=bytes(raw))
    prepare_face(half_visible)
    invisible = replace(half_visible, controls=_frozen({"play": (10, 40, 10, 20)}))
    with pytest.raises(FaceError, match="play must sit"):
        prepare_face(invisible)


def test_global_alpha_mask_composites_children_once_in_native_and_preview(audion_player, qapp):
    from amberfader.ui.face_surface import prepare_face

    window, _, face, _ = audion_player
    face = replace(face, alpha_mask=png(*face.size, b"\xe0\x10\x30\x80"))
    artwork = prepare_face(face)
    window._apply_face(face, artwork)
    window._play.clearFocus()
    qapp.processEvents()
    native = window._surface.grab().toImage()
    preview = _preview(face, artwork)
    # RGB mask channels are irrelevant; repeated masking would produce alpha64.
    for point, color in [((150, 90), (32, 32, 32)), ((20, 50), (16, 224, 16))]:
        assert preview.pixelColor(*point).alpha() == 128
        assert native.pixelColor(*point).alpha() == 128
        actual = _rgb(preview, *point)
        assert actual == _rgb(native, *point)
        assert all(abs(left - right) <= 1 for left, right in zip(actual, color, strict=True))
    window.select_face("amber-classic")
    qapp.processEvents()
    assert window._surface.graphicsEffect() is None


def test_global_alpha_mask_owns_shaped_hit_region(audion_face, qapp):
    from PySide6.QtCore import QPoint

    from amberfader.ui.face_surface import prepare_face

    face = replace(audion_face, alpha_mask=png(*audion_face.size, b"\x80\x40\x20\x00"))
    with pytest.raises(FaceError, match="must sit"):
        prepare_face(face)
    face = replace(face, alpha_mask=png(*face.size, b"\x00\x00\x00\xff"),
                   background=png(*face.size, b"\x00\x00\x00\x00"))
    artwork = prepare_face(face)
    assert artwork.mask.contains(QPoint(20, 50))


@pytest.mark.parametrize("scale", [1, 1.5, 2])
def test_global_mask_keeps_rotated_children_at_player_scale(audion_player, qapp, scale):
    from amberfader.ui.face_surface import prepare_face

    window, _, face, _ = audion_player
    face = replace(face, alpha_mask=png(*face.size, b"\x00\x00\x00\x80"),
                   control_rotations=_frozen({"play": 25, "volume": -20}))
    window._scale = scale
    window._apply_face(face, prepare_face(face))
    window._play.clearFocus()
    qapp.processEvents()
    native = window._surface.grab().toImage()
    color = native.pixelColor(round(20 * scale), round(50 * scale))
    assert color.alpha() == 128
    assert abs(color.red() - 16) <= 1 and abs(color.green() - 224) <= 1


@pytest.mark.parametrize("alpha", [1, 65, 127])
@pytest.mark.parametrize("scale", [1, 1.5, 2])
def test_imported_translucent_screen_is_visible_and_hittable(audion_player, qapp, alpha, scale):
    from PySide6.QtCore import QPoint

    from amberfader.ui.face_surface import prepare_face

    window, _, face, _ = audion_player
    face = replace(face, alpha_mask=png(*face.size, bytes((80, 160, 240, alpha))))
    artwork = prepare_face(face)
    assert artwork.mask.contains(QPoint(60, 49))
    window._scale = scale
    window._apply_face(face, artwork)
    qapp.processEvents()
    assert window.mask().contains(QPoint(round(60 * scale), round(49 * scale)))
    assert window._surface.grab().toImage().pixelColor(round(60 * scale), round(49 * scale)).alpha()


def test_legacy_translucent_cutouts_keep_threshold_mask(audion_face, qapp):
    from amberfader.ui.face_surface import prepare_face

    face = replace(audion_face, format_version=2,
                   background=png(*audion_face.size, b"\x00\x00\x00\x41"))
    with pytest.raises(FaceError, match="must sit"):
        prepare_face(face)


def test_repeated_asset_references_share_one_local_decode(audion_face, qapp, monkeypatch):
    from amberfader.ui import face_surface

    shared = audion_face.background
    other = png(2, 2, b"\x90\x40\x20\xff")
    face = replace(audion_face, alpha_mask=shared,
                   buttons=_frozen({"play": _frozen({
                       "normal": shared, "playing": shared, "pressed": other, "hover": other,
                   })}),
                   time_digits=tuple(TimeDigit(digit.rect, (shared,) * 10)
                                     for digit in audion_face.time_digits))
    decoded = []
    original = face_surface._decode

    def record_decode(data):
        decoded.append(data)
        return original(data)

    monkeypatch.setattr(face_surface, "_decode", record_decode)
    artwork = face_surface.prepare_face_preview(face)
    assert decoded == [shared, other]
    key = artwork.background.cacheKey()
    assert artwork.alpha_mask.cacheKey() == key
    assert artwork.buttons["play"]["normal"].cacheKey() == key
    assert artwork.buttons["play"]["playing"].cacheKey() == key
    assert {image.cacheKey() for digit in artwork.time_digits for image in digit.images} == {key}
    assert (
        artwork.buttons["play"]["hover"].cacheKey()
        == artwork.buttons["play"]["pressed"].cacheKey()
    )
    # A later draft owns a fresh bounded cache, rather than retaining old PNGs.
    decoded.clear()
    face_surface.prepare_face_preview(face)
    assert decoded == [shared, other]


@pytest.mark.parametrize("scale", [1, 1.5, 2])
def test_maskless_face_keeps_button_holes_and_every_sprite_state_hittable(
    audion_player, qapp, scale,
):
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, Qt
    from PySide6.QtGui import QColor, QImage
    from test_gui_features import _state

    from amberfader.ui.face_surface import prepare_face

    window, _, face, _ = audion_player

    def half_sprite(first, last, color):
        image = QImage(20, 20, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        for x in range(first, last):
            for y in range(20):
                image.setPixelColor(x, y, QColor(color))
        raw = QByteArray()
        buffer = QBuffer(raw)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        image.save(buffer, "PNG")
        return bytes(raw)

    sprites = _frozen({"normal": half_sprite(0, 8, "#10e010"),
                       "playing": half_sprite(12, 20, "#e01010")})
    face = replace(face, background=png(*face.size, b"\x00\x00\x00\x00"),
                   buttons=_frozen({**face.buttons, "play": sprites}))
    artwork = prepare_face(face)
    assert artwork.mask.contains(QPoint(12, 50))
    assert artwork.mask.contains(QPoint(27, 50))
    assert artwork.mask.contains(QPoint(60, 15))  # Changing text can fill its readout.
    assert not artwork.mask.contains(QPoint(20, 90))
    window._scale = scale
    window._apply_face(face, artwork)
    original_mask = window.mask()
    for status, x, expected in [("paused", 12, (16, 224, 16)),
                                ("playing", 27, (224, 16, 16))]:
        window.apply_state(_state(status=status, capabilities=["play", "pause", "volume", "seek"]))
        window._play.clearFocus()
        qapp.processEvents()
        assert window._surface.graphicsEffect() is None
        assert window.mask() == original_mask
        assert window.mask().contains(QPoint(round(12 * scale), round(50 * scale)))
        assert window.mask().contains(QPoint(round(27 * scale), round(50 * scale)))
        native = window._surface.grab().toImage()
        assert _rgb(native, round(x * scale), round(50 * scale)) == expected


def test_reopened_popup_refreshes_accessibility_labels(audion_player, qapp):
    window, _, _, _ = audion_player
    owner = window._vol
    slider = _open_popup(owner, qapp)
    owner.cancel_popup()
    owner.setAccessibleName("Output volume")
    owner.setToolTip("Change output volume")
    assert _open_popup(owner, qapp) is slider
    assert slider.accessibleName() == "Output volume"
    assert slider.toolTip() == "Change output volume"


@pytest.mark.parametrize("rotation", [0, 25])
def test_reopened_popup_follows_its_anchor_screen(audion_player, qapp, monkeypatch, rotation):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QGuiApplication

    from amberfader.ui.face_surface import prepare_face

    window, _, face, _ = audion_player
    owner = window._vol
    _open_popup(owner, qapp)
    owner.cancel_popup()
    face = replace(face, control_rotations=_frozen({"volume": rotation}))
    window._apply_face(face, prepare_face(face))
    window.move(900, 100)
    qapp.processEvents()
    anchor = window._surface.control_global_position(
        "volume", owner, QPoint(0, owner.height()),
    )

    class SecondaryScreen:
        def availableGeometry(self):
            return QRect(800, 0, 800, 800)

    def screen_at(point):
        assert point == anchor
        return SecondaryScreen()

    monkeypatch.setattr(QGuiApplication, "screenAt", screen_at)
    # Reusing a popup created on another monitor must not clamp to its old screen.
    owner._show_popup()
    qapp.processEvents()
    assert owner._popup.frameGeometry().topLeft() == anchor
