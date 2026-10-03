"""Covers and state outlines follow the physical shape of each control."""
import pytest

pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from amberfader.face_library import BUILTIN_DIRECTORY, load_face
from amberfader.ui.face_surface import CoverLabel, FaceButton


@pytest.mark.parametrize("face_id", ("aureole", "viridian"))
def test_drag_region_is_the_original_shell_without_a_branding_plaque(qapp, face_id):
    face = load_face(BUILTIN_DIRECTORY / face_id)
    background = QImage.fromData(face.background)
    source = QImage(str(BUILTIN_DIRECTORY.parents[2] / "artwork" / "generated" / f"{face_id}.png"))
    # QImage.scaled uses a different resampler around sharp metal reflections.
    # Compare the shell with a direct, unadorned painting of its source instead.
    original_shell = QImage(background.size(), QImage.Format.Format_ARGB32)
    original_shell.fill(Qt.GlobalColor.transparent)
    painter = QPainter(original_shell)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(QRectF(original_shell.rect()), source)
    painter.end()
    x, y, width, height = face.drag
    point = QPoint((x + width // 2) * 2, (y + height // 2) * 2)
    actual, original = background.pixelColor(point), original_shell.pixelColor(point)
    assert max(abs(a - b) for a, b in zip(actual.getRgb(), original.getRgb(), strict=True)) <= 2


def test_round_cover_reveals_the_shell_at_its_corners(qapp):
    shell = QWidget()
    shell.resize(80, 80)
    shell.setStyleSheet("background: #ff0000;")
    cover = CoverLabel(shell)
    cover.resize(80, 80)
    cover.set_shape("ellipse", 0, False)
    image = QPixmap(80, 80)
    image.fill(QColor("#0000ff"))
    cover.setPixmap(image)
    shell.show()
    qapp.processEvents()
    try:
        rendered = shell.grab().toImage()
        ratio = rendered.devicePixelRatio()
        assert rendered.pixelColor(round(2 * ratio), round(2 * ratio)).red() == 255
        assert rendered.pixelColor(round(40 * ratio), round(40 * ratio)).blue() == 255
        assert not cover._cover_path().contains(QPoint(2, 2))
        assert cover._cover_path().contains(QPoint(40, 40))
    finally:
        shell.close()
        shell.deleteLater()


@pytest.mark.parametrize("sprites", (False, True))
def test_round_button_clips_surface_outline_and_pointer_hits(qapp, sprites):
    shell = QWidget()
    shell.resize(48, 48)
    shell.setStyleSheet("QWidget { background: #ff0000; } QPushButton { background: #0000ff; }")
    button = FaceButton("", shell)
    button.resize(48, 48)
    button.set_shape("ellipse", 0)
    if sprites:
        image = QPixmap(48, 48)
        image.fill(QColor("#0000ff"))
        button.set_sprites({"normal": image})
    button.setProperty("pending", True)
    clicks = []
    button.clicked.connect(lambda: clicks.append(True))
    shell.show()
    qapp.processEvents()
    try:
        assert not button.hitButton(QPoint(2, 2))
        assert button.hitButton(QPoint(24, 24))
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(2, 2))
        assert not clicks
        QTest.mouseClick(button, Qt.MouseButton.LeftButton, pos=QPoint(24, 24))
        assert clicks == [True]
        rendered = shell.grab().toImage()
        ratio = rendered.devicePixelRatio()
        assert rendered.pixelColor(round(2 * ratio), round(2 * ratio)).red() == 255
        assert rendered.pixelColor(round(24 * ratio), round(24 * ratio)).blue() == 255
    finally:
        shell.close()
        shell.deleteLater()
