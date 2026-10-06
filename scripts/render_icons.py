"""Renders the Linux app icons from media-sources/icon.png.

  uv run python scripts/render_icons.py

writes packaging/icons/hicolor/<n>x<n>/apps/ch.lkmc.amberfader.png for each
size below. Commit the output: the deb installs it, and the Flatpak build
exports it, because the file is named after the app ID. The macOS build
renders its own .icns from the same source (scripts/build-macos.sh).
native/tests/test_icons.py fails when the committed files drift from the
source.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "media-sources" / "icon.png"
HICOLOR = ROOT / "packaging" / "icons" / "hicolor"
ICON_NAME = "ch.lkmc.amberfader"
SIZES = (128, 256, 512)


def icon_path(size: int) -> Path:
    return HICOLOR / f"{size}x{size}" / "apps" / f"{ICON_NAME}.png"


def render(size: int) -> QImage:
    source = QImage(str(SOURCE))
    if source.isNull():
        raise FileNotFoundError(f"cannot read {SOURCE}")
    # The source has no transparency; RGB keeps the PNGs small.
    return source.convertToFormat(QImage.Format.Format_RGB888).scaled(
        size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


def main() -> None:
    for size in SIZES:
        path = icon_path(size)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not render(size).save(str(path), "PNG"):
            raise OSError(f"cannot write {path}")
        print(f"-- {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
