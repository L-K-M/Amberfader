"""Socket security invariants: $XDG_RUNTIME_DIR required, dir mode 0700,
owner-only socket permissions, no /tmp fallback, stale sockets removed only
when provably dead."""
import os
import socket
import stat

import pytest

from amberfader.transport.paths import path_has_live_owner, runtime_socket_dir


@pytest.fixture()
def qtlocal(qapp):
    """The Qt-backed server, skipped when Qt cannot load in this environment."""
    return pytest.importorskip(
        "amberfader.transport.local",
        reason="GUI extra not installed or Qt shared libraries unavailable",
        exc_type=ImportError,
    )


@pytest.fixture()
def xdg(tmp_path, monkeypatch):
    d = tmp_path / "rt"
    d.mkdir(mode=0o700)
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(d))
    return d


def test_missing_runtime_dir_rejected(monkeypatch):
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    with pytest.raises(RuntimeError):
        runtime_socket_dir()


def test_nonexistent_runtime_dir_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "does-not-exist"))
    with pytest.raises(RuntimeError):
        runtime_socket_dir()


def test_dir_created_0700_and_permissions(xdg, qapp, qtlocal):
    path = os.path.join(runtime_socket_dir(), "control.sock")
    assert stat.S_IMODE(os.stat(os.path.dirname(path)).st_mode) == 0o700

    srv = qtlocal.LocalServer(path)
    assert srv.listen()
    try:
        # The socket itself must not be reachable by group/other.
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode & 0o077 == 0
        assert os.path.basename(path) == "control.sock"
    finally:
        srv.close()


def test_stale_socket_removed_live_socket_not(xdg, qapp, qtlocal):
    appdir = xdg / "amberfader"
    appdir.mkdir(mode=0o700)
    path = str(appdir / "control.sock")

    # Dead socket file (nothing listening) -> removed by a new server.
    open(path, "w").close()
    srv = qtlocal.LocalServer(path)
    assert srv.listen()
    srv.close()

    # Live listener -> a new server must refuse, not steal the path.
    live = socket.socket(socket.AF_UNIX)
    live.bind(path)
    live.listen(1)
    try:
        assert path_has_live_owner(path)
        thief = qtlocal.LocalServer(path)
        assert not thief.listen()
        assert os.path.exists(path)  # the owner's file was not unlinked
    finally:
        live.close()


def test_no_world_accessible_fallback(monkeypatch, tmp_path):
    # Even with a writable /tmp and missing runtime dir: refuse, never fall back.
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    with pytest.raises(RuntimeError):
        runtime_socket_dir()
    assert not list(tmp_path.iterdir()), "must not create files outside runtime dir"
