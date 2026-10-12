"""Lightbox: the album cover fills the window, and the controls sit on it.

Painted in code for artwork/render_faces.py (see PROCEDURAL_KIT there).
Lightbox sets coverBackdrop, so the player paints background.png, then, inside
the art aperture, the cover with background.png over it, composed as one
layer and clipped to the aperture once. This one image therefore holds four
layers:

1. a narrow graphite frame, opaque, round the window's edge;
2. a hole where the cover shows, fully transparent before the glass;
3. smoked glass painted into the hole, which lies over the cover;
4. an opaque seal along the hole's edge. The image's own antialiased hole
   edge is part frame and part glass, so without the seal those pixels would
   let the cover glow through the frame.

The glass is clear through the middle of the cover, from below the header
keys to above the title, and deepens behind the readouts and controls along
its lower edge. Readout text gets its contrast from that smoke alone, so the
budget below is sized for a pure white cover, the worst case for light text.
The keys are opaque in every state, so their labels never depend on the
cover. Light comes from the top left throughout.

All coordinates are logical pixels; kit.canvas scales the painter by 2. The
grip, the divider and the smoke rows are placed from face.json's drag region
and controls, so they follow the layout.
"""

from __future__ import annotations

import random
import zlib
from itertools import pairwise

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

SEED = zlib.crc32(b"lightbox")
# The window's outline sits 1 px inside the canvas, concentric with the
# aperture.
SILHOUETTE_INSET = 1
SMOKE = "#0b0c0e"
BRASS = "#e6b678"
FRAME_TOP, FRAME_BOTTOM = "#191a1e", "#121316"
GRAIN_TILE = 128
# Grain is added (CompositionMode_Plus) in device pixels with values
# 0..2 * GRAIN_LEVELS; the frame is painted GRAIN_LEVELS darker first, so the
# mean tone is unchanged and the dark gradient dithers instead of banding.
GRAIN_LEVELS = 2
# Smoke opacity down the aperture as (anchor, offset, alpha) knots, eased
# with a smoothstep between knots. Anchors are rows of the layout: the
# aperture's top and bottom, the title's and the status line's tops, and the
# divider. A faint band shades the header row, the glass is clear from below
# the header keys to above the title, and the smoke is at least 0.74 from
# just above the title down: over pure white that keeps the readouts above
# 7.5:1 and the muted status line above 5:1. The floor stays nearly flat to
# the divider, so light covers turn charcoal there rather than mid-grey;
# without blur, more of the cover cannot show and stay clean.
SMOKE_KNOTS = (
    ("top", 0, 0.2), ("top", 20, 0.2), ("top", 50, 0.0), ("title", -46, 0.0),
    ("title", -6, 0.74), ("divider", 2, 0.77), ("status", -6, 0.84), ("bottom", 0, 0.88),
)
SMOKE_STEP = 2
# The frame's inner wall shades the cover's edge. A dark core reaches just
# past the host's keyboard ring (2 to 3 px inside), so the ring has a dark
# bed on any cover; beyond it the shade decays as (1 - t) ** 2. The light
# comes from the top left, so the top and left walls throw a longer shade
# than the bottom and right ones: the decay stretches by 1 +/- LEAN.
INNER_SHADOW_CORE_ALPHA = 0.86
INNER_SHADOW_CORE, INNER_SHADOW_REACH = 3.25, 10.0
INNER_SHADOW_LEAN = 0.2
INNER_SHADOW_STEP = 0.25
# Pure black, so the shade darkens even a black cover's edge instead of
# lifting it to the smoke's tone.
SHADE = "#000000"
# The seal: an opaque line straddling the aperture's edge. Without it the
# edge pixels, part frame and part glass, would let the cover glow through.
SEAL, SEAL_WIDTH = "#060708", 1.5
# A 3x2 grip on a recessed pad, centred in the drag region's height and
# GRIP_INSET in from its left end. The pad is opaque, so the grip reads the
# same on any cover. Dimples are GRIP_PITCH apart, centred on the pad.
GRIP_INSET, GRIP_PAD_SIZE = 8, (20, 16)
GRIP_PITCH = (4, 6)
GRIP_RADIUS = 1.05
GRIP_WELL, GRIP_LIP_ALPHA = "#2a2c31", 70
# The engraved hairline between the track details and the transport keys:
# DIVIDER_GAP below the time row, as wide as the title.
DIVIDER_GAP = 4
# The slider seats are recessed like the divider and the grip's pad: a
# shaded upper wall and a lit lower lip, which also gives the slider tracks
# an edge on dark covers.
SEAT_WALL_ALPHA, SEAT_LIP_ALPHA = 70, 30
# Gel keys, Search among them. Hover lifts the body and lightens the edge.
# The edge stays neutral, so brass marks only the play key and a hovered key
# never reads as a second one, and opaque, so it stays clean on any cover.
GEL_TOP, GEL_BOTTOM, GEL_EDGE = "#2c2e33", "#1b1c20", "#44474e"
HOVER_LIFT = 112
HOVER_EDGE = "#5a5d65"
# Disabled keys recede into the glass: a flat body at the enabled gel's
# middle tone, with no edge, drop shadow or sheen. Over a light cover the
# glass is mid-grey, so a darker body would read as a hole; at this tone a
# disabled key never stands out more than an enabled one, and the missing
# relief and the host's muted label carry the state.
DISABLED_FILL = "#232529"
DROP_ALPHA = {"normal": 120, "hover": 120, "pressed": 70}
CRESCENT_ALPHA = {"normal": 34, "hover": 58}
# The play key's brass ring is its edge. Disabled (and so while pending) a
# neutral ring stays so the hero key keeps its form.
RING_ALPHA = {"normal": 185, "hover": 230, "pressed": 120}
DISABLED_RING = "#3b3d42"
RING_INSET, RING_WIDTH = 1.4, 1.2


def _color(value: str, alpha: int = 255) -> QColor:
    color = QColor(value)
    color.setAlpha(alpha)
    return color


def _darken(value: str | QColor, levels: int) -> QColor:
    color = QColor(value)
    return QColor(*(max(0, part - levels) for part in (color.red(), color.green(), color.blue())))


def _smoothstep(value: float) -> float:
    value = min(1.0, max(0.0, value))
    return value * value * (3 - 2 * value)


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


def _silhouette(face: dict) -> tuple[QRectF, float]:
    """The window's outline and its corner radius, concentric with the aperture."""
    width, height = face["size"]
    inset = SILHOUETTE_INSET
    return (
        QRectF(inset, inset, width - 2 * inset, height - 2 * inset),
        face["radius"] + face["controls"]["art"][0] - inset,
    )


def _grip(face: dict) -> tuple[QRectF, list[QPointF]]:
    """The grip's pad and its dimples' centres, placed from the drag region."""
    x, y, _, height = face["drag"]
    width, pad_height = GRIP_PAD_SIZE
    pad = QRectF(x + GRIP_INSET, y + (height - pad_height) / 2, width, pad_height)
    centre = pad.center()
    across, down = GRIP_PITCH
    dimples = [
        QPointF(centre.x() + column * across, centre.y() + row * down / 2)
        for column in (-1, 0, 1) for row in (-1, 1)
    ]
    return pad, dimples


def _divider(controls: dict) -> tuple[float, float, float]:
    """The divider's y and its left and right ends."""
    _, time_top, _, time_height = controls["time"]
    left, _, width, _ = controls["title"]
    return time_top + time_height + DIVIDER_GAP, left, left + width


def _smoke_knots(face: dict) -> list[tuple[float, float]]:
    """SMOKE_KNOTS resolved to (logical y, alpha) for this layout."""
    controls = face["controls"]
    _, top, _, height = controls["art"]
    anchors = {
        "top": top, "bottom": top + height, "title": controls["title"][1],
        "status": controls["status"][1], "divider": _divider(controls)[0],
    }
    knots = [(anchors[anchor] + offset, alpha) for anchor, offset, alpha in SMOKE_KNOTS]
    # _smoke_alpha needs strictly rising rows; a layout that reorders them
    # would silently drop the smoke floor under the readouts.
    if any(lower <= upper for (upper, _), (lower, _) in pairwise(knots)):
        raise ValueError(f"smoke knots do not descend the face for this layout: {knots}")
    return knots


def _paint_frame(painter: QPainter, kit, face: dict) -> None:
    width, height = face["size"]
    outline, radius = _silhouette(face)
    silhouette = kit.rounded(outline, radius)
    painter.save()
    painter.setClipPath(silhouette)
    painter.fillRect(
        outline,
        kit.gradient(
            outline, _darken(FRAME_TOP, GRAIN_LEVELS), _darken(FRAME_BOTTOM, GRAIN_LEVELS),
        ),
    )
    # The clip is kept in device space when the transform is reset, so the
    # tile lands one grain cell per device pixel.
    painter.save()
    painter.resetTransform()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.drawTiledPixmap(QRectF(0, 0, width * kit.SCALE, height * kit.SCALE), _grain_tile())
    painter.restore()
    # A broad, faint falloff from the top-left light keeps the matte finish
    # from reading as a flat fill.
    sheen = QRadialGradient(QPointF(30, -20), 420)
    sheen.setColorAt(0, _color("#ffffff", 9))
    sheen.setColorAt(1, _color("#ffffff", 0))
    painter.fillRect(outline, sheen)
    painter.restore()


def _paint_frame_edges(
    painter: QPainter, kit, face: dict, aperture: QRectF, radius: float,
) -> None:
    """Machined outer edge, and the light caught by the aperture's lower wall."""
    silhouette, corner = _silhouette(face)
    outline = kit.rounded(silhouette.adjusted(0.5, 0.5, -0.5, -0.5), corner - 0.5)
    chamfer = kit.rounded(silhouette.adjusted(1.5, 1.5, -1.5, -1.5), corner - 1.5)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(_color("#000000", 200), 1))
    painter.drawPath(outline)
    light = [(0, _color("#ffffff", 18)), (1, _color("#ffffff", 0))]
    painter.setPen(_vertical_pen(silhouette.top(), 220, light, 1))
    painter.drawPath(chamfer)
    shade = [(0, _color("#000000", 0)), (1, _color("#000000", 70))]
    painter.setPen(_vertical_pen(260, silhouette.bottom(), shade, 1))
    painter.drawPath(chamfer)

    # The cover sits a step below the frame. The frame's lower inner wall
    # faces the light, so a faint lit line runs just outside the seal along
    # the aperture's bottom edge and fades up its sides.
    lip = [(0, _color("#ffffff", 0)), (0.7, _color("#ffffff", 4)), (1, _color("#ffffff", 22))]
    painter.setPen(_vertical_pen(aperture.top(), aperture.bottom() + 1.5, lip, 0.5))
    outside = SEAL_WIDTH / 2 + 0.25
    painter.drawPath(kit.rounded(
        aperture.adjusted(-outside, -outside, outside, outside), radius + outside,
    ))


def _smoke_alpha(knots: list[tuple[float, float]], y: float) -> float:
    for (top, upper), (bottom, lower) in pairwise(knots):
        if y <= bottom:
            return upper + (lower - upper) * _smoothstep((y - top) / (bottom - top))
    return knots[-1][1]


def _paint_smoke(painter: QPainter, face: dict, aperture: QRectF) -> None:
    """One vertical gradient sampled from the smoke budget.

    No grain: one smoke colour changes only in opacity, a few levels per
    device pixel on the steep ramps and one level every few pixels on the
    gentle ones, too little to band. The clear core stays free of dirt.
    """
    knots = _smoke_knots(face)
    top, bottom = aperture.top(), aperture.bottom()
    smoke = QLinearGradient(0, top, 0, bottom)
    y = top
    while y <= bottom:
        alpha = round(255 * _smoke_alpha(knots, y))
        smoke.setColorAt((y - top) / (bottom - top), _color(SMOKE, alpha))
        y += SMOKE_STEP
    painter.fillRect(aperture, smoke)


def _inner_shadow_alpha(depth: float) -> float:
    if depth <= INNER_SHADOW_CORE:
        return INNER_SHADOW_CORE_ALPHA
    fade = min(1.0, (depth - INNER_SHADOW_CORE) / (INNER_SHADOW_REACH - INNER_SHADOW_CORE))
    return INNER_SHADOW_CORE_ALPHA * (1 - fade) ** 2


def _paint_inner_shadow(
    painter: QPainter, kit, aperture: QRectF, radius: float, width: int, height: int,
) -> None:
    """Shade the cover's edge with nested fills on a layer of its own.

    Each fill, from the edge inward, replaces the one before it
    (CompositionMode_Source), so neighbouring steps blend by coverage alone
    and no antialiased seams add up along the curves. The layer is then
    laid over the cover once.
    """
    layer, shade = kit.canvas(width, height)
    shade.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    shade.fillRect(QRectF(0, 0, width, height), _color(SHADE, round(255 * _inner_shadow_alpha(0))))
    depth = INNER_SHADOW_STEP
    while depth <= INNER_SHADOW_REACH:
        tail = INNER_SHADOW_LEAN * max(0.0, depth - INNER_SHADOW_CORE)
        lead, trail = depth + tail, depth - tail
        shade.fillPath(
            kit.rounded(aperture.adjusted(lead, lead, -trail, -trail), max(0.0, radius - depth)),
            _color(SHADE, round(255 * _inner_shadow_alpha(depth))),
        )
        depth += INNER_SHADOW_STEP
    shade.end()
    painter.drawImage(QRectF(0, 0, width, height), layer)


def _paint_grip(painter: QPainter, kit, face: dict) -> None:
    """Six dimples in an opaque recessed pad at the drag region's left end."""
    rect, dimples = _grip(face)
    pad = kit.rounded(rect, rect.height() / 2)
    painter.fillPath(pad, QColor(GRIP_WELL))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inner = kit.rounded(rect.adjusted(0.9, 0.9, -0.9, -0.9), rect.height() / 2 - 0.9)
    painter.setPen(_crescent_pen(rect, "#000000", 120, 1))
    painter.drawPath(inner)
    painter.setPen(QPen(QColor(GEL_EDGE), 0.8))
    painter.drawPath(pad)
    painter.setPen(Qt.PenStyle.NoPen)
    for dimple in dimples:
        painter.setBrush(_color("#ffffff", GRIP_LIP_ALPHA))
        painter.drawEllipse(dimple + QPointF(0.3, 0.5), GRIP_RADIUS, GRIP_RADIUS)
        painter.setBrush(QColor("#000000"))
        painter.drawEllipse(dimple, GRIP_RADIUS, GRIP_RADIUS)


def _paint_divider(painter: QPainter, controls: dict) -> None:
    """Engraved in the glass: shadowed upper wall, lit lower lip."""
    y, left, right = _divider(controls)
    painter.setPen(QPen(_color("#000000", 80), 1))
    painter.drawLine(QPointF(left, y - 0.5), QPointF(right, y - 0.5))
    painter.setPen(QPen(_color("#ffffff", 14), 1))
    painter.drawLine(QPointF(left, y + 0.5), QPointF(right, y + 0.5))


def _paint_seats(painter: QPainter, controls: dict) -> None:
    """Recessed seats for the host's inset rails: shadowed upper wall, lit lower lip."""
    for name in ("seek", "volume"):
        seat = QRectF(*controls[name]).adjusted(-2, 5, 2, -5)
        middle = seat.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_color("#000000", 70))
        painter.drawRoundedRect(seat, 4, 4)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_vertical_pen(seat.top(), middle, [
            (0, _color("#000000", SEAT_WALL_ALPHA)), (1, _color("#000000", 0)),
        ], 0.8))
        painter.drawRoundedRect(seat.adjusted(0.4, 0.4, -0.4, -0.4), 3.6, 3.6)
        painter.setPen(_vertical_pen(middle, seat.bottom() + 0.5, [
            (0, _color("#ffffff", 0)), (1, _color("#ffffff", SEAT_LIP_ALPHA)),
        ], 0.5))
        painter.drawRoundedRect(seat.adjusted(-0.25, -0.25, 0.25, 0.25), 4.25, 4.25)


def render_background(face: dict, kit) -> QImage:
    width, height = face["size"]
    controls = face["controls"]
    radius = face["radius"]
    aperture = QRectF(*controls["art"])
    aperture_path = kit.control_path(aperture, face["controlShapes"]["art"], radius)
    image, painter = kit.canvas(width, height)
    _paint_frame(painter, kit, face)

    # The hole must be fully transparent before the glass goes in, so the
    # glass alone decides how much of the cover shows.
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.fillPath(aperture_path, Qt.GlobalColor.transparent)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

    painter.save()
    painter.setClipPath(aperture_path)
    _paint_smoke(painter, face, aperture)
    _paint_inner_shadow(painter, kit, aperture, radius, width, height)
    _paint_grip(painter, kit, face)
    _paint_divider(painter, controls)
    _paint_seats(painter, controls)
    painter.restore()

    # The seal goes on unclipped, so it covers the edge pixels whole.
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(QPen(QColor(SEAL), SEAL_WIDTH))
    painter.drawPath(aperture_path)
    _paint_frame_edges(painter, kit, face, aperture, radius)
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
    """An opaque smoked-glass key. A ringed key (play) takes its edge from the ring."""
    path = kit.control_path(rect, shape, radius)
    if state in DROP_ALPHA:
        painter.fillPath(path.translated(0, 0.8), _color("#000000", DROP_ALPHA[state]))

    if state == "pressed":
        top, bottom, edge = QColor("#18191c"), QColor("#26282d"), QColor(GEL_EDGE)
    elif state == "disabled":
        top = bottom = QColor(DISABLED_FILL)
        edge = None
    elif state == "hover":
        top, bottom = QColor(GEL_TOP).lighter(HOVER_LIFT), QColor(GEL_BOTTOM).lighter(HOVER_LIFT)
        edge = QColor(HOVER_EDGE)
    else:
        top, bottom, edge = QColor(GEL_TOP), QColor(GEL_BOTTOM), QColor(GEL_EDGE)
    painter.fillPath(path, kit.gradient(rect, top, bottom))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if not ringed and edge is not None:
        painter.setPen(QPen(edge, 0.8))
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
    ring = rect.adjusted(RING_INSET, RING_INSET, -RING_INSET, -RING_INSET)
    if state == "disabled":
        pen = QPen(QColor(DISABLED_RING), RING_WIDTH)
    else:
        alpha = RING_ALPHA[state]
        brass = QColor(BRASS)
        pen = _vertical_pen(ring.top(), ring.bottom(), [
            (0, _color(brass.lighter(122).name(), alpha)), (0.5, _color(BRASS, alpha)),
            (1, _color(brass.darker(125).name(), alpha)),
        ], RING_WIDTH)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(pen)
    painter.drawPath(kit.control_path(ring, shape, radius - RING_INSET))


def render_button(face: dict, control: str, state: str, kit) -> QImage:
    _, _, width, height = face["controls"][control]
    shape = face["controlShapes"][control]
    radius = face["radius"]
    image, painter = kit.canvas(width, height)
    rect = QRectF(1, 1, width - 2, height - 2)
    ringed = control == "play"
    _paint_gel(painter, kit, rect, shape, radius, state, ringed=ringed)
    if ringed:
        _paint_brass_ring(painter, kit, rect, shape, radius, state)
    painter.end()
    return image
