"""Helper relay: framed JSON moves between a fake 'browser' (pipe pair) and a
fake 'GUI' (unix socket) in both directions; requests get disconnected errors
while the socket is down; state events coalesce under pressure."""
import contextlib
import json
import os
import selectors
import socket
import struct
import threading
import time

import pytest

from amberfader.helper import BoundedBus, Helper
from amberfader.protocol import FrameFeed, encode_frame

HELLO_FROM_BROWSER = {
    "protocolVersion": 1,
    "kind": "hello",
    "component": "controller",
    "componentVersion": "0.1.0",
}


def _read_frame(fd, timeout=5.0):
    """Read one framed message off a raw fd."""
    sel = selectors.DefaultSelector()
    sel.register(fd, selectors.EVENT_READ)
    try:
        deadline = time.time() + timeout
        buf = b""
        while len(buf) < 4:
            if not sel.select(max(0.01, deadline - time.time())):
                raise TimeoutError("no frame header")
            chunk = os.read(fd, 4 - len(buf))
            if not chunk:
                raise EOFError("pipe closed")
            buf += chunk
        (length,) = struct.unpack("=I", buf)
        body = b""
        while len(body) < length:
            if not sel.select(max(0.01, deadline - time.time())):
                raise TimeoutError("no frame body")
            chunk = os.read(fd, length - len(body))
            if not chunk:
                raise EOFError("pipe closed mid-body")
            body += chunk
        return json.loads(body.decode("utf-8"))
    finally:
        sel.close()


@pytest.fixture()
def helper_pipes(tmp_path):
    """Run Helper with pipe-backed streams injected — no sys.stdin/stdout
    swapping, which pytest's per-phase capture would clobber."""
    sock_path = str(tmp_path / "control.sock")
    in_r, in_w = os.pipe()      # we write -> helper stdin
    out_r, out_w = os.pipe()    # helper stdout -> we read

    stdin_obj = os.fdopen(in_r, "rb", buffering=0)
    stdout_obj = os.fdopen(out_w, "wb", buffering=0)
    helper = Helper(sock_path, stdin=stdin_obj, stdout=stdout_obj)
    t = threading.Thread(target=helper.run, daemon=True)
    t.start()
    try:
        yield sock_path, in_w, out_r, helper, t
    finally:
        helper.stop_event.set()
        for obj in (stdin_obj, stdout_obj):
            with contextlib.suppress(OSError):
                obj.close()
        for fd in (in_w, out_r):
            with contextlib.suppress(OSError):
                os.close(fd)
        t.join(timeout=3)


def test_requests_get_disconnected_error_without_gui(helper_pipes):
    _sock_path, browser_in, browser_out, _helper, _t = helper_pipes
    req = {
        "protocolVersion": 1,
        "kind": "request",
        "id": "r1",
        "sessionId": "s",
        "bindingToken": "b",
        "method": "player.play",
        "params": {},
    }
    os.write(browser_in, encode_frame(req))
    resp = _read_frame(browser_out)
    assert resp["kind"] == "response"
    assert resp["id"] == "r1"
    assert resp["ok"] is False
    assert resp["error"]["code"] == "disconnected"


def test_gui_roundtrip_and_connection_events(helper_pipes):
    sock_path, browser_in, browser_out, _helper, _t = helper_pipes

    # Browser says hello -> helper answers with its own hello.
    os.write(browser_in, encode_frame(HELLO_FROM_BROWSER))
    reply = _read_frame(browser_out)
    assert reply["kind"] == "hello"
    assert reply["component"] == "helper"

    # GUI server accepts the helper connection -> gui-connected event.
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    server.settimeout(10)
    conn, _ = server.accept()
    conn.settimeout(5)

    event = _read_frame(browser_out)
    assert event["kind"] == "event" and event["event"] == "connection"
    assert event["data"]["component"] == "gui"
    assert event["data"]["status"] == "connected"

    # GUI -> browser: a state event crosses the socket onto stdout.
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
    msg = _read_frame(browser_out)
    assert msg["kind"] == "event" and msg["event"] == "state"

    # browser -> GUI: a request crosses stdout->socket. The helper also sent
    # its own hello to the GUI first, so scan frames until the request shows.
    req = {
        "protocolVersion": 1,
        "kind": "request",
        "id": "r9",
        "sessionId": "s",
        "bindingToken": "b",
        "method": "player.next",
        "params": {},
    }
    os.write(browser_in, encode_frame(req))
    feed = FrameFeed()
    deadline = time.time() + 5
    seen = []
    while time.time() < deadline and not any(m.get("id") == "r9" for m in seen):
        data = conn.recv(65536)
        if not data:
            break
        seen.extend(feed.feed(data))
    assert any(m.get("id") == "r9" for m in seen)

    conn.close()
    server.close()


def test_bounded_bus_coalesces_state_events():
    bus = BoundedBus(bound=4)
    for i in range(10):
        bus.put({"kind": "event", "event": "state", "data": {"revision": i}})
    # Only the newest state event survives — coalescing, not a backlog.
    items = []
    while True:
        m = bus.get(timeout=0)
        if m is None:
            break
        items.append(m)
    assert len(items) == 1
    assert items[0]["data"]["revision"] == 9


def test_bounded_bus_never_drops_responses():
    bus = BoundedBus(bound=3)
    accepted = [
        bus.put({"kind": "response", "id": f"r{i}", "ok": True, "result": {}})
        for i in range(10)
    ]
    seen = []
    while True:
        m = bus.get(timeout=0)
        if m is None:
            break
        seen.append(m["id"])
    # Responses are never coalesced or reordered; the bound is the only limit.
    assert seen == [f"r{i}" for i, ok in enumerate(accepted) if ok]
    assert len(seen) <= 3
