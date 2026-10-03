"""Lens faces keep curved masks and readable text on their generated glass."""
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QImage, QRegion

from amberfader.face_library import BUILTIN_DIRECTORY, load_face
from amberfader.ui.face_surface import prepare_face

LENS_IDS = ("aureole", "viridian")
# Exterior regions beside the curved bodies, beyond ordinary corner cutouts.
CONTOUR_PROBES = {
    "aureole": ((485, 326, 24, 18), (560, 90, 16, 20)),
    "viridian": ((65, 64, 18, 16), (392, 370, 18, 14)),
}
LINEAR_CHANNELS = tuple(
    value / 255 / 12.92 if value / 255 <= 0.04045
    else ((value / 255 + 0.055) / 1.055) ** 2.4
    for value in range(256)
)


def _luminance(red, green, blue):
    return (
        LINEAR_CHANNELS[red] * 0.2126
        + LINEAR_CHANNELS[green] * 0.7152
        + LINEAR_CHANNELS[blue] * 0.0722
    )


def _minimum_contrast(foreground, image):
    foreground = _luminance(foreground.red(), foreground.green(), foreground.blue())
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = bytes(rgba.constBits())
    backgrounds = (
        _luminance(red, green, blue)
        for red, green, blue in zip(pixels[0::4], pixels[1::4], pixels[2::4], strict=True)
    )
    return min(
        (max(foreground, background) + 0.05) / (min(foreground, background) + 0.05)
        for background in backgrounds
    )


@pytest.mark.parametrize("face_id", LENS_IDS)
def test_lens_contours_preserve_controls_and_drag_at_exact_scales(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    artwork = prepare_face(face)
    for scale in (1.0, 1.5, 2.0):
        size = tuple(round(value * scale) for value in face.size)
        image = artwork.background.toImage().scaled(*size)
        mask = artwork.scaled_mask(size)
        for probe in CONTOUR_PROBES[face_id]:
            rectangle = QRect(*(round(value * scale) for value in probe))
            pixels = image.copy(rectangle).convertToFormat(QImage.Format.Format_RGBA8888)
            assert max(bytes(pixels.constBits())[3::4]) == 0, (face_id, scale, probe)
            assert QRegion(rectangle).intersected(mask).isEmpty(), (face_id, scale, probe)
        for name, region in {**face.controls, "drag": face.drag}.items():
            rectangle = QRect(*(round(value * scale) for value in region))
            assert QRegion(rectangle).subtracted(mask).isEmpty(), (face_id, scale, name)


@pytest.mark.parametrize("face_id", LENS_IDS)
def test_unbacked_lens_labels_contrast_throughout_their_glass(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    background = prepare_face(face).background.toImage()
    source_path = Path(__file__).resolve().parents[2] / "artwork" / "generated" / f"{face_id}.png"
    source = QImage(str(source_path))
    assert not source.isNull()
    source = source.scaled(
        background.size(), Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
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
            foreground = QColor(face.palette[token])
            for surface_name, image in (("source", source), ("background", background)):
                contrast = _minimum_contrast(foreground, image.copy(rectangle))
                assert contrast >= 4.5, (face_id, name, token, surface_name, contrast)
