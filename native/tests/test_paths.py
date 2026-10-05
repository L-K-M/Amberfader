"""Platform folders and the one-time macOS move from the old XDG folders."""
import shutil
from pathlib import Path

from amberfader import paths
from amberfader.paths import app_dirs, migrate_legacy_files


def test_linux_follows_xdg_and_ignores_relative_values(tmp_path):
    home = tmp_path / "home"
    env = {"XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CONFIG_HOME": "relative"}
    dirs = app_dirs("linux", env, home)
    assert dirs.data == tmp_path / "data" / "amberfader"
    assert dirs.config == home / ".config" / "amberfader"
    assert dirs.cache == home / ".cache" / "amberfader"
    assert dirs.state == home / ".local" / "state" / "amberfader"


def test_macos_uses_the_library_folders(tmp_path):
    dirs = app_dirs("darwin", {"XDG_DATA_HOME": str(tmp_path / "ignored")}, tmp_path)
    support = tmp_path / "Library" / "Application Support" / "Amberfader"
    assert (dirs.data, dirs.config, dirs.state) == (support, support, support)
    assert dirs.cache == tmp_path / "Library" / "Caches" / "Amberfader"


def _legacy(home: Path) -> None:
    (home / ".local/share/amberfader/faces/mine").mkdir(parents=True)
    (home / ".local/share/amberfader/faces/mine/face.json").write_text("{}")
    (home / ".local/share/amberfader/webengine").mkdir(parents=True)
    (home / ".local/share/amberfader/webengine/Cookies").write_text("cookies")
    (home / ".config/amberfader").mkdir(parents=True)
    (home / ".config/amberfader/appearance.json").write_text('{"face": "mine"}')
    (home / ".local/state/amberfader").mkdir(parents=True)
    (home / ".local/state/amberfader/embedded-search-history.json").write_text("{}")
    (home / ".cache/amberfader/webengine").mkdir(parents=True)


def test_macos_moves_faces_sign_in_appearance_and_history_once(tmp_path):
    _legacy(tmp_path)
    support = tmp_path / "Library" / "Application Support" / "Amberfader"

    assert migrate_legacy_files("darwin", {}, tmp_path) == []

    assert (support / "faces/mine/face.json").read_text() == "{}"
    assert (support / "webengine/Cookies").read_text() == "cookies"
    assert (support / "appearance.json").read_text() == '{"face": "mine"}'
    assert (support / "embedded-search-history.json").exists()
    assert not (tmp_path / ".local/share/amberfader/faces").exists()
    # The cache rebuilds itself and stays where it was.
    assert (tmp_path / ".cache/amberfader/webengine").is_dir()
    assert not (tmp_path / "Library/Caches/Amberfader").exists()
    # A second start finds nothing left to move.
    assert migrate_legacy_files("darwin", {}, tmp_path) == []


def test_macos_never_overwrites_newer_files(tmp_path):
    _legacy(tmp_path)
    support = tmp_path / "Library" / "Application Support" / "Amberfader"
    support.mkdir(parents=True)
    (support / "appearance.json").write_text('{"face": "newer"}')

    assert migrate_legacy_files("darwin", {}, tmp_path) == []

    assert (support / "appearance.json").read_text() == '{"face": "newer"}'
    assert (tmp_path / ".config/amberfader/appearance.json").exists()
    # Everything else still moved.
    assert (support / "faces/mine").is_dir()


def test_macos_reads_old_folders_from_xdg_variables(tmp_path):
    custom = tmp_path / "custom-data" / "amberfader" / "faces"
    custom.mkdir(parents=True)
    env = {"XDG_DATA_HOME": str(tmp_path / "custom-data")}

    assert migrate_legacy_files("darwin", env, tmp_path) == []
    assert (tmp_path / "Library/Application Support/Amberfader/faces").is_dir()


def test_failed_move_is_reported_and_the_rest_continue(tmp_path, monkeypatch):
    _legacy(tmp_path)
    real_move = shutil.move

    def flaky(source, target):
        if source.endswith("webengine"):
            raise PermissionError(13, "Permission denied")
        return real_move(source, target)

    monkeypatch.setattr(paths.shutil, "move", flaky)
    problems = migrate_legacy_files("darwin", {}, tmp_path)

    assert len(problems) == 1 and "webengine" in problems[0] and "Permission denied" in problems[0]
    assert (tmp_path / ".local/share/amberfader/webengine/Cookies").exists()
    assert (tmp_path / "Library/Application Support/Amberfader/faces/mine").is_dir()


def test_linux_never_moves_anything(tmp_path):
    _legacy(tmp_path)
    assert migrate_legacy_files("linux", {}, tmp_path) == []
    assert (tmp_path / ".local/share/amberfader/faces/mine").is_dir()
    assert not (tmp_path / "Library").exists()
