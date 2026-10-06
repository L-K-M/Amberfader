"""The committed hicolor icons are what scripts/render_icons.py makes from
media-sources/icon.png."""
import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("PySide6.QtGui", reason="PySide6 unavailable", exc_type=ImportError)

from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parents[2]
# Smooth scaling may round differently between Qt's SIMD code paths.
MAX_CHANNEL_DIFFERENCE = 2


def load_renderer():
    spec = importlib.util.spec_from_file_location(
        "render_icons", ROOT / "scripts" / "render_icons.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def rgb_bytes(image: QImage) -> bytes:
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    row = image.width() * 3
    return b"".join(
        bytes(image.constScanLine(y))[:row] for y in range(image.height())
    )


@pytest.mark.parametrize("size", [128, 256, 512])
def test_committed_icon_matches_the_source(size):
    renderer = load_renderer()
    assert size in renderer.SIZES
    committed = QImage(str(renderer.icon_path(size)))
    assert not committed.isNull(), f"run scripts/render_icons.py ({size} px missing)"
    assert (committed.width(), committed.height()) == (size, size)

    expected = rgb_bytes(renderer.render(size))
    actual = rgb_bytes(committed)
    worst = max(abs(a - b) for a, b in zip(expected, actual, strict=True))
    assert worst <= MAX_CHANNEL_DIFFERENCE, "icons are stale: run scripts/render_icons.py"


def test_only_rendered_icons_are_committed():
    renderer = load_renderer()
    committed = sorted(
        path.relative_to(ROOT) for path in (ROOT / "packaging" / "icons").rglob("*.png")
    )
    assert committed == sorted(
        renderer.icon_path(size).relative_to(ROOT) for size in renderer.SIZES
    )
