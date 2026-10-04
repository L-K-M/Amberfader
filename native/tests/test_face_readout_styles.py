"""Readout presentation remains bounded and resets when the face changes."""
import json

import pytest
from test_faces import make_pack

from amberfader.face_library import FaceError, FaceLibrary, load_face

READOUT_STYLES = {
    "title": {"align": "center", "font": "mono", "size": 18, "bold": False},
    "artists": {"align": "center", "font": "mono", "size": 14, "bold": True},
    "time": {"align": "center", "font": "serif", "size": 31, "bold": True},
    "playback": {"align": "right", "font": "serif", "size": 15},
    "status": {"align": "center", "font": "mono", "size": 11, "bold": True},
}


@pytest.fixture()
def styled_pack(tmp_path):
    directory, data = make_pack(tmp_path)
    data.update(formatVersion=2, readoutStyles=json.loads(json.dumps(READOUT_STYLES)))
    (directory / "face.json").write_text(json.dumps(data))
    return directory, data


@pytest.mark.parametrize("styles", [
    None, [], "center",
    {"seek": {"align": "center"}},
    {"title": None}, {"title": []}, {"title": "center"},
    {"title": {"align": "justify"}}, {"title": {"align": True}},
    {"title": {"font": "sans-serif; color:red"}},
    {"title": {"font": "comic"}},
    {"title": {"size": 9}}, {"title": {"size": 37}},
    {"title": {"size": 12.5}}, {"title": {"size": True}},
    {"title": {"bold": "true"}},
    {"title": {"padding": 4}},
])
def test_readout_styles_reject_unbounded_or_unknown_presentation(styled_pack, styles):
    directory, data = styled_pack
    data["readoutStyles"] = styles
    (directory / "face.json").write_text(json.dumps(data))
    with pytest.raises(FaceError):
        load_face(directory)


@pytest.mark.parametrize("styles", [{}, {"title": {"align": "center"}}])
def test_legacy_manifest_rejects_readout_styles(styled_pack, styles):
    directory, data = styled_pack
    data.update(formatVersion=1, readoutStyles=styles)
    (directory / "face.json").write_text(json.dumps(data))
    with pytest.raises(FaceError):
        load_face(directory)


@pytest.mark.parametrize("version", [1, 2])
def test_absent_readout_styles_inherit_each_faces_defaults(styled_pack, qapp, version):
    from PySide6.QtCore import Qt

    from amberfader.ui.face_surface import readout_style

    directory, data = styled_pack
    data.pop("readoutStyles")
    data.update(formatVersion=version, font="serif", timeSize=29)
    (directory / "face.json").write_text(json.dumps(data))
    face = load_face(directory)
    assert not face.readout_styles
    for name in READOUT_STYLES:
        style = readout_style(face, name)
        assert style.alignment == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        assert style.font == ("mono" if name == "time" else "serif")
        assert style.size == (29 if name == "time" else 12)
        assert style.bold == (name == "title")


@pytest.mark.parametrize("size", [10, 36])
def test_partial_readout_styles_inherit_unspecified_fields(styled_pack, qapp, size):
    from PySide6.QtCore import Qt

    from amberfader.ui.face_surface import readout_style

    directory, data = styled_pack
    data.update(font="serif", timeSize=29, readoutStyles={
        "title": {"align": "center", "size": size}, "time": {"bold": True},
    })
    (directory / "face.json").write_text(json.dumps(data))
    face = load_face(directory)
    title = readout_style(face, "title")
    assert title.alignment == Qt.AlignmentFlag.AlignCenter
    assert title.font == "serif"
    assert title.size == size
    assert title.bold is True
    time = readout_style(face, "time")
    assert time.font == "mono"
    assert time.size == 29
    assert time.bold is True
    assert dict(face.readout_styles["time"]) == {"bold": True}


def test_readout_styles_survive_install_and_restart_as_readonly_data(styled_pack, tmp_path):
    directory, _ = styled_pack
    face = load_face(directory)
    assert {name: dict(style) for name, style in face.readout_styles.items()} == READOUT_STYLES
    with pytest.raises(TypeError):
        face.readout_styles["title"]["size"] = 22
    with pytest.raises(TypeError):
        face.readout_styles["extra"] = {}

    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(directory)
    restarted = FaceLibrary(library.ensure_directory(), tmp_path / "appearance.json")
    restored = restarted.load(info.id)
    assert {name: dict(style) for name, style in restored.readout_styles.items()} == READOUT_STYLES


def test_readout_styles_reset_to_legacy_defaults_after_face_switch(styled_pack, qapp, tmp_path):
    from PySide6.QtCore import Qt

    from amberfader.ui.face_surface import FONT_FAMILIES
    from amberfader.ui.main_window import MainWindow

    directory, _ = styled_pack
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(directory)
    # A plain pack, so the reset does not depend on bundled face presentation.
    (tmp_path / "plain").mkdir()
    plain_directory, plain_data = make_pack(tmp_path / "plain")
    plain_data.update(id="plain-face", name="Plain Face")
    (plain_directory / "face.json").write_text(json.dumps(plain_data))
    plain = library.install(plain_directory)
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    original = dict(window._controls)
    try:
        window.select_face(info.id)
        qapp.processEvents()
        for name, style in READOUT_STYLES.items():
            label = window._controls[name]
            label.ensurePolished()
            horizontal = (
                Qt.AlignmentFlag.AlignRight if style["align"] == "right"
                else Qt.AlignmentFlag.AlignHCenter
            )
            assert label.alignment() == horizontal | Qt.AlignmentFlag.AlignVCenter
            assert label.font().family() == FONT_FAMILIES[style["font"]]
            assert label.font().pixelSize() == style["size"]
            assert label.font().bold() == style.get("bold", False)

        window.select_face(plain.id)
        qapp.processEvents()
        classic = library.load(plain.id)
        for name in READOUT_STYLES:
            label = window._controls[name]
            label.ensurePolished()
            assert label.alignment() == Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            family = "mono" if name == "time" else classic.font
            assert label.font().family() == FONT_FAMILIES[family]
            assert label.font().pixelSize() == (classic.time_size if name == "time" else 12)
            assert label.font().bold() == (name == "title")
        assert window._controls == original
        assert sent == []
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_mono_readout_resolves_fixed_pitch_after_stylesheet_polish(
    styled_pack, qapp, tmp_path,
):
    from PySide6.QtGui import QFontInfo

    from amberfader.ui.face_surface import readout_font
    from amberfader.ui.main_window import MainWindow

    directory, _ = styled_pack
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(directory)
    face = library.load(info.id)
    window = MainWindow(lambda *_: None, faces=library)
    try:
        window.select_face(info.id)
        qapp.processEvents()
        label = window._controls["title"]
        label.ensurePolished()
        # Check the resolved font, not merely the requested generic family.
        assert QFontInfo(readout_font(face, "title")).fixedPitch()
        assert QFontInfo(label.font()).fixedPitch()
    finally:
        window.close()
        window.deleteLater()
        qapp.processEvents()


def test_picker_and_native_paint_identical_readout_typography(
    styled_pack, qapp, tmp_path, monkeypatch,
):
    from PySide6.QtGui import QFont, QFontInfo, QFontMetrics, QPainter
    from PySide6.QtWidgets import QWidget

    from amberfader.ui import face_surface, faces_window
    from amberfader.ui.main_window import MainWindow

    directory, data = styled_pack
    data["controls"]["time"][2:] = [140, 26]
    # Room for PREVIEW in 15 px serif, so neither painter elides the sample.
    data["controls"]["playback"] = [416, 145, 96, 20]
    data["readoutStyles"]["time"]["size"] = 36
    (directory / "face.json").write_text(json.dumps(data))
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(directory)
    face = library.load(info.id)
    draws = {}

    def recording_painter(target):
        class RecordingPainter(QPainter):
            def drawText(self, rect, flags, text):
                draws[target, text] = QFont(self.font()), flags, rect
                return super().drawText(rect, flags, text)

        return RecordingPainter

    monkeypatch.setattr(face_surface, "QPainter", recording_painter("native"))
    monkeypatch.setattr(faces_window, "QPainter", recording_painter("picker"))
    window = MainWindow(lambda *_: None, faces=library)
    parent = QWidget()
    preview = faces_window.FacePreview(parent)
    preview.resize(720, 480)
    try:
        window.select_face(info.id)
        window._tick.stop()
        window._status_timer.stop()
        for name in READOUT_STYLES:
            label = window._controls[name]
            label.setText(faces_window.PREVIEW_LABELS[name])
            label.grab()
        preview.set_face(face, face_surface.prepare_face(face))
        preview.grab()
        for name in READOUT_STYLES:
            text = faces_window.PREVIEW_LABELS[name]
            native_font, native_flags, native_rect = draws["native", text]
            picker_font, picker_flags, picker_rect = draws["picker", text]
            assert native_flags == picker_flags, name
            assert native_font.family() == picker_font.family(), name
            assert native_font.bold() == picker_font.bold(), name
            assert native_font.pixelSize() == picker_font.pixelSize(), name
            assert native_rect.size() == picker_rect.size(), name
            if READOUT_STYLES[name]["font"] == "mono":
                assert QFontInfo(native_font).fixedPitch(), name
                assert QFontInfo(picker_font).fixedPitch(), name
            if name == "time":
                metrics = QFontMetrics(native_font)
                assert metrics.horizontalAdvance(text) <= native_rect.width()
                assert 10 <= native_font.pixelSize() <= native_rect.height() - 2
    finally:
        window.close()
        parent.close()
        window.deleteLater()
        parent.deleteLater()
        qapp.processEvents()


def test_picker_mono_readout_does_not_restyle_native_button_font(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QFont, QFontInfo, QPainter
    from PySide6.QtWidgets import QWidget

    from amberfader.ui import face_surface, faces_window
    from amberfader.ui.main_window import MainWindow

    draws = {}

    def recording_painter(target):
        class RecordingPainter(QPainter):
            def drawText(self, rect, flags, text):
                draws[target, text] = QFont(self.font())
                return super().drawText(rect, flags, text)

        return RecordingPainter

    monkeypatch.setattr(face_surface, "QPainter", recording_painter("native"))
    monkeypatch.setattr(faces_window, "QPainter", recording_painter("picker"))
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    window = MainWindow(lambda *_: None, faces=library)
    parent = QWidget()
    preview = faces_window.FacePreview(parent)
    try:
        window.select_face("viridian")
        face = library.load("viridian")
        preview.resize(face.size[0] + 24, face.size[1] + 24)
        button = window._controls["search"]
        button.ensurePolished()
        button.grab()
        preview.set_face(face, face_surface.prepare_face(face))
        preview.grab()
        native = QFontInfo(draws["native", button.text()])
        picker = QFontInfo(draws["picker", faces_window.PREVIEW_LABELS["search"]])
        assert picker.fixedPitch() == native.fixedPitch()
        assert picker.family() == native.family()
    finally:
        window.close()
        parent.close()
        window.deleteLater()
        parent.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("value", [None, True, {}, "round", "inset; color:red"])
def test_slider_style_is_a_constrained_token(styled_pack, value):
    directory, data = styled_pack
    data.pop("readoutStyles")
    data["sliderStyle"] = value
    (directory / "face.json").write_text(json.dumps(data))
    with pytest.raises(FaceError):
        load_face(directory)


def test_legacy_manifest_rejects_inset_slider_style(styled_pack):
    directory, data = styled_pack
    data.pop("readoutStyles")
    data.update(formatVersion=1, sliderStyle="inset")
    (directory / "face.json").write_text(json.dumps(data))
    with pytest.raises(FaceError):
        load_face(directory)


@pytest.mark.parametrize("style", [None, "classic", "inset"])
def test_format_two_slider_style_retains_classic_default(styled_pack, style):
    directory, data = styled_pack
    data.pop("readoutStyles")
    if style is not None:
        data["sliderStyle"] = style
    (directory / "face.json").write_text(json.dumps(data))
    assert load_face(directory).slider_style == (style or "classic")


@pytest.fixture()
def slider_window(styled_pack, qapp, tmp_path):
    from test_gui_features import _state

    from amberfader.ui.main_window import MainWindow

    directory, data = styled_pack
    data["sliderStyle"] = "inset"
    (directory / "face.json").write_text(json.dumps(data))
    library = FaceLibrary(tmp_path / "installed", tmp_path / "appearance.json")
    info = library.install(directory)
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    window.select_face(info.id)
    window.apply_state(_state(capabilities=["seek", "volume"]))
    window._tick.stop()
    window.show()
    qapp.processEvents()
    yield window, sent
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _slider_handle(slider):
    from PySide6.QtWidgets import QStyle, QStyleOptionSlider

    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    return slider.style().subControlRect(
        QStyle.ComplexControl.CC_Slider, option, QStyle.SubControl.SC_SliderHandle, slider,
    )


@pytest.mark.parametrize("face_id", ["my-face", "amber-classic"])
def test_slider_keyboard_values_and_actions_survive_presentation_change(slider_window, face_id):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest
    from PySide6.QtWidgets import QAbstractSlider

    window, sent = slider_window
    original = window._seek, window._vol
    window.select_face(face_id)
    assert (window._seek, window._vol) == original
    for slider in original:
        slider.setValue(slider.maximum() // 2)
        values = QSignalSpy(slider.valueChanged)
        actions = QSignalSpy(slider.actionTriggered)
        QTest.keyClick(slider, Qt.Key.Key_Right)
        assert slider.value() == slider.maximum() // 2 + slider.singleStep()
        assert actions.at(0)[0] == QAbstractSlider.SliderAction.SliderSingleStepAdd.value
        QTest.keyClick(slider, Qt.Key.Key_Home)
        assert slider.value() == slider.minimum()
        QTest.keyClick(slider, Qt.Key.Key_End)
        assert slider.value() == slider.maximum()
        assert values.count() == 3
    assert sent == []


@pytest.mark.parametrize("name,method", [("seek", "player.seek"), ("volume", "player.setVolume")])
def test_slider_thumb_drag_keeps_native_signals_and_command_mapping(slider_window, name, method):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QSignalSpy, QTest

    window, sent = slider_window
    slider = window._controls[name]
    slider.setValue(slider.maximum() // 4)
    pressed = QSignalSpy(slider.sliderPressed)
    moved = QSignalSpy(slider.sliderMoved)
    released = QSignalSpy(slider.sliderReleased)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=_slider_handle(slider).center())
    assert slider.isSliderDown()
    end = QPoint(3 * slider.width() // 4, slider.height() // 2)
    QTest.mouseMove(slider, end)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert pressed.count() == released.count() == 1
    assert moved.count() > 0
    assert slider.value() > slider.maximum() // 2
    assert not slider.isSliderDown()
    expected = (
        {"occurrenceId": "occ-1", "positionSeconds": 200 * slider.value() / 1000}
        if name == "seek" else {"volume": slider.value() / 100}
    )
    assert sent == [(method, expected)]


def test_switching_slider_style_during_seek_preserves_the_active_gesture(slider_window, qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    window, sent = slider_window
    slider = window._seek
    slider.setValue(250)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=_slider_handle(slider).center())
    assert window._seeking
    window.select_face("amber-classic")
    qapp.processEvents()
    assert window._seek is slider
    assert slider.isSliderDown()
    end = QPoint(3 * slider.width() // 4, slider.height() // 2)
    QTest.mouseMove(slider, end)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert sent == [("player.seek", {
        "occurrenceId": "occ-1", "positionSeconds": 200 * slider.value() / 1000,
    })]
    assert not window._seeking


def test_slider_drag_never_seeks_a_new_occurrence(slider_window):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from test_gui_features import _state

    window, sent = slider_window
    slider = window._seek
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=_slider_handle(slider).center())
    newer = _state(capabilities=["seek", "volume"])
    newer["track"]["occurrenceId"] = "occ-new"
    window.apply_state(newer)
    end = QPoint(3 * slider.width() // 4, slider.height() // 2)
    QTest.mouseMove(slider, end)
    QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=end)
    assert sent == []
    assert not window._seeking


def _logical_color(image, point):
    ratio = image.devicePixelRatio()
    return image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))


def test_inset_slider_paints_a_metal_thumb_at_qts_interactive_handle(slider_window):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor

    window, sent = slider_window
    slider = window._seek
    slider.setValue(500)
    face = window._faces.load("my-face")
    center = _slider_handle(slider).center()
    metal = center - QPoint(0, 4)
    inset = slider.grab().toImage()
    assert _logical_color(inset, center) == QColor(face.palette["accent"])
    window.select_face("amber-classic")
    assert _slider_handle(slider).center() == center
    classic = slider.grab().toImage()
    assert _logical_color(inset, metal) != _logical_color(classic, metal)
    assert slider.value() == 500
    assert sent == []


@pytest.mark.parametrize("reverse,rtl", [
    (False, False), (True, False), (False, True), (True, True),
])
def test_inset_slider_zero_value_has_no_filled_track_in_either_direction(
    slider_window, reverse, rtl,
):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QColor

    window, sent = slider_window
    slider = window._seek
    slider.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight,
    )
    slider.setInvertedAppearance(reverse)
    slider.setValue(slider.minimum())
    image = slider.grab().toImage()
    accent = QColor(window._faces.load("my-face").palette["accent"])
    for numerator in (1, 3):
        point = QPoint(numerator * slider.width() // 4, slider.height() // 2)
        assert _logical_color(image, point) != accent
    assert sent == []


def test_disabled_inset_slider_uses_muted_core_and_ignores_input(slider_window):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtTest import QTest

    window, sent = slider_window
    slider = window._seek
    slider.setValue(500)
    slider.setEnabled(False)
    center = _slider_handle(slider).center()
    image = slider.grab().toImage()
    muted = QColor(window._faces.load("my-face").palette["muted"])
    assert _logical_color(image, center) == muted
    QTest.keyClick(slider, Qt.Key.Key_Right)
    QTest.mouseClick(slider, Qt.MouseButton.LeftButton, pos=center)
    assert slider.value() == 500
    assert sent == []


def test_keyboard_focus_is_visible_on_the_inset_slider(slider_window, qapp):
    from PySide6.QtCore import Qt

    window, sent = slider_window
    slider = window._seek
    window._art.setFocus()
    unfocused = slider.grab().toImage()
    slider.setFocus(Qt.FocusReason.TabFocusReason)
    qapp.processEvents()
    assert slider.hasFocus()
    focused = slider.grab().toImage()
    assert focused != unfocused
    assert sent == []


def test_picker_and_runtime_use_inset_slider_presentation(slider_window, qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from amberfader.ui import face_surface, faces_window

    window, sent = slider_window
    face = window._faces.load("my-face")
    calls = []
    original = face_surface.draw_slider

    def record(target):
        def draw(*args, **kwargs):
            calls.append((target, args[1], args[2], dict(args[3])))
            return original(*args, **kwargs)

        return draw

    monkeypatch.setattr(face_surface, "draw_slider", record("native"))
    monkeypatch.setattr(faces_window, "draw_slider", record("picker"))
    parent = QWidget()
    preview = faces_window.FacePreview(parent)
    preview.resize(face.size[0] + 24, face.size[1] + 24)
    try:
        for name in ("seek", "volume"):
            window._controls[name].setValue(window._controls[name].maximum() // 2)
            window._controls[name].grab()
        preview.set_face(face, face_surface.prepare_face(face))
        preview.grab()
        native = [call for call in calls if call[0] == "native"]
        picker = [call for call in calls if call[0] == "picker"]
        assert len(native) == len(picker) == 2
        native.sort(key=lambda call: call[1].width())
        picker.sort(key=lambda call: call[1].width())
        for runtime, thumbnail in zip(native, picker, strict=True):
            assert runtime[1].size() == thumbnail[1].size()
            assert runtime[2].height() == thumbnail[2].height()
            assert runtime[3] == thumbnail[3] == dict(face.palette)
        calls.clear()
        window.select_face("amber-classic")
        window._seek.grab()
        assert calls == []
        assert sent == []
    finally:
        parent.close()
        parent.deleteLater()
        qapp.processEvents()
