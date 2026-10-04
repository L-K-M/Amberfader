"""Compose generated materials and precise host-control surfaces into Face packs.

The OpenAI-generated originals and exact prompts live in artwork/generated and
face-prompts.json. This offline exporter resamples those materials, applies the
window silhouettes, and paints clean readout wells and button state surfaces.
Text and transport symbols remain host-owned. No generation or network call is
needed to rebuild the shipped 2x PNGs.

Run: QT_QPA_PLATFORM=offscreen uv run python artwork/render_faces.py
Repeat --face ID to re-export only those packs.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)

SCALE = 2
MIN_ALPHA = 128
MAX_DIMENSION = 2048
MAX_FILE_BYTES = 4 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
FACES_ROOT = ROOT.parent / "native" / "amberfader" / "faces"
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


def _render_sculptural_background(face: dict, source: QImage) -> QImage:
    """Keep the generated object's alpha contour and its open interior spaces."""
    width, height = face["size"]
    image, painter = _canvas(width, height)
    painter.drawImage(QRectF(0, 0, width, height), source)
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
    _well(painter, _surround(controls["status"], 5), palette["panel"], palette["border"], radius)

    painter.end()
    return image


def _render_utilitarian_background(face: dict, source: QImage) -> QImage:
    """Use one display well so compact instruments keep a coherent readout."""
    width, height = face["size"]
    if source.width() * height != source.height() * width:
        raise RuntimeError(f"{face['id']}: generated material does not match the canvas aspect")
    image, painter = _canvas(width, height)
    painter.drawImage(QRectF(0, 0, width, height), source)
    palette = face["palette"]
    controls = face["controls"]
    readout = QRectF()
    for name in sorted(READOUT_CONTROLS):
        readout = readout.united(QRectF(*controls[name]))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
    _well(
        painter, readout.adjusted(-6, -6, 6, 6), palette["display"], palette["border"], 14,
    )
    painter.end()
    return image


def _render_lens_background(face: dict, source: QImage) -> QImage:
    """Keep the oval/circular glass intact, with host text directly on the lens."""
    width, height = face["size"]
    if source.width() * height != source.height() * width:
        raise RuntimeError(f"{face['id']}: generated material does not match the canvas aspect")
    image, painter = _canvas(width, height)
    painter.drawImage(QRectF(0, 0, width, height), source)
    painter.end()
    return image


def render_background(face: dict) -> QImage:
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
        # source disc across both the chassis and the shaped exterior.
        painter.drawImage(QRectF(0, 0, 441, 344), source, QRectF(0, 0, 790, 1024))
        painter.drawImage(QRectF(0, 286, 613, 58), source, QRectF(0, 852, 790, 172))
        painter.save()
        pod = QPainterPath()
        pod.addEllipse(QRectF(426, 64, 212, 212))
        painter.setClipPath(pod, Qt.ClipOperation.IntersectClip)
        painter.drawImage(QRectF(426, 64, 212, 212), source, QRectF(793, 156, 674, 674))
        painter.restore()
    p = face["palette"]
    c = face["controls"]
    radius = min(face["radius"], 10)
    if face["id"] == "copper-reel":
        display = QRectF(156, 64, 276, 132)
    else:
        display = QRectF(*c["title"]).united(QRectF(*c["playback"]))
        display = display.united(QRectF(*c["time"])).adjusted(-14, -8, 14, 12)
    _well(painter, display, p["display"], p["border"], radius)
    _well(painter, _surround(c["art"], 5), p["display"], p["border"], radius)
    _well(painter, _surround(c["seek"], 2), p["panel"], p["border"], radius)
    _well(painter, _surround(c["volume"], 4), p["panel"], p["border"], radius)
    _well(painter, _surround(c["status"], 2), p["window"], p["border"], 2)

    # Readable, static identity plate inside the safe drag region.
    drag = QRectF(*face["drag"])
    plate = QRectF(drag.x(), drag.y(), min(drag.width(), 264), drag.height())
    _well(painter, plate, p["window"], p["border"], radius)
    font = QFont("sans-serif")
    font.setPixelSize(12)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(p["text"]))
    painter.drawText(plate.adjusted(10, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, "AMBERFADER")
    font.setPixelSize(9)
    font.setBold(False)
    painter.setFont(font)
    painter.setPen(QColor(p["muted"]))
    painter.drawText(
        plate.adjusted(114, 0, -8, 0),
        Qt.AlignmentFlag.AlignVCenter,
        face["name"].upper(),
    )
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


def _sprite_family(face: dict, name: str) -> str:
    """Name the surface a button uses; Qt stretches a sprite to its control.

    Members matching their group representative's size and shape share the
    group surface. Any other member gets its own surface, so a face can give
    one button a different socket without distorting corners or rims.
    """
    group = BUTTON_GROUPS[name]
    representative = GROUP_REPRESENTATIVES[group]
    controls, shapes = face["controls"], face.get("controlShapes", {})
    same_size = controls[name][2:] == controls[representative][2:]
    same_shape = shapes.get(name) == shapes.get(representative)
    return group if same_size and same_shape else name


def render_button(face: dict, group: str, state: str, control: str | None = None) -> QImage:
    control = control or GROUP_REPRESENTATIVES[group]
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
        if face.get("buttons") != expected_buttons:
            wrong = sorted(
                f"{name} -> {family}-*.png" for name, family in families.items()
                if face.get("buttons", {}).get(name) != expected_buttons[name]
            )
            raise RuntimeError(f"{face['id']}: declare button sprites as {'; '.join(wrong)}")
        background = render_background(face)
        bad = _translucent_regions(face, background)
        if bad:
            raise RuntimeError(f"{face['id']}: transparent control regions: {bad}")
        if _encode_png(background) != _encode_png(render_background(face)):
            raise RuntimeError(f"{face['id']}: nondeterministic export")
        _save(background, manifest.with_name("background.png"))
        for family in sorted(set(families.values())):
            # A group family renders at its representative; an own family is the button.
            control = GROUP_REPRESENTATIVES.get(family, family)
            for state in BUTTON_STATES:
                image = render_button(face, BUTTON_GROUPS[control], state, control)
                _save(image, manifest.with_name(f"{family}-{state}.png"))
        # Drop surfaces a previous layout declared, so packs ship only used files.
        declared = {"background.png"} | {
            file for states in expected_buttons.values() for file in states.values()
        }
        for stale in sorted(manifest.parent.glob("*.png")):
            if stale.name not in declared:
                stale.unlink()
        print(
            f"{face['id']}: {background.width()}x{background.height()}, all control regions opaque"
        )
    app.quit()


if __name__ == "__main__":
    main()
