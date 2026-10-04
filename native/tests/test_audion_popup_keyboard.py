"""The original face's popup sliders commit through native keyboard input."""
import pytest
import test_audion_face_rendering as rendering

audion_face = rendering.audion_face
audion_player = rendering.audion_player


def _open_with_enter(owner, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    owner.setFocus()
    QTest.keyClick(owner, Qt.Key.Key_Return)
    qapp.processEvents()
    assert owner._popup.isVisible()
    assert owner._popup_slider.hasFocus()
    return owner._popup_slider


@pytest.mark.parametrize("name", ["seek", "volume"])
def test_enter_opens_popup_without_committing(audion_player, qapp, name):
    window, sent, _, _ = audion_player
    _open_with_enter(window._controls[name], qapp)
    assert sent == []


@pytest.mark.parametrize("name,method", [("seek", "player.seek"), ("volume", "player.setVolume")])
@pytest.mark.parametrize(
    "key", ["Left", "Right", "Up", "Down", "Home", "End", "PageUp", "PageDown"],
)
def test_keyboard_change_commits_once_through_owner(audion_player, qapp, name, method, key):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest

    window, sent, _, _ = audion_player
    owner = window._controls[name]
    owner.setValue(owner.maximum() // 2)
    slider = _open_with_enter(owner, qapp)
    original = owner.value()
    pressed, moved, released = (
        QSignalSpy(owner.sliderPressed), QSignalSpy(owner.sliderMoved),
        QSignalSpy(owner.sliderReleased),
    )
    QTest.keyClick(slider, getattr(Qt.Key, f"Key_{key}"))
    assert owner.value() != original
    assert pressed.count() == released.count() == 1
    assert moved.count() == 1
    assert not owner.isSliderDown() and not slider.isSliderDown()
    assert not window._seeking and window._seek_occ is None
    assert len(sent) == 1 and sent[0][0] == method
    if name == "seek":
        assert sent[0][1] == {
            "occurrenceId": "occ-1", "positionSeconds": 270 * owner.value() / 1000,
        }
    else:
        assert sent[0][1] == {"volume": owner.value() / 100}


@pytest.mark.parametrize("key,bound", [("Home", "minimum"), ("Left", "minimum"),
                                      ("End", "maximum"), ("Right", "maximum")])
def test_keyboard_noop_at_bounds_never_commits(audion_player, qapp, key, bound):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest

    window, sent, _, _ = audion_player
    owner = window._seek
    owner.setValue(getattr(owner, bound)())
    slider = _open_with_enter(owner, qapp)
    pressed, released = QSignalSpy(owner.sliderPressed), QSignalSpy(owner.sliderReleased)
    QTest.keyClick(slider, getattr(Qt.Key, f"Key_{key}"))
    assert pressed.count() == released.count() == 0
    assert not window._seeking
    assert sent == []


@pytest.mark.parametrize("name", ["seek", "volume"])
def test_disabled_owner_rejects_popup_keyboard(audion_player, qapp, name):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    window, sent, _, _ = audion_player
    owner = window._controls[name]
    slider = _open_with_enter(owner, qapp)
    original = owner.value()
    owner.setEnabled(False)
    QTest.keyClick(slider, Qt.Key.Key_Right)
    QTest.keyClick(owner, Qt.Key.Key_Return)
    assert not owner._popup.isVisible()
    assert owner.value() == original
    assert sent == []


@pytest.mark.parametrize("change", ["occurrence", "capability", "face"])
def test_keyboard_commit_retains_seek_safety_guards(audion_player, qapp, change):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from test_gui_features import _state

    window, sent, _, _ = audion_player
    owner = window._seek
    slider = _open_with_enter(owner, qapp)

    def change_state():
        if change == "face":
            window.select_face("amber-classic")
        else:
            window.apply_state(_state(
                track={"occurrenceId": "occ-2" if change == "occurrence" else "occ-1"},
                capabilities=["volume"] if change == "capability" else ["seek", "volume"],
                positionSeconds=228, durationSeconds=270,
            ))

    owner.sliderPressed.connect(change_state)
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert not owner.isSliderDown() and not window._seeking
    assert window._seek_occ is None
    assert sent == []


@pytest.mark.parametrize("name", ["seek", "volume"])
def test_keyboard_does_not_finish_pointer_gesture_and_escape_cancels(audion_player, qapp, name):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest

    window, sent, _, _ = audion_player
    owner = window._controls[name]
    slider = _open_with_enter(owner, qapp)
    released = QSignalSpy(owner.sliderReleased)
    QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=rendering._handle(slider))
    original = owner.value()
    QTest.keyClick(slider, Qt.Key.Key_Right)
    assert owner.isSliderDown() and slider.isSliderDown()
    assert owner.value() == original
    assert released.count() == 0
    assert sent == []
    QTest.keyClick(slider, Qt.Key.Key_Escape)
    assert not owner._popup.isVisible()
    assert not owner.isSliderDown() and not slider.isSliderDown()
    assert not window._seeking and sent == []


def test_escape_after_keyboard_commit_only_dismisses_popup(audion_player, qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QSignalSpy, QTest

    window, sent, _, _ = audion_player
    owner = window._seek
    slider = _open_with_enter(owner, qapp)
    cancelled = QSignalSpy(owner.gestureCancelled)
    QTest.keyClick(slider, Qt.Key.Key_Left)
    assert len(sent) == 1
    QTest.keyClick(slider, Qt.Key.Key_Escape)
    assert not owner._popup.isVisible()
    assert cancelled.count() == 0
    assert len(sent) == 1
