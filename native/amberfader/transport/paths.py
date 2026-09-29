"""Qt-free socket path helpers — usable by the helper and tests without
pulling Qt shared libraries."""
from __future__ import annotations

import os
import socket

from .. import NATIVE_HOST_NAME


def runtime_socket_dir() -> str:
    """$XDG_RUNTIME_DIR/amberfader, created mode 0700. Fails clearly when the
    runtime dir is missing — we never fall back to a world-visible /tmp path."""
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime:
        raise RuntimeError(
            "XDG_RUNTIME_DIR is not set; cannot create the private control socket"
        )
    if not os.path.isdir(runtime):
        raise RuntimeError(
            f"XDG_RUNTIME_DIR points at a non-existent directory: {runtime}"
        )
    path = os.path.join(runtime, NATIVE_HOST_NAME)
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def path_has_live_owner(path: str, timeout: float = 1.0) -> bool:
    """True when a process accepts connections on the unix socket at `path`.
    A connectable socket has a live owner whether or not it speaks our
    protocol — either way its file must not be unlinked."""
    try:
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(timeout)
        probe.connect(path)
        probe.close()
        return True
    except OSError:
        return False


def default_socket_path() -> str:
    return os.path.join(runtime_socket_dir(), "control.sock")
