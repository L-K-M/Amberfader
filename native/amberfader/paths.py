"""Where Amberfader keeps its files on each platform.

Linux follows the XDG base directories (unchanged since the first release).
macOS uses the standard Library folders: data, settings and state in
~/Library/Application Support/Amberfader, the HTTP cache in
~/Library/Caches/Amberfader.

Before macOS had its own folders, the face editor and the embedded browser
also used the XDG fallbacks there (~/.local/share/amberfader and friends).
migrate_legacy_files() moves those once, so faces, appearance, recent
searches and the Google sign-in carry over. It never overwrites anything.

Qt-free on purpose: the launcher calls it before Qt starts, and tests run it
without Qt.
"""
from __future__ import annotations

import logging
import os
import shutil
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

APP_FOLDER = "amberfader"
MACOS_APP_FOLDER = "Amberfader"
_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppDirs:
    data: Path    # faces, browser profile
    config: Path  # appearance and settings
    cache: Path   # HTTP cache
    state: Path   # recent searches


def _xdg(env: Mapping[str, str], home: Path, variable: str, fallback: str) -> Path:
    configured = env.get(variable, "")
    base = Path(configured) if configured and Path(configured).is_absolute() else home / fallback
    return base / APP_FOLDER


def xdg_dirs(env: Mapping[str, str], home: Path) -> AppDirs:
    return AppDirs(
        data=_xdg(env, home, "XDG_DATA_HOME", ".local/share"),
        config=_xdg(env, home, "XDG_CONFIG_HOME", ".config"),
        cache=_xdg(env, home, "XDG_CACHE_HOME", ".cache"),
        state=_xdg(env, home, "XDG_STATE_HOME", ".local/state"),
    )


def app_dirs(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> AppDirs:
    platform = platform or sys.platform
    env = os.environ if env is None else env
    home = home or Path.home()
    if platform != "darwin":
        return xdg_dirs(env, home)
    support = home / "Library" / "Application Support" / MACOS_APP_FOLDER
    return AppDirs(
        data=support, config=support, state=support,
        cache=home / "Library" / "Caches" / MACOS_APP_FOLDER,
    )


# (folder kind, relative path) pairs that moved on macOS. The HTTP cache is
# left behind: it rebuilds itself.
_MOVED = (
    ("data", "faces"),
    ("data", "webengine"),
    ("config", "appearance.json"),
    ("config", "settings.json"),
    ("state", "embedded-search-history.json"),
)


def migrate_legacy_files(
    platform: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> list[str]:
    """Move macOS files from the old XDG-style folders to the Library
    folders. Each item moves only when it exists at the old place and not at
    the new one. Returns problems for the caller to report; never raises."""
    platform = platform or sys.platform
    if platform != "darwin":
        return []
    env = os.environ if env is None else env
    home = home or Path.home()
    old, new = xdg_dirs(env, home), app_dirs(platform, env, home)

    problems = []
    for kind, name in _MOVED:
        source = getattr(old, kind) / name
        target = getattr(new, kind) / name
        if not source.exists() or target.exists() or target.is_symlink():
            continue
        try:
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        except OSError as exc:
            problem = f"could not move {source} to {target}: {exc.strerror or exc}"
            _LOG.warning("%s", problem)
            problems.append(problem)
    return problems
