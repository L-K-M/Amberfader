"""Compact faces preserve their contours and usable regions at exact scales."""
import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPalette, QRegion
from PySide6.QtWidgets import QWidget

from amberfader.face_library import BUILTIN_DIRECTORY, load_face
from amberfader.ui.face_surface import FaceButton, face_stylesheet, prepare_face
from amberfader.ui.search_window import SearchWindow

# The first three probes sit inside real rail/vent openings. Keystone is a
# solid badge, so its probe checks the intentionally clipped exterior corner.
CONTOUR_PROBES = (
    ("tangent", ((220, 66, 140, 4),)),
    ("switchback", ((543, 67, 16, 3),)),
    ("vane", ((146, 114, 12, 4), (500, 110, 12, 4))),
    ("keystone", ((4, 4, 30, 30),)),
)


@pytest.mark.parametrize("face_id, probes", CONTOUR_PROBES)
def test_utilitarian_contours_keep_every_control_and_drag_region(qapp, face_id, probes):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    artwork = prepare_face(face)
    for scale in (1.0, 1.5, 2.0):
        size = tuple(round(value * scale) for value in face.size)
        image = artwork.background.toImage().scaled(*size)
        mask = artwork.scaled_mask(size)
        for probe in probes:
            rectangle = QRect(*(round(value * scale) for value in probe))
            pixels = image.copy(rectangle).convertToFormat(QImage.Format.Format_RGBA8888)
            assert max(bytes(pixels.constBits())[3::4]) == 0, (face_id, scale, probe)
            assert QRegion(rectangle).intersected(mask).isEmpty(), (face_id, scale, probe)
        for name, region in {**face.controls, "drag": face.drag}.items():
            rectangle = QRect(*(round(value * scale) for value in region))
            assert QRegion(rectangle).subtracted(mask).isEmpty(), (face_id, scale, name)


def _luminance(color):
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in channels
    ]
    return sum(
        value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722), strict=True)
    )


def _contrast(first, second):
    bright, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("face_id", [face_id for face_id, _ in CONTOUR_PROBES])
def test_disabled_labels_contrast_with_their_artist_surfaces(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    artwork = prepare_face(face)
    parent = QWidget()
    button = FaceButton("", parent)
    button.setObjectName("like")
    button.setStyleSheet(face_stylesheet(face, 1))
    button.setEnabled(False)
    button.ensurePolished()
    foreground = button.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText)
    try:
        for name, states in artwork.buttons.items():
            image = states["disabled"].toImage()
            background = image.pixelColor(image.width() // 2, image.height() // 2)
            assert _contrast(foreground, background) >= 4.5, (face_id, name)
    finally:
        parent.deleteLater()
        qapp.processEvents()


@pytest.mark.parametrize("face_id", ("switchback", "vane"))
def test_light_readout_faces_keep_search_labels_legible(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    dialog = SearchWindow(lambda *_: None)
    dialog.setStyleSheet(face_stylesheet(face, 1))
    dialog.apply_response("search.history", True, {"queries": ["Test query"]})
    dialog.show()
    qapp.processEvents()
    try:
        recent = dialog.findChild(QWidget, "dim")
        assert recent is not None
        assert _contrast(
            recent.palette().color(QPalette.ColorRole.WindowText),
            dialog.palette().color(QPalette.ColorRole.Window),
        ) >= 4.5
        button = dialog._btn_radio
        assert not button.isEnabled()
        foreground = button.palette().color(
            QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText,
        )
        button.setText("")
        image = button.grab().toImage()
        background = image.pixelColor(image.width() // 2, image.height() // 2)
        assert _contrast(foreground, background) >= 4.5
    finally:
        dialog.close()
        dialog.deleteLater()
        qapp.processEvents()
