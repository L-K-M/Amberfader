"""Instant Print: a freshly developed instant photo taped up by one corner.

The cover is the picture: a 412 px print inside a 2 px near-black image
edge, set into a satin white frame. A strip of paper tape holds the top
left corner. The player lives on the wide white chin: transport buttons are
debossed dimples in the card, the utility buttons are small paper tabs, and
the window buttons are yellow archival dot stickers. Hover states are drawn
with a red marker, as if someone had circled the control by hand.

One light comes from the top left. Every random detail uses a seeded
random.Random, so the exporter's two renders match byte for byte. Sizes and
coordinates are logical pixels; kit.canvas scales the painter by kit.SCALE.
"""

from __future__ import annotations

import math
import random
import zlib
from itertools import pairwise

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)

SEED = zlib.crc32(b"instant-print")

PAPER = QRectF(2, 10, 456, 636)
PAPER_RADIUS = 6.0
# The tape strip in its own coordinates, about TAPE_CENTRE. It lies level:
# its top edge is the only part of the outline over air, and the window
# mask is a 1x alpha threshold, so any slant there would show as stair
# steps. The top edge sits on a whole logical pixel (y 4) for the same
# reason; the torn ends carry the hand-made feel instead.
TAPE = QRectF(-100, -13, 200, 26)
TAPE_CENTRE = QPointF(120, 17)
# Each torn end: a few irregular teeth along one dominant slant.
TEAR_TEETH = (4, 5)
TEAR_AMPLITUDE = (0.7, 2.1)
TEAR_SLANT = {"left": -2.6, "right": 3.4}

# The image edge: a 2 px recessed border around the 412 px art rect.
BEZEL = QRectF(22, 46, 416, 416)
# Readouts sit straight on the chin, so its texture is half strength below
# CHIN_CALM_Y, eased in over CHIN_FEATHER px so no seam shows in the borders.
CHIN_CALM_Y = 466.0
CHIN_FEATHER = 24.0
# The crimp over the developer pod: one faint full-width crease.
CREASE_Y = 639.25

PAPER_WHITE = QColor("#f4f1ea")
PAPER_EDGE = "#b7ae9e"
FIBRE = "#b9b0a0"
IMAGE_EDGE = QColor("#1a1816")
TAPE_OVER_AIR = QColor("#e4d3a0")
# Over the card the tape is this tint; at alpha 140 it averages #f0e0b2,
# lighter than the denser over-air colour, in the stickers' butter yellow.
TAPE_TINT = QColor(0xec, 0xd2, 0x84, 140)
TAPE_FIBRE = "#c9bc9c"
GROOVE = QColor("#e9e4d9")
# The slider channel's even margin around the host's inset rail.
GROOVE_MARGIN = 2.0
MARKER = "#b5402b"
SHADE_INK = "#8f8676"
# Speck strengths, in alpha steps out of 255.
GRAIN = 10
MOTTLE = 5
TAPE_GRAIN = 7

FAMILIES = {
    "previous": "transport", "next": "transport", "like": "transport",
    "play": "play",
    "search": "utility", "show": "utility", "hide": "utility",
    "menu": "chrome", "minimize": "chrome", "close": "chrome",
}


def _rgba(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


def _hairline(
    painter: QPainter, start: QPointF, end: QPointF, color: QColor, width: float = 0.5,
) -> None:
    painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    painter.drawLine(start, end)


# Noise tiles ----------------------------------------------------------------

_TILES: dict[tuple, QPixmap] = {}


def _speckle(grey: bytes, size: int, amplitude: int) -> QPixmap:
    """Turn grey noise into signed specks: black below mid-grey, white above.

    SoftLight barely moves near-white paper, so the grain is painted with
    ordinary alpha instead: each pixel darkens or lightens by up to
    amplitude/255, whatever lies beneath.
    """
    levels = [round((value / 255 * 2 - 1) * amplitude) for value in range(256)]
    shade = bytes(max(level, 0) for level in levels)
    alpha = bytes(abs(level) for level in levels)
    data = bytearray(size * size * 4)
    data[0::4] = data[1::4] = data[2::4] = grey.translate(shade)
    data[3::4] = grey.translate(alpha)
    # QImage borrows the buffer, so keep it referenced until the copy.
    buffer = bytes(data)
    image = QImage(buffer, size, size, size * 4, QImage.Format.Format_RGBA8888_Premultiplied)
    return QPixmap.fromImage(image.copy())


def _grain_tile(amplitude: int, salt: int) -> QPixmap:
    """A 256 px tile of independent specks, one per device pixel."""
    key = ("grain", amplitude, salt)
    if key not in _TILES:
        rng = random.Random(SEED + salt)
        _TILES[key] = _speckle(rng.randbytes(256 * 256), 256, amplitude)
    return _TILES[key]


def _mottle_tile(amplitude: int, salt: int, cell: int = 4) -> QPixmap:
    """A seamless low-frequency tile: coarse noise, bilinearly enlarged.

    The coarse field is tiled 3x3 before scaling and the centre cropped, so
    the interpolation wraps across tile edges and no seam shows.
    """
    key = ("mottle", amplitude, salt, cell)
    if key not in _TILES:
        size = 256 // cell
        rng = random.Random(SEED + 7919 * salt)
        noise = rng.randbytes(size * size)
        coarse = QImage(noise, size, size, size, QImage.Format.Format_Grayscale8).copy()
        wrapped = QImage(size * 3, size * 3, QImage.Format.Format_Grayscale8)
        painter = QPainter(wrapped)
        for row in range(3):
            for column in range(3):
                painter.drawImage(column * size, row * size, coarse)
        painter.end()
        large = wrapped.scaled(
            768, 768, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).copy(256, 256, 256, 256)
        grey = bytes(large.constBits())
        stride = large.bytesPerLine()
        rows = b"".join(grey[row * stride:row * stride + 256] for row in range(256))
        _TILES[key] = _speckle(rows, 256, amplitude)
    return _TILES[key]


def _overlay(
    painter: QPainter, path: QPainterPath, tile: QPixmap, opacity: float, scale: float,
) -> None:
    """Tile specks over path; scale 1/kit.SCALE puts one tile px per device px."""
    painter.save()
    painter.setClipPath(path, Qt.ClipOperation.IntersectClip)
    painter.setOpacity(opacity)
    bounds = path.boundingRect()
    painter.scale(scale, scale)
    painter.drawTiledPixmap(
        QRectF(
            math.floor(bounds.x() / scale), math.floor(bounds.y() / scale),
            math.ceil(bounds.width() / scale) + 4, math.ceil(bounds.height() / scale) + 4,
        ),
        tile,
    )
    painter.restore()


# Geometry -------------------------------------------------------------------


def _paper_path(kit) -> QPainterPath:
    return kit.rounded(PAPER, PAPER_RADIUS)


def _tape_transform() -> QTransform:
    return QTransform.fromTranslate(TAPE_CENTRE.x(), TAPE_CENTRE.y())


def _torn_end(rng: random.Random, x: float, slant: float, outward: int) -> list[QPointF]:
    """A hand tear across one short end of the tape, listed top to bottom.

    The tear runs along one dominant slant (slant px from top to bottom)
    and breaks into a few irregular teeth: uneven spacing, uneven depth,
    with a small kink inside each flank. Both corners stay on the long
    edges, so the level top edge is never broken.
    """
    top, bottom = TAPE.top(), TAPE.bottom()
    teeth = rng.choice(TEAR_TEETH)
    weights = [rng.uniform(0.6, 1.6) for _ in range(2 * teeth)]
    total = sum(weights)
    ys = [top]
    for weight in weights:
        ys.append(ys[-1] + (bottom - top) * weight / total)
    ys[-1] = bottom

    def base(y: float) -> float:
        return x + slant * ((y - top) / (bottom - top) - 0.5)

    vertices = []
    for index, y in enumerate(ys):
        if index in (0, len(ys) - 1):
            offset = 0.0
        elif index % 2:
            offset = outward * rng.uniform(*TEAR_AMPLITUDE)
        else:
            offset = -outward * rng.uniform(0.2, 0.9)
        vertices.append(QPointF(base(y) + offset, y))

    points = [vertices[0]]
    for first, second in pairwise(vertices):
        t = rng.uniform(0.35, 0.65)
        y = first.y() + (second.y() - first.y()) * t
        points.append(QPointF(
            first.x() + (second.x() - first.x()) * t + rng.uniform(-0.45, 0.45), y,
        ))
        points.append(second)
    return points


def _tears() -> tuple[list[QPointF], list[QPointF]]:
    """The left and right torn ends, each top to bottom, in tape coordinates."""
    rng = random.Random(SEED + 11)
    right = _torn_end(rng, TAPE.right(), TEAR_SLANT["right"], 1)
    left = _torn_end(rng, TAPE.left(), TEAR_SLANT["left"], -1)
    return left, right


def _polyline(points: list[QPointF]) -> QPainterPath:
    path = QPainterPath(points[0])
    for point in points[1:]:
        path.lineTo(point)
    return path


def _tape_local() -> QPainterPath:
    left, right = _tears()
    path = _polyline([*right, *reversed(left)])
    path.closeSubpath()
    return path


def _tape_path() -> QPainterPath:
    return _tape_transform().map(_tape_local())


# Background -----------------------------------------------------------------


def _paint_paper(painter: QPainter, kit, face: dict) -> None:
    paper = _paper_path(kit)
    painter.fillPath(paper, PAPER_WHITE)

    # Light from the top left: a faint brightening there, a faint fall-off
    # toward the bottom right corner.
    light = QLinearGradient(PAPER.topLeft(), PAPER.bottomRight())
    light.setColorAt(0, _rgba("#ffffff", 40))
    light.setColorAt(0.55, _rgba("#ffffff", 0))
    light.setColorAt(1, _rgba("#000000", 10))
    painter.fillPath(paper, light)
    # Held only by the tape, the card bows gently away from the wall: the
    # far corner turns a shade from the light.
    bow = QRadialGradient(TAPE_CENTRE, 760)
    bow.setColorAt(0, _rgba("#000000", 0))
    bow.setColorAt(0.62, _rgba("#000000", 0))
    bow.setColorAt(1, _rgba("#3a3022", 12))
    painter.fillPath(paper, bow)

    # Satin card: device-pixel grain plus a soft mottle. Half of it covers
    # the whole card; the other half fades out toward the chin, so the
    # readouts sit on calmer paper without a seam in the side borders.
    _paper_texture(painter, kit, paper, 0.5)
    width, height = face["size"]
    layer, layer_painter = kit.canvas(width, height)
    _paper_texture(layer_painter, kit, paper, 0.5)
    fade = QLinearGradient(QPointF(0, CHIN_CALM_Y - CHIN_FEATHER), QPointF(0, CHIN_CALM_Y))
    fade.setColorAt(0, _rgba("#000000", 255))
    fade.setColorAt(1, _rgba("#000000", 0))
    layer_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    layer_painter.fillRect(QRectF(0, 0, width, height), fade)
    layer_painter.end()
    painter.drawImage(QRectF(0, 0, width, height), layer)

    _paint_fibres(painter, face)


def _paper_texture(painter: QPainter, kit, path: QPainterPath, strength: float) -> None:
    """The card's satin grain: device-pixel noise over a soft mottle."""
    _overlay(painter, path, _grain_tile(GRAIN, 1), strength, 1 / kit.SCALE)
    _overlay(painter, path, _mottle_tile(MOTTLE, 2), strength, 1.0)


def _fibre_allowed(point: QPointF, chrome: list[QRectF]) -> bool:
    if any(rect.contains(point) for rect in chrome):
        return False
    x, y = point.x(), point.y()
    if y < 44:
        return True
    return y < CHIN_CALM_Y - 2 and (x < 21 or x > 439)


def _paint_fibres(painter: QPainter, face: dict) -> None:
    rng = random.Random(SEED + 23)
    controls = face["controls"]
    chrome = [
        QRectF(*controls[name]).adjusted(-2, -2, 2, 2)
        for name in ("menu", "minimize", "close")
    ]
    painter.save()
    painter.setClipRect(PAPER.adjusted(1.5, 1.5, -1.5, -1.5))
    placed = 0
    while placed < 250:
        point = QPointF(rng.uniform(4, 456), rng.uniform(12, 462))
        if not _fibre_allowed(point, chrome):
            continue
        placed += 1
        length = rng.uniform(1.5, 4.5)
        angle = rng.uniform(0, math.pi)
        bend = rng.uniform(-0.8, 0.8)
        dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
        start = QPointF(point.x() - dx, point.y() - dy)
        end = QPointF(point.x() + dx, point.y() + dy)
        control = QPointF(point.x() - dy * bend, point.y() + dx * bend)
        path = QPainterPath(start)
        path.quadTo(control, end)
        light = rng.random() < 0.3
        color = _rgba("#ffffff", rng.randint(50, 80)) if light else _rgba(
            FIBRE, rng.randint(18, 34)
        )
        painter.setPen(QPen(color, 0.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
    painter.restore()


def _paint_image_edge(painter: QPainter, face: dict) -> None:
    painter.fillRect(BEZEL, IMAGE_EDGE)
    art = QRectF(*face["controls"]["art"])
    painter.fillRect(art, IMAGE_EDGE)

    # The frame mask stands proud of the print: its window wall is in shade
    # along the top and left, and catches the light along the bottom and right.
    left, top, right, bottom = BEZEL.left(), BEZEL.top(), BEZEL.right(), BEZEL.bottom()
    _hairline(painter, QPointF(left - 1, top - 0.25), QPointF(right, top - 0.25),
              _rgba("#a69d8d", 150))
    _hairline(painter, QPointF(left - 1, top - 0.75), QPointF(right - 1, top - 0.75),
              _rgba("#a69d8d", 60))
    _hairline(painter, QPointF(left - 0.25, top), QPointF(left - 0.25, bottom),
              _rgba("#a69d8d", 150))
    _hairline(painter, QPointF(left - 0.75, top), QPointF(left - 0.75, bottom - 1),
              _rgba("#a69d8d", 60))
    _hairline(painter, QPointF(left, bottom + 0.25), QPointF(right + 1, bottom + 0.25),
              _rgba("#ffffff", 220))
    _hairline(painter, QPointF(left + 1, bottom + 0.75), QPointF(right + 1, bottom + 0.75),
              _rgba("#ffffff", 120))
    _hairline(painter, QPointF(right + 0.25, top), QPointF(right + 0.25, bottom + 1),
              _rgba("#ffffff", 220))
    _hairline(painter, QPointF(right + 0.75, top + 1), QPointF(right + 0.75, bottom + 1),
              _rgba("#ffffff", 120))

    # The outermost device pixel of the image edge: the cut frame's lip.
    _hairline(painter, QPointF(left, top + 0.25), QPointF(right, top + 0.25),
              _rgba("#000000", 120))
    _hairline(painter, QPointF(left + 0.25, top), QPointF(left + 0.25, bottom),
              _rgba("#000000", 120))
    _hairline(painter, QPointF(left, bottom - 0.25), QPointF(right, bottom - 0.25),
              _rgba("#4a443c", 200))
    _hairline(painter, QPointF(right - 0.25, top), QPointF(right - 0.25, bottom),
              _rgba("#4a443c", 200))


def _paint_groove(painter: QPainter, kit, control: QRectF) -> None:
    """A shallow channel pressed into the card around a slider rail.

    The host's inset rim is its 4 px groove grown by 1 px, centred in the
    control and spanning its full width. The channel is that rim grown by
    GROOVE_MARGIN on every side, so an even slot shows all round it: in
    shade along the upper left, catching the light along the lower right.
    """
    inset = (control.height() - 6) / 2
    rim = control.adjusted(0, inset, 0, -inset)
    rect = rim.adjusted(-GROOVE_MARGIN, -GROOVE_MARGIN, GROOVE_MARGIN, GROOVE_MARGIN)
    path = kit.rounded(rect, rect.height() / 2)
    painter.fillPath(path, GROOVE)
    painter.save()
    painter.setClipPath(path)
    painter.fillPath(path.subtracted(path.translated(0.6, 1.0)), _rgba("#000000", 38))
    painter.fillPath(path.subtracted(path.translated(0.3, 0.5)), _rgba("#000000", 18))
    painter.fillPath(path.subtracted(path.translated(-0.6, -1.0)), _rgba("#ffffff", 170))
    painter.restore()


def _paint_chin(painter: QPainter, kit, face: dict) -> None:
    controls = face["controls"]
    for name in ("seek", "volume"):
        _paint_groove(painter, kit, QRectF(*controls[name]))

    # The crimp over the developer pod: one faint crease across the card,
    # lit just above. Clean paper continues below it to the cut edge.
    painter.save()
    painter.setClipPath(kit.rounded(PAPER.adjusted(1, 1, -1, -1), PAPER_RADIUS - 1))
    left, right = PAPER.left(), PAPER.right()
    _hairline(painter, QPointF(left, CREASE_Y - 0.5), QPointF(right, CREASE_Y - 0.5),
              _rgba("#ffffff", 150))
    _hairline(painter, QPointF(left, CREASE_Y), QPointF(right, CREASE_Y), _rgba("#b5ab99", 70))
    painter.restore()


def _paint_paper_edge(painter: QPainter, kit) -> None:
    paper = _paper_path(kit)
    painter.save()
    painter.setClipPath(paper)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # The card's cut edge: one device pixel just inside the silhouette.
    painter.setPen(QPen(QColor(PAPER_EDGE), 1.0))
    painter.drawPath(paper)
    # A bevel inside it, lit at the top left and shaded at the bottom right.
    bevel = QLinearGradient(PAPER.topLeft(), PAPER.bottomRight())
    bevel.setColorAt(0, _rgba("#ffffff", 200))
    bevel.setColorAt(0.45, _rgba("#ffffff", 90))
    bevel.setColorAt(0.6, _rgba("#ffffff", 0))
    bevel.setColorAt(1, _rgba("#8a806f", 70))
    painter.setPen(QPen(bevel, 0.5))
    painter.drawPath(kit.rounded(PAPER.adjusted(0.75, 0.75, -0.75, -0.75), PAPER_RADIUS - 0.75))
    painter.restore()


def _paint_tape(painter: QPainter, kit) -> None:
    paper = _paper_path(kit)
    tape = _tape_path()
    on_paper = paper.intersected(tape)

    # Contact shadow: the tape barely lifts off the card, so only a sliver
    # past its lower right edge darkens. Under the tape the card stays clean.
    painter.save()
    painter.setClipPath(paper)
    painter.fillPath(tape.translated(0.5, 1.0).subtracted(tape), _rgba("#3c321e", 34))
    painter.fillPath(tape.translated(0.25, 0.5).subtracted(tape), _rgba("#3c321e", 40))
    painter.restore()

    # Over the air the tape must be opaque, so it takes a pre-blended,
    # denser colour. Over the card it is a real tint: the card's grain and
    # fibres show through it.
    painter.fillPath(tape.subtracted(paper), TAPE_OVER_AIR)
    painter.fillPath(on_paper, TAPE_TINT)
    # The card's top edge shows through as a soft step.
    painter.save()
    painter.setClipPath(on_paper)
    painter.setPen(QPen(_rgba(PAPER_EDGE, 120), 1.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(paper)
    painter.restore()

    painter.save()
    painter.setClipPath(tape)
    painter.setTransform(_tape_transform(), True)
    # The tape lies slightly domed: a little light along its middle.
    sheen = QLinearGradient(QPointF(0, TAPE.top()), QPointF(0, TAPE.bottom()))
    sheen.setColorAt(0, _rgba("#fffaf0", 0))
    sheen.setColorAt(0.4, _rgba("#fffaf0", 40))
    sheen.setColorAt(1, _rgba("#6b5a35", 14))
    painter.fillRect(TAPE.adjusted(-4, 0, 4, 0), sheen)
    # Paper tape crepe: fine creases across the strip, one device pixel
    # wide and a few long.
    painter.setOpacity(0.7)
    painter.scale(0.5, 3.0)
    painter.drawTiledPixmap(
        QRectF(TAPE.left() / 0.5 - 16, TAPE.top() / 3 - 4, TAPE.width() / 0.5 + 32,
               TAPE.height() / 3 + 8),
        _grain_tile(TAPE_GRAIN, 31),
    )
    painter.restore()

    rng = random.Random(SEED + 41)
    painter.save()
    painter.setClipPath(tape)
    painter.setTransform(_tape_transform(), True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for _ in range(6):
        y = rng.uniform(TAPE.top() + 2, TAPE.bottom() - 2)
        start = rng.uniform(TAPE.left(), TAPE.right() - 40)
        length = rng.uniform(30, 110)
        drift = rng.uniform(-0.6, 0.6)
        path = QPainterPath(QPointF(start, y))
        path.cubicTo(
            QPointF(start + length / 3, y + drift), QPointF(start + 2 * length / 3, y - drift),
            QPointF(start + length, y + drift / 2),
        )
        painter.setPen(QPen(_rgba(TAPE_FIBRE, rng.randint(40, 70)), 0.4))
        painter.drawPath(path)

    # Slit long edges: lit along the top, a denser line along the bottom.
    span = (TAPE.left() + 3, TAPE.right() - 3)
    _hairline(painter, QPointF(span[0], TAPE.top() + 0.25), QPointF(span[1], TAPE.top() + 0.25),
              _rgba("#fffaf0", 170))
    _hairline(painter, QPointF(span[0], TAPE.top() + 0.75), QPointF(span[1], TAPE.top() + 0.75),
              _rgba("#fffaf0", 60))
    _hairline(painter, QPointF(span[0], TAPE.bottom() - 0.25),
              QPointF(span[1], TAPE.bottom() - 0.25), _rgba("#a49470", 150))
    painter.restore()

    # Torn ends fray: loose fibres make them a touch lighter and softer,
    # following each tear. Only the inner half of each stroke lands on tape.
    painter.save()
    painter.setClipPath(tape)
    painter.setTransform(_tape_transform(), True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for end in map(_polyline, _tears()):
        for width, alpha in ((5.0, 40), (2.0, 70)):
            painter.setPen(QPen(
                _rgba("#fffaf0", alpha), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap,
                Qt.PenJoinStyle.RoundJoin,
            ))
            painter.drawPath(end)
    painter.restore()


def render_background(face: dict, kit) -> QImage:
    width, height = face["size"]
    image, painter = kit.canvas(width, height)
    _paint_paper(painter, kit, face)
    _paint_image_edge(painter, face)
    _paint_chin(painter, kit, face)
    _paint_paper_edge(painter, kit)
    _paint_tape(painter, kit)
    painter.end()
    return image


# Buttons --------------------------------------------------------------------


def _marker_loop(
    centre: QPointF, rx: float, ry: float, salt: int, *,
    squareness: float = 2.0, count: int = 24, lean: float = 10.0, begin: float = 112.0,
    widen: float = 3.0, wobble: float = 1.0,
) -> QPainterPath:
    """A hand-drawn loop in red marker, overshooting where it began.

    count points on a slightly leaning superellipse (squareness 2 is an
    ellipse; higher values square it up to circle a word) with a slow
    seeded wobble. The loop widens by `widen` px toward its end, so the 25
    degree overshoot runs just outside the start of the stroke, not on top
    of it.
    """
    rng = random.Random(SEED + salt)
    start = math.radians(begin + rng.uniform(-12, 12))
    sweep = math.radians(360 + 25)
    tilt = math.radians(-lean * rng.uniform(0.6, 1.4))
    phases = (rng.uniform(0, math.tau), rng.uniform(0, math.tau))
    exponent = 2 / squareness
    points = []
    for index in range(count + 1):
        t = index / count
        angle = start - sweep * t
        spread = widen * (t ** 3 - 0.36) + wobble * (
            0.35 * math.sin(2 * angle + phases[0]) + 0.25 * math.sin(3 * angle + phases[1])
            + rng.uniform(-0.12, 0.12)
        )
        cos, sin = math.cos(angle), math.sin(angle)
        x = math.copysign(abs(cos) ** exponent, cos) * (rx + spread) * 1.03
        y = -math.copysign(abs(sin) ** exponent, sin) * (ry + spread) * 0.97
        points.append(QPointF(
            centre.x() + x * math.cos(tilt) - y * math.sin(tilt),
            centre.y() + x * math.sin(tilt) + y * math.cos(tilt),
        ))
    path = QPainterPath(points[0])
    # Catmull-Rom through the points, as cubic Beziers.
    for index in range(len(points) - 1):
        p0 = points[max(index - 1, 0)]
        p1, p2 = points[index], points[index + 1]
        p3 = points[min(index + 2, len(points) - 1)]
        path.cubicTo(
            QPointF(p1.x() + (p2.x() - p0.x()) / 6, p1.y() + (p2.y() - p0.y()) / 6),
            QPointF(p2.x() - (p3.x() - p1.x()) / 6, p2.y() - (p3.y() - p1.y()) / 6),
            p2,
        )
    return path


def _draw_marker(painter: QPainter, loop: QPainterPath, width: float = 1.6) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(
        _rgba(MARKER, 200), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    ))
    painter.drawPath(loop)


def _dimple(painter: QPainter, kit, rect: QRectF, state: str, play: bool) -> None:
    path = kit.control_path(rect, "ellipse", 6)
    if state == "disabled":
        painter.fillPath(path, QColor("#e9e6df"))
        strength = 0.5
    else:
        # A hollow lit from the top left: its upper-left wall turns from the
        # light and its lower-right wall faces it, around a level floor.
        pressed = state == "pressed"
        shade, floor, lit = (
            ("#d4cdbf", "#e6e0d3", "#ece7dc") if pressed else ("#e0dacd", "#f3f0e8", "#f9f7f1")
        )
        walls = QLinearGradient(rect.topLeft(), rect.bottomRight())
        walls.setColorAt(0.15, QColor(shade))
        walls.setColorAt(0.5, QColor(floor))
        walls.setColorAt(0.85, QColor(lit))
        painter.fillPath(path, walls)
        level = QRadialGradient(rect.center(), rect.width() / 2)
        level.setColorAt(0, QColor(floor))
        level.setColorAt(0.5, QColor(floor))
        level.setColorAt(0.8, _rgba(floor, 0))
        painter.fillPath(path, level)
        strength = 1.45 if pressed else 1.0
    _paper_texture(painter, kit, path, 0.5)

    # Concave: the upper-left wall is in shade, the lower-right wall is lit.
    painter.save()
    painter.setClipPath(path)
    shade = path.subtracted(path.translated(0.9, 1.1))
    painter.fillPath(shade, _rgba(SHADE_INK, min(255, round(110 * strength))))
    deep = path.subtracted(path.translated(0.45, 0.55))
    painter.fillPath(deep, _rgba(SHADE_INK, min(255, round(60 * strength))))
    if state != "pressed":
        light = path.subtracted(path.translated(-0.8, -1.0))
        painter.fillPath(light, _rgba("#ffffff", round(200 * strength)))
    painter.restore()

    # The crease where the card bends into the dimple, only along the
    # shaded upper-left lip (45 to 225 degrees), tapering out at both ends.
    crease = QConicalGradient(rect.center(), 45)
    alpha = round(90 * strength)
    for stop, value in ((0, 0), (0.12, alpha), (0.38, alpha), (0.5, 0), (1, 0)):
        crease.setColorAt(stop, _rgba("#9a9182", value))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(crease, 0.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    painter.drawArc(rect.adjusted(0.25, 0.25, -0.25, -0.25), 45 * 16, 180 * 16)

    if play:
        ring = QRectF(0, 0, rect.width() * 0.78, rect.height() * 0.78)
        ring.moveCenter(rect.center())
        # Under the hover marker the ring steps back, so the two never read
        # as one muddy double line.
        fade = min(strength, 1.0) * (0.4 if state == "hover" else 1.0)
        painter.setPen(QPen(_rgba("#a79e8e", round(140 * fade)), 0.8))
        painter.drawEllipse(ring)
        painter.setPen(QPen(_rgba("#ffffff", round(170 * fade)), 0.5))
        painter.drawEllipse(ring.translated(0.5, 0.6))

    if state == "hover":
        if play:
            # Outside the embossed ring, and calm enough that the overshoot
            # stays on the 44 px sprite.
            radius = rect.width() / 2 * 0.9
            loop = _marker_loop(rect.center(), radius, radius, 53, widen=2.0, wobble=0.6)
        else:
            radius = rect.width() / 2 * 0.84
            loop = _marker_loop(rect.center(), radius, radius, 59)
        _draw_marker(painter, loop)


def _sticker(painter: QPainter, kit, rect: QRectF, state: str) -> None:
    path = kit.control_path(rect, "ellipse", 6)
    fills = {
        "normal": ("#f3d77a", "#c9a94a"),
        "hover": ("#f8e295", MARKER),
        "pressed": ("#e2c25f", "#b8963c"),
        "disabled": ("#eee6cf", "#cfc6b2"),
    }
    fill, edge = fills[state]
    if state != "pressed":
        # The sticker's lifted edge casts a hairline shadow on the card.
        lift = 35 if state == "disabled" else 70
        painter.fillPath(path.translated(0.6, 0.8), _rgba("#3c2d0a", lift))
    face = QLinearGradient(rect.topLeft(), rect.bottomRight())
    face.setColorAt(0, QColor(fill).lighter(104))
    face.setColorAt(1, QColor(fill).darker(103))
    painter.fillPath(path, face)
    if state == "pressed":
        painter.save()
        painter.setClipPath(path)
        painter.fillPath(path.subtracted(path.translated(0, 1.0)), _rgba("#000000", 60))
        painter.restore()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(edge), 1.0 if state == "hover" else 0.8))
    painter.drawEllipse(rect.adjusted(0.4, 0.4, -0.4, -0.4))
    if state in ("normal", "hover"):
        sheen = QRectF(0, 0, rect.width() * 0.8, rect.height() * 0.8)
        sheen.moveCenter(rect.center())
        painter.setPen(QPen(_rgba("#ffffff", 120), 1.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap))
        painter.drawArc(sheen, 110 * 16, 50 * 16)


def _tab(painter: QPainter, kit, width: int, height: int, state: str) -> None:
    rect = QRectF(1, 1, width - 2, height - 2.6)
    path = kit.control_path(rect, "capsule", 6)
    if state not in ("pressed", "disabled"):
        painter.fillPath(path.translated(0.5, 0.8), _rgba("#463c28", 60))
    if state == "disabled":
        painter.fillPath(path, QColor("#efece5"))
        border = QColor("#cfc8bb")
    else:
        top, bottom = QColor("#fbf9f3"), QColor("#ece7dc")
        if state == "pressed":
            top, bottom = bottom.darker(102), top.darker(101)
        painter.fillPath(path, kit.gradient(rect, top, bottom))
        border = QColor("#9f9686")
    _paper_texture(painter, kit, path, 0.5)
    painter.save()
    painter.setClipPath(path)
    if state == "pressed":
        painter.fillPath(path.subtracted(path.translated(0, 1.0)), _rgba("#000000", 70))
    elif state != "disabled":
        painter.fillPath(path.subtracted(path.translated(0, 0.6)), _rgba("#ffffff", 220))
    painter.restore()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(border, 0.8))
    painter.drawPath(kit.control_path(rect.adjusted(0.4, 0.4, -0.4, -0.4), "capsule", 6))
    if state == "hover":
        # The word circled in marker, not the tab outlined: a looser loop
        # that leaves cream paper between it and the tab's edge. It starts
        # near top centre, so the overshoot runs along the flat top edge.
        loop = _marker_loop(
            rect.center(), rect.width() / 2 - 5.5, rect.height() / 2 - 4, 61,
            squareness=3.0, count=36, lean=0.8, begin=80.0, widen=1.0, wobble=0.5,
        )
        _draw_marker(painter, loop, 1.4)


def render_button(face: dict, control: str, state: str, kit) -> QImage:
    width, height = face["controls"][control][2:]
    image, painter = kit.canvas(width, height)
    family = FAMILIES[control]
    rect = QRectF(1, 1, width - 2, height - 2)
    if family == "chrome":
        _sticker(painter, kit, rect, state)
    elif family == "utility":
        _tab(painter, kit, width, height, state)
    else:
        _dimple(painter, kit, rect, state, play=family == "play")
    painter.end()
    return image
