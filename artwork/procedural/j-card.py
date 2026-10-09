"""J-Card: an unfolded cobalt cassette insert, read flat on the desk.

Left to right the card has three panels: the back flap (window keys and a
ruled tracklist that doubles as the drag area), the spine (tape hubs that are
the transport buttons) and the front (the cover print, a white write-on panel
for the readouts, and two white slots for the sliders). Two creases separate
the panels; the cobalt ink has cracked to bare board along them.

One light comes from the top left. Every random detail uses a seeded
random.Random, so the exporter's two renders match byte for byte. Sizes and
coordinates are logical pixels; kit.canvas scales the painter by kit.SCALE.
No text is painted: the host owns every label.
"""

from __future__ import annotations

import math
import random
import zlib

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPixmap,
    QRadialGradient,
    QTransform,
)

SEED = zlib.crc32(b"j-card")

CARD = QRectF(2, 2, 596, 592)
CARD_RADIUS = 3
CREASES = (102.0, 178.0)
FLAP = QRectF(CARD.left(), CARD.top(), CREASES[0] - CARD.left(), CARD.height())
SPINE = QRectF(CREASES[0], CARD.top(), CREASES[1] - CREASES[0], CARD.height())
FRONT = QRectF(CREASES[1], CARD.top(), CARD.right() - CREASES[1], CARD.height())

FLAP_INK = QColor("#2b47a6")
# The spine faces the shelf, so it is printed darkest.
SPINE_INK = QColor("#1f3584")
FRONT_INK = QColor("#26409a")
DEEP_INK = "#0e1a4d"
BOARD = "#e9e4da"
STOCK = QColor("#fbfbf7")
STOCK_EDGE = "#c8cfe0"
RULE_BLUE = "#5876d0"
# The warm ink shares the accent's hue (palette.accent fills the sliders),
# printed lighter, so the stripes and the slider fill read as one family.
ACCENT = "#bf3f15"
ORANGE = "#f0602c"
PINK = "#e8467c"
YELLOW = "#f2c14e"

# Back flap: the ruled tracklist is exactly the drag region.
FLAP_RULE_X = (10.0, 94.0)
FLAP_RULE_YS = tuple(range(52, 465, 22))
FLAP_MARGIN_X = 18.5
# The margin rule overhangs the first and the last rule by the same 8 px.
FLAP_RULE_SPAN = (FLAP_RULE_YS[0] - 8.0, FLAP_RULE_YS[-1] + 9.0)
KEY_RULE_Y = 40.25
SIDE_RULE_Y = 250

# Spine: a printed cassette pictogram, the stripe motif, hub seats under
# the transport buttons, and below them the stripe ribbon: three bars run
# down the spine and sweep right into the bottom band, the classic cassette
# spine graphic. Its colours are ordered so each bar lands on its own stripe.
PICTOGRAM = QRectF(118, 30, 44, 28)
SPINE_BAR_YS = (70.0, 74.0, 78.0)
SPINE_BAR_X = (114.0, 166.0)
RIBBON_TOP = 342.0
RIBBON_XS = (144.0, 140.0, 136.0)  # bar centres, inner (orange) bar first
RIBBON_RADIUS = 10.0  # the inner bar's bend; each outer bar adds 4 px

# Front: the write-on panel and slider slots share the cover's column, so
# the cobalt margin is 10 px on both sides of the whole front stack.
WELL = QRectF(188, 420, 400, 118)
SLOTS = (QRectF(188, 544, 258, 26), QRectF(450, 544, 138, 26))
PANEL_RADIUS = 3
WELL_RULE_YS = (451.25, 475.25, 511.25)
WELL_MARGIN_X = 191.5

STRIPE_YS = (576.0, 580.0, 584.0)
STRIPE_COLOURS = (ORANGE, PINK, YELLOW)
STRIPE_HEIGHT = 3.0
# Where the ribbon's bend lands in the band: the spine's band starts here.
RIBBON_BEND_X = RIBBON_XS[0] + RIBBON_RADIUS

CRACKS_PER_CREASE = 20

TRANSPORT = frozenset({"previous", "next", "like"})
UTILITY = frozenset({"search", "show", "hide"})


def _rgba(color: str | QColor, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


def _circle(centre: QPointF, radius: float) -> QRectF:
    return QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)


# Rules use flat caps so they end exactly where they are told to. Their
# positions and widths land on whole device pixels at 2x, so they print crisp.
def _hline(painter: QPainter, y: float, x0: float, x1: float, pen: QPen) -> None:
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(x0, y), QPointF(x1, y))


def _vline(painter: QPainter, x: float, y0: float, y1: float, pen: QPen) -> None:
    pen.setCapStyle(Qt.PenCapStyle.FlatCap)
    painter.setPen(pen)
    painter.drawLine(QPointF(x, y0), QPointF(x, y1))


# ---------------------------------------------------------------- textures

_TILES: dict[tuple[int, int, int], QPixmap] = {}


def _noise_tile(size: int, amplitude: int, salt: int) -> QPixmap:
    """A grey tile, 128 +/- amplitude, neutral under SoftLight."""
    key = (size, amplitude, salt)
    if key not in _TILES:
        rng = random.Random(SEED + salt)
        table = bytes(
            128 + round((value / 255 * 2 - 1) * amplitude) for value in range(256)
        )
        data = rng.randbytes(size * size).translate(table)
        image = QImage(data, size, size, size, QImage.Format.Format_Grayscale8).copy()
        _TILES[key] = QPixmap.fromImage(
            image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
        )
    return _TILES[key]


def _speck_tile(size: int, max_alpha: int, salt: int) -> QPixmap:
    """Dark specks of random alpha: tooth that also shows on white stock."""
    key = (size, -max_alpha, salt)
    if key not in _TILES:
        rng = random.Random(SEED + salt)
        alphas = rng.randbytes(size * size).translate(
            bytes(round(value / 255 * max_alpha) for value in range(256))
        )
        # Premultiplied black: only the alpha byte is non-zero (BGRA order).
        data = b"".join(b"\0\0\0" + alphas[i:i + 1] for i in range(size * size))
        image = QImage(data, size, size, size * 4, QImage.Format.Format_ARGB32_Premultiplied)
        _TILES[key] = QPixmap.fromImage(image.copy())
    return _TILES[key]


def _tile(painter: QPainter, clip: QPainterPath, scale: int, tile: QPixmap,
          mode: QPainter.CompositionMode, opacity: float) -> None:
    """Tile a device-pixel texture over clip."""
    painter.save()
    painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    painter.setCompositionMode(mode)
    painter.setOpacity(opacity)
    painter.resetTransform()
    bounds = clip.boundingRect()
    painter.drawTiledPixmap(
        QRectF(
            math.floor(bounds.x()) * scale, math.floor(bounds.y()) * scale,
            math.ceil(bounds.width() + 2) * scale, math.ceil(bounds.height() + 2) * scale,
        ),
        tile,
    )
    painter.restore()


def _grain(
    painter: QPainter, clip: QPainterPath, scale: int, amplitude: int,
    opacity: float, salt: int,
) -> None:
    """Soft-light device-pixel tooth over clip."""
    _tile(painter, clip, scale, _noise_tile(256, amplitude, salt),
          QPainter.CompositionMode.CompositionMode_SoftLight, opacity)


def _mottle(painter: QPainter, clip: QPainterPath, opacity: float, salt: int) -> None:
    """Broad ink-density clouds: a tiny noise image stretched smoothly."""
    painter.save()
    painter.setClipPath(clip, Qt.ClipOperation.IntersectClip)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
    painter.setOpacity(opacity)
    painter.drawPixmap(CARD, _noise_tile(24, 90, salt), QRectF(0, 0, 24, 24))
    painter.restore()


def _rect_path(rect: QRectF) -> QPainterPath:
    path = QPainterPath()
    path.addRect(rect)
    return path


def _print_ink(painter: QPainter, kit, inks: list[tuple[QPainterPath, str]]) -> None:
    """Lay flat colour like the card's own ink: with tooth and a pooled edge.

    Ink pools slightly along the edges that face away from the top-left
    light, and the board's tooth shows through it, so the stripes share the
    card stock's printed character instead of sitting on it like a sticker.
    """
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    union = QPainterPath()
    union.setFillRule(Qt.FillRule.WindingFill)
    for shape, colour in inks:
        painter.fillPath(shape, QColor(colour))
        # Half a pixel is one device pixel at 2x.
        painter.fillPath(shape.subtracted(shape.translated(-0.5, -0.5)), _rgba("#000000", 34))
        union.addPath(shape)
    painter.restore()
    _mottle(painter, union, 0.06, salt=7)
    _grain(painter, union, kit.SCALE, 40, 0.26, salt=1)


# ---------------------------------------------------------------- card

def _card_path(kit) -> QPainterPath:
    return kit.rounded(CARD, CARD_RADIUS)


def _calm(point: QPointF, zones: list[QRectF]) -> bool:
    return any(zone.contains(point) for zone in zones)


def _calm_zones(face: dict) -> list[QRectF]:
    """Text, keys and the cover: fibres stay out of them."""
    controls = face["controls"]
    zones = [
        QRectF(*controls["art"]).adjusted(-2, -2, 2, 2),
        WELL.adjusted(-2, -2, 2, 2),
        *(slot.adjusted(-2, -2, 2, 2) for slot in SLOTS),
    ]
    for name in ("menu", "minimize", "close", "search", "show", "hide"):
        zones.append(QRectF(*controls[name]).adjusted(-2, -2, 2, 3))
    return zones


def _paint_stock(painter: QPainter, face: dict, kit, rng: random.Random) -> None:
    card = _card_path(kit)
    painter.save()
    painter.setClipPath(card)
    painter.fillRect(FLAP, FLAP_INK)
    painter.fillRect(SPINE, SPINE_INK)
    painter.fillRect(FRONT, FRONT_INK)
    # Unfolded panels never lie quite flat: each bows between its creases,
    # so it catches the light on its left and turns away on its right.
    for panel in (FLAP, SPINE, FRONT):
        bow = QLinearGradient(panel.topLeft(), panel.topRight())
        bow.setColorAt(0, _rgba("#ffffff", 12))
        bow.setColorAt(0.4, _rgba("#ffffff", 0))
        bow.setColorAt(1, _rgba("#000000", 18))
        painter.fillRect(panel, bow)
    painter.restore()

    _mottle(painter, card, 0.10, salt=7)
    _grain(painter, card, kit.SCALE, 40, 0.16, salt=1)

    painter.save()
    painter.setClipPath(card)
    # Satin varnish catching the top-left light, fading by mid-card.
    sheen = QLinearGradient(QPointF(0, 0), QPointF(*face["size"]))
    sheen.setColorAt(0, _rgba("#ffffff", 18))
    sheen.setColorAt(0.45, _rgba("#ffffff", 0))
    sheen.setColorAt(1, _rgba("#000000", 14))
    painter.fillRect(CARD, sheen)

    # Loose board fibres showing through the ink.
    zones = _calm_zones(face)
    placed = 0
    while placed < 420:
        middle = QPointF(rng.uniform(CARD.left() + 3, CARD.right() - 3),
                         rng.uniform(CARD.top() + 3, CARD.bottom() - 3))
        angle = rng.uniform(0, math.pi)
        length = rng.uniform(1.5, 5.0)
        light = rng.random() < 0.6
        alpha = rng.randint(10, 24) if light else rng.randint(14, 28)
        bend = rng.uniform(-1.0, 1.0)
        if _calm(middle, zones):
            continue
        placed += 1
        dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
        fibre = QPainterPath(QPointF(middle.x() - dx, middle.y() - dy))
        fibre.quadTo(
            QPointF(middle.x() - dy * bend / 3, middle.y() + dx * bend / 3),
            QPointF(middle.x() + dx, middle.y() + dy),
        )
        painter.setPen(QPen(_rgba("#c9d4ff" if light else DEEP_INK, alpha), 0.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(fibre)
    painter.restore()


def _paint_flap(painter: QPainter) -> None:
    painter.save()
    rule = QPen(_rgba(RULE_BLUE, 170), 1)
    for y in FLAP_RULE_YS:
        if y == SIDE_RULE_Y:
            # Side A above, side B below: a printed double rule.
            divider = QPen(_rgba("#ffffff", 120), 1)
            _hline(painter, y - 1.0, *FLAP_RULE_X, divider)
            _hline(painter, y + 2.0, *FLAP_RULE_X, divider)
        else:
            _hline(painter, y + 0.5, *FLAP_RULE_X, rule)
    _vline(painter, FLAP_MARGIN_X, *FLAP_RULE_SPAN, QPen(_rgba(ORANGE, 225), 1))
    # A white printed rule closes the window-key row.
    _hline(painter, KEY_RULE_Y, *FLAP_RULE_X, QPen(_rgba("#ffffff", 120), 1.5))
    painter.restore()


def _paint_pictogram(painter: QPainter) -> None:
    ink = _rgba("#ffffff", 170)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(ink, 1.2))
    painter.drawRoundedRect(PICTOGRAM.adjusted(0.6, 0.6, -0.6, -0.6), 4, 4)
    window = QRectF(124, 37, 32, 13)
    painter.setPen(QPen(ink, 0.9))
    painter.drawRoundedRect(window, 2.5, 2.5)
    for x in (130.5, 149.5):
        painter.drawEllipse(_circle(QPointF(x, 43.5), 3.6))
        painter.setBrush(ink)
        painter.drawEllipse(_circle(QPointF(x, 43.5), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    head = QPainterPath(QPointF(127, 57.4))
    head.lineTo(130, 52.5)
    head.lineTo(150, 52.5)
    head.lineTo(153, 57.4)
    painter.drawPath(head)
    painter.restore()


def _ribbon(index: int) -> QPainterPath:
    """One bar of the spine ribbon as a filled shape, from the top to the band.

    The bars bend about one centre, so they stay parallel through the turn
    and each one leaves the bend exactly on its stripe of the band.
    """
    x = RIBBON_XS[index]
    radius = RIBBON_RADIUS + 4 * index
    centre = QPointF(RIBBON_XS[0] + RIBBON_RADIUS, STRIPE_YS[0] + 1.5 - RIBBON_RADIUS)
    line = QPainterPath(QPointF(x, RIBBON_TOP))
    line.lineTo(x, centre.y())
    line.arcTo(_circle(centre, radius), 180, 90)
    # Overlap the band by half a pixel so the joint has no seam.
    line.lineTo(centre.x() + 0.5, centre.y() + radius)
    stroker = QPainterPathStroker()
    stroker.setWidth(STRIPE_HEIGHT)
    stroker.setCapStyle(Qt.PenCapStyle.FlatCap)
    stroker.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
    return stroker.createStroke(line).simplified()


def _paint_spine(painter: QPainter, face: dict, kit) -> None:
    _paint_pictogram(painter)
    left, right = SPINE_BAR_X
    inks = [(_rect_path(QRectF(left, y, right - left, STRIPE_HEIGHT)), colour)
            for y, colour in zip(SPINE_BAR_YS, STRIPE_COLOURS, strict=True)]
    inks += [(_ribbon(index), colour) for index, colour in enumerate(STRIPE_COLOURS)]
    _print_ink(painter, kit, inks)

    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    # Hub seats: a contact shadow and a printed ring just outside each hub.
    controls = face["controls"]
    for name in ("previous", "play", "next", "like"):
        x, y, w, h = controls[name]
        centre = QPointF(x + w / 2, y + h / 2)
        radius = w / 2
        shadow = QRadialGradient(centre + QPointF(0.6, 1.4), radius + 3)
        shadow.setColorAt(0, _rgba("#000000", 90))
        shadow.setColorAt((radius - 1) / (radius + 3), _rgba("#000000", 80))
        shadow.setColorAt(1, _rgba("#000000", 0))
        painter.setBrush(shadow)
        painter.drawEllipse(_circle(centre + QPointF(0.6, 1.4), radius + 3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_rgba("#132460", 160), 2))
        painter.drawEllipse(_circle(centre, radius + 1.5))
        painter.setPen(Qt.PenStyle.NoPen)
    painter.restore()


def _paint_panel(painter: QPainter, rect: QRectF, kit) -> None:
    """White printed write-on stock: flat, with a crisp offset edge."""
    painter.save()
    painter.setPen(QPen(_rgba("#000000", 60), 1))
    painter.setBrush(STOCK)
    painter.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), PANEL_RADIUS, PANEL_RADIUS)
    painter.setPen(QPen(QColor(STOCK_EDGE), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inner = PANEL_RADIUS - 0.5
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), inner, inner)
    painter.restore()
    _tile(painter, kit.rounded(rect.adjusted(1, 1, -1, -1), PANEL_RADIUS), kit.SCALE,
          _speck_tile(128, 10, salt=3), QPainter.CompositionMode.CompositionMode_SourceOver, 1.0)


def _paint_front(painter: QPainter, face: dict, kit) -> None:
    art = QRectF(*face["controls"]["art"])
    painter.save()
    painter.fillRect(art, QColor("#10193f"))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_rgba("#000000", 120), 1))
    painter.drawRect(art.adjusted(-0.5, -0.5, 0.5, 0.5))
    _hline(painter, art.bottom() + 1.5, art.left(), art.right() + 2, QPen(_rgba("#ffffff", 50), 1))
    _vline(painter, art.right() + 1.5, art.top(), art.bottom() + 1, QPen(_rgba("#ffffff", 50), 1))
    painter.restore()

    _paint_panel(painter, WELL, kit)
    painter.save()
    for y in WELL_RULE_YS:
        _hline(painter, y, WELL.left() + 8, WELL.right() - 8, QPen(QColor("#d9dfeb"), 0.5))
    margin = QPen(_rgba(ORANGE, 170), 1)
    _vline(painter, WELL_MARGIN_X, WELL.top() + 4, WELL.bottom() - 4, margin)
    painter.restore()
    for slot in SLOTS:
        _paint_panel(painter, slot, kit)


def _paint_stripes(painter: QPainter, kit, rng: random.Random) -> None:
    # The spine's stretch of the band starts where the ribbon lands in it;
    # the flap's stretch stops just short of its crease.
    spans = ((CARD.left(), CREASES[0] - 0.5), (RIBBON_BEND_X, CARD.right()))
    inks = []
    for y, colour in zip(STRIPE_YS, STRIPE_COLOURS, strict=True):
        band = QPainterPath()
        for x0, x1 in spans:
            band.addRect(QRectF(x0, y, x1 - x0, STRIPE_HEIGHT))
        inks.append((band.intersected(_card_path(kit)), colour))
    _print_ink(painter, kit, inks)

    # Where the band crosses a crease its ink breaks to bare board.
    painter.save()
    top, bottom = STRIPE_YS[0], STRIPE_YS[-1] + STRIPE_HEIGHT
    for xc in CREASES:
        if xc > RIBBON_BEND_X:
            painter.fillRect(QRectF(xc - 0.5, top, 1, bottom - top), QColor(BOARD))
        for _ in range(2):
            x = xc + rng.choice((-1, 1)) * rng.uniform(1.0, 2.0)
            y = rng.uniform(top, bottom - 2)
            end = QPointF(x + rng.uniform(-0.6, 0.6), y + rng.uniform(1, 2))
            painter.setPen(QPen(_rgba(BOARD, rng.randint(70, 110)), 0.5))
            painter.drawLine(QPointF(x, y), end)
    painter.restore()


def _paint_creases(painter: QPainter, kit, rng: random.Random) -> None:
    painter.save()
    painter.setClipPath(_card_path(kit))
    for xc in CREASES:
        # A valley fold lit from the left: the left wall turns away from the
        # light, the right wall towards it.
        shade = QLinearGradient(QPointF(xc - 7, 0), QPointF(xc, 0))
        shade.setColorAt(0, _rgba("#000000", 0))
        shade.setColorAt(1, _rgba("#000000", 48))
        painter.fillRect(QRectF(xc - 7, CARD.top(), 7, CARD.height()), shade)
        lift = QLinearGradient(QPointF(xc, 0), QPointF(xc + 6, 0))
        lift.setColorAt(0, _rgba("#000000", 26))
        lift.setColorAt(0.35, _rgba("#ffffff", 14))
        lift.setColorAt(1, _rgba("#ffffff", 0))
        painter.fillRect(QRectF(xc, CARD.top(), 6, CARD.height()), lift)
        _vline(painter, xc, CARD.top(), CARD.bottom(), QPen(_rgba(DEEP_INK, 150), 1))
        _vline(painter, xc - 1.5, CARD.top(), CARD.bottom(), QPen(_rgba("#ffffff", 18), 1))
        _vline(painter, xc + 1.5, CARD.top(), CARD.bottom(), QPen(_rgba("#ffffff", 34), 1))

        # Ink cracked to bare board along the fold, a little denser near the
        # ends where the card is handled. Each fissure keeps clear of its
        # neighbours so it reads as one crack, not as a stitched seam.
        taken: list[tuple[float, float]] = []
        for index in range(CRACKS_PER_CREASE):
            segments = rng.randint(2, 4)
            for _attempt in range(40):
                if index < 3:
                    y = CARD.top() + rng.uniform(2, 36)
                elif index < 7:
                    y = CARD.bottom() - rng.uniform(10, 44)
                else:
                    y = rng.uniform(CARD.top() + 40, CARD.bottom() - 48)
                length = segments * 2.2
                if all(y > end + 2 or y + length < start - 2 for start, end in taken):
                    break
            taken.append((y, y + length))
            x = xc + rng.uniform(-1.0, 1.0)
            crack = QPainterPath(QPointF(x, y))
            for _ in range(segments):
                x = min(xc + 1.6, max(xc - 1.6, x + rng.uniform(-0.7, 0.7)))
                y += rng.uniform(0.8, 2.2)
                crack.lineTo(x, y)
            painter.setPen(QPen(_rgba(BOARD, rng.randint(60, 110)), 0.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(crack)
        painter.setPen(Qt.PenStyle.NoPen)
        for _ in range(12):
            centre = QPointF(xc + rng.uniform(-1.2, 1.2),
                             rng.uniform(CARD.top() + 2, CARD.bottom() - 2))
            flake = QPainterPath()
            for corner in range(5):
                angle = corner * 2 * math.pi / 5 + rng.uniform(-0.4, 0.4)
                radius = rng.uniform(0.3, 0.9)
                point = QPointF(centre.x() + math.cos(angle) * radius * 0.7,
                                centre.y() + math.sin(angle) * radius * 1.4)
                if corner == 0:
                    flake.moveTo(point)
                else:
                    flake.lineTo(point)
            flake.closeSubpath()
            painter.fillPath(flake, _rgba(BOARD, rng.randint(110, 180)))
    painter.restore()


def _paint_wear(painter: QPainter, kit, rng: random.Random) -> None:
    """Rubbed corners and crease ends where handling exposed the board."""
    painter.save()
    painter.setClipPath(_card_path(kit))
    spots = [
        (QPointF(CARD.left(), CARD.top()), 1, 1),
        (QPointF(CARD.right(), CARD.top()), -1, 1),
        (QPointF(CARD.left(), CARD.bottom()), 1, -1),
        (QPointF(CARD.right(), CARD.bottom()), -1, -1),
    ]
    for corner, sx, sy in spots:
        for _ in range(34):
            distance = rng.uniform(0, 5) ** 1.3
            along = rng.random() < 0.5
            x = corner.x() + sx * (rng.uniform(0, 1.2) if along else distance)
            y = corner.y() + sy * (distance if along else rng.uniform(0, 1.2))
            length = rng.uniform(0.6, 2.5)
            angle = rng.uniform(0, math.pi)
            painter.setPen(QPen(_rgba(BOARD, rng.randint(60, 130)), 0.5))
            painter.drawLine(QPointF(x, y), QPointF(x + math.cos(angle) * length,
                                                    y + math.sin(angle) * length))
    # Scuffs along the cut edges.
    for _ in range(70):
        side = rng.randrange(4)
        depth = rng.uniform(0, 1.3)
        if side < 2:
            x = rng.uniform(CARD.left() + 6, CARD.right() - 6)
            y = CARD.top() + depth if side == 0 else CARD.bottom() - depth
            end = QPointF(x + rng.uniform(0.8, 2.6), y + rng.uniform(-0.3, 0.3))
        else:
            y = rng.uniform(CARD.top() + 6, CARD.bottom() - 6)
            x = CARD.left() + depth if side == 2 else CARD.right() - depth
            end = QPointF(x + rng.uniform(-0.3, 0.3), y + rng.uniform(0.8, 2.6))
        painter.setPen(QPen(_rgba(BOARD, rng.randint(50, 110)), 0.5))
        painter.drawLine(QPointF(x, y), end)
    for xc in CREASES:
        for edge, direction in ((CARD.top(), 1), (CARD.bottom(), -1)):
            notch = QPainterPath(QPointF(xc - 1.4, edge))
            notch.quadTo(QPointF(xc, edge + direction * 3.2), QPointF(xc + 1.4, edge))
            notch.closeSubpath()
            painter.fillPath(notch, _rgba(BOARD, 150))
    painter.restore()


def _paint_edge(painter: QPainter, kit) -> None:
    painter.save()
    painter.setClipPath(_card_path(kit))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_rgba(DEEP_INK, 200), 1))
    inner = CARD_RADIUS - 0.5
    painter.drawRoundedRect(CARD.adjusted(0.5, 0.5, -0.5, -0.5), inner, inner)
    # The cut board edge catches the light along the top and the left.
    top_light, left_light = QPen(_rgba("#ffffff", 40), 1), QPen(_rgba("#ffffff", 28), 1)
    _hline(painter, CARD.top() + 1.5, CARD.left() + 3, CARD.right() - 3, top_light)
    _vline(painter, CARD.left() + 1.5, CARD.top() + 3, CARD.bottom() - 3, left_light)
    painter.restore()


def render_background(face: dict, kit) -> QImage:
    width, height = face["size"]
    image, painter = kit.canvas(width, height)
    rng = random.Random(SEED)
    _paint_stock(painter, face, kit, rng)
    _paint_flap(painter)
    _paint_spine(painter, face, kit)
    _paint_front(painter, face, kit)
    _paint_stripes(painter, kit, rng)
    _paint_creases(painter, kit, rng)
    _paint_wear(painter, kit, rng)
    _paint_edge(painter, kit)
    painter.end()
    return image


# ---------------------------------------------------------------- buttons

def _tooth(angle_degrees: float, centre: QPointF, inner: float, outer: float,
           width: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(QRectF(inner, -width / 2, outer - inner, width), 0.8, 0.8)
    transform = QTransform()
    transform.translate(centre.x(), centre.y())
    transform.rotate(angle_degrees)
    return transform.map(path)


def _pending_seat(painter: QPainter, centre: QPointF, w: int, outer: float,
                  inner: float) -> None:
    """A dark seat band under the host's pending ring on a disabled hub.

    While a play or like command waits for its outcome the host shows the
    disabled sprite with a 1 px dashed ring 2.5 px inside the button, in the
    disabled palette's mid-grey highlight. On the light rim those dashes
    vanish, so the disabled hub sits lower in its seat: a navy band (lit on
    the lower right, like the far wall of a recess) carries the dashes at
    3:1 or better, and a thin light lip keeps the hub's silhouette.
    """
    ring = w / 2 - 2.5
    band_outer = min(outer - 0.5, ring + 1)
    band_inner = min(inner, ring - 1)
    corner = QPointF(band_outer, band_outer)
    wall = QLinearGradient(centre - corner, centre + corner)
    wall.setColorAt(0, QColor("#232c4a"))
    wall.setColorAt(1, QColor("#3a4565"))
    band = QPainterPath()
    band.addEllipse(_circle(centre, band_outer))
    band.addEllipse(_circle(centre, band_inner))
    painter.fillPath(band, QBrush(wall))


def _hub(painter: QPainter, w: int, h: int, state: str, supply: bool) -> None:
    """A tape hub around the glyph, lit from the top left.

    From the outside in: a white moulded rim, a recessed groove bridged by
    sprocket teeth, and a raised spindle cap that carries the host glyph.
    The supply hub (play) adds a flange band and eight teeth.
    """
    centre = QPointF(w / 2, h / 2)
    outer = (w - 2) / 2
    pressed, hover, disabled = state == "pressed", state == "hover", state == "disabled"

    # Contact shadow: only its lower sliver shows inside the host's clip.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(_rgba("#050a24", 35 if pressed else 110))
    painter.drawEllipse(_circle(centre + QPointF(0.3, 0.9), outer))
    if pressed:
        painter.translate(0, 1)

    disc = outer
    if supply:
        # The flange: a moulded band whose sheen turns with the light.
        band = QConicalGradient(centre, 135)
        light, dark = ("#c9cfdc", "#bcc3d2") if disabled else ("#f6f8fc", "#c3ccdf")
        for stop, colour in ((0, light), (0.25, dark), (0.5, light), (0.75, dark), (1, light)):
            band.setColorAt(stop, QColor(colour))
        painter.setBrush(band)
        painter.drawEllipse(_circle(centre, outer))
        disc = outer - 3
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_rgba("#5a6688", 90 if disabled else 150), 0.6))
        painter.drawEllipse(_circle(centre, disc + 0.3))
        painter.setPen(Qt.PenStyle.NoPen)

    groove_outer = 0.86 * disc
    cap = (0.66 if supply else 0.64) * disc
    light_focus = centre + QPointF(-0.35 * disc, -0.4 * disc)

    def dome(radius: float, inverted: bool, deep: bool = False) -> QBrush:
        if disabled:
            return QBrush(QColor("#c9cfdc"))
        gradient = QRadialGradient(light_focus, radius * 1.9)
        first, last = ("#ffffff", "#d9dfed")
        if inverted:
            # A pressed rim sinks deeper than the cap that carries the glyph.
            first, last = ("#b9c3d8", "#e6eaf3") if deep else ("#c7d0e3", "#f3f5fa")
        gradient.setColorAt(0, QColor(first))
        gradient.setColorAt(1, QColor(last))
        return QBrush(gradient)

    def bevel(radius: float, width: float, sunken: bool, strength: int) -> None:
        if disabled:
            return
        corner = QPointF(radius, radius)
        gradient = QLinearGradient(centre - corner, centre + corner)
        lit, shade = _rgba("#ffffff", min(255, strength * 2)), _rgba("#5d6a8e", strength)
        gradient.setColorAt(0, shade if sunken else lit)
        gradient.setColorAt(1, lit if sunken else shade)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QBrush(gradient), width))
        painter.drawEllipse(_circle(centre, radius))
        painter.setPen(Qt.PenStyle.NoPen)

    # Rim.
    painter.setBrush(dome(disc, pressed, deep=True))
    painter.drawEllipse(_circle(centre, disc))
    bevel(disc - 0.9, 0.9, pressed, 110)

    # Groove, its inner shadow under the rim wall and the teeth across it.
    groove = QColor("#b4bccc") if disabled else QColor("#9ca7bf" if pressed else "#bcc5d8")
    painter.setBrush(groove)
    painter.drawEllipse(_circle(centre, groove_outer))
    bevel(groove_outer - 0.6, 1.2, True, 0 if disabled else 150)
    count = 8 if supply else 6
    tooth_width = (0.075 if supply else 0.085) * w
    for index in range(count):
        angle = index * 360 / count + (22.5 if supply else 30)
        tooth = _tooth(angle, centre, cap + 0.9, groove_outer + 0.6, tooth_width)
        if not disabled:
            painter.fillPath(tooth.translated(0.45, 0.7), _rgba("#3b4666", 80))
        painter.fillPath(tooth, QColor("#c9cfdc") if disabled else QColor("#eef1f8"))
        if not disabled:
            painter.setPen(QPen(_rgba("#7d88a6", 110), 0.4))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(tooth)
            painter.setPen(Qt.PenStyle.NoPen)

    # Spindle cap: casts a soft shadow into the groove, then a lit dome.
    if not disabled:
        painter.setBrush(_rgba("#2c3656", 70))
        painter.drawEllipse(_circle(centre + QPointF(0.5, 0.8), cap + 0.2))
    painter.setBrush(dome(cap, pressed))
    painter.drawEllipse(_circle(centre, cap))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor("#a1abc2") if disabled else _rgba("#7d88a6", 170), 0.6))
    painter.drawEllipse(_circle(centre, cap - 0.3))
    bevel(cap - 1.0, 0.8, pressed, 70)

    if disabled:
        _pending_seat(painter, centre, w, outer, disc if supply else groove_outer)

    # Outer edge, and on hover an accent edge with a warm halo inside it.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if hover:
        painter.setPen(QPen(_rgba(ORANGE, 80), 2))
        painter.drawEllipse(_circle(centre, outer - 2))
        painter.setPen(QPen(QColor(ACCENT), 1.2))
    elif disabled:
        painter.setPen(QPen(QColor("#8a93ab"), 0.8))
    else:
        painter.setPen(QPen(QColor("#5a6688"), 0.8))
    painter.drawEllipse(_circle(centre, outer - 0.5))


def _box_key(painter: QPainter, kit, w: int, h: int, state: str, tab: bool) -> None:
    """A printed white key box with a coloured index tab."""
    pressed, hover, disabled = state == "pressed", state == "hover", state == "disabled"
    rect = QRectF(1, 1, w - 2, h - 2)
    painter.setPen(Qt.PenStyle.NoPen)
    shadow = _rgba("#050a24", 35 if pressed else 110)
    painter.fillPath(kit.rounded(rect.translated(0.3, 0.9), 4), shadow)
    if pressed:
        painter.translate(0, 1)
    path = kit.rounded(rect, 4)
    if disabled:
        painter.fillPath(path, QColor("#c9cfdc"))
    else:
        top, bottom = (QColor("#cfd6e6"), QColor("#e8ecf4")) if pressed else (
            QColor("#ffffff"), QColor("#dde3f0"))
        painter.fillPath(path, kit.gradient(rect, top, bottom))
    painter.save()
    painter.setClipPath(path)
    if tab:
        # Printed flush against the key's edge.
        colour = "#9aa3b8" if disabled else (ACCENT if hover else ORANGE)
        painter.fillRect(QRectF(rect.left() + 1, rect.top(), 3, rect.height()), QColor(colour))
    if pressed:
        # The pressed key sits below the card: its top and left walls shade it.
        for start, end in (
            (QPointF(0, rect.top() + 1), QPointF(0, rect.top() + 3.5)),
            (QPointF(rect.left() + 1, 0), QPointF(rect.left() + 2.5, 0)),
        ):
            wall = QLinearGradient(start, end)
            wall.setColorAt(0, _rgba(DEEP_INK, 64))
            wall.setColorAt(1, _rgba(DEEP_INK, 0))
            painter.fillRect(rect, wall)
    painter.restore()
    if not pressed and not disabled:
        painter.setPen(QPen(_rgba("#ffffff", 150), 1))
        start = rect.left() + (6 if tab else 3.5)
        painter.drawLine(QPointF(start, rect.top() + 1.5),
                         QPointF(rect.right() - 3.5, rect.top() + 1.5))
    edge = "#8a93ab" if disabled else (ACCENT if hover else DEEP_INK)
    # One logical pixel on half-pixel insets: two whole device pixels at 2x.
    painter.setPen(QPen(QColor(edge), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 3.5, 3.5)


def render_button(face: dict, control: str, state: str, kit) -> QImage:
    _, _, width, height = face["controls"][control]
    image, painter = kit.canvas(width, height)
    if control in TRANSPORT or control == "play":
        _hub(painter, width, height, state, supply=control == "play")
    else:
        _box_key(painter, kit, width, height, state, tab=control in UTILITY)
    painter.end()
    return image
