"""Crash recovery for unsaved faces, kept apart from every face folder.

    <state folder>/editor-autosave/<window token>/
        autosave.json   {"version": 1, "source": folder or null, "saved": fingerprint or null}
        face.json       the working manifest, possibly an unfinished draft
        *.png           its declared images

The editor writes a snapshot shortly after an unsaved change and removes it
when the face is saved, discarded or closed. A snapshot still present at
launch means the editor ended unexpectedly, so it reopens as an unsaved
document. Recovery never writes into a face folder.

Qt-free: the editor's application object schedules the writes.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from .face_document import FaceDocument
from .face_library import FaceError, _read_bounded
from .paths import app_dirs

AUTOSAVE_FOLDER = "editor-autosave"
INFO_FILE = "autosave.json"
INFO_VERSION = 1
MAX_INFO_BYTES = 16 * 1024
TOKEN_CHARACTERS = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class RecoveredFace:
    token: str
    document: FaceDocument


def _valid_token(token: str) -> bool:
    return 0 < len(token) <= 64 and set(token) <= TOKEN_CHARACTERS


class AutosaveStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or app_dirs().state / AUTOSAVE_FOLDER

    @property
    def root(self) -> Path:
        return self._root

    def write(self, token: str, document: FaceDocument) -> None:
        """Replace the token's snapshot with the document's working state."""
        if not _valid_token(token):
            raise FaceError("Invalid autosave token")
        try:
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
            staging = Path(mkdtemp(prefix=f".{token}-", dir=self._root))
            try:
                snapshot = staging / "face"
                document.write_recovery(snapshot)
                info = {
                    "version": INFO_VERSION,
                    "source": str(document.path) if document.path is not None else None,
                    "saved": document.saved_fingerprint,
                }
                (snapshot / INFO_FILE).write_text(json.dumps(info), encoding="utf-8")
                target = self._root / token
                if target.exists():
                    target.replace(staging / "previous")
                snapshot.replace(target)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        except OSError as exc:
            raise FaceError(f"Cannot write autosave: {exc}") from exc

    def remove(self, token: str) -> None:
        if _valid_token(token):
            shutil.rmtree(self._root / token, ignore_errors=True)

    def recover(self) -> tuple[list[RecoveredFace], list[str]]:
        """Documents left by an unexpected exit, and problems with the rest.

        Unreadable snapshots stay on disk so nothing is deleted silently.
        """
        faces: list[RecoveredFace] = []
        problems: list[str] = []
        try:
            entries = sorted(self._root.iterdir()) if self._root.is_dir() else []
        except OSError as exc:
            return [], [f"Cannot read autosaves: {exc}"]
        for entry in entries:
            if entry.name.startswith(".") or not entry.is_dir() or entry.is_symlink():
                if entry.name.startswith("."):
                    shutil.rmtree(entry, ignore_errors=True)  # An interrupted write.
                continue
            if not _valid_token(entry.name):
                continue
            try:
                info = json.loads(_read_bounded(entry / INFO_FILE, MAX_INFO_BYTES))
                if not isinstance(info, dict) or info.get("version") != INFO_VERSION:
                    raise FaceError("Unsupported autosave")
                source = info.get("source")
                saved = info.get("saved")
                document = FaceDocument.recover(
                    entry,
                    source=Path(source) if isinstance(source, str) else None,
                    fingerprint=saved if isinstance(saved, str) else None,
                )
            except (FaceError, OSError, ValueError, RecursionError) as exc:
                problems.append(f"{entry.name}: {exc}")
                continue
            faces.append(RecoveredFace(entry.name, document))
        return faces, problems
