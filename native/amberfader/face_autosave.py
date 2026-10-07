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

from .face_document import FaceDocument
from .face_library import FaceError, _read_bounded
from .paths import app_dirs

AUTOSAVE_FOLDER = "editor-autosave"
INFO_FILE = "autosave.json"
INFO_VERSION = 1
MAX_INFO_BYTES = 16 * 1024
TOKEN_CHARACTERS = frozenset("0123456789abcdef")
# A rewrite builds <token>~new, moves <token> aside to <token>~old, then
# renames ~new into place. Whatever an interruption leaves behind, one
# complete snapshot remains: <token>, else ~new (complete once its info file
# exists), else ~old.
NEW_SUFFIX = "~new"
OLD_SUFFIX = "~old"
SUFFIXES = ("", NEW_SUFFIX, OLD_SUFFIX)


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
        target = self._root / token
        fresh = self._root / f"{token}{NEW_SUFFIX}"
        old = self._root / f"{token}{OLD_SUFFIX}"
        try:
            self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
            shutil.rmtree(fresh, ignore_errors=True)
            document.write_recovery(fresh)
            info = {
                "version": INFO_VERSION,
                "source": str(document.path) if document.path is not None else None,
                "saved": document.saved_fingerprint,
            }
            # Written last: a snapshot without it is incomplete.
            (fresh / INFO_FILE).write_text(json.dumps(info), encoding="utf-8")
            if target.exists():
                shutil.rmtree(old, ignore_errors=True)
                target.replace(old)
            fresh.replace(target)
            shutil.rmtree(old, ignore_errors=True)
        except OSError as exc:
            raise FaceError(f"Cannot write autosave: {exc}") from exc

    def remove(self, token: str) -> None:
        if _valid_token(token):
            for suffix in SUFFIXES:
                shutil.rmtree(self._root / f"{token}{suffix}", ignore_errors=True)

    def recover(self) -> tuple[list[RecoveredFace], list[str]]:
        """Documents left by an unexpected exit, and problems with the rest.

        Unreadable snapshots stay on disk so nothing is deleted silently.
        """
        try:
            entries = sorted(self._root.iterdir()) if self._root.is_dir() else []
        except OSError as exc:
            return [], [f"Cannot read autosaves: {exc}"]
        tokens = []
        for entry in entries:
            token = entry.name.split("~", 1)[0]
            if (
                entry.is_dir() and not entry.is_symlink() and _valid_token(token)
                and entry.name in {f"{token}{suffix}" for suffix in SUFFIXES}
                and token not in tokens
            ):
                tokens.append(token)
        faces: list[RecoveredFace] = []
        problems: list[str] = []
        for token in tokens:
            candidates = [
                self._root / f"{token}{suffix}" for suffix in SUFFIXES
                if (self._root / f"{token}{suffix}" / INFO_FILE).is_file()
            ]
            failure = None
            for candidate in candidates:
                try:
                    faces.append(RecoveredFace(token, self._read(candidate)))
                    break
                except (FaceError, OSError, ValueError, RecursionError) as exc:
                    failure = failure or exc
            else:
                if failure is not None:
                    problems.append(f"{token}: {failure}")
        return faces, problems

    @staticmethod
    def _read(snapshot: Path) -> FaceDocument:
        info = json.loads(_read_bounded(snapshot / INFO_FILE, MAX_INFO_BYTES))
        if not isinstance(info, dict) or info.get("version") != INFO_VERSION:
            raise FaceError("Unsupported autosave")
        source = info.get("source")
        saved = info.get("saved")
        return FaceDocument.recover(
            snapshot,
            source=Path(source) if isinstance(source, str) else None,
            fingerprint=saved if isinstance(saved, str) else None,
        )
