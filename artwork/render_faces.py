"""Render the five Amberfader face backgrounds to PNG.

Original, reproducible artwork painted with QPainter onto offscreen
QImages: no borrowed bitmaps, fonts, or network assets, and no Qt event
loop (QImage painting needs no QApplication). Output is deterministic for
a fixed Qt build: every texture uses a seeded RNG and the engraved
branding uses the built-in 5x7 dot font defined below.

Run with the repository venv:

    QT_QPA_PLATFORM=offscreen \
    LD_LIBRARY_PATH=$PWD/.venv/qt-system-libs/runtime/lib/x86_64-linux-gnu:\
$PWD/.venv/qt-system-libs/runtime/usr/lib/x86_64-linux-gnu \
    uv run python artwork/render_faces.py

Each PNG is written to its face directory at 2x the manifest's logical
size. After rendering, every control rectangle and the drag rectangle
from face.json is verified to sit on background with alpha >= 128, so a
silhouette regression fails the run instead of shipping a hole.
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

SCALE = 2
MIN_ALPHA = 128
MAX_DIMENSION = 2048
MAX_FILE_BYTES = 4 * 1024 * 1024
FACES_ROOT = Path(__file__).resolve().parent.parent / "native" / "amberfader" / "faces"

Rect = tuple[float, float, float, float]

# --- built-in 5x7 dot font (original; covers the engraved branding) ----

GLYPHS: dict[str, tuple[str, ...]] = {
    " ": (".....", ".....", ".....", ".....", ".....", ".....", "....."),
    "-": (".....", ".....", ".....", ".###.", ".....", ".....", "....."),
    ".": (".....", ".....", ".....", ".....", ".....", ".##..", ".##.."),
    "0": (".###.", "#...#", "#..##", "#.#.#", "##..#", "#...#", ".###."),
    "1": ("..#..", ".##..", "..#..", "..#..", "..#..", "..#..", ".###."),
    "2": (".###.", "#...#", "....#", "..##.", ".#...", "#....", "#####"),
    "3": ("####.", "....#", "....#", ".###.", "....#", "....#", "####."),
    "4": ("...#.", "..##.", ".#.#.", "#..#.", "#####", "...#.", "...#."),
    "6": (".###.", "#....", "#....", "####.", "#...#", "#...#", ".###."),
    "7": ("#####", "....#", "...#.", "..#..", "..#..", "..#..", "..#.."),
    "9": (".###.", "#...#", "#...#", ".####", "....#", "....#", ".###."),
    "A": (".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"),
    "B": ("####.", "#...#", "#...#", "####.", "#...#", "#...#", "####."),
    "C": (".####", "#....", "#....", "#....", "#....", "#....", ".####"),
    "D": ("####.", "#...#", "#...#", "#...#", "#...#", "#...#", "####."),
    "E": ("#####", "#....", "#....", "####.", "#....", "#....", "#####"),
    "F": ("#####", "#....", "#....", "####.", "#....", "#....", "#...."),
    "I": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"),
    "K": ("#...#", "#..#.", "#.#..", "##...", "#.#..", "#..#.", "#...#"),
    "L": ("#....", "#....", "#....", "#....", "#....", "#....", "#####"),
    "M": ("#...#", "##.##", "#.#.#", "#.#.#", "#...#", "#...#", "#...#"),
    "N": ("#...#", "##..#", "##..#", "#.#.#", "#..##", "#..##", "#...#"),
    "O": (".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
    "P": ("####.", "#...#", "#...#", "####.", "#....", "#....", "#...."),
    "R": ("####.", "#...#", "#...#", "####.", "#.#..", "#..#.", "#...#"),
    "S": (".####", "#....", "#....", ".###.", "....#", "....#", "####."),
    "T": ("#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."),
    "U": ("#...#", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."),
}

GLYPH_ADVANCE = 6.0


def _c(hex_rgb: str, alpha: int = 255) -> QColor:
    color = QColor(hex_rgb)
    color.setAlpha(alpha)
    return color


def _rr(rect: Rect, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(*rect), radius, radius)
    return path


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QPointF(cx, cy), rx, ry)
    return path


def _vgrad(rect: Rect, stops: list[tuple[float, QColor]]) -> QLinearGradient:
    grad = QLinearGradient(0, rect[1], 0, rect[1] + rect[3])
    for pos, color in stops:
        grad.setColorAt(pos, color)
    return grad


def _hgrad(rect: Rect, stops: list[tuple[float, QColor]]) -> QLinearGradient:
    grad = QLinearGradient(rect[0], 0, rect[0] + rect[2], 0)
    for pos, color in stops:
        grad.setColorAt(pos, color)
    return grad


def _canvas(width: float, height: float) -> QImage:
    image = QImage(
        int(width * SCALE), int(height * SCALE), QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(0)
    return image


def _open(image: QImage) -> QPainter:
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(SCALE, SCALE)
    return painter


def _recess(
    p: QPainter,
    rect: Rect,
    radius: float,
    stops: list[tuple[float, str]],
    rim_alpha: int = 110,
) -> QPainterPath:
    """Sunken panel: dark gradient, inner rim shadow, faint bottom catchlight."""
    path = _rr(rect, radius)
    p.fillPath(path, _vgrad(rect, [(pos, _c(c)) for pos, c in stops]))
    p.save()
    p.setClipPath(path)
    p.setPen(QPen(_c("#000000", rim_alpha), 1.2))
    p.drawPath(path)
    p.setPen(QPen(_c("#ffffff", 42), 0.7))
    p.drawLine(QPointF(rect[0] + radius, rect[1] + rect[3] - 0.8),
               QPointF(rect[0] + rect[2] - radius, rect[1] + rect[3] - 0.8))
    p.restore()
    return path


def _raised(
    p: QPainter, rect: Rect, radius: float, stops: list[tuple[float, str]], edge: str
) -> QPainterPath:
    """Raised plate: light-top gradient, dark rim, top inner highlight."""
    path = _rr(rect, radius)
    p.fillPath(path, _vgrad(rect, [(pos, _c(c)) for pos, c in stops]))
    p.save()
    p.setClipPath(path)
    p.setPen(QPen(_c(edge, 190), 1.0))
    p.drawPath(path)
    p.setPen(QPen(_c("#ffffff", 60), 0.8))
    p.drawLine(QPointF(rect[0] + radius, rect[1] + 0.9),
               QPointF(rect[0] + rect[2] - radius, rect[1] + 0.9))
    p.restore()
    return path


def _scanlines(
    p: QPainter, clip: QPainterPath, rect: Rect, step: float = 3.0, alpha: int = 18
) -> None:
    """CRT/LCD texture: 1 device-px dark rows every `step` logical px."""
    p.save()
    p.setClipPath(clip)
    fill = _c("#000000", alpha)
    y = rect[1] + 1.0
    while y < rect[1] + rect[3]:
        p.fillRect(QRectF(rect[0], y, rect[2], 0.5), fill)
        y += step
    p.restore()


def _glare(p: QPainter, clip: QPainterPath, rect: Rect, alpha: int = 26) -> None:
    """Soft top-light inside a panel."""
    grad = _vgrad(
        rect, [(0.0, _c("#ffffff", alpha)), (1.0, _c("#ffffff", 0))]
    )
    p.save()
    p.setClipPath(clip)
    p.fillRect(QRectF(*rect), grad)
    p.restore()


def _brush_h(
    p: QPainter,
    clip: QPainterPath,
    rect: Rect,
    seed: int,
    count: int = 110,
    alpha: int = 10,
) -> None:
    """Brushed metal / grain texture: short horizontal streaks, seeded."""
    rng = random.Random(seed)
    p.save()
    p.setClipPath(clip)
    x0, y0, w, h = rect
    for _ in range(count):
        y = rng.uniform(y0, y0 + h)
        x = rng.uniform(x0, x0 + w * 0.6)
        length = rng.uniform(w * 0.25, w * 0.95)
        shade = rng.choice(("#ffffff", "#000000"))
        p.setPen(QPen(_c(shade, rng.randint(alpha // 2, alpha)), rng.uniform(0.3, 0.8)))
        p.drawLine(QPointF(x, y), QPointF(min(x + length, x0 + w), y))
    p.restore()


def _wood_grain(p: QPainter, clip: QPainterPath, rect: Rect, seed: int) -> None:
    """Walnut grain: long, gently wavering horizontal streaks."""
    rng = random.Random(seed)
    p.save()
    p.setClipPath(clip)
    x0, y0, w, h = rect
    for _ in range(30):
        base_y = rng.uniform(y0 + 2, y0 + h - 2)
        amp = rng.uniform(0.4, 1.8)
        phase = rng.uniform(0, math.tau)
        drift = rng.uniform(-2.0, 2.0)
        path = QPainterPath(QPointF(x0, base_y))
        for i in range(1, 10):
            t = i / 9
            path.lineTo(
                QPointF(x0 + w * t, base_y + math.sin(phase + t * 2.4) * amp + drift * t)
            )
        warm = rng.random() < 0.4
        color = _c("#5a3d1e" if warm else "#000000", rng.randint(9, 22))
        p.setPen(QPen(color, rng.uniform(0.5, 1.1)))
        p.drawPath(path)
    p.restore()


def _groove_v(p: QPainter, x: float, y0: float, y1: float, lit: str = "#ffffff") -> None:
    """Engraved vertical separator: dark cut with a light edge on the right."""
    p.setPen(QPen(_c("#000000", 120), 0.9))
    p.drawLine(QPointF(x, y0), QPointF(x, y1))
    p.setPen(QPen(_c(lit, 48), 0.7))
    p.drawLine(QPointF(x + 1.0, y0), QPointF(x + 1.0, y1))


def _groove_h(p: QPainter, x0: float, x1: float, y: float, lit: str = "#ffffff") -> None:
    """Engraved horizontal separator: dark cut with a light edge below."""
    p.setPen(QPen(_c("#000000", 120), 0.9))
    p.drawLine(QPointF(x0, y), QPointF(x1, y))
    p.setPen(QPen(_c(lit, 48), 0.7))
    p.drawLine(QPointF(x0, y + 1.0), QPointF(x1, y + 1.0))


def _screw(p: QPainter, cx: float, cy: float, r: float, tone: str, angle: float) -> None:
    """Slotted machine screw with a radial metal dome."""
    grad = QRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 1.9)
    grad.setColorAt(0.0, _c("#ffffff", 170))
    grad.setColorAt(0.45, _c(tone))
    grad.setColorAt(1.0, _c("#000000", 210))
    p.fillPath(_ellipse(cx, cy, r, r), grad)
    p.setPen(QPen(_c("#000000", 150), 0.7))
    p.drawEllipse(QPointF(cx, cy), r, r)
    rad = math.radians(angle)
    dx, dy = math.cos(rad) * r * 0.62, math.sin(rad) * r * 0.62
    p.setPen(QPen(_c("#000000", 200), 0.9))
    p.drawLine(QPointF(cx - dx, cy - dy), QPointF(cx + dx, cy + dy))
    p.setPen(QPen(_c("#ffffff", 70), 0.5))
    p.drawLine(QPointF(cx - dx, cy - dy + 0.7), QPointF(cx + dx, cy + dy + 0.7))


def _jewel(p: QPainter, cx: float, cy: float, r: float, color: str) -> None:
    """Small pilot lamp: glowing core on a darker socket."""
    p.fillPath(_ellipse(cx, cy, r * 1.5, r * 1.5), _c("#000000", 110))
    grad = QRadialGradient(cx - r * 0.25, cy - r * 0.3, r * 1.6)
    grad.setColorAt(0.0, _c("#ffffff", 230))
    grad.setColorAt(0.35, _c(color))
    grad.setColorAt(1.0, _c(color, 60))
    p.fillPath(_ellipse(cx, cy, r, r), grad)


def _dots(p: QPainter, x: float, y: float, text: str, color: QColor, scale: float) -> float:
    """Draw TEXT in the 5x7 dot font; returns the advance width."""
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    cursor = x
    for ch in text:
        rows = GLYPHS.get(ch.upper(), GLYPHS[" "])
        for row_i, row in enumerate(rows):
            for col_i, bit in enumerate(row):
                if bit == "#":
                    p.drawRect(QRectF(cursor + col_i * scale, y + row_i * scale, scale, scale))
        cursor += GLYPH_ADVANCE * scale
    p.restore()
    return cursor - x


def _wordmark(
    p: QPainter,
    x: float,
    y: float,
    text: str,
    ink: str,
    scale: float = 1.0,
    relief: str | None = None,
    relief_alpha: int = 90,
) -> None:
    """Engraved branding: optional light catchline under the ink pass."""
    if relief is not None:
        _dots(p, x, y + scale * 0.9, text, _c(relief, relief_alpha), scale)
    _dots(p, x, y, text, _c(ink), scale)


# --- face painters -----------------------------------------------------


def render_amber_classic(_face: dict[str, Any]) -> QImage:
    """Warm dark walnut hi-fi remote: gold trim, smoked glass, brass screws."""
    w, h = 440.0, 274.0
    image = _canvas(w, h)
    p = _open(image)
    p.fillRect(QRectF(0, 0, w, h), _c("#120b05"))

    body = _rr((1.5, 1.5, w - 3, h - 3), 6)
    p.fillPath(
        body,
        _vgrad((0, 0, w, h), [(0.0, _c("#4d3620")), (0.55, _c("#2e1f10")), (1.0, _c("#1a1107"))]),
    )
    _wood_grain(p, body, (0, 0, w, h), seed=7101)
    vignette = QRadialGradient(220, 140, 280)
    vignette.setColorAt(0.0, _c("#000000", 0))
    vignette.setColorAt(1.0, _c("#000000", 52))
    p.fillPath(body, vignette)

    p.setPen(QPen(_c("#6e4514"), 1.0))
    p.drawPath(_rr((4, 4, w - 8, h - 8), 5))
    p.setPen(QPen(_c("#e8a33d", 120), 0.7))
    p.drawPath(_rr((5, 5, w - 10, h - 10), 4))

    for i, (sx, sy) in enumerate(((10, 10), (430, 10), (10, 264), (430, 264))):
        _screw(p, sx, sy, 3.2, "#8a6428", 18 + i * 35)

    # Smoked amber glass behind title/artists/time/playback.
    glass = _recess(p, (126, 44, 304, 104), 6, [(0.0, "#20150c"), (1.0, "#0f0a05")])
    _scanlines(p, glass, (126, 44, 304, 104), alpha=16)
    _glare(p, glass, (126, 44, 304, 26), alpha=16)

    # Cover bezel and dark well behind the art square.
    _raised(p, (14, 48, 108, 108), 5, [(0.0, "#c99a4a"), (1.0, "#5d3c14")], "#2a1a08")
    _recess(p, (17, 51, 102, 102), 3, [(0.0, "#150d06"), (1.0, "#0c0703")])

    # Transport rail and its button separators.
    _recess(p, (128, 148, 208, 40), 4, [(0.0, "#241709"), (1.0, "#170f07")])
    for gx in (181, 231, 281):
        _groove_v(p, gx, 158, 178, "#e8a33d")

    # Seek channel with faint calibration ticks above the slider groove.
    seek_slot = _recess(p, (16, 190, 408, 24), 3, [(0.0, "#1c1207"), (1.0, "#100a04")])
    p.save()
    p.setClipPath(seek_slot)
    p.setPen(QPen(_c("#c98f3b", 38), 0.8))
    for tx in range(30, 410, 34):
        p.drawLine(QPointF(tx, 191.5), QPointF(tx, 195.5))
    p.restore()

    # Volume and utility-button plates.
    _recess(p, (14, 218, 122, 32), 4, [(0.0, "#221608"), (1.0, "#160e06")])
    _recess(p, (140, 216, 242, 34), 4, [(0.0, "#221608"), (1.0, "#160e06")])

    p.fillRect(QRectF(14, 250, 412, 19), _c("#000000", 30))
    _jewel(p, 104, 170, 3.0, "#f4c56e")

    _wordmark(p, 138, 19, "AMBERFADER", "#0d0803", relief="#f4c56e", relief_alpha=70)
    _wordmark(p, 252, 19, "A-440", "#0d0803", relief="#f4c56e", relief_alpha=60)
    _groove_h(p, 112, 132, 21.5, "#e8a33d")
    _groove_h(p, 204, 246, 21.5, "#e8a33d")
    p.end()
    return image


def render_midnight_rack(_face: dict[str, Any]) -> QImage:
    """1997 graphite rack unit: machined ears, vents, green phosphor CRT."""
    w, h = 480.0, 274.0
    image = _canvas(w, h)
    p = _open(image)
    p.fillRect(QRectF(0, 0, w, h), _c("#0e0f15"))

    body = _rr((1, 1, w - 2, h - 2), 3)
    p.fillPath(
        body,
        _vgrad((0, 0, w, h), [(0.0, _c("#3b3f4c")), (0.5, _c("#23262f")), (1.0, _c("#14161d"))]),
    )
    _brush_h(p, body, (0, 0, w, h), seed=4402, count=90, alpha=7)

    # Rack ears with slotted screws; the left ear carries the power lamp.
    for ex in (0.0, w - 15):
        ear = QRectF(ex, 2, 15, h - 4)
        p.fillRect(ear, _vgrad((ex, 0, 15, h), [(0.0, _c("#4a4f5e")), (1.0, _c("#1d2029"))]))
        p.setPen(QPen(_c("#0a0b10"), 1.0))
        inner_x = ex + 14.5 if ex == 0 else ex + 0.5
        p.drawLine(QPointF(inner_x, 4), QPointF(inner_x, h - 4))
        p.setPen(QPen(_c("#ffffff", 40), 0.6))
        p.drawLine(QPointF(inner_x + (-0.8 if ex == 0 else 0.8), 4),
                   QPointF(inner_x + (-0.8 if ex == 0 else 0.8), h - 4))
        _screw(p, ex + 7.5, 48, 4.2, "#565c6c", 62 if ex == 0 else 128)
        _screw(p, ex + 7.5, 226, 4.2, "#565c6c", 96 if ex == 0 else 30)
    _jewel(p, 7.5, 16, 2.6, "#9dff7a")

    # Recessed label strip across the drag row.
    _recess(p, (14, 6, 354, 32), 2, [(0.0, "#15171f"), (1.0, "#1e212b")])
    _wordmark(p, 26, 18, "AMBERFADER", "#05070a", relief="#8fa0b8", relief_alpha=80)
    _wordmark(p, 290, 18, "RACK UNIT 97", "#05070a", relief="#8fa0b8", relief_alpha=70)

    # Vent slots between the label strip and the display.
    for i in range(6):
        _recess(p, (24 + i * 19, 45, 13, 3.5), 1.5, [(0.0, "#0a0c10"), (1.0, "#181b23")], 140)

    # Phosphor CRT recess behind title/artists/time/playback.
    crt = _recess(p, (148, 44, 312, 120), 4, [(0.0, "#0c1a12"), (1.0, "#040b07")], 150)
    _scanlines(p, crt, (148, 44, 312, 120), alpha=22)
    _glare(p, crt, (148, 44, 312, 30), alpha=14)
    p.save()
    p.setClipPath(crt)
    p.setPen(QPen(_c("#a4ff8a", 26), 0.6))
    p.drawPath(_rr((150.5, 46.5, 307, 115), 3))
    p.restore()

    # Machined art bezel.
    _raised(p, (14, 52, 120, 120), 3, [(0.0, "#565c6b"), (1.0, "#22242d")], "#0b0d12")
    _recess(p, (17, 55, 114, 114), 2, [(0.0, "#0d0f14"), (1.0, "#07090c")])

    _groove_h(p, 140, 460, 169, "#a1abb6")

    # Milled transport plate behind prev/play/next/like/volume/search.
    _raised(p, (14, 174, 452, 38), 3, [(0.0, "#4a4f5d"), (1.0, "#24262f")], "#0c0e13")
    for gx in (61, 115, 161, 212, 342):
        _groove_v(p, gx, 182, 204, "#a1abb6")

    seek_slot = _recess(p, (16, 213, 448, 21), 2, [(0.0, "#10131a"), (1.0, "#090b10")], 140)
    p.save()
    p.setClipPath(seek_slot)
    p.setPen(QPen(_c("#a1abb6", 34), 0.8))
    for tx in range(30, 452, 42):
        p.drawLine(QPointF(tx, 214.5), QPointF(tx, 218.0))
    p.restore()

    _recess(p, (14, 236, 180, 32), 2, [(0.0, "#171a21"), (1.0, "#101218")])
    p.fillRect(QRectF(200, 240, 266, 24), _c("#000000", 26))

    p.setPen(QPen(_c("#0a0b10"), 1.0))
    p.drawPath(body)
    p.end()
    return image


def render_moonstone(_face: dict[str, Any]) -> QImage:
    """Y2K silver capsule: blue LCD glass, cover porthole, floating dock."""
    w, h = 600.0, 306.0
    image = _canvas(w, h)
    p = _open(image)

    capsule = _rr((16, 6, 568, 256), 56)
    dock = _rr((80, 264, 470, 40), 20)

    p.fillPath(
        capsule,
        _vgrad(
            (0, 6, 600, 256),
            [(0.0, _c("#f4f7f9")), (0.45, _c("#d3dbe1")), (1.0, _c("#9caab6"))],
        ),
    )
    p.fillPath(
        dock,
        _vgrad((0, 264, 0, 40), [(0.0, _c("#e6edf1")), (1.0, _c("#96a5b1"))]),
    )
    _brush_h(p, capsule, (16, 6, 568, 256), seed=9031, count=150, alpha=7)

    sheen = QRadialGradient(180, 30, 430)
    sheen.setColorAt(0.0, _c("#ffffff", 80))
    sheen.setColorAt(1.0, _c("#ffffff", 0))
    p.fillPath(capsule, sheen)
    shade = QRadialGradient(470, 300, 320)
    shade.setColorAt(0.0, _c("#33505f", 44))
    shade.setColorAt(1.0, _c("#33505f", 0))
    p.fillPath(capsule, shade)

    # Blue LCD glass behind the readouts.
    lcd = _recess(p, (178, 54, 362, 116), 14, [(0.0, "#1b485f"), (1.0, "#0c2431")], 90)
    p.save()
    p.setClipPath(lcd)
    p.setPen(QPen(_c("#ffffff", 90), 1.0))
    p.drawPath(_rr((179, 55, 360, 114), 13))
    p.restore()
    _scanlines(p, lcd, (178, 54, 362, 116), alpha=15)
    _glare(p, lcd, (178, 54, 362, 30), alpha=30)

    # Chrome porthole framing the cover art.
    rim = QPainterPath()
    rim.addEllipse(QPointF(100, 128), 96, 96)
    rim.addEllipse(QPointF(100, 128), 88, 88)
    rim.setFillRule(Qt.FillRule.OddEvenFill)
    ring_grad = QRadialGradient(74, 92, 130)
    ring_grad.setColorAt(0.0, _c("#ffffff"))
    ring_grad.setColorAt(0.55, _c("#aebcc6"))
    ring_grad.setColorAt(1.0, _c("#6d7f8b"))
    p.fillPath(rim, ring_grad)
    p.setPen(QPen(_c("#5f707c", 170), 0.9))
    p.drawEllipse(QPointF(100, 128), 96, 96)
    p.drawEllipse(QPointF(100, 128), 88, 88)
    well = _ellipse(100, 128, 88, 88)
    p.fillPath(
        well, _vgrad((0, 40, 0, 176), [(0.0, _c("#14293a")), (1.0, _c("#0a1a26"))])
    )
    _glare(p, well, (40, 56, 120, 34), alpha=22)

    # Recessed transport tray and engraved seek channel.
    _recess(p, (176, 174, 372, 58), 20, [(0.0, "#a9b7c0"), (1.0, "#ccd6dc")], 70)
    p.save()
    seek_clip = _rr((70, 236, 460, 24), 12)
    p.setClipPath(seek_clip)
    p.fillRect(QRectF(70, 236, 460, 24), _c("#8fa0ab", 130))
    p.restore()
    _groove_h(p, 84, 516, 238.5, "#ffffff")
    _groove_h(p, 84, 516, 257.5, "#ffffff")

    _wordmark(p, 223, 26, "AMBERFADER", "#33505f", relief="#ffffff", relief_alpha=120)
    _wordmark(p, 295, 26, "MS-306", "#33505f", relief="#ffffff", relief_alpha=100)

    p.setPen(QPen(_c("#ffffff", 90), 0.8))
    p.drawLine(QPointF(104, 265.5), QPointF(526, 265.5))
    _jewel(p, 92, 284, 3.2, "#7fd4e8")

    edge = QPen(_c("#647682", 220), 1.0)
    p.setPen(edge)
    p.drawPath(capsule)
    p.drawPath(dock)
    p.end()
    return image


def render_copper_reel(_face: dict[str, Any]) -> QImage:
    """Copper pocket-space-age remote: honey LCD and a circular pod."""
    w, h = 612.0, 322.0
    image = _canvas(w, h)
    p = _open(image)

    chassis = _rr((24, 26, 390, 290), 24)
    bump = _ellipse(448, 90, 62, 54)
    pod = _ellipse(496, 187, 116, 116)
    shelf = _rr((388, 282, 196, 34), 16)
    silhouette = chassis.united(bump).united(pod).united(shelf)

    p.fillPath(
        silhouette,
        _vgrad((0, 0, 0, 322), [(0.0, _c("#a8693d")), (0.5, _c("#77421f")), (1.0, _c("#47240f"))]),
    )

    chassis_all = chassis.united(bump)
    p.save()
    p.setClipPath(chassis_all)
    p.fillRect(
        QRectF(0, 0, 520, 322),
        _vgrad((0, 0, 0, 322), [(0.0, _c("#b47443")), (0.55, _c("#7e4623")), (1.0, _c("#4e2712"))]),
    )
    p.restore()
    _brush_h(p, chassis_all, (24, 26, 400, 290), seed=6207, count=120, alpha=11)

    # Status shelf: darker bronze dock fused under the pod's lower arc.
    p.fillPath(
        shelf,
        _vgrad((0, 282, 0, 34), [(0.0, _c("#5d3218")), (1.0, _c("#38190a"))]),
    )
    p.save()
    p.setClipPath(shelf)
    p.setPen(QPen(_c("#ffcb70", 70), 0.8))
    p.drawLine(QPointF(400, 283.4), QPointF(572, 283.4))
    p.restore()

    # Turntable pod: dark disc, rim band, groove rings, hub, dial ticks.
    pod_grad = QRadialGradient(470, 150, 130)
    pod_grad.setColorAt(0.0, _c("#6b3a1e"))
    pod_grad.setColorAt(0.62, _c("#482613"))
    pod_grad.setColorAt(1.0, _c("#2c1408"))
    p.fillPath(pod, pod_grad)
    rim = QPainterPath()
    rim.addEllipse(QPointF(496, 187), 115, 115)
    rim.addEllipse(QPointF(496, 187), 108, 108)
    rim.setFillRule(Qt.FillRule.OddEvenFill)
    rim_grad = QRadialGradient(450, 140, 150)
    rim_grad.setColorAt(0.0, _c("#e9a866"))
    rim_grad.setColorAt(0.55, _c("#9a5a2c"))
    rim_grad.setColorAt(1.0, _c("#4a2410"))
    p.fillPath(rim, rim_grad)
    p.save()
    p.setClipPath(pod)
    for radius in (60, 74, 88, 102):
        p.setPen(QPen(_c("#140a04", 70), 0.7))
        p.drawEllipse(QPointF(496, 187), radius, radius)
        p.setPen(QPen(_c("#d98f4e", 34), 0.5))
        p.drawEllipse(QPointF(496, 187.6), radius, radius)
    p.setPen(QPen(_c("#ffd9a0", 60), 1.0))
    for i in range(24):
        ang = math.tau * i / 24
        p.drawLine(
            QPointF(496 + 96 * math.cos(ang), 187 + 96 * math.sin(ang)),
            QPointF(496 + 104 * math.cos(ang), 187 + 104 * math.sin(ang)),
        )
    p.restore()
    p.setPen(QPen(_c("#2a1408", 160), 1.2))
    p.drawEllipse(QPointF(499, 177), 40, 40)
    p.setPen(QPen(_c("#e9a866", 60), 0.7))
    p.drawEllipse(QPointF(499, 177.8), 40, 40)

    # Engraved seam where the pod meets the chassis shoulder.
    p.setPen(QPen(_c("#1c0d05", 130), 1.0))
    p.drawArc(QRectF(496 - 112, 187 - 112, 224, 224), 138 * 16, 84 * 16)
    p.setPen(QPen(_c("#e9a866", 55), 0.6))
    p.drawArc(QRectF(496 - 111, 187 - 111, 222, 222), 138 * 16, 84 * 16)

    # Honey LCD panel behind title/artists/time/playback.
    _raised(p, (158, 70, 250, 162), 10, [(0.0, "#8a4f28"), (1.0, "#3f2010")], "#261206")
    lcd = _recess(p, (162, 74, 242, 154), 8, [(0.0, "#ffd478"), (1.0, "#f0a840")], 70)
    _scanlines(p, lcd, (162, 74, 242, 154), alpha=10)
    _glare(p, lcd, (162, 74, 242, 34), alpha=36)
    p.save()
    p.setClipPath(lcd)
    p.setPen(QPen(_c("#7a4416", 90), 1.0))
    p.drawPath(_rr((163, 75, 240, 152), 7))
    p.restore()

    # Cover bezel, seek channel, rivets, reel emblem.
    _raised(p, (36, 82, 120, 120), 10, [(0.0, "#b97a46"), (1.0, "#5a2e14")], "#2e1608")
    _recess(p, (39, 85, 114, 114), 6, [(0.0, "#2a1509"), (1.0, "#170b04")])
    _recess(p, (38, 230, 356, 22), 9, [(0.0, "#552c14"), (1.0, "#35180a")])
    for ry in (56, 92, 232, 268):
        _screw(p, 30, ry, 2.6, "#7c4426", 40 + ry)

    reel_cx, reel_cy, reel_r = 48, 296, 12
    for dy, color in ((0.0, "#2a1408"), (0.8, "#d98f4e")):
        p.setPen(QPen(_c(color, 120 if dy == 0 else 45), 0.9))
        p.drawEllipse(QPointF(reel_cx, reel_cy + dy), reel_r, reel_r)
        for hole in range(3):
            ang = math.tau * hole / 3 + 0.5
            p.drawEllipse(
                QPointF(reel_cx + 6.4 * math.cos(ang), reel_cy + dy + 6.4 * math.sin(ang)),
                2.4,
                2.4,
            )
        p.drawEllipse(QPointF(reel_cx, reel_cy + dy), 1.6, 1.6)

    _wordmark(p, 48, 46, "AMBERFADER", "#2a1408", relief="#ffcb70", relief_alpha=80)
    _wordmark(p, 300, 46, "CR-612", "#2a1408", relief="#ffcb70", relief_alpha=70)

    p.setPen(QPen(_c("#241108", 230), 1.0))
    p.drawPath(silhouette)
    p.end()
    return image


def render_paper_signal(_face: dict[str, Any]) -> QImage:
    """Classic-Mac cream paper window: pinstripe title bar, album sleeve."""
    w, h = 420.0, 432.0
    image = _canvas(w, h)
    p = _open(image)
    p.fillRect(QRectF(0, 0, w, h), _c("#e9dfba"))

    p.fillRect(
        QRectF(0, 0, w, h),
        _vgrad((0, 0, w, h), [(0.0, _c("#f7efcf")), (1.0, _c("#ddd0aa"))]),
    )
    rng = random.Random(5104)
    p.setPen(Qt.PenStyle.NoPen)
    for _ in range(700):
        shade = rng.choice(("#ffffff", "#8a8064"))
        p.setBrush(_c(shade, rng.randint(4, 10)))
        p.drawRect(QRectF(rng.uniform(2, w - 2), rng.uniform(2, h - 2), 0.7, 0.7))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Pinstripe title bar with the wordmark set like a Mac window title.
    p.fillRect(QRectF(0, 0, w, 40), _c("#f9f0d2"))
    p.setPen(QPen(_c("#d6c9a4"), 0.7))
    for sy in range(6, 38, 4):
        p.drawLine(QPointF(0, sy + 0.5), QPointF(w, sy + 0.5))
    p.fillRect(QRectF(160, 4, 100, 32), _c("#f9f0d2"))
    _wordmark(p, 171, 15, "AMBERFADER", "#302d29", scale=1.3)
    p.setPen(QPen(_c("#302d29"), 1.0))
    p.drawLine(QPointF(0, 40), QPointF(w, 40))
    p.setPen(QPen(_c("#fff9df"), 0.8))
    p.drawLine(QPointF(0, 41.2), QPointF(w, 41.2))

    # Vinyl peeking from a cream album sleeve around the cover square.
    vinyl = _ellipse(124, 142, 98, 98)
    p.fillPath(vinyl, _c("#26221e"))
    p.save()
    p.setClipPath(vinyl)
    p.setPen(QPen(_c("#4a453c", 90), 0.6))
    for radius in range(36, 96, 8):
        p.drawEllipse(QPointF(124, 142), radius, radius)
    p.restore()
    p.fillPath(_ellipse(124, 142, 30, 30), _c("#7a3b2e"))
    p.setPen(QPen(_c("#a35548"), 0.8))
    p.drawEllipse(QPointF(124, 142), 30, 30)

    sleeve = _rr((14, 42, 200, 200), 1).subtracted(_ellipse(214, 142, 12, 12))
    p.fillPath(sleeve, _c("#fbf3d8"))

    # Ringwear and a dog-eared corner live only in the sleeve margin.
    margin = sleeve.subtracted(_rr((24, 52, 180, 180), 0))
    p.save()
    p.setClipPath(margin)
    p.setPen(QPen(_c("#b3a67e", 70), 0.9))
    p.drawEllipse(QPointF(114, 142), 95, 95)
    p.drawEllipse(QPointF(114, 142), 88, 88)
    p.restore()
    fold = QPainterPath(QPointF(14, 54))
    fold.lineTo(QPointF(14, 42))
    fold.lineTo(QPointF(26, 42))
    fold.closeSubpath()
    p.fillPath(fold, _c("#e6d9b0"))
    p.setPen(QPen(_c("#b3a67e", 120), 0.7))
    p.drawLine(QPointF(14, 54), QPointF(26, 42))
    p.setPen(QPen(_c("#7e796a"), 1.0))
    p.drawPath(sleeve)

    # Ruled index card behind the track readouts.
    p.fillRect(QRectF(216, 56, 190, 178), _c("#fff9df"))
    p.setPen(QPen(_c("#7e796a"), 1.0))
    p.drawRect(QRectF(216, 56, 190, 178))
    p.setPen(QPen(_c("#d8cfae"), 0.7))
    p.drawRect(QRectF(218.5, 58.5, 185, 173))

    # Seek ruler: thin slot with tick marks along the upper edge.
    p.fillRect(QRectF(22, 294, 376, 24), _c("#f2e7c4"))
    p.setPen(QPen(_c("#7e796a"), 1.0))
    p.drawRect(QRectF(22, 294, 376, 24))
    p.setPen(QPen(_c("#7e796a", 110), 0.7))
    for tx in range(34, 392, 31):
        p.drawLine(QPointF(tx, 295.5), QPointF(tx, 299.0))

    # Tear-off perforation above the status strip.
    p.setPen(QPen(_c("#b3a684", 160), 0.8, Qt.PenStyle.DashLine))
    p.drawLine(QPointF(20, 369), QPointF(400, 369))

    # Ink-stamped monogram and tiny model engraving on the bottom margin.
    p.save()
    p.translate(390, 412)
    p.rotate(-7)
    p.setPen(QPen(_c("#a52f29", 150), 1.2))
    p.drawEllipse(QPointF(0, 0), 11, 11)
    _dots(p, -7.2, -4.5, "AF", _c("#a52f29", 170), 1.3)
    p.restore()
    _wordmark(p, 26, 410, "PS-420", "#5c584f", scale=0.9)

    p.setPen(QPen(_c("#302d29"), 1.0))
    p.drawRect(QRectF(0.5, 0.5, w - 1, h - 1))
    p.end()
    return image


# --- driver ------------------------------------------------------------

RENDERERS = {
    "amber-classic": render_amber_classic,
    "copper-reel": render_copper_reel,
    "midnight-rack": render_midnight_rack,
    "moonstone": render_moonstone,
    "paper-signal": render_paper_signal,
}


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenMode.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(buffer.data())


def _translucent_regions(face: dict[str, Any], image: QImage) -> list[str]:
    """Names of manifest regions that contain any pixel below MIN_ALPHA."""
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    regions = {"drag": face["drag"], **face["controls"]}
    bad = []
    for name, rect in sorted(regions.items()):
        x, y, rw, rh = (int(v * SCALE) for v in rect)
        for row in range(y, y + rh):
            start = row * stride + x * 4 + 3
            if min(data[start : start + rw * 4 : 4]) < MIN_ALPHA:
                bad.append(name)
                break
    return bad


def _render(face: dict[str, Any]) -> tuple[QImage, bytes, list[str]]:
    renderer = RENDERERS[face["id"]]
    first = renderer(face)
    if _encode_png(first) != _encode_png(renderer(face)):
        raise RuntimeError(f"{face['id']}: render is not deterministic")
    problems = []
    width, height = face["size"]
    if first.width() != int(width * SCALE) or first.height() != int(height * SCALE):
        problems.append("bad canvas size")
    if max(first.width(), first.height()) > MAX_DIMENSION:
        problems.append("exceeds 2048px")
    translucent = _translucent_regions(face, first)
    if translucent:
        problems.append(f"alpha<128 under: {','.join(translucent)}")
    png = _encode_png(first)
    if len(png) > MAX_FILE_BYTES:
        problems.append("exceeds 4 MiB")
    return first, png, problems


def main() -> int:
    failures = 0
    for face_dir in sorted(FACES_ROOT.iterdir()):
        manifest = face_dir / "face.json"
        if not manifest.is_file():
            continue
        face = json.loads(manifest.read_text())
        image, png, problems = _render(face)
        if problems:
            failures += 1
            print(f"{face['id']}: FAIL ({'; '.join(problems)})")
            continue
        out = manifest.with_name("background.png")
        out.write_bytes(png)
        print(
            f"{face['id']}: {image.width()}x{image.height()} "
            f"{len(png) / 1024:.0f} KiB  alpha>=128 on all regions  -> {out.name}"
        )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
