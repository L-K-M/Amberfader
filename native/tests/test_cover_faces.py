"""Cover-first faces make the artwork the hero and keep their readouts legible."""
import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QRegion
from test_lens_faces import _minimum_contrast

from amberfader.face_library import BUILTIN_DIRECTORY, load_face
from amberfader.ui.face_surface import prepare_face

COVER_IDS = ("nightglass", "inner-sleeve", "instant-print", "j-card")
MIN_COVER_EDGE = 320


@pytest.mark.parametrize("face_id", COVER_IDS)
def test_cover_is_the_dominant_element(face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    _, _, width, height = face.controls["art"]
    cover = width * height
    largest_other = max(
        w * h for name, (_, _, w, h) in face.controls.items() if name != "art"
    )
    assert min(width, height) >= MIN_COVER_EDGE
    assert cover >= 0.4 * face.size[0] * face.size[1]
    assert cover >= 4 * largest_other


@pytest.mark.parametrize("face_id", COVER_IDS)
def test_readouts_contrast_with_every_pixel_of_their_wells(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    background = prepare_face(face).background.toImage()
    x_scale = background.width() / face.size[0]
    y_scale = background.height() / face.size[1]
    for name in ("title", "artists", "time", "playback", "status"):
        interior = QRect(*face.controls[name]).adjusted(1, 1, -1, -1)
        rectangle = QRect(
            round(interior.x() * x_scale), round(interior.y() * y_scale),
            round(interior.width() * x_scale), round(interior.height() * y_scale),
        )
        tokens = ("muted", "danger") if name == "status" else ("readout",)
        for token in tokens:
            contrast = _minimum_contrast(QColor(face.palette[token]), background.copy(rectangle))
            assert contrast >= 4.5, (face_id, name, token, contrast)


@pytest.mark.parametrize("face_id", COVER_IDS)
def test_window_mask_keeps_every_control_and_the_drag_region(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    artwork = prepare_face(face)
    for scale in (1.0, 1.5, 2.0):
        size = tuple(round(value * scale) for value in face.size)
        mask = artwork.scaled_mask(size)
        for name, region in {**face.controls, "drag": face.drag}.items():
            rectangle = QRect(*(round(value * scale) for value in region))
            assert QRegion(rectangle).subtracted(mask).isEmpty(), (face_id, scale, name)
