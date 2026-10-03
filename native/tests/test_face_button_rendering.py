"""Artist surfaces must not blur control states or dim host indicators."""
import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtGui import QColor, QImage, QPalette, QPixmap
from PySide6.QtWidgets import QWidget

from amberfader.ui.face_surface import FaceButton


@pytest.fixture()
def button(qapp):
    parent = QWidget()
    parent.setStyleSheet("background: #000000;")
    button = FaceButton("", parent)
    button.setObjectName("play")
    button.setStyleSheet("QPushButton { color: #ffffff; border: none; }")
    button.resize(30, 24)
    parent.show()
    qapp.processEvents()
    yield button
    parent.close()
    parent.deleteLater()
    qapp.processEvents()


def test_scaled_button_surface_is_interpolated(button):
    surface = QImage(2, 2, QImage.Format.Format_RGB32)
    for y in range(2):
        surface.setPixelColor(0, y, QColor("#000000"))
        surface.setPixelColor(1, y, QColor("#ffffff"))
    button.setObjectName("like")
    button.set_sprites({"normal": QPixmap.fromImage(surface)})
    image = button.grab().toImage()
    # An enlarged two-pixel boundary should blend across its center rather
    # than produce a visibly jagged edge at fractional face scales.
    assert any(20 < image.pixelColor(x, 12).red() < 235 for x in range(10, 20))


def test_disabled_sprite_fallback_keeps_transport_icon_legible(button):
    surface = QPixmap(2, 2)
    surface.fill(QColor("#202020"))
    button.set_sprites({"normal": surface})
    button.setEnabled(False)
    image = button.grab().toImage()
    assert image.pixelColor(1, 12).red() < 32
    assert image.pixelColor(15, 12).red() == 255


def test_disabled_sprite_fallback_keeps_pending_indicator_visible(button):
    surface = QPixmap(2, 2)
    surface.fill(QColor("#202020"))
    button.set_sprites({"normal": surface})
    palette = button.palette()
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Highlight, QColor("#ff0000"))
    button.setPalette(palette)
    button.setProperty("pending", True)
    button.setEnabled(False)
    image = button.grab().toImage()
    assert any(
        image.pixelColor(x, 2).red() == 255 and image.pixelColor(x, 2).green() == 0
        for x in range(2, 27)
    )
