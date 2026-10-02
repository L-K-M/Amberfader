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

from amberfader.protocol import encode_frame, validate_message


@pytest.mark.parametrize("reply", [
    None,
    {"kind": "activate-response", "ok": False},
    {"kind": "response", "ok": True, "id": "unrelated", "result": {}},
])
def test_activation_requires_an_acknowledgement(qapp, tmp_path, reply):
    from amberfader.transport.local import try_activate_existing

    path = str(tmp_path / "control.sock")
    server = pysock.socket(pysock.AF_UNIX)
    server.bind(path)
    server.listen(1)

    # A separate process can answer while Qt blocks the caller's event loop.
    worker = subprocess.Popen([
        sys.executable, "-c", """
import socket, sys, time
server = socket.socket(fileno=int(sys.argv[1]))
with server.accept()[0] as connection:
    connection.recv(4096)
    reply = bytes.fromhex(sys.argv[2])
    if reply:
        connection.sendall(reply)
    time.sleep(1)
""", str(server.fileno()), encode_frame(reply).hex() if reply is not None else "",
    ], pass_fds=(server.fileno(),))
    try:
        assert not try_activate_existing(path, timeout_ms=500)
    finally:
        worker.wait(timeout=5)
        server.close()


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
    # Keep pumping while waiting for the ack — a plain blocking recv would
    # starve the event loop that writes the server's side of the socket.
    resp_box: list[dict] = []

    def got_response() -> bool:
        try:
            resp_box.append(_frame_from(conn, timeout=0.05))
            return True
        except (TimeoutError, OSError):
            return False

    assert pump(qapp, got_response, timeout_s=5), "no activate-response frame"
    resp = resp_box[0]
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


@pytest.mark.parametrize("source", ["event", "response"])
def test_native_snapshot_establishes_the_command_binding(app, qapp, source):
    sent = []
    app._send = lambda message: sent.append(message) or True
    state = {
        "bindingToken": "binding", "revision": 1, "track": None,
        "status": "paused", "contentKind": "unknown", "positionSeconds": 0,
        "durationSeconds": None, "playbackRate": 1, "volume": 0.8,
        "muted": False, "capabilities": ["play", "pause"],
    }
    applied = []
    app.window.apply_state = lambda value: applied.append(value)
    message = {"protocolVersion": 1, "sessionId": "session", "bindingToken": "binding"}
    if source == "response":
        app.request("state.get", {})
        message.update(kind="response", id=sent[-1]["id"], ok=True, result=state)
    else:
        message.update(kind="event", event="state", data=state)
    app._on_message(message)
    assert applied == [state]
    app.request("player.pause", {})
    assert not validate_message(sent[-1])
    assert sent[-1]["sessionId"] == "session"
    assert sent[-1]["bindingToken"] == "binding"


def test_request_ids_do_not_repeat_when_the_gui_reopens(app, qapp):
    from amberfader.app import AmberfaderApp

    messages = []
    app._send = lambda value: messages.append(value) or True
    second = AmberfaderApp(app.socket_path + "-second")
    second.window = app.window
    second._send = lambda value: messages.append(value) or True
    app.request("state.get", {})
    second.request("state.get", {})
    try:
        assert messages[0]["id"] != messages[1]["id"]
    finally:
        app._settle(messages[0]["id"], True, {})
        second._settle(messages[1]["id"], True, {})


def test_invalid_snapshot_is_reported_as_failure(app, qapp):
    sent = []
    app._send = lambda value: sent.append(value) or True
    app.request("state.get", {})
    responses = []
    app.window.route_response = lambda method, ok, payload: responses.append((method, ok, payload))
    app._on_message({
        "protocolVersion": 1, "kind": "response", "id": sent[-1]["id"],
        "ok": True, "result": {"invalid": "snapshot"},
    })
    assert responses[0][1] is False
    assert "invalid" in responses[0][2]["message"]


def test_late_response_does_not_restore_an_old_binding(app, qapp):
    sent = []
    app._send = lambda value: sent.append(value) or True
    def bind(session, token):
        app._on_message({
            "protocolVersion": 1, "kind": "event", "event": "binding",
            "sessionId": session, "bindingToken": token, "data": {"status": "bound"},
        })
    bind("old-session", "old-token")
    app.request("player.pause", {})
    request_id = sent[-1]["id"]
    bind("new-session", "new-token")
    app._on_message({
        "protocolVersion": 1, "kind": "response", "id": request_id, "ok": True,
        "sessionId": "old-session", "bindingToken": "old-token", "result": {},
    })
    app.request("player.pause", {})
    assert sent[-1]["sessionId"] == "new-session"
    assert sent[-1]["bindingToken"] == "new-token"


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
