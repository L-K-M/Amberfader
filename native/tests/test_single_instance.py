"""Single-instance + live socket behavior. Qt runs offscreen.

The second-instance check is exercised two ways: a stdlib-socket client that
emulates a second process (the real `try_activate_existing` blocks on the
socket peer, which deadlocks inside one process/event-loop), and a real
subprocess running `python -m amberfader.app`.
"""
import json
import os
import socket as pysock
import struct
import subprocess
import sys
import time

import pytest

# Skips cleanly when Qt's shared libraries are missing (the bare PySide6
# package imports lazily and would otherwise pass, then fail inside fixtures).
pytest.importorskip(
    "amberfader.app",
    reason="GUI extra not installed or Qt unavailable",
    exc_type=ImportError,
)

from conftest import pump

from amberfader.protocol import encode_frame


def _frame_from(conn: pysock.socket, timeout=5.0) -> dict:
    conn.settimeout(timeout)
    raw_len = b""
    while len(raw_len) < 4:
        raw_len += conn.recv(4 - len(raw_len))
    (length,) = struct.unpack("=I", raw_len)
    body = b""
    while len(body) < length:
        body += conn.recv(length - len(body))
    return json.loads(body.decode())


@pytest.fixture()
def app(qapp, tmp_path):
    from amberfader.app import AmberfaderApp

    a = AmberfaderApp(str(tmp_path / "control.sock"))
    assert a.start()
    yield a
    a.close()


def test_second_instance_handshake_activates_first(app, qapp):
    """A gui-instance hello on the socket raises the window and gets an ack."""
    activated = []
    app.window.raise_requested = lambda: activated.append(True)  # type: ignore[attr-defined]

    conn = pysock.socket(pysock.AF_UNIX)
    conn.connect(app.socket_path)
    conn.sendall(
        encode_frame(
            {
                "protocolVersion": 1,
                "kind": "hello",
                "component": "gui-instance",
                "componentVersion": "0.1.0",
            }
        )
    )
    # The server answers over the same frame channel; spin the Qt loop so the
    # pending connection + first-frame dispatch run.
    assert pump(qapp, lambda: bool(activated), timeout_s=5), (
        "first instance never raised its window"
    )
    resp = _frame_from(conn)
    assert resp["kind"] == "activate-response"
    conn.close()


def test_cli_second_instance_exits_zero(app, qapp):
    """`python -m amberfader.app` against a live socket: raise first, exit 0."""
    activated = []
    app.window.raise_requested = lambda: activated.append(True)  # type: ignore[attr-defined]

    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["AMBERFADER_SOCKET"] = app.socket_path
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in [os.path.join(os.path.dirname(__file__), ".."), *sys.path] if p
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "amberfader.app"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 15
        while proc.poll() is None and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)
        assert proc.wait(timeout=5) == 0, "second instance did not exit 0"
        assert activated, "second launch did not raise the first window"
    finally:
        if proc.poll() is None:
            proc.kill()


def test_socket_roundtrip_state(app, qapp):
    """A helper peer sends hello, then a framed state event reaches the window."""
    seen = []
    app.window.apply_state = lambda s: seen.append(s)  # type: ignore[attr-defined]

    conn = pysock.socket(pysock.AF_UNIX)
    conn.connect(app.socket_path)
    conn.sendall(
        encode_frame(
            {
                "protocolVersion": 1,
                "kind": "hello",
                "component": "helper",
                "componentVersion": "0.1.0",
            }
        )
    )
    # Identify as helper first; the app then sends state.get back over the link.
    assert pump(qapp, lambda: app.conn is not None, timeout_s=5), (
        "helper peer was never accepted"
    )
    conn.sendall(
        encode_frame(
            {
                "protocolVersion": 1,
                "kind": "event",
                "sessionId": "s",
                "bindingToken": "b",
                "event": "state",
                "data": {
                    "bindingToken": "b",
                    "revision": 1,
                    "track": None,
                    "status": "paused",
                    "contentKind": "unknown",
                    "positionSeconds": None,
                    "durationSeconds": None,
                    "playbackRate": None,
                    "volume": None,
                    "muted": None,
                    "capabilities": [],
                },
            }
        )
    )
    assert pump(qapp, lambda: bool(seen), timeout_s=5), "state event never applied"
    conn.close()


def test_foreign_first_frame_rejected(app, qapp):
    """A peer that opens with something that is not a hello is dropped."""
    conn = pysock.socket(pysock.AF_UNIX)
    conn.connect(app.socket_path)
    conn.sendall(
        encode_frame(
            {
                "protocolVersion": 1,
                "kind": "response",
                "id": "x",
                "ok": True,
                "result": {},
            }
        )
    )
    conn.sendall(
        encode_frame(
            {
                "protocolVersion": 1,
                "kind": "event",
                "sessionId": "s",
                "bindingToken": "b",
                "event": "state",
                "data": {
                    "bindingToken": "b", "revision": 1, "track": None,
                    "status": "paused", "contentKind": "unknown",
                    "positionSeconds": None, "durationSeconds": None,
                    "playbackRate": None, "volume": None, "muted": None,
                    "capabilities": [],
                },
            }
        )
    )
    # Invalid peer: never promoted to helper, and the server closes it.
    conn.setblocking(False)

    def peer_closed():
        try:
            return conn.recv(1) == b""
        except BlockingIOError:
            return False
        except OSError:
            return True

    assert pump(qapp, peer_closed, timeout_s=3), "invalid peer was not disconnected"
    assert app.conn is None
    conn.close()
