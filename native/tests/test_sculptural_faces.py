"""Sculptural faces keep transparent openings and host-owned states usable."""
import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QRegion
from test_gui_features import _state

from amberfader.face_library import FaceLibrary
from amberfader.ui.face_surface import prepare_face
from amberfader.ui.main_window import MainWindow

SCULPTURAL_IDS = ("orbit-99", "manta-ray", "jellyfish-fm", "boom-bot")
# Substantial openings inside each shape's bounding box, away from its corners:
# between Orbit's body and satellite, under Manta's body inside the tail curl,
# between Jellyfish's left tentacles, and between Boom Bot's torso and feet.
OPENINGS = {
    "orbit-99": (466, 136, 36, 20),
    "manta-ray": (400, 414, 42, 32),
    "jellyfish-fm": (166, 346, 28, 16),
    "boom-bot": (288, 496, 44, 20),
}


@pytest.fixture(params=[1.0, 1.5, 2.0])
def sculptural_window(qapp, tmp_path, request):
    library = FaceLibrary(tmp_path / "faces", tmp_path / "appearance.json")
    sent = []
    window = MainWindow(
        lambda method, params: sent.append((method, params)), scale=request.param, faces=library
    )
    window.show()
    qapp.processEvents()
    yield window, library, sent
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("face_id", SCULPTURAL_IDS)
def test_sculptural_openings_stay_outside_the_scaled_hitmask(
    sculptural_window, qapp, face_id
):
    window, library, _ = sculptural_window
    face = library.load(face_id)
    artwork = prepare_face(face)
    opening = QRect(*OPENINGS[face_id])
    assert QRect(20, 20, face.size[0] - 40, face.size[1] - 40).contains(opening)
    assert QRegion(opening).intersected(artwork.mask).isEmpty()

    window.select_face(face_id)
    qapp.processEvents()
    # Read the fitted window dimensions: a requested 2x face can be reduced to
    # the available screen, while the opening and controls must still agree.
    x_scale = window.width() / face.size[0]
    y_scale = window.height() / face.size[1]
    scaled = QRect(
        round(opening.x() * x_scale), round(opening.y() * y_scale),
        round(opening.width() * x_scale), round(opening.height() * y_scale),
    )
    image = artwork.background.toImage().scaled(window.size()).copy(scaled)
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    assert max(bytes(image.constBits())[3::4]) <= 1
    assert QRegion(scaled).intersected(window.mask()).isEmpty()
    for name, control in window._controls.items():
        assert QRegion(control.geometry()).subtracted(window.mask()).isEmpty(), name
    assert QRegion(window._surface._drag).subtracted(window.mask()).isEmpty()


@pytest.mark.parametrize("face_id", SCULPTURAL_IDS)
def test_sculptural_switch_keeps_pending_states(sculptural_window, qapp, face_id):
    window, _, sent = sculptural_window
    window.apply_state(_state(liked=True))
    window._like.click()
    window._play.click()
    assert sent == [
        ("player.setLiked", {"occurrenceId": "occ-1", "liked": False}),
        ("player.play", {}),
    ]
    sent.clear()

    window.select_face(face_id)
    qapp.processEvents()
    assert window._pending_like and window._pending_transport
    assert window._like.property("pending") and window._play.property("pending")
    assert not window._like.isEnabled() and not window._play.isEnabled()
    assert window._like.text() == "♥"
    window._like.click()
    window._play.click()
    assert not sent

    window.route_response("player.play", True, {})
    assert window._play.isEnabled()
    assert not window._like.isEnabled()
    window.route_response("player.setLiked", True, {})
    assert window._like.isEnabled()


@pytest.mark.parametrize("face_id", SCULPTURAL_IDS)
def test_sculptural_faces_retain_long_metadata_and_time(
    sculptural_window, qapp, face_id
):
    window, _, _ = sculptural_window
    state = _state(positionSeconds=59999, durationSeconds=119999)
    title = "<b>" + "Long song & title " * 30
    artists = "<i>" + "Long artist & collaborator " * 20
    state["track"].update(title=title, artists=[artists])
    window.apply_state(state)
    window.select_face(face_id)
    qapp.processEvents()
    for label, text in ((window._title, title), (window._artists, artists)):
        assert label.textFormat() == Qt.TextFormat.PlainText
        assert label.text() == text
        assert label.toolTip() == text

    expected = "999:59 / 1999:59"
    assert window._time.text() == expected
    assert window._time.toolTip() == expected
