"""Persistent app settings: the switches for the embedded browser's built-in
ad blocking and "continue playing".

Stored as JSON in the user's config folder. A missing, unreadable, corrupt
or oversized file reads as the defaults, and each invalid value falls back
on its own (intentional recovery: a broken settings file must not stop the
music). Write failures raise OSError for the caller to report.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .paths import app_dirs

MAX_FILE_BYTES = 64 * 1024
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppSettings:
    block_ads: bool = True
    continue_playing: bool = True

    def as_json(self) -> dict[str, bool]:
        return {"blockAds": self.block_ads, "continuePlaying": self.continue_playing}


def _flag(raw: dict[str, object], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    return value if isinstance(value, bool) else default


class SettingsStore:
    """`path=None` keeps settings in memory, for the scripted test page."""

    def __init__(self, path: Path | None) -> None:
        self._path = path
        self._memory = AppSettings()

    def load(self) -> AppSettings:
        if self._path is None:
            return self._memory
        try:
            if self._path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("settings file is too large")
            raw = json.loads(self._path.read_text("utf-8"))
        except FileNotFoundError:
            return AppSettings()
        except (OSError, ValueError) as exc:
            _LOG.warning("using default settings: %s", type(exc).__name__)
            return AppSettings()
        if not isinstance(raw, dict):
            return AppSettings()
        defaults = AppSettings()
        return AppSettings(
            block_ads=_flag(raw, "blockAds", defaults.block_ads),
            continue_playing=_flag(raw, "continuePlaying", defaults.continue_playing),
        )

    def save(self, settings: AppSettings) -> None:
        if self._path is None:
            self._memory = settings
            return
        directory = self._path.parent
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Write-then-rename so a crash never leaves a truncated file behind.
        fd, temp = tempfile.mkstemp(dir=directory, prefix=".settings-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(settings.as_json(), handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self._path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(temp)
            raise


def default_settings_path() -> Path:
    return app_dirs().config / "settings.json"
