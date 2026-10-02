"""Render the real player widgets with sample metadata for docs/faces-preview.png.

Run `QT_QPA_PLATFORM=offscreen uv run python artwork/preview_faces.py`.
No browser, native socket, playback commands or persistent preferences are used.
"""
from __future__ import annotations

import base64
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QBuffer, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

from amberfader.face_library import FaceLibrary
from amberfader.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
FACE_POSITIONS = (
    ("amber-classic", 32, 126), ("midnight-rack", 676, 126),
    ("moonstone", 32, 486), ("copper-reel", 676, 486), ("paper-signal", 32, 866),
)


def _sample_cover() -> bytes:
    cover = QImage(256, 256, QImage.Format.Format_ARGB32)
    painter = QPainter(cover)
    gradient = QLinearGradient(0, 0, 256, 256)
    gradient.setColorAt(0, QColor("#301f4b"))
    gradient.setColorAt(0.5, QColor("#6b4369"))
    gradient.setColorAt(1, QColor("#dd9567"))
    painter.fillRect(cover.rect(), gradient)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    for radius in (38, 66, 96, 132):
        painter.setPen(QPen(QColor("#efcbb0"), 1.4))
        painter.drawEllipse(QRectF(128 - radius, 128 - radius, radius * 2, radius * 2))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#ffc993"))
    shape = QPainterPath()
    shape.moveTo(0, 186)
    shape.cubicTo(80, 180, 144, 42, 256, 54)
    shape.lineTo(256, 86)
    shape.cubicTo(148, 60, 90, 214, 0, 218)
    shape.closeSubpath()
    painter.drawPath(shape)
    painter.end()
    buffer = QBuffer()
    buffer.open(QBuffer.OpenMode.WriteOnly)
    cover.save(buffer, "PNG")
    return bytes(buffer.data())


def main() -> None:
    app = QApplication([])
    poster = QImage(1320, 1320, QImage.Format.Format_RGB32)
    poster.fill(QColor("#34363d"))
    painter = QPainter(poster)
    font = QFont("sans-serif")
    font.setPixelSize(28)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#f3e9d9"))
    painter.drawText(32, 42, "AMBERFADER / FACES")
    font.setPixelSize(14)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor("#c0c3ce"))
    painter.drawText(32, 70, "Original Linux faces · Rendered with sample metadata")

    with TemporaryDirectory() as directory:
        library = FaceLibrary(Path(directory) / "faces", Path(directory) / "appearance.json")
        window = MainWindow(lambda *_: None, faces=library)
        window.apply_state({
            "bindingToken": "preview", "revision": 1,
            "track": {
                "occurrenceId": "preview", "providerId": "sample", "title": "Velvet Circuit",
                "artists": ["Amberfader"], "album": "Night Drive 1997", "artworkId": "sample",
            },
            "status": "paused", "positionSeconds": 228, "durationSeconds": 270,
            "playbackRate": 1, "volume": 0.8, "muted": False, "liked": True,
            "capabilities": ["play", "pause", "previous", "next", "seek", "volume", "setLiked"],
        })
        window.apply_asset({"dataBase64": base64.b64encode(_sample_cover()).decode()})
        window.show_status("Sample preview · Firefox remote")
        window.show()
        for face_id, x, y in FACE_POSITIONS:
            window.select_face(face_id)
            app.processEvents()
            font.setPixelSize(18)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#f3e9d9"))
            painter.drawText(x, y - 18, library.load(face_id).info.name)
            painter.drawPixmap(x, y, window.grab())
        window.close()

    font.setPixelSize(24)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(700, 928, "One player. Five shells.")
    font.setPixelSize(18)
    font.setBold(False)
    painter.setFont(font)
    for index, line in enumerate((
        "Cover art and likes in every face",
        "Search, recents, and Start mix",
        "Saved selection and local installation",
        "Shaped windows and high-DPI scaling",
        "Versioned JSON + PNG plugin format",
        "Ctrl+, to choose your face",
    )):
        painter.drawText(700, 984 + index * 42, line)
    painter.end()
    if not poster.save(str(ROOT / "docs" / "faces-preview.png")):
        raise RuntimeError("Could not save face preview")
    print("Rendered five player windows with sample metadata")


if __name__ == "__main__":
    main()
