"""Embedded launcher: where the single-instance socket lives per platform."""
import os
import stat
import sys

import pytest

from amberfader.embedded import __main__ as launcher


@pytest.fixture()
def macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setattr(launcher.tempfile, "gettempdir", lambda: str(tmp_path))
    return tmp_path


def test_macos_uses_a_private_folder_in_the_user_temp_dir(macos):
    path = launcher.default_socket_path()

    assert path == str(macos / "amberfader" / "embedded.sock")
    assert stat.S_IMODE((macos / "amberfader").stat().st_mode) == 0o700
    # A second launch reuses the folder.
    assert launcher.default_socket_path() == path


def test_macos_tightens_an_existing_folder(macos):
    folder = macos / "amberfader"
    folder.mkdir(mode=0o755)
    folder.chmod(0o755)

    launcher.default_socket_path()

    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_macos_refuses_a_symlinked_folder(macos, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    elsewhere.chmod(0o755)
    (macos / "amberfader").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(RuntimeError, match="not a directory owned by you"):
        launcher.default_socket_path()
    # The symlink's target keeps its permissions.
    assert stat.S_IMODE(elsewhere.stat().st_mode) == 0o755


def test_macos_refuses_a_folder_owned_by_someone_else(macos, monkeypatch):
    (macos / "amberfader").mkdir(mode=0o700)
    monkeypatch.setattr(launcher.os, "getuid", lambda: os.stat(macos).st_uid + 1)

    with pytest.raises(RuntimeError, match="not a directory owned by you"):
        launcher.default_socket_path()


def test_macos_prefers_xdg_runtime_dir_when_set(macos, monkeypatch, tmp_path_factory):
    runtime = tmp_path_factory.mktemp("runtime")
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))

    assert launcher.default_socket_path() == str(runtime / "amberfader" / "embedded.sock")


def test_linux_still_requires_xdg_runtime_dir(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(RuntimeError, match="XDG_RUNTIME_DIR is not set"):
        launcher.default_socket_path()


def test_macos_refuses_a_file_in_place_of_the_folder(macos):
    (macos / "amberfader").write_text("not a folder")

    with pytest.raises(RuntimeError, match="not a directory owned by you"):
        launcher.default_socket_path()
