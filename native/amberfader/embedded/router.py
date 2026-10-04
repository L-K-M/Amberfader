"""In-process router for the embedded YouTube Music page.

Takes the role the extension's background router plays in Firefox mode, but
for exactly one page that this process owns. It speaks the public protocol
(protocol/schemas) to the desktop client, so the client's deadlines, binding
checks and schema validation apply unchanged.

Binding: every page document registers with a fresh nonce and receives a new
binding token. Commands carry the nonce they were issued for; a reload,
navigation away, or renderer exit revokes the binding and settles pending
commands as stale instead of leaving them to time out.

Qt-free on purpose: the page host and artwork fetcher are injected
callables, so this logic is unit-tested without QtWebEngine.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .. import PROTOCOL_VERSION
from ..protocol import TRANSPORT_MAX_BYTES, load_schema, validate_definition, validate_message
from .history import SearchHistoryStore

# Methods the page adapter executes. History is answered here. Showing and
# hiding the page window never reaches the router: the desktop app handles it
# locally because it must work before any page document is bound.
PAGE_METHODS = frozenset((
    "player.play",
    "player.pause",
    "player.previous",
    "player.next",
    "player.seek",
    "player.setVolume",
    "player.setMuted",
    "player.setLiked",
    "search.songs",
    "search.playResult",
    "search.startRadio",
))
MAX_PENDING = 64
# The client gives up after 5 s (control) or 15 s (search). Entries older than
# this are abandoned so a hung page cannot grow the table without bound.
PENDING_TTL_SECONDS = 30.0
MAX_NONCE_LENGTH = 128
MAX_REASON_LENGTH = 500
MAX_ERROR_MESSAGE_LENGTH = 1000
ERROR_CODES = frozenset(load_schema()["$defs"]["errorCode"]["enum"])

_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Pending:
    method: str
    query: str | None
    binding_token: str
    created: float


@dataclass(frozen=True)
class _ArtworkRequest:
    url: str
    artwork_id: str
    occurrence_id: str | None


class EmbeddedRouter:
    def __init__(
        self,
        *,
        emit: Callable[[dict[str, Any]], None],
        send_to_page: Callable[[dict[str, Any]], bool],
        request_artwork: Callable[[str, str, str | None], None],
        history: SearchHistoryStore,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._emit = emit
        self._send_to_page = send_to_page
        self._request_artwork = request_artwork
        self._history = history
        self._clock = clock

        self._session_id = f"embedded-{uuid.uuid4()}"
        self._document_nonce: str | None = None
        self._binding_token: str | None = None
        self._last_state: dict[str, Any] | None = None
        self._artwork: _ArtworkRequest | None = None
        self._history_occurrence: str | None = None
        self._pending: dict[str, _Pending] = {}

    @property
    def attached(self) -> bool:
        return self._document_nonce is not None

    # ---- client -> router -------------------------------------------------

    def handle_request(self, msg: dict[str, Any]) -> None:
        if msg.get("kind") != "request" or validate_message(msg):
            # Without a valid envelope there is no trustworthy id to answer.
            _LOG.warning("dropped an invalid client request")
            return

        rid: str = msg["id"]
        method: str = msg["method"]
        params: dict[str, Any] = msg["params"]
        if method in PAGE_METHODS:
            self._forward(rid, method, params, msg)
            return

        match method:
            case "connection.ping":
                self._ok(rid, {"pong": int(time.time() * 1000), "sessionId": self._session_id})
            case "state.get":
                self._ok(rid, self._last_state, binding=self._binding_token)
                # A reopened client needs the cover bytes again; the fetcher
                # answers repeats from its cache.
                if self._artwork is not None:
                    self._request_artwork(
                        self._artwork.url, self._artwork.artwork_id, self._artwork.occurrence_id,
                    )
            case "state.subscribe" | "state.unsubscribe":
                self._ok(rid, {"subscribed": method == "state.subscribe"})
            case "search.history" | "search.clearHistory":
                self._answer_history(rid, method)
            case _:
                self._error(
                    rid, "unsupported_operation",
                    "The embedded prototype has a single YouTube Music page.",
                )

    def _forward(self, rid: str, method: str, params: dict[str, Any], msg: dict[str, Any]) -> None:
        if self._document_nonce is None or self._binding_token is None:
            self._error(
                rid, "stale_target",
                "YouTube Music is not ready. Use Show YT to check the page or sign in.",
            )
            return
        if msg.get("sessionId") != self._session_id:
            self._error(rid, "disconnected", "Session changed. Request a fresh snapshot.")
            return
        if msg.get("bindingToken") != self._binding_token:
            self._error(rid, "stale_target", "Binding token is stale or wrong.")
            return

        self._prune_pending()
        if len(self._pending) >= MAX_PENDING:
            self._error(rid, "internal_error", "Too many requests in flight.")
            return

        query = params.get("query") if method == "search.songs" else None
        self._pending[rid] = _Pending(
            method, query if isinstance(query, str) else None, self._binding_token, self._clock(),
        )
        command = {
            "requestId": rid, "method": method, "params": params,
            "expectedNonce": self._document_nonce,
        }
        if not self._send_to_page(command):
            self._pending.pop(rid, None)
            self._error(
                rid, "disconnected", "The YouTube Music page is not reachable.",
                binding=self._binding_token,
            )

    def _answer_history(self, rid: str, method: str) -> None:
        try:
            history = self._history.get() if method == "search.history" else self._history.clear()
        except OSError:
            self._error(rid, "internal_error", "Cannot access local search history")
            return
        self._ok(rid, history.as_result())

    # ---- page -> router ---------------------------------------------------

    def on_page_message(self, text: str) -> None:
        if len(text.encode("utf-8")) > TRANSPORT_MAX_BYTES:
            _LOG.warning("dropped an oversized page message")
            return
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            _LOG.warning("dropped a malformed page message")
            return
        if not isinstance(msg, dict):
            return
        nonce = msg.get("documentNonce")
        if not isinstance(nonce, str) or not nonce or len(nonce) > MAX_NONCE_LENGTH:
            return

        kind = msg.get("type")
        if kind == "register":
            self._register(nonce)
            return
        # Everything else must come from the registered document.
        if nonce != self._document_nonce:
            return
        match kind:
            case "state":
                self._accept_state(msg.get("state"), msg.get("artworkUrl"))
            case "notice":
                self._accept_notice(msg.get("notice"))
            case "reply":
                self._accept_reply(msg.get("requestId"), msg.get("outcome"))
            case "unload":
                self._detach("The YouTube Music page is reloading.")

    def on_page_lost(self, reason: str) -> None:
        """The page host saw the document go away: navigation to another
        site (for example sign-in) or a renderer exit."""
        if self._document_nonce is not None:
            self._detach(reason)

    def on_asset(self, asset: dict[str, Any]) -> None:
        current = self._artwork
        if current is None or asset.get("artworkId") != current.artwork_id:
            return  # superseded by a newer track
        event = self._event("asset", {**asset, "occurrenceId": current.occurrence_id})
        if validate_message(event):
            _LOG.warning("dropped an invalid artwork asset")
            return
        self._emit(event)

    def _register(self, nonce: str) -> None:
        if nonce == self._document_nonce:
            return
        self._document_nonce = nonce
        self._binding_token = str(uuid.uuid4())
        self._last_state = None
        self._artwork = None
        self._abandon_pending("The YouTube Music page reloaded while the request was pending.")
        self._emit(self._event("binding", {"status": "bound"}, binding=self._binding_token))

    def _detach(self, reason: str) -> None:
        reason = reason[:MAX_REASON_LENGTH]
        self._document_nonce = None
        self._binding_token = None
        self._last_state = None
        self._artwork = None
        self._abandon_pending(reason)
        self._emit(self._event("binding", {"status": "revoked", "reason": reason}))
        self._emit(self._event(
            "connection", {"component": "target", "status": "disconnected", "reason": reason},
        ))

    def _accept_state(self, state: Any, artwork_url: Any) -> None:
        if not isinstance(state, dict) or self._binding_token is None:
            return
        stamped = {**state, "bindingToken": self._binding_token}
        event = self._event("state", stamped, binding=self._binding_token)
        if validate_message(event):
            _LOG.warning("dropped an invalid player state from the page")
            return

        self._last_state = stamped
        self._record_artists(stamped)
        self._emit(event)
        self._propose_artwork(stamped, artwork_url)

    def _accept_notice(self, notice: Any) -> None:
        if not isinstance(notice, dict):
            return
        data: dict[str, Any] = {"component": "adapter", "status": notice.get("status")}
        reason = notice.get("reason")
        if isinstance(reason, str):
            data["reason"] = reason[:MAX_REASON_LENGTH]
        event = self._event("connection", data)
        if not validate_message(event):
            self._emit(event)

    def _accept_reply(self, rid: Any, outcome: Any) -> None:
        if not isinstance(rid, str):
            return
        entry = self._pending.pop(rid, None)
        if entry is None:
            return  # abandoned, or answered already
        binding = entry.binding_token

        if not isinstance(outcome, dict):
            self._error(rid, "internal_error", "The page returned no outcome.", binding=binding)
            return
        if outcome.get("ok") is not True:
            error = outcome.get("error") if isinstance(outcome.get("error"), dict) else {}
            code = error.get("code")
            message = error.get("message")
            self._error(
                rid,
                code if code in ERROR_CODES else "internal_error",
                message[:MAX_ERROR_MESSAGE_LENGTH] if isinstance(message, str)
                else "Adapter command failed",
                binding=binding,
            )
            return

        result = outcome.get("result")
        if entry.method == "search.songs":
            if validate_definition("searchSongsResult", result):
                self._error(
                    rid, "internal_error", "The page returned invalid search results.",
                    binding=binding,
                )
                return
            self._record_query(entry.query)
        self._ok(rid, result if isinstance(result, dict) else {}, binding=binding)

    # ---- helpers ----------------------------------------------------------

    def _propose_artwork(self, state: dict[str, Any], url: Any) -> None:
        track = state.get("track") or {}
        artwork_id = track.get("artworkId")
        if not isinstance(url, str) or not url or not isinstance(artwork_id, str) or not artwork_id:
            self._artwork = None
            return
        request = _ArtworkRequest(url, artwork_id, track.get("occurrenceId"))
        if request == self._artwork:
            return  # position samples repeat the same proposal ~1 Hz
        self._artwork = request
        self._request_artwork(request.url, request.artwork_id, request.occurrence_id)

    def _record_artists(self, state: dict[str, Any]) -> None:
        track = state.get("track")
        if not track or state.get("status") != "playing":
            return
        if state.get("contentKind") == "advertisement":
            return
        occurrence = f"{state['bindingToken']}/{track['occurrenceId']}"
        if occurrence == self._history_occurrence:
            return
        self._history_occurrence = occurrence
        try:
            self._history.record_artists(list(track.get("artists") or []))
        except OSError:
            _LOG.warning("could not save recent artists")

    def _record_query(self, query: str | None) -> None:
        if not query:
            return
        try:
            self._history.record_query(query)
        except OSError:
            _LOG.warning("could not save recent search")

    def _prune_pending(self) -> None:
        cutoff = self._clock() - PENDING_TTL_SECONDS
        for rid in [rid for rid, entry in self._pending.items() if entry.created < cutoff]:
            del self._pending[rid]

    def _abandon_pending(self, reason: str) -> None:
        pending, self._pending = self._pending, {}
        for rid, entry in pending.items():
            self._error(rid, "stale_target", reason, binding=entry.binding_token)

    def _event(
        self, name: str, data: dict[str, Any], *, binding: str | None = None,
    ) -> dict[str, Any]:
        # Only state and binding events carry a token: the client learns its
        # binding from events, so an asset for an old track must not carry one.
        msg: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION, "kind": "event",
            "sessionId": self._session_id, "event": name, "data": data,
        }
        if binding is not None:
            msg["bindingToken"] = binding
        return msg

    def _ok(self, rid: str, result: dict[str, Any] | None, *, binding: str | None = None) -> None:
        self._respond(rid, {"ok": True, "result": result}, binding)

    def _error(self, rid: str, code: str, message: str, *, binding: str | None = None) -> None:
        self._respond(rid, {"ok": False, "error": {"code": code, "message": message}}, binding)

    def _respond(self, rid: str, body: dict[str, Any], binding: str | None) -> None:
        msg: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION, "kind": "response", "id": rid,
            "sessionId": self._session_id, **body,
        }
        if binding is not None:
            msg["bindingToken"] = binding
        self._emit(msg)
