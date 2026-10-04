"""Amberfader desktop application.

Owns the per-user control socket, applies helper protocol traffic to the
windows, and enforces request deadlines. The GUI is independent of the
helper's process tree: closing the app leaves music playing, and a dead
helper is a real disconnect — never silently retried.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from enum import Enum, auto
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from . import PROTOCOL_VERSION
from .face_library import FaceError
from .hosts import HOST_COPY, PlaybackHost
from .protocol import validate_message
from .transport.local import (
    FramedSocket,
    LocalServer,
    default_socket_path,
    try_activate_existing,
)

if TYPE_CHECKING:  # pragma: no cover
    from PySide6.QtCore import QTimer

    from .ui.main_window import MainWindow

CONTROL_DEADLINE_MS = 5000
SEARCH_DEADLINE_MS = 15000
MAX_PENDING = 64
BINDING_METHOD_PREFIXES = ("player.", "search.", "browser.")
UNBOUND_SEARCH_METHODS = frozenset(("search.history", "search.clearHistory"))
WINDOW_METHODS = frozenset(("browser.showPlayer", "browser.hidePlayer"))


def _requires_binding(method: str) -> bool:
    return method.startswith(BINDING_METHOD_PREFIXES) and method not in UNBOUND_SEARCH_METHODS


class _BindingState(Enum):
    UNKNOWN = auto()
    BOUND = auto()
    REVOKED = auto()


class AmberfaderApp:
    """One running desktop instance: socket server + windows + pending calls.

    Requires a QApplication to exist. `start()` fails cleanly when a live
    process already owns the socket path (second-instance semantics live in
    main(): it activates the existing window and exits instead)."""

    def __init__(
        self,
        socket_path: str,
        scale: float = 1.0,
        host: PlaybackHost = PlaybackHost.FIREFOX,
        show_page: Callable[[bool], bool] | None = None,
    ) -> None:
        from PySide6.QtWidgets import QApplication

        self.app = QApplication.instance()
        if self.app is None:
            raise RuntimeError("AmberfaderApp requires a QApplication")
        # The embedded page window is local to this process: showing it must
        # work before any page is bound (for example to sign in), so it never
        # becomes a bound protocol request.
        if (host is PlaybackHost.EMBEDDED) != (show_page is not None):
            raise ValueError("show_page is required for, and only for, the embedded host")
        self.socket_path = socket_path
        self._scale = scale
        self._host = host
        self._copy = HOST_COPY[host]
        self._show_page = show_page
        self.server = LocalServer(socket_path)
        self.window: MainWindow | None = None
        self.conn: FramedSocket | None = None
        self._pending: dict[str, dict[str, Any]] = {}
        self._session_id: str | None = None
        self._binding_token: str | None = None
        self._binding_state = _BindingState.UNKNOWN
        self._state_epoch = 0

    # ---- lifecycle --------------------------------------------------------

    def start(self) -> bool:
        """Listen on the control socket and show the player window."""
        if not self.server.listen():
            return False
        from .ui.main_window import MainWindow

        try:
            self.window = MainWindow(self.request, scale=self._scale, host=self._host)
        except FaceError:
            self.server.close()
            raise
        if self._host is PlaybackHost.FIREFOX:
            self.server.helperConnected.connect(self._on_helper)
        else:
            # The embedded socket only serves single-instance activation.
            self.server.helperConnected.connect(lambda s: s.socket.disconnectFromServer())
        self.server.activationRequested.connect(self._on_activation)
        self.server.invalidPeer.connect(lambda s: s.socket.disconnectFromServer())
        self.window.show()
        return True

    def close(self) -> None:
        self.server.close()

    # ---- outbound protocol ------------------------------------------------

    def _send(self, msg: dict) -> bool:
        return self.conn.send(msg) if self.conn is not None else False

    def request(self, method: str, params: dict) -> None:
        if self.window is None:
            return
        if self._show_page is not None and method in WINDOW_METHODS:
            changed = self._show_page(method == "browser.showPlayer")
            self.window.route_response(method, changed, {} if changed else {
                "message": "Could not change the YouTube Music window.",
            })
            return
        needs_binding = _requires_binding(method)
        if needs_binding and (self._session_id is None or self._binding_token is None):
            self.window.route_response(method, False, {"message": self._copy.unbound})
            return
        if len(self._pending) >= MAX_PENDING:
            self.window.show_status("Too many requests in flight", error=True)
            return
        # The adapter dedup cache survives GUI restarts within one document.
        rid = f"gui-{uuid4().hex}"
        msg: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "kind": "request",
            "id": rid,
            "method": method,
            "params": params,
        }
        if self._session_id is not None:
            msg["sessionId"] = self._session_id
        if needs_binding:
            msg["bindingToken"] = self._binding_token
        from PySide6.QtCore import QTimer

        deadline = SEARCH_DEADLINE_MS if method == "search.songs" else CONTROL_DEADLINE_MS
        timer: QTimer = QTimer(self.app)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda r=rid, m=method: self._on_timeout(r, m))
        self._pending[rid] = {
            "method": method, "timer": timer,
            "binding": (self._session_id, self._binding_token),
            "state_epoch": self._state_epoch,
        }
        timer.start(deadline)
        if not self._send(msg):
            self._settle(rid, False, {"message": self._copy.not_connected})

    def _on_timeout(self, rid: str, method: str) -> None:
        # A timeout does not prove the operation never ran — report
        # pending-outcome rather than silently retrying non-idempotent work.
        self._settle(
            rid, False, {"message": f"{method}: outcome uncertain after deadline"}
        )

    def _settle(self, rid: str, ok: bool, payload: dict) -> None:
        entry = self._pending.pop(rid, None)
        if entry is None or self.window is None:
            return
        entry["timer"].stop()
        if ok and entry["method"] == "state.get" and payload:
            snapshot = {
                "protocolVersion": PROTOCOL_VERSION, "kind": "event", "event": "state",
                "data": payload,
            }
            if validate_message(snapshot):
                ok = False
                payload = {"message": self._copy.invalid_snapshot}
            else:
                self.window.apply_state(payload)
        self.window.route_response(entry["method"], ok, payload)

    # ---- inbound wiring ---------------------------------------------------

    def attach_upstream(self, upstream: FramedSocket) -> None:
        """Attach an in-process upstream instead of a helper socket. It must
        offer FramedSocket's interface: send(), messageReceived and
        disconnected."""
        self._on_helper(upstream)

    def _on_helper(self, sock: FramedSocket) -> None:
        self._state_epoch += 1
        self._session_id = self._binding_token = None
        self._binding_state = _BindingState.UNKNOWN
        self.conn = sock
        sock.messageReceived.connect(self._on_message)
        sock.disconnected.connect(self._on_helper_gone)
        if self.window is not None:
            self.window.show_status(self._copy.connected)
        self.request("state.get", {})

    def _on_helper_gone(self) -> None:
        self._state_epoch += 1
        self.conn = None
        self._session_id = self._binding_token = None
        self._binding_state = _BindingState.UNKNOWN
        for rid in list(self._pending):
            self._settle(rid, False, {"message": self._copy.disconnected})
        if self.window is not None:
            self.window.set_connection("gui", "disconnected", "helper socket closed")

    def _on_message(self, msg: dict) -> None:
        if self.window is None:
            return
        problems = validate_message(msg)
        kind = msg.get("kind")
        if kind in ("activate-request",):
            return  # handled at server level
        if problems:
            return  # invalid peer traffic is dropped silently
        learn_binding = True
        if kind == "response":
            entry = self._pending.get(msg.get("id"))
            if entry is None:
                return
            if entry["method"] == "state.get" and entry["state_epoch"] != self._state_epoch:
                # New state or a disconnect superseded this resync. Discard it
                # before it can restore an old track, cover, or binding.
                self._pending.pop(msg["id"])["timer"].stop()
                return
            current = (self._session_id, self._binding_token)
            received = (msg.get("sessionId"), msg.get("bindingToken"))
            # Responses can establish the first snapshot binding, but cannot
            # replace a newer observation or revive an explicitly lost target.
            learn_binding = (
                entry["binding"] == current or received == current
                or (self._binding_state is _BindingState.UNKNOWN
                    and msg.get("sessionId") == self._session_id)
            )
            method = entry["method"]
            bound_request = _requires_binding(method)
            if not learn_binding and (method == "state.get" or bound_request):
                self._settle(msg["id"], False, {
                    "message": "Playback binding changed while the request was pending.",
                })
                return
        session_id = msg.get("sessionId")
        if learn_binding and isinstance(session_id, str):
            if self._session_id != session_id:
                self._binding_token = None
                self._binding_state = _BindingState.UNKNOWN
            self._session_id = session_id
        binding_token = msg.get("bindingToken")
        if learn_binding and isinstance(binding_token, str) and binding_token:
            self._binding_token = binding_token
            self._binding_state = _BindingState.BOUND
        if kind == "response":
            ok = bool(msg.get("ok"))
            payload = (
                (msg.get("result") or {})
                if ok
                else {"message": (msg.get("error") or {}).get("message", "error")}
            )
            rid = msg.get("id")
            if isinstance(rid, str):
                self._settle(rid, ok, payload)
        elif kind == "event":
            event = msg.get("event")
            data = msg.get("data") or {}
            if event == "state":
                self._state_epoch += 1
                self.window.apply_state(data)
            elif event == "asset":
                self.window.apply_asset(data)
            elif event == "connection":
                if (
                    data.get("component") in ("gui", "target", "adapter")
                    and data.get("status") != "connected"
                ):
                    self._state_epoch += 1
                self.window.set_connection(
                    data.get("component", ""), data.get("status", ""), data.get("reason", "")
                )
            elif event == "binding":
                if data.get("status") != "bound":
                    self._state_epoch += 1
                    self._binding_token = None
                    self._binding_state = _BindingState.REVOKED

                current = (self._session_id, self._binding_token)
                # Settle old UI guards before a new request can start. Later
                # replies for these IDs cannot clear a newer command's busy flag.
                for rid, entry in list(self._pending.items()):
                    if _requires_binding(entry["method"]) and entry["binding"] != current:
                        self._settle(rid, False, {
                            "message": "Playback binding changed while the request was pending.",
                        })

                if data.get("status") == "bound":
                    self.window.binding_changed()
                else:
                    self.window.set_connection("target", "disconnected", data.get("reason", ""))

    def _on_activation(self, sock: FramedSocket) -> None:
        sock.send({"kind": "activate-response", "ok": True})
        # The activating peer blocks in waitForReadyRead; push the ack out
        # now instead of relying on a later event-loop turn to flush it.
        sock.socket.flush()
        sock.socket.waitForBytesWritten(1000)
        if self.window is not None:
            self.window.raise_requested()
        sock.socket.disconnectFromServer()


def main() -> int:  # pragma: no cover - exercised via entry point
    parser = argparse.ArgumentParser(prog="amberfader")
    parser.add_argument("--socket", default=os.environ.get("AMBERFADER_SOCKET"))
    parser.add_argument("--scale", type=float, default=1.0, choices=(1.0, 1.5, 2.0))
    args = parser.parse_args()

    # Late Qt import: --help and the helper path stay PySide6-free.
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("amberfader")
    app.setOrganizationDomain("ch.lkmc")

    try:
        path = args.socket or default_socket_path()
    except RuntimeError as exc:
        print(f"amberfader: {exc}", file=sys.stderr)
        return 2

    # Single instance: a second launch activates the existing window and exits.
    if try_activate_existing(path):
        return 0

    amber = AmberfaderApp(path, scale=args.scale)
    try:
        started = amber.start()
    except FaceError as exc:
        print(f"amberfader: {exc}", file=sys.stderr)
        return 2
    if not started:
        print(f"amberfader: cannot listen on {path}", file=sys.stderr)
        return 2
    app.aboutToQuit.connect(amber.close)
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
