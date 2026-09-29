"""Amberfader native-messaging helper.

Firefox launches this process (see packaging/native-messaging manifests).
stdin/stdout carry framed JSON to/from the browser; a Unix-domain socket
carries the same framed JSON to/from the desktop GUI. The helper RELAYS:

  * validates every message against the protocol schema,
  * keeps stdout exclusively for framed messages (diagnostics on stderr),
  * never interprets page DOM, never runs shell commands, never touches
    the network,
  * keeps both directions independent with bounded queues so one blocked
    output cannot deadlock the other,
  * answers requests itself with a `disconnected` error while the GUI socket
    is down, rather than queueing an offline backlog of commands.

Environment: AMBERFADER_SOCKET overrides the default
$XDG_RUNTIME_DIR/amberfader/control.sock path.
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import os
import socket
import sys
import threading
from typing import Any, BinaryIO

from . import NATIVE_HOST_NAME, PROTOCOL_VERSION, __version__
from .protocol import (
    TRANSPORT_MAX_BYTES,
    FrameError,
    FrameFeed,
    encode_frame,
    validate_message,
)

LOG = logging.getLogger("amberfader.helper")

QUEUE_BOUND = 128
CONNECT_RETRY_MIN_S = 0.5
CONNECT_RETRY_MAX_S = 8.0

STATE_EVENT_KEY = ("event", "state")


def default_socket_path() -> str:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime:
        raise SystemExit(
            "XDG_RUNTIME_DIR is not set; cannot locate the per-user runtime "
            "directory for the control socket"
        )
    return os.path.join(runtime, NATIVE_HOST_NAME, "control.sock")


class BoundedBus:
    """Bounded message queue with state-event coalescing: a queued 'state'
    event is replaceable by a newer one; responses and other messages are
    never dropped or reordered."""

    def __init__(self, bound: int = QUEUE_BOUND) -> None:
        self._items: list[dict[str, Any]] = []
        self._cond = threading.Condition()
        self._bound = bound
        self.closed = False

    def put(self, msg: dict[str, Any]) -> bool:
        with self._cond:
            if self.closed:
                return False
            if self._is_state_event(msg):
                # Replace the most recent queued state event if present.
                for i in range(len(self._items) - 1, -1, -1):
                    if self._is_state_event(self._items[i]):
                        self._items[i] = msg
                        self._cond.notify()
                        return True
            if len(self._items) >= self._bound:
                if self._is_state_event(msg):
                    return False  # cheap to drop; a newer one will follow
                # Shed the oldest state event to make room for a real message.
                for i, it in enumerate(self._items):
                    if self._is_state_event(it):
                        del self._items[i]
                        break
                if len(self._items) >= self._bound:
                    return False
            self._items.append(msg)
            self._cond.notify()
            return True

    def get(self, timeout: float | None = None) -> dict[str, Any] | None:
        with self._cond:
            if not self._items and not self.closed:
                self._cond.wait(timeout)
            if self._items:
                return self._items.pop(0)
            return None

    def close(self) -> None:
        with self._cond:
            self.closed = True
            self._cond.notify_all()

    @staticmethod
    def _is_state_event(msg: dict[str, Any]) -> bool:
        return msg.get("kind") == "event" and msg.get("event") == "state"


def _write_all(fd: BinaryIO, data: bytes) -> None:
    """Handle short writes — a single write() is not guaranteed complete."""
    view = memoryview(data)
    while view:
        n = fd.write(view)
        if n is None or n <= 0:
            raise OSError("short write")
        view = view[n:]


def _event(component: str, status: str, reason: str = "") -> dict[str, Any]:
    data: dict[str, Any] = {"component": component, "status": status}
    if reason:
        data["reason"] = reason[:500]
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "kind": "event",
        "event": "connection",
        "data": data,
    }


def _disconnect_response(req: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "kind": "response",
        "id": req.get("id", "unknown"),
        "ok": False,
        "error": {
            "code": "disconnected",
            "message": "desktop app is not connected to the control socket",
        },
    }


class Helper:
    def __init__(
        self,
        socket_path: str,
        stdin: BinaryIO | None = None,
        stdout: BinaryIO | None = None,
    ) -> None:
        self.socket_path = socket_path
        self._stdin = stdin
        self._stdout = stdout
        self.to_browser = BoundedBus()
        self.to_socket = BoundedBus()
        self.stop_event = threading.Event()
        self.sock: socket.socket | None = None
        self.sock_lock = threading.Lock()

    # ---- stdout side ------------------------------------------------------

    def stdin_reader(self) -> None:
        """browser -> (socket | synthesized error)."""
        feed = FrameFeed(max_bytes=TRANSPORT_MAX_BYTES)
        # read1 exists on BufferedReader; wrapped or unbuffered stdio (test
        # harnesses, some embedders) only guarantees .read.
        stdin = self._stdin if self._stdin is not None else sys.stdin.buffer
        read = getattr(stdin, "read1", stdin.read)
        try:
            while not self.stop_event.is_set():
                chunk = read(65536)
                if not chunk:
                    break  # EOF: Firefox closed the pipe — clean termination.
                for msg in feed.feed(chunk):
                    self._from_browser(msg)
        except FrameError as exc:
            LOG.warning("dropping malformed browser input: %s", exc)
        finally:
            self.to_socket.close()
            self.stop_event.set()

    def _from_browser(self, msg: dict[str, Any]) -> None:
        problems = validate_message(msg)
        if problems:
            LOG.warning("invalid message from browser: %s", problems[0])
            return
        if msg.get("kind") == "hello":
            self.to_browser.put(
                {
                    "protocolVersion": PROTOCOL_VERSION,
                    "kind": "hello",
                    "component": "helper",
                    "componentVersion": __version__,
                }
            )
            # Forward the hello too — the GUI learns the session exists.
            self._to_socket_or_drop(msg)
            return
        if msg.get("kind") == "request":
            if not self._to_socket_or_drop(msg):
                self.to_browser.put(_disconnect_response(msg))
            return
        # events/responses destined for the GUI
        self._to_socket_or_drop(msg)

    def _to_socket_or_drop(self, msg: dict[str, Any]) -> bool:
        with self.sock_lock:
            alive = self.sock is not None
        if not alive:
            return False
        return self.to_socket.put(msg)

    def stdout_writer(self) -> None:
        stdout = self._stdout if self._stdout is not None else sys.stdout.buffer
        while not self.stop_event.is_set():
            msg = self.to_browser.get(timeout=0.25)
            if msg is None:
                continue
            try:
                _write_all(stdout, encode_frame(msg))
                stdout.flush()
            except (OSError, FrameError) as exc:
                LOG.error("stdout write failed: %s", exc)
                self.stop_event.set()
                return

    # ---- socket side ------------------------------------------------------

    def socket_pump(self, sock: socket.socket) -> None:
        """GUI -> browser."""
        feed = FrameFeed(max_bytes=TRANSPORT_MAX_BYTES)
        try:
            while not self.stop_event.is_set():
                data = sock.recv(65536)
                if not data:
                    break
                for msg in feed.feed(data):
                    problems = validate_message(msg)
                    if problems:
                        LOG.warning("invalid message from GUI: %s", problems[0])
                        continue
                    self.to_browser.put(msg)
        except (OSError, FrameError) as exc:
            LOG.warning("socket pump ended: %s", exc)

    def socket_writer(self, sock: socket.socket) -> None:
        try:
            while not self.stop_event.is_set():
                msg = self.to_socket.get(timeout=0.25)
                if msg is None:
                    continue
                try:
                    sock.sendall(encode_frame(msg))
                except OSError as exc:
                    LOG.warning("socket write failed: %s", exc)
                    return
        finally:
            # Free queued requests with a synthesized error so the browser is
            # not left waiting on a dead channel.
            while True:
                msg = self.to_socket.get(timeout=0)
                if msg is None:
                    break
                if msg.get("kind") == "request":
                    self.to_browser.put(_disconnect_response(msg))

    def run(self) -> int:
        threads = [
            threading.Thread(target=self.stdin_reader, daemon=True, name="stdin"),
            threading.Thread(target=self.stdout_writer, daemon=True, name="stdout"),
        ]
        for t in threads:
            t.start()

        delay = CONNECT_RETRY_MIN_S
        first = True
        while not self.stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect(self.socket_path)
                sock.settimeout(None)
            except OSError as exc:
                if first:
                    LOG.info("waiting for GUI socket %s (%s)", self.socket_path, exc)
                    first = False
                sock.close()
                self.stop_event.wait(delay)
                delay = min(delay * 2, CONNECT_RETRY_MAX_S)
                continue

            delay = CONNECT_RETRY_MIN_S
            with self.sock_lock:
                self.sock = sock
            LOG.info("GUI socket connected")
            self.to_browser.put(_event("gui", "connected"))
            with contextlib.suppress(OSError):
                # Tell the GUI who we are.
                sock.sendall(
                    encode_frame(
                        {
                            "protocolVersion": PROTOCOL_VERSION,
                            "kind": "hello",
                            "component": "helper",
                            "componentVersion": __version__,
                        }
                    )
                )

            pump = threading.Thread(
                target=self.socket_pump, args=(sock,), daemon=True, name="sock-in"
            )
            writer = threading.Thread(
                target=self.socket_writer, args=(sock,), daemon=True, name="sock-out"
            )
            pump.start()
            writer.start()
            pump.join()
            if self.stop_event.is_set():
                break
            # Socket ended: report the GUI as gone, then reconnect.
            with self.sock_lock:
                self.sock = None
            with contextlib.suppress(OSError):
                sock.close()
            self.to_browser.put(
                _event("gui", "disconnected", "control socket closed")
            )
            writer.join(timeout=1)

        with self.sock_lock:
            if self.sock is not None:
                with contextlib.suppress(OSError):
                    self.sock.close()
                self.sock = None
        self.to_browser.close()
        self.to_socket.close()
        return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(name)s: %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(prog="amberfader-helper")
    parser.add_argument(
        "--socket",
        default=os.environ.get("AMBERFADER_SOCKET"),
        help="path to the GUI control socket (default: $XDG_RUNTIME_DIR/amberfader/control.sock)",
    )
    args = parser.parse_args(argv)
    path = args.socket or default_socket_path()
    return Helper(path).run()


if __name__ == "__main__":  # pragma: no cover
    # stdout is protocol-only; anything that prints must go to stderr.
    raise SystemExit(main())
