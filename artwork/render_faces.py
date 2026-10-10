"""Compose generated materials and precise host-control surfaces into Face packs.

The OpenAI-generated originals and exact prompts live in artwork/generated and
face-prompts.json. This offline exporter resamples those materials, applies the
window silhouettes, and paints clean readout wells and button state surfaces.
Text and transport symbols remain host-owned. No generation or network call is
needed to rebuild the shipped 2x PNGs.

Faces with a module in artwork/procedural/<id>.py are painted entirely in code
instead: the module's render_background(face, kit) returns the 2x background,
and its render_button(face, control, state, kit) returns one button surface.
`kit` is PROCEDURAL_KIT, the exporter's shared drawing helpers.

Run: QT_QPA_PLATFORM=offscreen uv run python artwork/render_faces.py
Repeat --face ID to re-export only those packs.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from types import ModuleType, SimpleNamespace

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
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
ROOT = Path(__file__).resolve().parent
FACES_ROOT = ROOT.parent / "native" / "amberfader" / "faces"
PROCEDURAL_ROOT = ROOT / "procedural"
BUTTON_GROUPS = {
    "previous": "transport",
    "next": "transport",
    "like": "transport",
    "play": "play",
    "search": "utility",
    "show": "utility",
    "hide": "utility",
    "menu": "chrome",
    "minimize": "chrome",
    "close": "chrome",
}
SCULPTURAL_FACES = frozenset({"orbit-99", "manta-ray", "jellyfish-fm", "boom-bot"})
UTILITARIAN_FACES = frozenset({"tangent", "keystone", "switchback", "vane"})
LENS_FACES = frozenset({"aureole", "viridian"})
SHAPED_FACES = SCULPTURAL_FACES | UTILITARIAN_FACES | LENS_FACES
READOUT_CONTROLS = frozenset({"title", "artists", "time", "playback", "status"})
GROUP_REPRESENTATIVES = {
    "transport": "previous", "play": "play", "utility": "show", "chrome": "menu",
}
BUTTON_STATES = ("normal", "hover", "pressed", "disabled")
EXPORTED_SPRITES = frozenset(
    f"{family}-{state}.png"
    for family in {*BUTTON_GROUPS, *BUTTON_GROUPS.values()}
    for state in BUTTON_STATES
)
# Rectangular faces: well padding around controls, (horizontal, vertical) in
# logical pixels. A classic slider's 14 px thumb travels the full control
# width, so an 18 px tall slider gets the same clearance on every side. The
# display's vertical pad is smaller because a 26 px title row already leaves
# 8 px above its capitals, and a 37 px time row 8 px below its digits; the
# glass then shows even ink margins on all four sides. Its right pad is 1 px
# wider than its left: left-aligned time digits start 2 px inside their rect,
# right-aligned playback words end within 0.5 px of theirs.
DISPLAY_PAD = (14, 6, 15, 6)  # left, top, right, bottom
PLATE_TEXT_INSET = 10
PLATE_NAME_GAP = 12
SLIDER_PAD = (6, 4)
STATUS_PAD = (10, 4)
# Rave Grid's status strip fills the 24 px decorative band below its panel
# (panel edge line to outer frame line), which the default pad overflows.
# Its plate ends short of the lime stripe band, so the name sits closer.
# Moonstone's plate ends before the top crest's descending rim, for the same
# reason.
FACE_STATUS_PAD = {"rave-grid": (10, 1)}
FACE_PLATE_NAME_GAP = {"rave-grid": 8, "moonstone": 8}
# Those two plates stop short of their artwork; the invisible drag region
# keeps covering the rest of the header band up to the window buttons.
FACE_PLATE_WIDTH = {"rave-grid": 166, "moonstone": 178}
# Paper Signal types its status line straight onto the cream paper, centred
# on the seal stamped at the line's end. A well tall enough for the text
# cannot share the seal's centre without crossing the bottom ruled line.
FACES_WITHOUT_STATUS_WELL = frozenset({"paper-signal"})
# Utilitarian display wells pad the readout union by (horizontal, vertical).
UTILITARIAN_WELL_PADDING = {"tangent": (8, 6)}


def _rounded(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    return path


def _control_path(rect: QRectF, shape: str, radius: float) -> QPainterPath:
    path = QPainterPath()
    if shape == "ellipse":
        path.addEllipse(rect)
    elif shape in {"rounded", "capsule"}:
        corner = min(rect.width(), rect.height()) / 2 if shape == "capsule" else radius
        path.addRoundedRect(rect, corner, corner)
    elif shape == "rectangle":
        path.addRect(rect)
    else:
        raise ValueError(f"Unknown control shape: {shape}")
    return path


def _gradient(rect: QRectF, top: QColor, bottom: QColor) -> QLinearGradient:
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    gradient.setColorAt(0, top)
    gradient.setColorAt(1, bottom)
    return gradient


def _canvas(width: int, height: int) -> tuple[QImage, QPainter]:
    image = QImage(width * SCALE, height * SCALE, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
    )
    painter.scale(SCALE, SCALE)
    return image, painter


def _silhouette(face: dict) -> QPainterPath:
    width, height = face["size"]
    rect = QRectF(1, 1, width - 2, height - 2)
    face_id = face["id"]
    if face_id == "copper-reel":
        body = _rounded(QRectF(1, 1, 440, 342), 18)
        pod = QPainterPath()
        pod.addEllipse(QRectF(426, 64, 212, 212))
        shelf = _rounded(QRectF(1, 286, 612, 57), 14)
        return body.united(pod).united(shelf)
    if face_id in ("memphis-93", "rave-grid"):
        # A clipped-corner silhouette without cutouts beneath controls.
        cut = 14 if face_id == "memphis-93" else 24
        path = QPainterPath()
        path.moveTo(cut, 1)
        for x, y in (
            (width - cut, 1),
            (width - 1, cut),
            (width - 1, height - cut),
            (width - cut, height - 1),
            (cut, height - 1),
            (1, height - cut),
            (1, cut),
        ):
            path.lineTo(x, y)
        path.closeSubpath()
        return path
    radius = {"moonstone": 32, "arcade-clear": 28, "paper-signal": 2}.get(face_id, 12)
    return _rounded(rect, radius)


def _well(painter: QPainter, rect: QRectF, color: str, border: str, radius: int = 7) -> None:
    # Opaque wells protect live metadata contrast from the material underneath.
    painter.setPen(QPen(QColor("#080a0c"), 2))
    painter.setBrush(QColor(color))
    painter.drawRoundedRect(rect, radius, radius)
    painter.setPen(QPen(QColor(border), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius, radius)
    shine = QColor("#ffffff")
    shine.setAlpha(45)
    painter.setPen(QPen(shine, 0.7))
    painter.drawLine(rect.topLeft() + QPointF(8, 2), rect.topRight() + QPointF(-8, 2))


def _surround(rectangle: list[int], margin: int) -> QRectF:
    return QRectF(*rectangle).adjusted(-margin, -margin, margin, margin)


def _padded(rectangle: QRectF | list[int], padding: tuple[int, int]) -> QRectF:
    x, y = padding
    rect = rectangle if isinstance(rectangle, QRectF) else QRectF(*rectangle)
    return rect.adjusted(-x, -y, x, y)


def _manta_ray_close_socket(painter: QPainter, face: dict, source: QImage) -> None:
    """Give close a copy of the art's neighbouring chrome socket.

    The generated channel holds two chrome sockets for three chrome buttons.
    The right socket (logical centre and radius with its dark ring, measured
    from artwork/generated/manta-ray.png) is copied onto close's centre at
    92 % size, because the channel narrows toward the tail there: the dark
    ring then meets the channel's top bevel like its neighbour's and keeps
    teal below it. Its outer ring fades into the channel.
    """
    centre_x, centre_y, radius, scale = 597.0, 304.75, 19.5, 0.92
    ratio = source.width() / face["size"][0]
    size = round(2 * radius * scale * SCALE)
    patch = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    patch.fill(Qt.GlobalColor.transparent)
    patch_painter = QPainter(patch)
    patch_painter.setRenderHints(
        QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform
    )
    patch_painter.drawImage(
        QRectF(0, 0, size, size), source,
        QRectF(
            (centre_x - radius) * ratio, (centre_y - radius) * ratio,
            2 * radius * ratio, 2 * radius * ratio,
        ),
    )
    fade = QRadialGradient(QPointF(size / 2, size / 2), size / 2)
    fade.setColorAt(0.88, QColor(0, 0, 0, 255))
    fade.setColorAt(1, QColor(0, 0, 0, 0))
    patch_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    patch_painter.fillRect(QRectF(0, 0, size, size), fade)
    patch_painter.end()

    x, y, width, height = face["controls"]["close"]
    drawn = radius * scale
    target = QRectF(x + width / 2 - drawn, y + height / 2 - drawn, 2 * drawn, 2 * drawn)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    painter.drawImage(target, patch)


def _orbit_pod_cap(painter: QPainter) -> None:
    """Cap Orbit 99's lower satellite pod so it reads as trim, not a button.

    The pod's domed glass matches the populated sockets, but no host button
    fits it: "Search" needs a wider capsule than the ~44 px glass. A flat,
    concentrically machined navy cap with a centre boss echoes the main
    disc. Centre and radius sit just inside the pod's cyan ring (logical,
    measured from the exported background), so the ring stays visible.
    """
    centre, radius = QPointF(282.16, 440.17), 21.75

    def circle(r: float) -> QRectF:
        return QRectF(centre.x() - r, centre.y() - r, 2 * r, 2 * r)

    enamel = QRadialGradient(centre - QPointF(0, 4), 26)
    enamel.setColorAt(0, QColor("#163a63"))
    enamel.setColorAt(1, QColor("#081a30"))
    painter.setPen(QPen(QColor("#050d18"), 0.8))
    painter.setBrush(enamel)
    painter.drawEllipse(circle(radius))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for step in range(3, 14):
        groove = QColor("#6fb6d6")
        groove.setAlpha(26 if step % 2 else 16)
        painter.setPen(QPen(groove, 0.5))
        painter.drawEllipse(circle(1.5 * step))
    shine = QColor("#ffffff")
    shine.setAlpha(40)
    painter.setPen(QPen(shine, 0.7))
    painter.drawArc(circle(radius - 1.2), 30 * 16, 120 * 16)
    boss = QRadialGradient(centre - QPointF(1, 1.2), 5)
    boss.setColorAt(0, QColor("#e6e9eb"))
    boss.setColorAt(0.5, QColor("#7d8388"))
    boss.setColorAt(1, QColor("#23282e"))
    painter.setPen(QPen(QColor("#1a1f25"), 0.6))
    painter.setBrush(boss)
    painter.drawEllipse(circle(3.6))


def _render_sculptural_background(face: dict, source: QImage) -> QImage:
    """Keep the generated object's alpha contour and its open interior spaces."""
    width, height = face["size"]
    image, painter = _canvas(width, height)
    painter.drawImage(QRectF(0, 0, width, height), source)
    if face["id"] == "manta-ray":
        # Its generated kidney-shaped window and curved status slot are already
        # dark display glass; no axis-aligned well fits them with even clearance.
        _manta_ray_close_socket(painter, face, source)
        painter.end()
        return image
    palette = face["palette"]
    controls = face["controls"]
    radius = min(face["radius"], 12)

    # Wells change the material color without extending the original contour
    # or filling the character's transparent interior spaces.
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    readout = QRectF()
    for name in sorted(READOUT_CONTROLS - {"status"}):
        readout = readout.united(QRectF(*controls[name]))
    _well(
        painter, readout.adjusted(-5, -5, 5, 5), palette["display"],
        palette["border"], radius,
    )
    if face["id"] == "boom-bot":
        # Its status well sits in a narrow gap between the cover bezel and the
        # hip joints, so it gets less vertical padding. Its volume rail would
        # otherwise cross the bar's short decorative pill (narrower than the
        # 80 px slider minimum), so a slot spanning the bar's flat section
        # covers the pill and gives the rail its own channel.
        _well(
            painter, _padded(controls["status"], (5, 3)), palette["panel"],
            palette["border"], radius,
        )
        _well(
            painter, _padded(controls["volume"], (6, 0)), palette["display"],
            palette["border"], 9,
        )
    elif face["id"] == "jellyfish-fm":
        # Long status text elides to the full rect width, so the well's 12 px
        # corners need wider side padding to keep the ink off the arcs. 8 px
        # matches the space above the capitals and below the descenders.
        _well(
            painter, _padded(controls["status"], (8, 5)), palette["panel"],
            palette["border"], radius,
        )
    else:
        _well(
            painter, _surround(controls["status"], 5), palette["panel"],
            palette["border"], radius,
        )
    if face["id"] == "orbit-99":
        _orbit_pod_cap(painter)

    painter.end()
    return image


def _render_utilitarian_background(face: dict, source: QImage) -> QImage:
    """Use one display well so compact instruments keep a coherent readout."""
    width, height = face["size"]
    if source.width() * height != source.height() * width:
        raise RuntimeError(f"{face['id']}: generated material does not match the canvas aspect")
    image, painter = _canvas(width, height)
    painter.drawImage(QRectF(0, 0, width, height), source)
    if face["id"] == "keystone":
        # Its generated window is already dark display glass, and no rounded
        # well can follow the glass's clipped corner with even clearance.
        painter.end()
        return image
    palette = face["palette"]
    controls = face["controls"]
    readout = QRectF()
    for name in sorted(READOUT_CONTROLS):
        readout = readout.united(QRectF(*controls[name]))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    if face["id"] == "vane":
        _vane_glass_well(painter, palette)
    else:
        # Text ink starts at a left-aligned label's edge but sits about 3 px
        # inside an 18 px row, so an even pad leaves the sides tighter than
        # the top and bottom. Tangent pads its sides more to even them out.
        pad_x, pad_y = UTILITARIAN_WELL_PADDING.get(face["id"], (6, 6))
        _well(
            painter, readout.adjusted(-pad_x, -pad_y, pad_x, pad_y),
            palette["display"], palette["border"], 14,
        )
    painter.end()
    return image



# Vane's ice-blue glass is a wide, slightly trapezoidal oval: a radius-14 well
# either pokes past its rim or shrinks below a usable readout. Its display
# follows the glass outline measured from artwork/generated/vane.png instead
# (logical bounds, then top and bottom elliptical corner radii), inset so the
# glass rim stays visible around it. The readout rects are laid out inside it.
VANE_GLASS = (QRectF(135.25, 115.5, 390.25, 83.5), (128.0, 42.5), (85.0, 33.0))
VANE_GLASS_INSET = 3.0


def _vane_glass_path(inset: float) -> QPainterPath:
    bounds, top, bottom = VANE_GLASS
    rect = bounds.adjusted(inset, inset, -inset, -inset)
    (tx, ty), (bx, by) = ((x - inset, y - inset) for x, y in (top, bottom))
    left, right, upper, lower = rect.left(), rect.right(), rect.top(), rect.bottom()
    path = QPainterPath()
    path.moveTo(left + tx, upper)
    path.arcTo(QRectF(right - 2 * tx, upper, 2 * tx, 2 * ty), 90, -90)
    path.arcTo(QRectF(right - 2 * bx, lower - 2 * by, 2 * bx, 2 * by), 0, -90)
    path.arcTo(QRectF(left, lower - 2 * by, 2 * bx, 2 * by), 270, -90)
    path.arcTo(QRectF(left, upper, 2 * tx, 2 * ty), 180, -90)
    path.closeSubpath()
    return path


def _vane_glass_well(painter: QPainter, palette: dict) -> None:
    """Paint _well's display treatment on Vane's glass-shaped outline."""
    painter.setPen(QPen(QColor("#080a0c"), 2))
    painter.setBrush(QColor(palette["display"]))
    painter.drawPath(_vane_glass_path(VANE_GLASS_INSET))
    painter.setPen(QPen(QColor(palette["border"]), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_vane_glass_path(VANE_GLASS_INSET + 1))
    shine = QColor("#ffffff")
    shine.setAlpha(45)
    painter.setPen(QPen(shine, 0.7))
    top = VANE_GLASS[0].top() + VANE_GLASS_INSET
    painter.save()
    painter.setClipRect(QRectF(0, top, VANE_GLASS[0].right(), 5))
    painter.drawPath(_vane_glass_path(VANE_GLASS_INSET + 2))
    painter.restore()


def _render_lens_background(face: dict, source: QImage) -> QImage:
    """Keep the oval/circular glass intact, with host text directly on the lens."""
    width, height = face["size"]
    if source.width() * height != source.height() * width:
        raise RuntimeError(f"{face['id']}: generated material does not match the canvas aspect")
    image, painter = _canvas(width, height)
    painter.drawImage(QRectF(0, 0, width, height), source)
    painter.end()
    return image


_PROCEDURAL_MODULES: dict[str, ModuleType | None] = {}


def _procedural(face_id: str) -> ModuleType | None:
    """The face's painting module, or None for faces built from generated art."""
    if face_id not in _PROCEDURAL_MODULES:
        path = PROCEDURAL_ROOT / f"{face_id}.py"
        module = None
        if path.is_file():
            spec = importlib.util.spec_from_file_location(
                f"amberfader_procedural_{face_id.replace('-', '_')}", path,
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        _PROCEDURAL_MODULES[face_id] = module
    return _PROCEDURAL_MODULES[face_id]


def render_background(face: dict) -> QImage:
    procedural = _procedural(face["id"])
    if procedural is not None:
        return procedural.render_background(face, PROCEDURAL_KIT)
    width, height = face["size"]
    source = QImage(str(ROOT / "generated" / f"{face['id']}.png"))
    if source.isNull():
        raise RuntimeError(f"Missing generated material for {face['id']}")
    if face["id"] in SHAPED_FACES:
        if not source.hasAlphaChannel():
            raise RuntimeError(f"{face['id']}: shaped material needs an alpha channel")
        if face["id"] in UTILITARIAN_FACES:
            return _render_utilitarian_background(face, source)
        if face["id"] in LENS_FACES:
            return _render_lens_background(face, source)
        return _render_sculptural_background(face, source)
    image, painter = _canvas(width, height)
    shape = _silhouette(face)
    painter.setClipPath(shape)
    painter.drawImage(QRectF(0, 0, width, height), source)
    if face["id"] == "copper-reel":
        # Place the complete platter in its pod instead of stretching a cropped
        # source disc across both the chassis and the shaped exterior. Chassis
        # and shelf share one mapping, so the left rail and the brushed texture
        # run on across the shelf without a seam.
        painter.drawImage(QRectF(0, 0, 613, 344), source, QRectF(0, 0, 613 * 790 / 441, 1024))
        painter.save()
        pod = QPainterPath()
        pod.addEllipse(QRectF(426, 64, 212, 212))
        painter.setClipPath(pod, Qt.ClipOperation.IntersectClip)
        # The crop is centred on the platter bowl measured in the source
        # (centre 1137.3, 485.1 px), so the gold ring is concentric with the pod.
        painter.drawImage(QRectF(426, 64, 212, 212), source, QRectF(800.3, 148.1, 674, 674))
        painter.restore()
    p = face["palette"]
    c = face["controls"]
    radius = min(face["radius"], 10)
    display = QRectF()
    for name in ("title", "artists", "time", "playback"):
        display = display.united(QRectF(*c[name]))
    left, top, right, bottom = DISPLAY_PAD
    display = display.adjusted(-left, -top, right, bottom)
    _well(painter, display, p["display"], p["border"], radius)
    _well(painter, _surround(c["art"], 5), p["display"], p["border"], radius)
    # Bars keep sliders' thumb travel and status text clear of the well rims.
    _well(painter, _padded(c["seek"], SLIDER_PAD), p["panel"], p["border"], radius)
    _well(painter, _padded(c["volume"], SLIDER_PAD), p["panel"], p["border"], radius)
    if face["id"] not in FACES_WITHOUT_STATUS_WELL:
        status_pad = FACE_STATUS_PAD.get(face["id"], STATUS_PAD)
        _well(painter, _padded(c["status"], status_pad), p["window"], p["border"], 2)

    # Readable, static identity plate filling the safe drag region, so the
    # title bar spans the same grid columns as the rows beneath it.
    plate = QRectF(*face["drag"])
    if face["id"] in FACE_PLATE_WIDTH:
        plate.setWidth(FACE_PLATE_WIDTH[face["id"]])
    _well(painter, plate, p["window"], p["border"], radius)
    # Both strings share one baseline that centres AMBERFADER's capitals on
    # the plate, snapped to whole device pixels so the caps stay crisp.
    font = QFont("sans-serif")
    font.setPixelSize(12)
    font.setBold(True)
    metrics = QFontMetricsF(font)
    baseline = round((plate.center().y() + metrics.capHeight() / 2) * SCALE) / SCALE
    name_x = plate.x() + PLATE_TEXT_INSET + metrics.horizontalAdvance("AMBERFADER")
    name_gap = FACE_PLATE_NAME_GAP.get(face["id"], PLATE_NAME_GAP)
    name_x = round((name_x + name_gap) * SCALE) / SCALE
    painter.save()
    painter.setClipRect(plate.adjusted(2, 2, -2, -2), Qt.ClipOperation.IntersectClip)
    painter.setFont(font)
    painter.setPen(QColor(p["text"]))
    painter.drawText(QPointF(plate.x() + PLATE_TEXT_INSET, baseline), "AMBERFADER")
    font.setPixelSize(9)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor(p["muted"]))
    painter.drawText(QPointF(name_x, baseline), face["name"].upper())
    painter.restore()
    painter.setClipping(False)
    painter.setPen(QPen(QColor(p["border"]), 1))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(shape)
    painter.end()
    return image


def _render_shaped_button(face: dict, control: str, state: str) -> QImage:
    _, _, width, height = face["controls"][control]
    image, painter = _canvas(width, height)
    palette = face["palette"]
    top, bottom = QColor(palette["buttonTop"]), QColor(palette["buttonBottom"])
    edge = QColor(palette["border"])
    if state == "hover":
        top, bottom, edge = top.lighter(106), bottom.lighter(106), edge.lighter(115)
    elif state == "pressed":
        top, bottom, edge = bottom.darker(105), top.darker(105), edge.darker(115)
    elif state == "disabled":
        if face["id"] in {"switchback", "vane"}:
            # Their dark disabled glyphs need quiet metal, not luminous glass.
            top, bottom = QColor("#d0d6da"), QColor("#b8c1c7")
        else:
            matte = QColor(
                (top.red() + bottom.red()) // 2,
                (top.green() + bottom.green()) // 2,
                (top.blue() + bottom.blue()) // 2,
            )
            top, bottom = matte.lighter(103), matte.darker(103)

    shape = face.get("controlShapes", {}).get(control, "rounded")
    radius = min(face["radius"], (height - 4) / 2)
    rect = QRectF(1.25, 1.25, width - 2.5, height - 3)
    path = _control_path(rect, shape, radius)
    shadow = QColor("#0b1015")
    shadow.setAlpha(70 if state == "pressed" else 45)
    painter.fillPath(_control_path(rect.translated(0, 0.75), shape, radius), shadow)
    painter.setPen(QPen(edge, 0.9))
    painter.setBrush(_gradient(rect, top, bottom))
    painter.drawPath(path)

    light, shade = QColor("#ffffff"), QColor("#0b1015")
    light.setAlpha(35 if state == "disabled" else 85)
    shade.setAlpha(85 if state == "pressed" else 45)
    rim_top, rim_bottom = (shade, light) if state == "pressed" else (light, shade)
    painter.setPen(QPen(QBrush(_gradient(rect, rim_top, rim_bottom)), 0.75))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_control_path(rect.adjusted(1.2, 1.2, -1.2, -1.2), shape, radius))
    painter.end()
    return image


def _group_representative(face: dict, group: str) -> str:
    # Viridian's supplied layout enlarges Show YT while retaining the original
    # utility images. Re-export those images at Search's original dimensions.
    if face["id"] == "viridian" and group == "utility":
        return "search"
    return GROUP_REPRESENTATIVES[group]


def _sprite_family(face: dict, name: str) -> str:
    """Name the surface a button uses; Qt stretches a sprite to its control.

    Members matching their group representative's size and shape share the
    group surface. Any other member gets its own surface, so a face can give
    one button a different socket without distorting corners or rims.
    """
    group = BUTTON_GROUPS[name]
    representative = _group_representative(face, group)
    controls, shapes = face["controls"], face.get("controlShapes", {})
    same_size = controls[name][2:] == controls[representative][2:]
    same_shape = shapes.get(name) == shapes.get(representative)
    if (
        face["id"] == "viridian" and name == "show"
        and controls[name][2:] == [71, 24]
        and controls[representative][2:] == [70, 22]
        and shapes.get(name) == shapes.get(representative) == "ellipse"
    ):
        return group
    return group if same_size and same_shape else name


def render_button(face: dict, group: str, state: str, control: str | None = None) -> QImage:
    control = control or GROUP_REPRESENTATIVES[group]
    procedural = _procedural(face["id"])
    if procedural is not None:
        return procedural.render_button(face, control, state, PROCEDURAL_KIT)
    if face["id"] in SHAPED_FACES:
        return _render_shaped_button(face, control, state)
    _, _, width, height = face["controls"][control]
    image, painter = _canvas(width, height)
    p = face["palette"]
    top, bottom, edge = QColor(p["buttonTop"]), QColor(p["buttonBottom"]), QColor(p["border"])
    flat = face["id"] in ("memphis-93", "rave-grid", "paper-signal")
    if face["id"] == "memphis-93":
        top = bottom = QColor(
            {"play": "#f57b9e", "transport": "#f6ce55", "chrome": "#48c9c1", "utility": "#fff8e7"}[
                group
            ]
        )
    if state == "hover":
        top, bottom, edge = top.lighter(115), bottom.lighter(115), QColor(p["accent"])
    elif state == "pressed":
        top, bottom, edge = bottom.darker(115), top.darker(115), QColor(p["accent"])
    elif state == "disabled":
        top, bottom = QColor(p["panel"]), QColor(p["window"])
        if face["id"] in ("switchback", "vane") or face["id"] in LENS_FACES:
            # These light readouts use dark muted labels, including disabled
            # host glyphs. Keep their matte button surface equally legible.
            top = bottom = QColor(p["display"])
    radius = min(face["radius"], (height - 4) / 2)
    rect = QRectF(1, 1, width - 2, height - 3)
    shadow = rect.translated(0, 1)
    painter.fillPath(_rounded(shadow, radius), QColor("#080a0c"))
    painter.setPen(QPen(edge, 1.5 if flat else 1))
    painter.setBrush(_gradient(rect, top, bottom))
    painter.drawRoundedRect(rect, radius, radius)
    if not flat:
        highlight = QColor("#ffffff")
        highlight.setAlpha(85 if state != "disabled" else 25)
        painter.setPen(QPen(highlight, 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), max(0, radius - 2), max(0, radius - 2))
    painter.end()
    return image


# The helpers procedural face modules may use; see the module docstring.
PROCEDURAL_KIT = SimpleNamespace(
    SCALE=SCALE,
    BUTTON_GROUPS=BUTTON_GROUPS,
    canvas=_canvas,
    control_path=_control_path,
    gradient=_gradient,
    rounded=_rounded,
)


def _encode_png(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QBuffer.OpenMode.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError("Could not encode face image")
    return bytes(buffer.data())


def _translucent_regions(face: dict, image: QImage) -> list[str]:
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    data = bytes(rgba.constBits())
    stride = image.width() * 4
    bad = []
    for name, rect in {"drag": face["drag"], **face["controls"]}.items():
        x, y, width, height = (value * SCALE for value in rect)
        for row in range(y, y + height):
            start = row * stride + x * 4 + 3
            if min(data[start : start + width * 4 : 4]) < MIN_ALPHA:
                bad.append(name)
                break
    return bad


def _save(image: QImage, path: Path) -> None:
    data = _encode_png(image)
    if len(data) > MAX_FILE_BYTES or max(image.width(), image.height()) > MAX_DIMENSION:
        raise RuntimeError(f"Face image exceeds resource limits: {path}")
    path.write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--face", action="append", dest="face_ids", metavar="ID",
        help="Re-export only this face; repeat to select several faces",
    )
    options = parser.parse_args()
    manifests = sorted(FACES_ROOT.glob("*/face.json"))
    if options.face_ids:
        unknown = set(options.face_ids) - {manifest.parent.name for manifest in manifests}
        if unknown:
            parser.error("Unknown face IDs: " + ", ".join(sorted(unknown)))
        manifests = [manifest for manifest in manifests if manifest.parent.name in options.face_ids]
    app = QGuiApplication.instance() or QGuiApplication([])
    for manifest in manifests:
        face = json.loads(manifest.read_text())
        # Shared surface families keep pack size small; host text stays live.
        families = {name: _sprite_family(face, name) for name in BUTTON_GROUPS}
        expected_buttons = {
            name: {state: f"{family}-{state}.png" for state in BUTTON_STATES}
            for name, family in families.items()
        }
        declared_buttons = face.get("buttons", {})
        if declared_buttons != expected_buttons:
            wrong = sorted(
                f"declare {name} sprites as {family}-*.png"
                for name, family in families.items()
                if declared_buttons.get(name) != expected_buttons[name]
            ) + sorted(
                f"remove unknown button {name}"
                for name in declared_buttons.keys() - families.keys()
            )
            raise RuntimeError(f"{face['id']}: {'; '.join(wrong)}")
        plate_width = FACE_PLATE_WIDTH.get(face["id"])
        if plate_width is not None and plate_width > face["drag"][2]:
            # A plate wider than the drag region would look like a title bar
            # that does not move the window.
            raise RuntimeError(
                f"{face['id']}: plate width {plate_width} exceeds drag width {face['drag'][2]}"
            )
        background = render_background(face)
        bad = _translucent_regions(face, background)
        if bad:
            raise RuntimeError(f"{face['id']}: transparent control regions: {bad}")
        if _encode_png(background) != _encode_png(render_background(face)):
            raise RuntimeError(f"{face['id']}: nondeterministic export")
        _save(background, manifest.with_name("background.png"))
        # A group family renders at its representative; an own family is the button.
        sources = {}
        for name, family in families.items():
            group = BUTTON_GROUPS[name]
            sources.setdefault(
                family, _group_representative(face, group) if family == group else name,
            )
        for family, control in sorted(sources.items()):
            for state in BUTTON_STATES:
                image = render_button(face, BUTTON_GROUPS[control], state, control)
                _save(image, manifest.with_name(f"{family}-{state}.png"))
        # Drop surfaces a previous layout declared, so packs ship only used
        # files. Never touch files this exporter cannot have written.
        declared = {file for states in expected_buttons.values() for file in states.values()}
        for stale in sorted(EXPORTED_SPRITES - declared):
            path = manifest.with_name(stale)
            if path.exists():
                path.unlink()
                print(f"{face['id']}: removed stale sprite {stale}")
        print(
            f"{face['id']}: {background.width()}x{background.height()}, all control regions opaque"
        )
    app.quit()


if __name__ == "__main__":
    main()
