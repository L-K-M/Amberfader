"""Focus rings follow keyboard navigation instead of marking every face."""
import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import Qt
from test_faces import BUNDLED_IDS

from amberfader.face_library import FaceLibrary
from amberfader.ui.main_window import MainWindow

FOCUSABLE = ("art", "play", "search", "seek")
UNMARKED_REASONS = (
    Qt.FocusReason.MouseFocusReason,
    Qt.FocusReason.OtherFocusReason,
    Qt.FocusReason.ActiveWindowFocusReason,
)


@pytest.fixture()
def player(qapp, tmp_path):
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    sent = []
    window = MainWindow(lambda method, params: sent.append((method, params)), faces=library)
    window.show()
    window.activateWindow()
    qapp.processEvents()
    yield window, sent
    window.close()
    window.deleteLater()
    qapp.processEvents()


def _focus(qapp, window, widget, reason):
    # Park focus on another control so each request delivers a focus-in event.
    other = window._next if widget is not window._next else window._prev
    other.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    widget.setFocus(reason)
    qapp.processEvents()
    assert widget.hasFocus()


@pytest.mark.parametrize("face_id", sorted(BUNDLED_IDS))
def test_startup_focus_leaves_the_cover_unmarked(player, qapp, face_id):
    window, sent = player
    window.select_face(face_id)
    qapp.processEvents()
    window._art.clearFocus()
    qapp.processEvents()
    unfocused = window._art.grab().toImage()
    window._art.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    qapp.processEvents()
    assert window._art.hasFocus()
    assert window._art.grab().toImage() == unfocused
    assert sent == []


@pytest.mark.parametrize("name", FOCUSABLE)
@pytest.mark.parametrize("reason", UNMARKED_REASONS)
def test_pointer_and_window_focus_draw_no_ring(player, qapp, name, reason):
    window, sent = player
    window.select_face("orbit-99")
    widget = window._controls[name]
    window._prev.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    unfocused = widget.grab().toImage()
    _focus(qapp, window, widget, reason)
    assert widget.grab().toImage() == unfocused
    assert sent == []


@pytest.mark.parametrize("name", FOCUSABLE)
@pytest.mark.parametrize(
    "reason", (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason),
)
def test_keyboard_focus_ring_survives_restored_focus(player, qapp, name, reason):
    window, sent = player
    window.select_face("orbit-99")
    widget = window._controls[name]
    window._prev.setFocus(Qt.FocusReason.OtherFocusReason)
    qapp.processEvents()
    unfocused = widget.grab().toImage()
    _focus(qapp, window, widget, reason)
    focused = widget.grab().toImage()
    assert focused != unfocused

    # Qt reports window reactivation as ActiveWindowFocusReason; restoring
    # focus with that reason must not change how it arrived.
    widget.clearFocus()
    widget.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
    qapp.processEvents()
    assert widget.grab().toImage() == focused

    # A later pointer focus hides the ring again.
    _focus(qapp, window, widget, Qt.FocusReason.MouseFocusReason)
    assert widget.grab().toImage() == unfocused
    assert sent == []
