"""Recent searches and played artists for the embedded host.

Mirrors the extension's SearchHistoryService rules: control characters
become spaces, items are trimmed to 500 characters, duplicates are dropped
case-insensitively, and each list keeps the 20 most recent entries.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from ..paths import app_dirs

RECENT_ITEMS_CAP = 20
MAX_ITEM_LENGTH = 500
MAX_FILE_BYTES = 256 * 1024


@dataclass(frozen=True)
class SearchHistory:
    queries: tuple[str, ...] = ()
    artists: tuple[str, ...] = ()

    def as_result(self) -> dict[str, list[str]]:
        return {"queries": list(self.queries), "artists": list(self.artists)}


def normalized_items(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()

    seen: set[str] = set()
    items: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            continue

        cleaned = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in raw)
        item = cleaned.strip()[:MAX_ITEM_LENGTH]
        key = item.lower()
        if not item or key in seen:
            continue

        seen.add(key)
        items.append(item)
        if len(items) == RECENT_ITEMS_CAP:
            break
    return tuple(items)


class SearchHistoryStore:
    """JSON file store. Read and write failures raise OSError for the caller
    to report. A corrupt or oversized file reads as empty history and is
    replaced on the next change (intentional recovery: history is
    convenience data, never worth blocking search over)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self) -> SearchHistory:
        try:
            if self._path.stat().st_size > MAX_FILE_BYTES:
                return SearchHistory()
            raw = json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return SearchHistory()
        except (UnicodeDecodeError, json.JSONDecodeError):
            return SearchHistory()

        if not isinstance(raw, dict):
            return SearchHistory()
        return SearchHistory(
            normalized_items(raw.get("queries")), normalized_items(raw.get("artists")),
        )

    def record_query(self, query: str) -> SearchHistory:
        current = self.get()
        queries = normalized_items([query, *current.queries])
        return self._save(SearchHistory(queries, current.artists))

    def record_artists(self, artists: list[str]) -> SearchHistory:
        current = self.get()
        recent = normalized_items([*artists, *current.artists])
        return self._save(SearchHistory(current.queries, recent))

    def clear(self) -> SearchHistory:
        return self._save(SearchHistory())

    def _save(self, history: SearchHistory) -> SearchHistory:
        directory = self._path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Write-then-rename so a crash never leaves a truncated file behind.
        fd, temp = tempfile.mkstemp(dir=directory, prefix=".search-history-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(history.as_result(), handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp)
            raise
        return history


def default_history_path() -> Path:
    return app_dirs().state / "embedded-search-history.json"
