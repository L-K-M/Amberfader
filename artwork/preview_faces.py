"""Render the real player widgets with sample metadata for docs/faces-preview.png.

Run `QT_QPA_PLATFORM=offscreen uv run python artwork/preview_faces.py --states`
to include contact sheets for long metadata, offline and pending states.
No browser, native socket, playback commands or persistent preferences are used.
"""
from __future__ import annotations

import argparse
import base64
from pathlib import Path
from tempfile import TemporaryDirectory

from PySide6.QtCore import QBuffer, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

from amberfader.face_library import Face, FaceLibrary
from amberfader.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
FACE_ORDER = (
    "amber-classic", "midnight-rack", "moonstone", "copper-reel", "paper-signal",
    "memphis-93", "arcade-clear", "rave-grid",
)
PREVIEW_DIRECTORY = ROOT / "build" / "face-previews"
MARGIN = 48
COLUMN_GAP = 64
CAPTION_HEIGHT = 48
ROW_GAP = 48
HEADER_HEIGHT = 148
FOOTER_HEIGHT = 96


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


def _sample_state() -> dict:
    return {
        "bindingToken": "preview", "revision": 1,
        "track": {
            "occurrenceId": "preview", "providerId": "sample", "title": "Velvet Circuit",
            "artists": ["Amberfader"], "album": "Night Drive 1997", "artworkId": "sample",
        },
        "status": "paused", "positionSeconds": 228, "durationSeconds": 270,
        "playbackRate": 1, "volume": 0.8, "muted": False, "liked": True,
        "capabilities": ["play", "pause", "previous", "next", "seek", "volume", "setLiked"],
    }


def _set_sample(window: MainWindow, state_name: str, cover: bytes) -> None:
    window._pending_transport = False
    window._pending_like = False
    state = _sample_state()
    if state_name == "long-metadata":
        state["track"].update(
            title="A Very Long Song Title from the End of the Last Century (Extended Club Mix)",
            artists=["The International Electronic Music Collective", "A Guest with a Long Name"],
            album="Signals from the Future: The Complete Late Night Sessions, Volume Three",
        )
        state.update(positionSeconds=3678, durationSeconds=43201)
    elif state_name == "offline":
        state.update(
            status="unknown", positionSeconds=None, durationSeconds=None, liked=None,
            capabilities=[],
        )
    window.apply_state(state)
    window.apply_asset({"dataBase64": base64.b64encode(cover).decode()})
    if state_name == "offline":
        window.set_connection("gui", "disconnected")
        window._render_time()
    elif state_name == "pending":
        # Render host-owned pending guards without issuing any command.
        window._pending_transport = True
        window._pending_like = True
        window._render_transport_pending()
        window._render_like()
        window.show_status("Waiting for the observed player outcome…", error=True)
    else:
        window.show_status("Sample preview · Firefox remote")


def _contact_sheet(
    app: QApplication, window: MainWindow, faces: list[Face], state_name: str, cover: bytes,
) -> QImage:
    column_width = max(face.size[0] for face in faces)
    rows = [faces[index:index + 2] for index in range(0, len(faces), 2)]
    height = (
        HEADER_HEIGHT + FOOTER_HEIGHT + ROW_GAP * (len(rows) - 1)
        + sum(CAPTION_HEIGHT + max(face.size[1] for face in row) for row in rows)
    )
    width = 2 * MARGIN + 2 * column_width + COLUMN_GAP
    poster = QImage(width, height, QImage.Format.Format_RGB32)
    poster.fill(QColor("#151820"))
    painter = QPainter(poster)
    font = QFont("sans-serif")
    font.setPixelSize(36)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor("#f7f1e6"))
    painter.drawText(MARGIN, 62, "AMBERFADER / FACES")
    font.setPixelSize(18)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor("#bbc2ce"))
    captions = {
        "sample": "Sample metadata",
        "long-metadata": "Long metadata and extended duration",
        "offline": "Unknown playback and liked state · Disconnected from Firefox",
        "pending": "Pending playback and like commands · Awaiting an observed outcome",
    }
    painter.drawText(
        MARGIN, 96, f"{len(faces)} faces · Actual Qt player widgets · {captions[state_name]}",
    )
    painter.fillRect(QRect(MARGIN, 120, width - 2 * MARGIN, 2), QColor("#434955"))

    _set_sample(window, state_name, cover)
    top = HEADER_HEIGHT
    for row in rows:
        for column, face in enumerate(row):
            window.select_face(face.info.id)
            app.processEvents()
            snapshot = window.grab()
            # Grabbed pixmaps may carry a platform DPR; explicitly draw into
            # logical dimensions to preserve a 1:1 player-to-poster scale.
            x = MARGIN + column * (column_width + COLUMN_GAP)
            x += (column_width - face.size[0]) // 2
            font.setPixelSize(26)
            font.setBold(True)
            painter.setFont(font)
            painter.setPen(QColor("#f7f1e6"))
            painter.drawText(x, top + 27, face.info.name)
            painter.drawPixmap(QRect(x, top + CAPTION_HEIGHT, *face.size), snapshot)
            suffix = "" if state_name == "sample" else f"-{state_name}"
            destination = PREVIEW_DIRECTORY / f"{face.info.id}{suffix}.png"
            if not snapshot.save(str(destination)):
                raise RuntimeError(f"Could not save {destination}")
        top += CAPTION_HEIGHT + max(face.size[1] for face in row) + ROW_GAP

    font.setPixelSize(18)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor("#bbc2ce"))
    painter.drawText(
        MARGIN, height - 40, "One player. Choose your shell with Ctrl+, · Music stays in Firefox.",
    )
    painter.end()
    return poster


def _reject_command(*_) -> None:
    raise RuntimeError("A preview must never send a player command")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--states", action="store_true", help="Render additional state contact sheets",
    )
    options = parser.parse_args()
    app = QApplication([])
    PREVIEW_DIRECTORY.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory() as directory:
        library = FaceLibrary(Path(directory) / "faces", Path(directory) / "appearance.json")
        if library.problems:
            raise RuntimeError("Cannot render every bundled face: " + "; ".join(library.problems))
        order = {face_id: index for index, face_id in enumerate(FACE_ORDER)}
        infos = sorted(library.faces, key=lambda info: (order.get(info.id, len(order)), info.id))
        faces = [library.load(info.id) for info in infos]
        window = MainWindow(_reject_command, faces=library)
        window.show()
        cover = _sample_cover()
        try:
            poster = _contact_sheet(app, window, faces, "sample", cover)
            if not poster.save(str(ROOT / "docs" / "faces-preview.png")):
                raise RuntimeError("Could not save face preview")
            if options.states:
                for state_name in ("long-metadata", "offline", "pending"):
                    sheet = _contact_sheet(app, window, faces, state_name, cover)
                    destination = PREVIEW_DIRECTORY / f"faces-{state_name}.png"
                    if not sheet.save(str(destination)):
                        raise RuntimeError(f"Could not save {destination}")
        finally:
            window.close()
    print(f"Rendered {len(faces)} faces; individual previews are in {PREVIEW_DIRECTORY}")


if __name__ == "__main__":
    main()
