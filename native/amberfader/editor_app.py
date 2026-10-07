"""Standalone face authoring tool, independent of YouTube Music."""
from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__
from .face_library import FaceError

APP_NAME = "Amberfader Face Editor"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="amberfader-face-editor",
        description="Create and edit Amberfader faces on macOS or Linux.",
    )
    parser.add_argument(
        "faces", nargs="*", type=Path, metavar="face",
        help="face folder or face.json to open",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    args = parser.parse_args(argv)

    # Help and version work without importing Qt.
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        print(
            f"amberfader-face-editor: PySide6 is missing; reinstall Amberfader ({exc})",
            file=sys.stderr,
        )
        return 2

    from .paths import migrate_legacy_files

    for problem in migrate_legacy_files():
        print(f"amberfader-face-editor: {problem}", file=sys.stderr)

    from .face_document import FaceDocument

    documents = []
    for face in args.faces:
        directory = face.parent if face.name == "face.json" else face
        try:
            documents.append(FaceDocument.open(directory))
        except FaceError as exc:
            print(f"amberfader-face-editor: {exc}", file=sys.stderr)
            return 2

    from .ui.editor_application import FaceEditorApplication

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setOrganizationDomain("ch.lkmc")
    try:
        editor = FaceEditorApplication(app)
        editor.start(documents)
    except FaceError as exc:
        print(f"amberfader-face-editor: {exc}", file=sys.stderr)
        return 2
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
