"""Standalone face authoring tool, independent of the Firefox bridge."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .face_library import FaceError


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amberfader-face-editor",
        description="Create and edit Amberfader faces on macOS or Linux.",
    )
    parser.add_argument("face", nargs="?", type=Path, help="face folder or face.json to open")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    # Help and version work in helper-only environments without importing Qt.
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(
            f"amberfader-face-editor: install Amberfader with the gui extra ({exc})",
            file=sys.stderr,
        )
        return 2

    from .face_document import FaceDocument

    document = None
    if args.face is not None:
        directory = args.face.parent if args.face.name == "face.json" else args.face
        try:
            document = FaceDocument.open(directory)
        except FaceError as exc:
            print(f"amberfader-face-editor: {exc}", file=sys.stderr)
            return 2

    from .ui.face_editor import FaceEditorWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName("Amberfader Face Editor")
    app.setOrganizationDomain("ch.lkmc")
    try:
        window = FaceEditorWindow(document=document)
    except FaceError as exc:
        print(f"amberfader-face-editor: {exc}", file=sys.stderr)
        return 2
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
