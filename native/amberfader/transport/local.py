"""Qt transport glue: a framed-JSON connection over QLocalSocket, and the
per-user local socket server that accepts helper and second-instance
connections."""
from __future__ import annotations

import contextlib
import os
import stat
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from ..protocol import FrameError, FrameFeed, encode_frame
from .paths import default_socket_path, path_has_live_owner, runtime_socket_dir

__all__ = [
    "ACTIVATE_REQUEST",
    "ACTIVATE_RESPONSE",
    "FramedSocket",
    "LocalServer",
    "default_socket_path",
    "path_has_live_owner",
    "runtime_socket_dir",
    "try_activate_existing",
]

# Socket-internal activation handshake (not part of the browser protocol —
# discriminated before schema validation).
ACTIVATE_REQUEST = "activate-request"
ACTIVATE_RESPONSE = "activate-response"


class FramedSocket(QObject):
    """One framed-JSON duplex over a connected QLocalSocket."""

    messageReceived = Signal(dict)
    disconnected = Signal()

    def __init__(self, sock: QLocalSocket, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._sock = sock
        self._feed = FrameFeed()
        sock.readyRead.connect(self._on_ready)
        sock.disconnected.connect(self.disconnected)

    @property
    def socket(self) -> QLocalSocket:
        return self._sock

    def send(self, msg: dict[str, Any]) -> bool:
        try:
            frame = encode_frame(msg)
        except FrameError:
            return False
        return self._sock.write(frame) == len(frame)

    def _on_ready(self) -> None:
        data = bytes(self._sock.readAll())
        try:
            for msg in self._feed.feed(data):
                self.messageReceived.emit(msg)
        except FrameError:
            self._sock.disconnectFromServer()


class LocalServer(QObject):
    """The GUI-owned socket server. First frame on each connection declares
    the peer: a protocol 'hello' from a helper, or 'activate-request' from a
    second GUI instance."""

    helperConnected = Signal(object)      # FramedSocket
    activationRequested = Signal(object)  # FramedSocket
    invalidPeer = Signal(object)          # FramedSocket (closed by caller)

    def __init__(self, path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        self._pending: list[FramedSocket] = []

    def listen(self) -> bool:
        # Stale socket removal only after proving no live owner — a live
        # server (even a foreign one) keeps its file.
        if os.path.exists(self._path):
            if path_has_live_owner(self._path):
                return False
            os.unlink(self._path)
        dirpath = os.path.dirname(self._path)
        ok = self._server.listen(self._path)
        if ok:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
            os.chmod(dirpath, 0o700)
        return ok

    def close(self) -> None:
        self._server.close()
        with contextlib.suppress(OSError):
            os.unlink(self._path)

    def _on_connection(self) -> None:
        while self._server.hasPendingConnections():
            sock = self._server.nextPendingConnection()
            framed = FramedSocket(sock, self)
            self._pending.append(framed)
            framed.messageReceived.connect(
                lambda msg, f=framed: self._first_frame(f, msg)
            )
            framed.disconnected.connect(lambda f=framed: self._drop(f))

    def _first_frame(self, framed: FramedSocket, msg: dict) -> None:
        kind = msg.get("kind")
        if kind == "hello" and msg.get("component") in ("helper", "gui-instance"):
            if msg.get("component") == "gui-instance":
                self._release(framed)
                self.activationRequested.emit(framed)
            else:
                self._release(framed)
                self.helperConnected.emit(framed)
            return
        if kind == ACTIVATE_REQUEST:
            self._release(framed)
            self.activationRequested.emit(framed)
            return
        self._drop(framed)
        self.invalidPeer.emit(framed)

    def _release(self, framed: FramedSocket) -> None:
        with contextlib.suppress(RuntimeError):
            framed.messageReceived.disconnect()
        if framed in self._pending:
            self._pending.remove(framed)

    def _drop(self, framed: FramedSocket) -> None:
        if framed in self._pending:
            self._pending.remove(framed)


def try_activate_existing(path: str, timeout_ms: int = 1500) -> bool:
    """Second-instance fast path: connect to the existing GUI's socket and ask
    it to raise its window. Returns True when a live server acknowledged."""
    sock = QLocalSocket()
    sock.connectToServer(path)
    if not sock.waitForConnected(timeout_ms):
        return False
    sock.write(
        encode_frame(
            {
                "protocolVersion": 1,
                "kind": "hello",
                "component": "gui-instance",
                "componentVersion": "0",
            }
        )
    )
    sock.flush()
    sock.waitForReadyRead(timeout_ms)
    feed = FrameFeed()
    try:
        for _ in feed.feed(bytes(sock.readAll())):
            return True
    except FrameError:
        return False
    return True
