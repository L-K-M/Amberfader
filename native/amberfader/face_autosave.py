"""Crash recovery for unsaved faces, kept apart from every face folder.

    <state folder>/editor-autosave/
        .session-<id>.lock  held by each running editor while it lives
        <window token>/
            autosave.json   {"version": 2, "session": id, "source": folder or null,
                             "saved": fingerprint or null}
            face.json       the working manifest, possibly an unfinished draft
            *.png           its declared images

The editor writes a snapshot shortly after an unsaved change and removes it
when the face is saved, discarded or closed. A snapshot whose session lock
is no longer held means its editor ended unexpectedly. The next editor to
start claims it with one atomic rename, so two running editors never
recover, overwrite or delete each other's work, and reopens it as an unsaved
document. Recovery never writes into a face folder.

Qt-free: the editor's application object schedules the writes.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO
from uuid import uuid4

from .face_document import FaceDocument
from .face_library import FaceError, _read_bounded
from .paths import app_dirs

AUTOSAVE_FOLDER = "editor-autosave"
INFO_FILE = "autosave.json"
INFO_VERSION = 2
MAX_INFO_BYTES = 16 * 1024
TOKEN_CHARACTERS = frozenset("0123456789abcdef")
# A rewrite builds <token>~new, moves <token> aside to <token>~old, then
# renames ~new into place. Whatever an interruption leaves behind, one
# complete snapshot remains: <token>, else ~new (complete once its info file
# exists), else ~old.
NEW_SUFFIX = "~new"
OLD_SUFFIX = "~old"
SUFFIXES = ("", NEW_SUFFIX, OLD_SUFFIX)
# A recovering editor renames a snapshot to <token>~claim-<its session>.
# If it crashes before finishing, the claim is recovered like any snapshot.
CLAIM_PREFIX = "~claim-"
LOCK_PREFIX = ".session-"
TOKEN_LOCK_PREFIX = ".token-"
SESSION_LOCK_ATTEMPTS = 5
SESSION_LOCK_RETRY_SECONDS = 0.01
LOCK_SUFFIX = ".lock"


@dataclass(frozen=True)
class RecoveredFace:
    token: str
    document: FaceDocument


def _valid_token(token: str) -> bool:
    return 0 < len(token) <= 64 and set(token) <= TOKEN_CHARACTERS


def _session_alive(lock_path: Path) -> bool:
    """Whether a running editor still holds this session lock."""
    try:
        with lock_path.open("r") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
            fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError:
        return False
    return False


def _lock_file(path: Path) -> IO[str] | None:
    """Exclusively lock `path`, creating it; None if another process holds it.

    A sweep may unlink the file between our open and our lock. Locking an
    unlinked inode would protect nothing, so check the path still names it.
    """
    for _attempt in range(3):
        handle = path.open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            return None
        try:
            if os.stat(path).st_ino == os.fstat(handle.fileno()).st_ino:
                return handle
        except FileNotFoundError:
            pass
        handle.close()
    raise OSError(f"Cannot lock {path.name}")


class AutosaveStore:
    def __init__(self, root: Path | None = None) -> None:
        self._root = root or app_dirs().state / AUTOSAVE_FOLDER
        self._session = uuid4().hex
        self._lock: IO[str] | None = None

    @property
    def root(self) -> Path:
        return self._root

    def _lock_path(self, session: str) -> Path:
        return self._root / f"{LOCK_PREFIX}{session}{LOCK_SUFFIX}"

    def _hold_session(self) -> None:
        """Mark this editor's snapshots as live for as long as it runs."""
        if self._lock is not None:
            return
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        for _attempt in range(SESSION_LOCK_ATTEMPTS):
            handle = _lock_file(self._lock_path(self._session))
            if handle is not None:
                self._lock = handle
                return
            # Only another editor's lock sweep holds a new session briefly.
            time.sleep(SESSION_LOCK_RETRY_SECONDS)
        raise OSError("Autosave session is in use")

    def close(self) -> None:
        """Release the session at a clean exit."""
        if self._lock is None:
            return
        lock, self._lock = self._lock, None
        try:
            self._lock_path(self._session).unlink(missing_ok=True)
        finally:
            lock.close()

    def write(self, token: str, document: FaceDocument) -> None:
        """Replace the token's snapshot with the document's working state."""
        if not _valid_token(token):
            raise FaceError("Invalid autosave token")
        target = self._root / token
        fresh = self._root / f"{token}{NEW_SUFFIX}"
        old = self._root / f"{token}{OLD_SUFFIX}"
        try:
            self._hold_session()
            shutil.rmtree(fresh, ignore_errors=True)
            document.write_recovery(fresh)
            info = {
                "version": INFO_VERSION,
                "session": self._session,
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
            for claim in self._root.glob(f"{token}{CLAIM_PREFIX}*"):
                shutil.rmtree(claim, ignore_errors=True)

    def recover(self) -> tuple[list[RecoveredFace], list[str]]:
        """Claim the work of editors that ended unexpectedly.

        Snapshots of running editors are left alone. Each recovered face gets
        a new token owned by this editor. Unreadable snapshots stay on disk
        so nothing is deleted silently.
        """
        try:
            entries = sorted(self._root.iterdir()) if self._root.is_dir() else []
            if entries:
                # Claims made from here on are attributable to a live editor.
                self._hold_session()
        except OSError as exc:
            return [], [f"Cannot read autosaves: {exc}"]
        tokens = []
        for entry in entries:
            token = entry.name.split("~", 1)[0]
            known = entry.name in {f"{token}{suffix}" for suffix in SUFFIXES} or (
                entry.name.startswith(f"{token}{CLAIM_PREFIX}")
            )
            if (
                entry.is_dir() and not entry.is_symlink() and _valid_token(token) and known
                and token not in tokens
            ):
                tokens.append(token)
        faces: list[RecoveredFace] = []
        problems: list[str] = []
        for token in tokens:
            recovered = self._recover_token(token, problems)
            if recovered is not None:
                faces.append(recovered)
        self._remove_dead_locks()
        return faces, problems

    def _recover_token(self, token: str, problems: list[str]) -> RecoveredFace | None:
        # One editor at a time works on a token; the next finds it recovered.
        token_lock = self._root / f"{TOKEN_LOCK_PREFIX}{token}{LOCK_SUFFIX}"
        try:
            handle = _lock_file(token_lock)
        except OSError:
            return None
        if handle is None:
            return None
        try:
            return self._recover_locked(token, problems)
        finally:
            token_lock.unlink(missing_ok=True)
            handle.close()

    def _recover_locked(self, token: str, problems: list[str]) -> RecoveredFace | None:
        claims = sorted(self._root.glob(f"{token}{CLAIM_PREFIX}*"))
        for claim in claims:
            claimer = claim.name.removeprefix(f"{token}{CLAIM_PREFIX}")
            if self._live(claimer):
                return None  # Another running editor is recovering it.
        # A complete ~new is the newest copy, and a dead claim holds the best
        # copy its claimer found; ~old only backs up an interrupted rename.
        ordered = (
            self._root / f"{token}{NEW_SUFFIX}", *claims, self._root / token,
            self._root / f"{token}{OLD_SUFFIX}",
        )
        candidates = [path for path in ordered if (path / INFO_FILE).is_file()]
        failure: Exception | None = None
        for candidate in candidates:
            try:
                info = self._info(candidate)
                if self._live(info.get("session")):
                    return None  # A running editor's live work.
            except (FaceError, OSError, ValueError, RecursionError) as exc:
                failure = failure or exc
                continue
            claimed = self._root / f"{token}{CLAIM_PREFIX}{self._session}"
            try:
                os.rename(candidate, claimed)
            except OSError:
                return None  # Another editor claimed it first.
            try:
                document = self._read(claimed.resolve(), info)
            except (FaceError, OSError, ValueError, RecursionError) as exc:
                self._unclaim(claimed, candidate)
                failure = failure or exc
                continue
            fresh = uuid4().hex
            try:
                self.write(fresh, document)
            except FaceError as exc:
                self._unclaim(claimed, candidate)
                problems.append(f"{token}: {exc}")
                return None
            self.remove(token)
            return RecoveredFace(fresh, document)
        if failure is not None:
            problems.append(f"{token}: {failure}")
        return None

    @staticmethod
    def _unclaim(claimed: Path, candidate: Path) -> None:
        """Put a snapshot back so it stays visible to later launches."""
        # On failure it stays on disk under its claim name.
        with contextlib.suppress(OSError):
            os.rename(claimed, candidate)

    def _live(self, session: object) -> bool:
        """Whether a session belongs to a running editor, this one included."""
        if not isinstance(session, str) or not _valid_token(session):
            return False  # Not written by an editor: treat as abandoned.
        return session == self._session or _session_alive(self._lock_path(session))

    def _remove_dead_locks(self) -> None:
        """Delete lock files of ended sessions.

        Each is unlinked while we hold its lock, so an editor that is just
        taking it either finds it busy or sees the unlink and retries.
        """
        for path in self._root.glob(f"{LOCK_PREFIX}*{LOCK_SUFFIX}"):
            if path == self._lock_path(self._session):
                continue
            try:
                with path.open("r") as handle:
                    try:
                        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue  # A running editor's session.
                    if os.stat(path).st_ino == os.fstat(handle.fileno()).st_ino:
                        path.unlink()
            except OSError:
                continue

    @staticmethod
    def _info(snapshot: Path) -> dict:
        info = json.loads(_read_bounded(snapshot / INFO_FILE, MAX_INFO_BYTES))
        if not isinstance(info, dict) or info.get("version") != INFO_VERSION:
            raise FaceError("Unsupported autosave")
        return info

    @staticmethod
    def _read(snapshot: Path, info: dict) -> FaceDocument:
        source = info.get("source")
        saved = info.get("saved")
        return FaceDocument.recover(
            snapshot,
            source=Path(source) if isinstance(source, str) else None,
            fingerprint=saved if isinstance(saved, str) else None,
        )
