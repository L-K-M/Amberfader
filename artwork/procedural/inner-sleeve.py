"""Inner Sleeve: a record jacket with its kraft inner sleeve half pulled out.

The jacket is the cover bezel: 10 px of dark board around the 400 px art.
The sleeve slides out of the jacket's opening on the right. The player is
printed on it around a die-cut window that shows the record's label, with
the play button as the label's centre sticker.

One light comes from the top left. Every random detail uses a seeded
random.Random, so the exporter's two renders match byte for byte. Sizes and
coordinates are logical pixels; kit.canvas scales the painter by kit.SCALE.
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
    QPen,
    QPixmap,
    QRadialGradient,
)

SEED = zlib.crc32(b"inner-sleeve")

JACKET = QRectF(4, 4, 420, 420)
JACKET_RADIUS = 3
SLEEVE = QRectF(400, 12, 292, 404)
SLEEVE_RADIUS = 12
OPENING_X = JACKET.right()

LINER = QRectF(436, 52, 244, 118)
# The rule well keeps 6 px above the seek channel and below the like card,
# and 10 px gaps to the die cut above and below the label window.
RULE = QRectF(436, 303, 244, 65)
WELL_RADIUS = 4
# Liner rows: an accent rule above the title, hairlines in the 6 px gaps
# between artists/time and time/status. The 1 px rule covers logical row 57,
# so it stays crisp at 1x and 2x, midway between the well edge and the caps.
ACCENT_RULE_Y = 57.5
HAIRLINE_YS = (107, 143)

LABEL_CENTRE = QPointF(558, 236)
CUT_RADIUS = 56.0
LABEL_RADIUS = 42.0
GROOVE_RADII = (44, 46.5, 49, 51, 53, 54.5)
# The glued bottom flap's folded edge.
SEAM_Y = 409.0
# Fibres and specks stay this far from the die cut, so its edge reads clean.
CUT_CALM_RADIUS = 60.0

KRAFT = QColor("#b5895a")
KRAFT_DARK = "#6f4c2a"
KRAFT_LIGHT = "#e0c08e"
BOARD = QColor("#2c2722")
CREAM = "#f4ecda"
OXBLOOD = "#8e2f24"
INK_BROWN = "#3d2a18"
DISABLED_PAPER = "#e8dfcd"
DISABLED_INK = "#a8998a"


def _rgba(color: str, alpha: int) -> QColor:
    value = QColor(color)
    value.setAlpha(alpha)
    return value


def _circle(centre: QPointF, radius: float) -> QRectF:
    return QRectF(centre.x() - radius, centre.y() - radius, 2 * radius, 2 * radius)


def _disc(centre: QPointF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(_circle(centre, radius))
    return path


# QImage, not QPixmap: cached pixmaps would outlive the QGuiApplication.
_TILES: dict[tuple[int, int], QImage] = {}


def _noise_tile(amplitude: int, salt: int) -> QImage:
    """A 256 px grey tile, 128 +/- amplitude, neutral under SoftLight."""
    key = (amplitude, salt)
    if key not in _TILES:
        rng = random.Random(SEED + salt)
        table = bytes(
            128 + round((value / 255 * 2 - 1) * amplitude) for value in range(256)
        )
        data = rng.randbytes(256 * 256).translate(table)
        image = QImage(data, 256, 256, 256, QImage.Format.Format_Grayscale8)
        _TILES[key] = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return _TILES[key]


def _grain(
    painter: QPainter, path: QPainterPath, scale: int, amplitude: int,
    opacity: float, salt: int = 0,
) -> None:
    """Soft-light a device-pixel noise tile over path."""
    painter.save()
    painter.setClipPath(path)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
    painter.setOpacity(opacity)
    bounds = path.boundingRect()
    painter.scale(1 / scale, 1 / scale)
    painter.drawTiledPixmap(
        QRectF(
            math.floor(bounds.x()) * scale, math.floor(bounds.y()) * scale,
            math.ceil(bounds.width() + 2) * scale, math.ceil(bounds.height() + 2) * scale,
        ),
        QPixmap.fromImage(_noise_tile(amplitude, salt)),
    )
    painter.restore()


def _calm_zones(face: dict) -> list[QRectF]:
    """Where text, rails and tabs sit: no fibres or specks there."""
    controls = face["controls"]
    zones = [LINER.adjusted(-3, -3, 3, 3), RULE.adjusted(-3, -3, 3, 3)]
    for name in ("search", "show", "hide", "menu", "minimize", "close"):
        zones.append(QRectF(*controls[name]).adjusted(-3, -3, 3, 5))
    return zones


def _is_calm(point: QPointF, zones: list[QRectF]) -> bool:
    if math.dist((point.x(), point.y()), (LABEL_CENTRE.x(), LABEL_CENTRE.y())) < CUT_CALM_RADIUS:
        return True
    return any(zone.contains(point) for zone in zones)


def _paint_sleeve(painter: QPainter, face: dict, kit, rng: random.Random) -> None:
    sleeve = kit.rounded(SLEEVE, SLEEVE_RADIUS)
    painter.save()
    painter.setClipPath(sleeve)
    painter.fillRect(SLEEVE, KRAFT)
    # Light falls from the top left across the sheet.
    shade = QLinearGradient(SLEEVE.topLeft(), SLEEVE.bottomRight())
    shade.setColorAt(0, _rgba("#c99d6c", 70))
    shade.setColorAt(0.55, _rgba("#b5895a", 0))
    shade.setColorAt(1, _rgba("#9a6f43", 70))
    painter.fillRect(SLEEVE, shade)

    # Pulp mottling: broad, faint clouds of lighter and darker fibre.
    painter.setPen(Qt.PenStyle.NoPen)
    for _ in range(110):
        centre = QPointF(rng.uniform(SLEEVE.left(), SLEEVE.right()),
                         rng.uniform(SLEEVE.top(), SLEEVE.bottom()))
        radius = rng.uniform(10, 34)
        tone = "#d1a674" if rng.random() < 0.5 else "#8d6238"
        cloud = QRadialGradient(centre, radius)
        cloud.setColorAt(0, _rgba(tone, rng.randint(10, 22)))
        cloud.setColorAt(1, _rgba(tone, 0))
        painter.setBrush(cloud)
        painter.drawEllipse(_circle(centre, radius))
    painter.restore()

    _grain(painter, sleeve, kit.SCALE, 36, 0.22, salt=1)

    painter.save()
    painter.setClipPath(sleeve)
    # Machine-direction streaks, then loose fibres and specks.
    for _ in range(46):
        y = rng.uniform(SLEEVE.top(), SLEEVE.bottom())
        x = rng.uniform(OPENING_X - 40, SLEEVE.right())
        length = rng.uniform(40, 160)
        tone = "#d6b27f" if rng.random() < 0.5 else "#8a5f35"
        streak = QLinearGradient(QPointF(x, y), QPointF(x + length, y))
        streak.setColorAt(0, _rgba(tone, 0))
        streak.setColorAt(0.5, _rgba(tone, rng.randint(14, 26)))
        streak.setColorAt(1, _rgba(tone, 0))
        painter.setPen(QPen(QBrush(streak), rng.uniform(0.4, 0.9)))
        painter.drawLine(QPointF(x, y), QPointF(x + length, y + rng.uniform(-0.6, 0.6)))

    zones = _calm_zones(face)
    placed = 0
    while placed < 380:
        middle = QPointF(rng.uniform(OPENING_X, SLEEVE.right()),
                         rng.uniform(SLEEVE.top(), SLEEVE.bottom()))
        angle = rng.uniform(0, math.pi)
        length = rng.uniform(2.5, 7)
        tone = KRAFT_LIGHT if rng.random() < 0.55 else KRAFT_DARK
        alpha = rng.randint(18, 32)
        bend = rng.uniform(-1.2, 1.2)
        if _is_calm(middle, zones):
            continue
        placed += 1
        dx, dy = math.cos(angle) * length / 2, math.sin(angle) * length / 2
        fibre = QPainterPath(QPointF(middle.x() - dx, middle.y() - dy))
        fibre.quadTo(
            QPointF(middle.x() - dy * bend / 3, middle.y() + dx * bend / 3),
            QPointF(middle.x() + dx, middle.y() + dy),
        )
        pen = QPen(_rgba(tone, alpha), 0.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(fibre)
    specks = 0
    painter.setPen(Qt.PenStyle.NoPen)
    while specks < 45:
        point = QPointF(rng.uniform(OPENING_X, SLEEVE.right()),
                        rng.uniform(SLEEVE.top(), SLEEVE.bottom()))
        radius = rng.uniform(0.3, 0.65)
        alpha = rng.randint(35, 75)
        if _is_calm(point, zones):
            continue
        specks += 1
        painter.setBrush(_rgba("#4a3018", alpha))
        painter.drawEllipse(_circle(point, radius))

    # The jacket, thicker and on top, shades the sheet beside its opening.
    cast = QLinearGradient(QPointF(OPENING_X, 0), QPointF(OPENING_X + 10, 0))
    cast.setColorAt(0, QColor(40, 25, 10, 110))
    cast.setColorAt(0.35, QColor(40, 25, 10, 45))
    cast.setColorAt(1, QColor(40, 25, 10, 0))
    painter.fillRect(QRectF(OPENING_X, SLEEVE.top(), 10, SLEEVE.height()), cast)
    painter.restore()


def _paint_well(painter: QPainter, rect: QRectF, kit) -> None:
    """A cream panel printed on the kraft, with a slight offset-print edge."""
    path = kit.rounded(rect, WELL_RADIUS)
    painter.save()
    painter.setPen(QPen(_rgba("#000000", 45), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    outline = WELL_RADIUS + 0.5
    painter.drawRoundedRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5), outline, outline)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(CREAM))
    painter.drawPath(path)
    painter.restore()
    _grain(painter, path, kit.SCALE, 4, 0.03, salt=2)
    painter.save()
    painter.setPen(QPen(QColor("#d8c7a5"), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    edge = WELL_RADIUS - 0.5
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), edge, edge)
    painter.restore()


def _paint_liner(painter: QPainter, kit) -> None:
    _paint_well(painter, LINER, kit)
    left, right = LINER.left() + 10, LINER.right() - 10
    painter.save()
    painter.setPen(QPen(QColor(OXBLOOD), 1))
    painter.drawLine(QPointF(left, ACCENT_RULE_Y), QPointF(right, ACCENT_RULE_Y))
    painter.setPen(QPen(_rgba("#8a6c4a", 90), 0.6))
    for y in HAIRLINE_YS:
        painter.drawLine(QPointF(left, y), QPointF(right, y))
    painter.restore()


def _paint_rule_well(painter: QPainter, face: dict, kit) -> None:
    _paint_well(painter, RULE, kit)
    controls = face["controls"]
    painter.save()
    for name in ("seek", "volume"):
        channel = QRectF(*controls[name]).adjusted(-4, 3, 4, -3)
        radius = channel.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#e9dcc2"))
        painter.drawRoundedRect(channel, radius, radius)
        # Pressed into the card: shade along the top, light along the bottom.
        rim = QLinearGradient(channel.topLeft(), channel.bottomLeft())
        rim.setColorAt(0, _rgba("#000000", 46))
        rim.setColorAt(0.5, _rgba("#000000", 0))
        rim.setColorAt(0.51, _rgba("#ffffff", 0))
        rim.setColorAt(1, _rgba("#ffffff", 110))
        painter.setPen(QPen(QBrush(rim), 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        inner = channel.adjusted(0.5, 0.5, -0.5, -0.5)
        painter.drawRoundedRect(inner, inner.height() / 2, inner.height() / 2)
    painter.restore()


def _paint_label_window(painter: QPainter, kit, rng: random.Random) -> None:
    c = LABEL_CENTRE
    hole = _disc(c, CUT_RADIUS)

    painter.save()
    painter.setClipPath(hole)
    wax = QRadialGradient(c, CUT_RADIUS)
    wax.setColorAt(LABEL_RADIUS / CUT_RADIUS, QColor("#1c1c20"))
    wax.setColorAt(1, QColor("#0d0d0f"))
    painter.fillRect(_circle(c, CUT_RADIUS), wax)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    radius = LABEL_RADIUS + 1.0
    while radius < CUT_RADIUS:
        painter.setPen(QPen(_rgba("#34343a", 34), 0.4))
        painter.drawEllipse(_circle(c, radius))
        radius += 0.75
    for groove in GROOVE_RADII:
        painter.setPen(QPen(_rgba("#2a2a30", 160), 0.5))
        painter.drawEllipse(_circle(c, groove))
        painter.setPen(QPen(_rgba("#050506", 150), 0.5))
        painter.drawEllipse(_circle(c, groove + 0.5))

    # Concentric grooves catch the top-left light in a bow tie that points at it.
    annulus = hole.subtracted(_disc(c, LABEL_RADIUS))
    painter.setClipPath(annulus)
    sheen = QConicalGradient(c, 0)
    for start in (118, 298):
        sheen.setColorAt(start / 360, _rgba("#ffffff", 0))
        sheen.setColorAt((start + 17) / 360, _rgba("#ffffff", 58))
        sheen.setColorAt((start + 34) / 360, _rgba("#ffffff", 0))
    sheen.setColorAt(0, _rgba("#ffffff", 0))
    sheen.setColorAt(1, _rgba("#ffffff", 0))
    painter.fillRect(_circle(c, CUT_RADIUS), sheen)
    painter.restore()

    # The label: matte oxblood paper with two printed cream rings.
    label = _disc(c, LABEL_RADIUS)
    paper = QRadialGradient(c - QPointF(12, 14), LABEL_RADIUS * 1.5)
    paper.setColorAt(0, QColor("#a2392c"))
    paper.setColorAt(1, QColor("#74201a"))
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(paper)
    painter.drawPath(label)
    painter.restore()
    _grain(painter, label, kit.SCALE, 30, 0.2, salt=3)
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_rgba("#000000", 70), 0.6))
    painter.drawEllipse(_circle(c, LABEL_RADIUS - 0.3))
    painter.setPen(QPen(_rgba("#efe2c8", 200), 0.8))
    painter.drawEllipse(_circle(c, 38))
    painter.setPen(QPen(_rgba("#efe2c8", 150), 0.6))
    painter.drawEllipse(_circle(c, 33))

    # The play sticker's seat: a soft contact shadow, offset away from the light.
    seat = QRadialGradient(c + QPointF(0.5, 1.2), 28.5)
    seat.setColorAt(23.5 / 28.5, _rgba("#1a0605", 120))
    seat.setColorAt(1, _rgba("#1a0605", 0))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(seat)
    painter.drawEllipse(_circle(c + QPointF(0.5, 1.2), 28.5))

    # The sleeve's paper casts a thin crescent into the top-left of the hole.
    painter.setClipPath(hole)
    for offset, alpha in ((QPointF(3.0, 4.0), 45), (QPointF(1.5, 2.0), 80)):
        crescent = hole.subtracted(_disc(c + offset, CUT_RADIUS))
        painter.fillPath(crescent, QColor(0, 0, 0, alpha))
    painter.setClipping(False)

    # Die-cut wall: dark where it faces away from the light, lit at bottom right.
    edge = QLinearGradient(c + QPointF(-40, -40), c + QPointF(40, 40))
    edge.setColorAt(0, QColor("#6a4626"))
    edge.setColorAt(0.5, QColor("#b08452"))
    edge.setColorAt(1, QColor("#f0d9b0"))
    painter.setPen(QPen(QBrush(edge), 1.3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(_circle(c, CUT_RADIUS + 0.65))
    painter.restore()


def _paint_seam(painter: QPainter, kit) -> None:
    """The sleeve's glued bottom flap: a faintly darker band under a folded edge."""
    painter.save()
    painter.setClipPath(kit.rounded(SLEEVE, SLEEVE_RADIUS))
    band = QRectF(OPENING_X, SEAM_Y, SLEEVE.right() - OPENING_X, SLEEVE.bottom() - SEAM_Y)
    painter.fillRect(band, _rgba("#6f4c2a", 26))
    painter.setPen(QPen(_rgba("#4a3018", 70), 0.5))
    painter.drawLine(QPointF(OPENING_X, SEAM_Y - 0.25), QPointF(SLEEVE.right(), SEAM_Y - 0.25))
    painter.setPen(QPen(_rgba("#e8c996", 110), 0.6))
    painter.drawLine(QPointF(OPENING_X, SEAM_Y + 0.4), QPointF(SLEEVE.right(), SEAM_Y + 0.4))
    painter.restore()


def _paint_sleeve_edge(painter: QPainter) -> None:
    painter.save()
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_rgba(KRAFT_DARK, 170), 1))
    inset = SLEEVE.adjusted(0.5, 0.5, -0.5, -0.5)
    painter.drawRoundedRect(inset, SLEEVE_RADIUS - 0.5, SLEEVE_RADIUS - 0.5)
    shine = QLinearGradient(QPointF(OPENING_X, 0), QPointF(SLEEVE.right() - 8, 0))
    shine.setColorAt(0, _rgba("#e2c08f", 130))
    shine.setColorAt(0.8, _rgba("#e2c08f", 100))
    shine.setColorAt(1, _rgba("#e2c08f", 0))
    painter.setPen(QPen(QBrush(shine), 1))
    y = SLEEVE.top() + 1.5
    painter.drawLine(QPointF(OPENING_X, y), QPointF(SLEEVE.right() - 8, y))
    painter.restore()


def _paint_jacket(painter: QPainter, face: dict, kit, rng: random.Random) -> None:
    jacket = kit.rounded(JACKET, JACKET_RADIUS)
    painter.save()
    painter.setClipPath(jacket)
    painter.fillRect(JACKET, BOARD)
    tone = QLinearGradient(JACKET.topLeft(), JACKET.bottomRight())
    tone.setColorAt(0, _rgba("#443b32", 130))
    tone.setColorAt(0.5, _rgba("#2c2722", 0))
    tone.setColorAt(1, _rgba("#0e0c0a", 110))
    painter.fillRect(JACKET, tone)
    painter.restore()
    _grain(painter, jacket, kit.SCALE, 32, 0.3, salt=4)

    painter.save()
    painter.setClipPath(jacket)
    # Spine side on the left.
    painter.fillRect(QRectF(JACKET.left(), JACKET.top(), 3, JACKET.height()), QColor("#1b1815"))
    painter.setPen(QPen(_rgba("#000000", 70), 0.5))
    painter.drawLine(QPointF(JACKET.left() + 3.25, JACKET.top()),
                     QPointF(JACKET.left() + 3.25, JACKET.bottom()))

    # Board edges: gloss where the light falls, the opening's cut edge on the right.
    painter.setPen(QPen(_rgba("#ffffff", 60), 1))
    painter.drawLine(QPointF(JACKET.left() + 3, JACKET.top() + 0.5),
                     QPointF(JACKET.right() - 3, JACKET.top() + 0.5))
    painter.setPen(QPen(_rgba("#ffffff", 52), 1))
    painter.drawLine(QPointF(JACKET.left() + 0.5, JACKET.top() + 3),
                     QPointF(JACKET.left() + 0.5, JACKET.bottom() - 3))
    painter.setPen(QPen(_rgba("#000000", 90), 1))
    painter.drawLine(QPointF(JACKET.left() + 3, JACKET.bottom() - 0.5),
                     QPointF(JACKET.right() - 3, JACKET.bottom() - 0.5))
    painter.setPen(QPen(QColor("#4a423a"), 1))
    painter.drawLine(QPointF(OPENING_X - 1.5, JACKET.top() + 3),
                     QPointF(OPENING_X - 1.5, JACKET.bottom() - 3))
    painter.setPen(QPen(_rgba("#000000", 120), 1))
    painter.drawLine(QPointF(OPENING_X - 0.5, JACKET.top()),
                     QPointF(OPENING_X - 0.5, JACKET.bottom()))

    # Shelf wear: scuffed board shows its lighter fibre just inside the edge,
    # brightest where the light falls (top left), dull at the shaded corner.
    corners = (
        (JACKET.topLeft(), 1, 1, "#a39886", (50, 90)),
        (JACKET.topRight(), -1, 1, "#8a7f70", (40, 75)),
        (JACKET.bottomLeft(), 1, -1, "#8a7f70", (40, 75)),
        (JACKET.bottomRight(), -1, -1, "#5a5148", (40, 80)),
    )
    for corner, sx, sy, colour, (low, high) in corners:
        for _ in range(40):
            along = rng.uniform(0.75, 6)
            depth = 0.75 + rng.uniform(0, 1.4) ** 1.5
            length = rng.uniform(1, 4)
            if rng.random() < 0.5:
                start = QPointF(corner.x() + sx * along, corner.y() + sy * depth)
                end = QPointF(start.x() + sx * length, start.y() + sy * rng.uniform(-0.3, 0.4))
            else:
                start = QPointF(corner.x() + sx * depth, corner.y() + sy * along)
                end = QPointF(start.x() + sx * rng.uniform(-0.3, 0.4), start.y() + sy * length)
            painter.setPen(QPen(_rgba(colour, rng.randint(low, high)), 0.6))
            painter.drawLine(start, end)
    # Along the edges: light rub on the lit top and left, dark grime on the
    # shaded bottom and right.
    for _ in range(70):
        side = rng.randrange(4)
        along = rng.uniform(10, JACKET.width() - 10)
        depth = rng.uniform(0.75, 1.6)
        length = rng.uniform(1.5, 6)
        if side == 0:
            start = QPointF(JACKET.left() + along, JACKET.top() + depth)
            end = start + QPointF(length, 0)
        elif side == 1:
            start = QPointF(JACKET.left() + along, JACKET.bottom() - depth)
            end = start + QPointF(length, 0)
        elif side == 2:
            start = QPointF(JACKET.left() + depth, JACKET.top() + along)
            end = start + QPointF(0, length)
        else:
            start = QPointF(JACKET.right() - depth, JACKET.top() + along)
            end = start + QPointF(0, length)
        lit = side in (0, 2)
        alpha = rng.randint(40, 70)
        painter.setPen(QPen(_rgba("#8a7f70", alpha) if lit else _rgba("#0e0c0a", alpha), 0.5))
        painter.drawLine(start, end)

    # The print bed under the cover (hidden while art shows) and its edges.
    art = QRectF(*face["controls"]["art"])
    painter.fillRect(art, QColor("#1a1715"))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_rgba("#000000", 150), 1))
    painter.drawRect(art.adjusted(-0.5, -0.5, 0.5, 0.5))
    lip = art.adjusted(-1.5, -1.5, 1.5, 1.5)
    painter.setPen(QPen(_rgba("#4a423a", 110), 1))
    painter.drawLine(lip.topLeft(), lip.topRight())
    painter.drawLine(lip.topLeft(), lip.bottomLeft())
    painter.setPen(QPen(_rgba("#000000", 60), 1))
    painter.drawLine(lip.bottomLeft(), lip.bottomRight())
    painter.drawLine(lip.topRight(), lip.bottomRight())
    painter.restore()


def render_background(face: dict, kit) -> QImage:
    width, height = face["size"]
    image, painter = kit.canvas(width, height)
    rng = random.Random(SEED)
    _paint_sleeve(painter, face, kit, rng)
    _paint_liner(painter, kit)
    _paint_rule_well(painter, face, kit)
    _paint_label_window(painter, kit, rng)
    _paint_seam(painter, kit)
    _paint_sleeve_edge(painter)
    _paint_jacket(painter, face, kit, rng)
    painter.end()
    return image


# Buttons -------------------------------------------------------------------

def _button_path(kit, width: int, height: int, shape: str) -> tuple[QRectF, QPainterPath]:
    if shape == "ellipse":
        diameter = min(width - 2, height - 2.5)
        rect = QRectF((width - diameter) / 2, 1, diameter, diameter)
    else:
        rect = QRectF(1, 1, width - 2, height - 2.5)
    return rect, kit.control_path(rect, shape, 6)


def _inner_top_shadow(painter: QPainter, path: QPainterPath, rect: QRectF, alpha: int) -> None:
    painter.save()
    painter.setClipPath(path)
    shade = QLinearGradient(rect.topLeft(), rect.topLeft() + QPointF(0, 4))
    shade.setColorAt(0, _rgba(INK_BROWN, alpha))
    shade.setColorAt(1, _rgba(INK_BROWN, 0))
    painter.setPen(QPen(QBrush(shade), 3))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


def _label_ring(rect: QRectF) -> QRectF:
    """The printed hairline ring of a punched label disc, at 0.84 r."""
    inset = rect.width() * 0.08
    return rect.adjusted(inset, inset, -inset, -inset)


def _card(painter: QPainter, kit, state: str, rect: QRectF,
          path: QPainterPath, shape: str) -> None:
    """A die-cut cream card standing on the kraft."""
    if state == "disabled":
        # Unlit paper: flat and faded, but still the same card and label ring.
        painter.fillPath(path.translated(0, 0.8), _rgba(INK_BROWN, 30))
        painter.fillPath(path, QColor(DISABLED_PAPER))
        _grain(painter, path, kit.SCALE, 6, 0.03, salt=5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if shape == "ellipse":
            painter.setPen(QPen(_rgba(DISABLED_INK, 140), 0.7))
            painter.drawEllipse(_label_ring(rect))
        painter.setPen(QPen(_rgba(DISABLED_INK, 140), 0.9))
        painter.drawPath(path)
        return
    tops = {"normal": ("#fbf5e8", "#e6d8bc"), "hover": ("#fff9ee", "#eadcbf"),
            "pressed": ("#dccaa6", "#f4ead6")}
    top, bottom = tops[state]
    if state != "pressed":
        painter.fillPath(path.translated(0, 0.8), _rgba(INK_BROWN, 60))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(kit.gradient(rect, QColor(top), QColor(bottom)))
    painter.drawPath(path)
    _grain(painter, path, kit.SCALE, 6, 0.04, salt=5)
    if state == "pressed":
        _inner_top_shadow(painter, path, rect, 90)
    else:
        inner = rect.adjusted(1.2, 1.2, -1.2, -1.2)
        highlight = kit.gradient(inner, _rgba("#ffffff", 120), _rgba("#8a6c4a", 50))
        painter.setPen(QPen(QBrush(highlight), 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(kit.control_path(inner, shape, 4.8))
    if shape == "ellipse":
        painter.setPen(QPen(_rgba(OXBLOOD, 140), 0.7))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(_label_ring(rect))
    rim = {"normal": (_rgba("#8a6c4a", 170), 0.9), "hover": (_rgba(OXBLOOD, 200), 1.1),
           "pressed": (QColor(KRAFT_DARK), 0.9)}[state]
    painter.setPen(QPen(*rim))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)


def _sticker(painter: QPainter, kit, state: str, rect: QRectF, path: QPainterPath) -> None:
    """The record label's cream centre sticker."""
    centre = rect.center()
    radius = rect.width() / 2
    rings = {"normal": OXBLOOD, "hover": "#b23b2d", "pressed": "#6c2119", "disabled": DISABLED_INK}
    if state == "disabled":
        painter.fillPath(path, QColor(DISABLED_PAPER))
        _grain(painter, path, kit.SCALE, 6, 0.03, salt=6)
    else:
        if state != "pressed":
            painter.fillPath(path.translated(0, 0.8), _rgba("#1a0605", 90))
        face_colour = {"normal": "#fffaf0", "hover": "#ffffff", "pressed": "#e9dcc0"}[state]
        edge_colour = {"normal": "#e9dcc0", "hover": "#f1e6cf", "pressed": "#fbf4e6"}[state]
        focus = QPointF(rect.left() + 0.4 * rect.width(), rect.top() + 0.38 * rect.height())
        body = QRadialGradient(focus, radius * 1.25)
        body.setColorAt(0, QColor(face_colour))
        body.setColorAt(1, QColor(edge_colour))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body)
        painter.drawPath(path)
        _grain(painter, path, kit.SCALE, 6, 0.04, salt=6)
        if state == "pressed":
            _inner_top_shadow(painter, path, rect, 100)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    # Hover matches the cards' oxblood rim and prints the main ring heavier.
    painter.setPen(QPen(QColor(rings[state]), 1.8 if state == "hover" else 1.4))
    painter.drawEllipse(_circle(centre, radius * 0.80))
    painter.setPen(QPen(_rgba(rings[state], 150), 0.6))
    painter.drawEllipse(_circle(centre, radius * 0.72))
    edge = {"disabled": (_rgba(DISABLED_INK, 160), 1.0), "hover": (_rgba(OXBLOOD, 220), 1.2)}
    colour, width = edge.get(state, (_rgba("#5a3a26", 180), 1.0))
    painter.setPen(QPen(colour, width))
    painter.drawEllipse(rect.adjusted(width / 2, width / 2, -width / 2, -width / 2))


def render_button(face: dict, control: str, state: str, kit) -> QImage:
    _, _, width, height = face["controls"][control]
    shape = face.get("controlShapes", {}).get(control, "rounded")
    image, painter = kit.canvas(width, height)
    rect, path = _button_path(kit, width, height, shape)
    if control == "play":
        _sticker(painter, kit, state, rect, path)
    else:
        _card(painter, kit, state, rect, path, shape)
    painter.end()
    return image
