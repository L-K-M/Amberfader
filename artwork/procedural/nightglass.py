"""Nightglass: a quiet dark slab, a near-frameless cover and a smoked-glass strip.

Painted in code for artwork/render_faces.py (see PROCEDURAL_KIT there). Two
materials only: a matte, finely grained slab and one smoked-glass strip that
carries every readout and control below the cover. The cover is the only
colour. Light comes from the top left throughout: highlights sit on upper
edges, contact shadows fall down and slightly right, recesses catch light on
their lower lip.

All coordinates are logical pixels; kit.canvas scales the painter by 2.
"""

from __future__ import annotations

import random
import zlib

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
    QPixmap,
    QRadialGradient,
)

SEED = zlib.crc32(b"nightglass")
SILHOUETTE = QRectF(1, 1, 406, 638)
SILHOUETTE_RADIUS = 16
STRIP = QRectF(12, 428, 384, 202)
STRIP_RADIUS = 12
# The groove separating the info block (title to time) from the controls
# sits between the time digits (baseline 533, the slash ends at 535) and the
# play key's top edge (546). It spans the text column, 26..382, which is
# where every readout ends; only controls reach out to 22..386.
DIVIDER_Y = 540
DIVIDER_X = (26, 382)
# A 3x2 grip centred on the header row (y 17), inside the drag region.
GRIP_COLUMNS = (20, 24, 28)
GRIP_ROWS = (15, 19)
GRIP_RADIUS = 1.05
# The strip's one reflection: a shallow diagonal band across its top-left
# corner (see _paint_reflection). Stops are (phase / reach, white alpha).
REFLECTION_SLOPE = 5.0
REFLECTION_REACH = 120.0
REFLECTION_STOPS = ((0.0, 0), (0.3, 0), (0.55, 12), (0.85, 0))
GRAIN_TILE = 128
# Grain is added (CompositionMode_Plus) in device pixels with values
# 0..2 * GRAIN_LEVELS; the slab is painted GRAIN_LEVELS darker first, so the
# mean tone is unchanged and the dark gradient dithers instead of banding.
GRAIN_LEVELS = 2
SLAB_TOP, SLAB_BOTTOM = "#1a1b1f", "#131417"
GLASS = "#1e2024"
BED = "#0d0e10"
BRASS = "#d9a86c"
# Gel keys. Hover lifts the body and edge and adds a faint brass edge, the
# same cue the search field gives, so hover reads alike across the face.
GEL_TOP, GEL_BOTTOM, GEL_EDGE = "#2c2e33", "#1b1c20", "#3a3c42"
HOVER_LIFT = 112
HOVER_EDGE, HOVER_BRASS_ALPHA = "#55585f", 70
DISABLED_FILL, DISABLED_EDGE = "#232529", "#35373c"
DROP_ALPHA = {"normal": 120, "hover": 120, "pressed": 70, "disabled": 90}
CRESCENT_ALPHA = {"normal": 34, "hover": 58}
# The play key's brass ring is its edge; a ghost of it stays when disabled
# (and so while pending) so the hero key keeps its form.
RING_ALPHA = {"normal": 185, "hover": 230, "pressed": 120, "disabled": 28}
RING_INSET, RING_WIDTH = 1.4, 1.2


def _color(value: str, alpha: int = 255) -> QColor:
    color = QColor(value)
    color.setAlpha(alpha)
    return color


def _darken(value: str | QColor, levels: int) -> QColor:
    color = QColor(value)
    return QColor(*(max(0, part - levels) for part in (color.red(), color.green(), color.blue())))


def _grain_tile() -> QPixmap:
    rng = random.Random(SEED)
    top = 2 * GRAIN_LEVELS
    pixels = bytearray()
    for _ in range(GRAIN_TILE * GRAIN_TILE):
        # A triangular distribution keeps most pixels near the mean: grain,
        # not salt and pepper.
        value = round((rng.randint(0, top) + rng.randint(0, top)) / 2)
        pixels += bytes((value, value, value, value))
    image = QImage(
        bytes(pixels), GRAIN_TILE, GRAIN_TILE, GRAIN_TILE * 4,
        QImage.Format.Format_ARGB32_Premultiplied,
    ).copy()
    return QPixmap.fromImage(image)


def _vertical_pen(
    top: float, bottom: float, stops: list[tuple[float, QColor]], width: float,
) -> QPen:
    gradient = QLinearGradient(0, top, 0, bottom)
    for position, color in stops:
        gradient.setColorAt(position, color)
    pen = QPen(QBrush(gradient), width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _add_grain(painter: QPainter, kit, grain: QPixmap, width: int, height: int) -> None:
    """Add the grain tile in device pixels inside the current clip.

    The clip set by the caller is kept in device space when the transform is
    reset, so the tile lands one grain cell per device pixel.
    """
    painter.save()
    painter.resetTransform()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.drawTiledPixmap(QRectF(0, 0, width * kit.SCALE, height * kit.SCALE), grain)
    painter.restore()


def _paint_slab(painter: QPainter, kit, grain: QPixmap, width: int, height: int) -> None:
    silhouette = kit.rounded(SILHOUETTE, SILHOUETTE_RADIUS)
    painter.save()
    painter.setClipPath(silhouette)
    painter.fillRect(
        SILHOUETTE,
        kit.gradient(
            SILHOUETTE, _darken(SLAB_TOP, GRAIN_LEVELS), _darken(SLAB_BOTTOM, GRAIN_LEVELS),
        ),
    )
    _add_grain(painter, kit, grain, width, height)

    # A broad, faint falloff from the top-left light keeps the matte finish
    # from reading as a flat fill.
    sheen = QRadialGradient(QPointF(30, -20), 520)
    sheen.setColorAt(0, _color("#ffffff", 9))
    sheen.setColorAt(1, _color("#ffffff", 0))
    painter.fillRect(SILHOUETTE, sheen)
    painter.restore()

    # Machined edge: a dark outer line, a highlight on the upper half that
    # fades downward, and a faint shade along the lower edge.
    outline = kit.rounded(SILHOUETTE.adjusted(0.5, 0.5, -0.5, -0.5), SILHOUETTE_RADIUS - 0.5)
    chamfer = kit.rounded(SILHOUETTE.adjusted(1.5, 1.5, -1.5, -1.5), SILHOUETTE_RADIUS - 1.5)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color("#000000", 200), 1))
    painter.drawPath(outline)
    light = [(0, _color("#ffffff", 18)), (1, _color("#ffffff", 0))]
    painter.setPen(_vertical_pen(1, 320, light, 1))
    painter.drawPath(chamfer)
    shade = [(0, _color("#000000", 0)), (1, _color("#000000", 70))]
    painter.setPen(_vertical_pen(480, 639, shade, 1))
    painter.drawPath(chamfer)


def _paint_grip(painter: QPainter) -> None:
    """Six dimples at the drag region's left end, lit on their lower lip."""
    painter.setPen(Qt.PenStyle.NoPen)
    for x in GRIP_COLUMNS:
        for y in GRIP_ROWS:
            painter.setBrush(_color("#ffffff", 42))
            painter.drawEllipse(QPointF(x + 0.3, y + 0.5), GRIP_RADIUS, GRIP_RADIUS)
            painter.setBrush(_color("#000000", 150))
            painter.drawEllipse(QPointF(x, y), GRIP_RADIUS, GRIP_RADIUS)


def _paint_cover_aperture(painter: QPainter, kit, art: QRectF, radius: float) -> None:
    # Contact shadow first, so the bed sits on it; it falls down and half a
    # pixel right, away from the top-left light.
    painter.setPen(Qt.PenStyle.NoPen)
    for (left, top, right, bottom), corner, alpha in (
        ((-3, 2, 3, 8), radius + 3, 12),
        ((-2, 1, 2, 5), radius + 2, 25),
        ((-1, 0, 1, 3), radius + 1, 40),
    ):
        painter.setBrush(_color("#000000", alpha))
        painter.drawPath(kit.rounded(art.adjusted(left + 0.5, top, right + 0.5, bottom), corner))

    painter.setBrush(QColor(BED))
    painter.drawPath(kit.rounded(art, radius))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color("#000000", 150), 1))
    painter.drawPath(kit.rounded(art.adjusted(-0.5, -0.5, 0.5, 0.5), radius + 0.5))
    # The print's lip catches the light at the top left and fades away from it.
    rim = QLinearGradient(art.topLeft(), art.bottomRight())
    rim.setColorAt(0, _color("#ffffff", 22))
    rim.setColorAt(0.5, _color("#ffffff", 10))
    rim.setColorAt(1, _color("#ffffff", 4))
    painter.setPen(QPen(QBrush(rim), 1))
    painter.drawPath(kit.rounded(art.adjusted(-1.5, -1.5, 1.5, 1.5), radius + 1.5))


def _paint_reflection(painter: QPainter) -> None:
    """One soft diagonal band of the top-left light, inside the strip clip.

    The band's lines of equal brightness run from the strip's top edge (at
    most about 100 px in) down to its left edge, slanted so only its fading
    tail reaches the title's cap line and it is gone well above the baseline.
    """
    origin = STRIP.topLeft()
    # Phase s = dx + slope * dy; the gradient vector is the normal of the
    # band's lines, scaled so its length in phase units is REFLECTION_REACH.
    slope = REFLECTION_SLOPE
    normal = QPointF(1, slope) / (1 + slope * slope)
    band = QLinearGradient(origin, origin + normal * REFLECTION_REACH)
    for position, alpha in REFLECTION_STOPS:
        band.setColorAt(position, _color("#ffffff", alpha))
    corner = origin + QPointF(REFLECTION_REACH, REFLECTION_REACH / slope)
    painter.fillRect(QRectF(origin, corner), band)


def _paint_strip(
    painter: QPainter, kit, grain: QPixmap, controls: dict, width: int, height: int,
) -> None:
    strip_path = kit.rounded(STRIP, STRIP_RADIUS)

    # The glass rests on the slab: a short contact shadow, then the seam.
    painter.setPen(Qt.PenStyle.NoPen)
    for (left, top, right, bottom), alpha in (((-2, 1, 2, 4), 16), ((-1, 0, 1, 2), 34)):
        painter.setBrush(_color("#000000", alpha))
        shadow = STRIP.adjusted(left + 0.5, top, right + 0.5, bottom)
        painter.drawPath(kit.rounded(shadow, STRIP_RADIUS + 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color("#000000", 100), 1))
    painter.drawPath(kit.rounded(STRIP.adjusted(-0.5, -0.5, 0.5, 0.5), STRIP_RADIUS + 0.5))

    # Smoked glass looks a shade lighter where the light enters at the top
    # and deepens toward the base; the mid tone stays GLASS behind the text.
    # Like the slab it is painted GRAIN_LEVELS darker and grained back up, so
    # the shallow gradients dither instead of banding.
    body = QColor(GLASS)
    painter.fillPath(strip_path, kit.gradient(
        STRIP, _darken(body.lighter(112), GRAIN_LEVELS), _darken(body.darker(108), GRAIN_LEVELS),
    ))
    painter.save()
    painter.setClipPath(strip_path)
    _add_grain(painter, kit, grain, width, height)
    specular = QLinearGradient(0, STRIP.top(), 0, STRIP.top() + 18)
    specular.setColorAt(0, _color("#ffffff", 18))
    specular.setColorAt(1, _color("#ffffff", 0))
    painter.fillRect(QRectF(STRIP.left(), STRIP.top(), STRIP.width(), 18), specular)
    _paint_reflection(painter)
    painter.restore()

    # Polished edge, one device pixel wide: bright where the light lands,
    # quieter toward the base. Just inside it the glass thickness reads as a
    # darker line.
    painter.setPen(_vertical_pen(STRIP.top(), STRIP.bottom(), [
        (0, _color("#ffffff", 44)), (0.3, _color("#ffffff", 14)), (1, _color("#ffffff", 10)),
    ], 0.5))
    painter.drawPath(kit.rounded(STRIP.adjusted(0.25, 0.25, -0.25, -0.25), STRIP_RADIUS - 0.25))
    painter.setPen(QPen(_color("#000000", 46), 0.5))
    painter.drawPath(kit.rounded(STRIP.adjusted(0.75, 0.75, -0.75, -0.75), STRIP_RADIUS - 0.75))
    # Glass thickness: the light that enters at the top leaves as a faint
    # catch just inside the bottom edge.
    painter.setPen(_vertical_pen(STRIP.bottom() - STRIP_RADIUS, STRIP.bottom(), [
        (0, _color("#ffffff", 0)), (1, _color("#ffffff", 12)),
    ], 0.5))
    painter.drawPath(kit.rounded(STRIP.adjusted(1.25, 1.25, -1.25, -1.25), STRIP_RADIUS - 1.25))

    # Engraved divider: shadowed upper wall, lit lower lip.
    left, right = DIVIDER_X
    painter.setPen(QPen(_color("#000000", 80), 1))
    painter.drawLine(QPointF(left, DIVIDER_Y - 0.5), QPointF(right, DIVIDER_Y - 0.5))
    painter.setPen(QPen(_color("#ffffff", 12), 1))
    painter.drawLine(QPointF(left, DIVIDER_Y + 0.5), QPointF(right, DIVIDER_Y + 0.5))

    # Recessed seats for the host's inset rails.
    for name in ("seek", "volume"):
        seat = QRectF(*controls[name]).adjusted(-2, 5, 2, -5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color("#000000", 60))
        painter.drawRoundedRect(seat, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(_color("#ffffff", 12), 0.5))
        painter.save()
        painter.setClipRect(QRectF(seat.left(), seat.center().y(), seat.width(), seat.height()))
        painter.drawRoundedRect(seat.adjusted(-0.25, -0.25, 0.25, 0.25), 4.25, 4.25)
        painter.restore()


def render_background(face: dict, kit) -> QImage:
    width, height = face["size"]
    controls = face["controls"]
    image, painter = kit.canvas(width, height)
    grain = _grain_tile()
    _paint_slab(painter, kit, grain, width, height)
    _paint_grip(painter)
    _paint_cover_aperture(painter, kit, QRectF(*controls["art"]), face["radius"])
    _paint_strip(painter, kit, grain, controls, width, height)
    painter.end()
    return image


def _crescent_pen(rect: QRectF, color: str, alpha: int, width: float) -> QPen:
    """A highlight that fades out by 45 % of the key's height."""
    return _vertical_pen(rect.top(), rect.top() + rect.height() * 0.45, [
        (0, _color(color, alpha)), (1, _color(color, 0)),
    ], width)


def _paint_gel(
    painter: QPainter, kit, rect: QRectF, shape: str, radius: float, state: str,
    *, ringed: bool = False,
) -> None:
    """A smoked-glass key. A ringed key (play) takes its edge from the ring."""
    path = kit.control_path(rect, shape, radius)
    painter.fillPath(path.translated(0, 0.8), _color("#000000", DROP_ALPHA[state]))

    if state == "pressed":
        top, bottom, edge = QColor("#18191c"), QColor("#26282d"), QColor(GEL_EDGE)
    elif state == "disabled":
        top = bottom = QColor(DISABLED_FILL)
        edge = QColor(DISABLED_EDGE)
    elif state == "hover":
        top, bottom = QColor(GEL_TOP).lighter(HOVER_LIFT), QColor(GEL_BOTTOM).lighter(HOVER_LIFT)
        edge = QColor(HOVER_EDGE)
    else:
        top, bottom, edge = QColor(GEL_TOP), QColor(GEL_BOTTOM), QColor(GEL_EDGE)
    painter.fillPath(path, kit.gradient(rect, top, bottom))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if not ringed:
        painter.setPen(QPen(edge, 0.8))
        painter.drawPath(path)
        if state == "hover":
            painter.setPen(QPen(_color(BRASS, HOVER_BRASS_ALPHA), 0.8))
            painter.drawPath(path)

    # Inside a ring the crescent moves in past it, so it never washes the brass.
    inset = RING_INSET + RING_WIDTH if ringed else 0.9
    inner = kit.control_path(rect.adjusted(inset, inset, -inset, -inset), shape, radius - inset)
    if state in CRESCENT_ALPHA:
        painter.setPen(_crescent_pen(rect, "#ffffff", CRESCENT_ALPHA[state], 0.8))
        painter.drawPath(inner)
    elif state == "pressed":
        painter.setPen(_crescent_pen(rect, "#000000", 140, 1))
        painter.drawPath(inner)


def _paint_brass_ring(
    painter: QPainter, kit, rect: QRectF, shape: str, radius: float, state: str,
) -> None:
    """Polished brass lit from above: bright on top, deeper (not muddy) below."""
    alpha = RING_ALPHA[state]
    ring = rect.adjusted(RING_INSET, RING_INSET, -RING_INSET, -RING_INSET)
    brass = QColor(BRASS)
    pen = _vertical_pen(ring.top(), ring.bottom(), [
        (0, _color(brass.lighter(122).name(), alpha)), (0.5, _color(BRASS, alpha)),
        (1, _color(brass.darker(125).name(), alpha)),
    ], RING_WIDTH)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(pen)
    painter.drawPath(kit.control_path(ring, shape, radius - RING_INSET))


def _paint_search_field(
    painter: QPainter, kit, rect: QRectF, shape: str, radius: float, state: str,
) -> None:
    """Search is a recessed field, not a key: dark well, shadowed top, lit lip.

    Disabled recedes: a flat fill at the normal tone with a quieter edge and
    no inner shadow, so only the muted label signals unavailability.
    """
    path = kit.control_path(rect, shape, radius)
    inner = kit.control_path(rect.adjusted(0.9, 0.9, -0.9, -0.9), shape, radius - 0.9)
    fill = {"pressed": "#0e0f11", "disabled": "#141517"}.get(state, "#121316")
    painter.fillPath(path, QColor(fill))
    if state != "disabled":
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_crescent_pen(rect, "#000000", 120, 1))
        painter.drawPath(inner)
        lip = _vertical_pen(rect.top(), rect.bottom(), [
            (0.6, _color("#ffffff", 0)), (1, _color("#ffffff", 16)),
        ], 0.8)
        painter.setPen(lip)
        painter.drawPath(path.translated(0, 0.6))
    edges = {"hover": _color(BRASS, 120), "disabled": QColor("#2a2c30")}
    edge = edges.get(state, QColor(GEL_EDGE))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(edge, 0.8))
    painter.drawPath(path)


def render_button(face: dict, control: str, state: str, kit) -> QImage:
    _, _, width, height = face["controls"][control]
    shape = face["controlShapes"][control]
    radius = face["radius"]
    image, painter = kit.canvas(width, height)
    rect = QRectF(1, 1, width - 2, height - 2)
    if control == "search":
        _paint_search_field(painter, kit, rect, shape, radius, state)
    else:
        ringed = control == "play"
        _paint_gel(painter, kit, rect, shape, radius, state, ringed=ringed)
        if ringed:
            _paint_brass_ring(painter, kit, rect, shape, radius, state)
    painter.end()
    return image

