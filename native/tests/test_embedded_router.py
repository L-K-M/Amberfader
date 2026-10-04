"""Embedded router: binding per page document, protocol answers, and the
page-message contract the TypeScript bridge implements. Qt-free."""
import json

import pytest

from amberfader import PROTOCOL_VERSION
from amberfader.embedded.history import SearchHistoryStore
from amberfader.embedded.router import MAX_PENDING, PENDING_TTL_SECONDS, EmbeddedRouter
from amberfader.protocol import validate_message


def page_state(**overrides):
    state = {
        "revision": 3,
        "track": {
            "occurrenceId": "occ-1",
            "providerId": "abc",
            "title": "Amber Fade",
            "artists": ["Slow Decay"],
            "album": "Warm Static",
            "artworkId": "art-1",
        },
        "status": "playing",
        "contentKind": "track",
        "positionSeconds": 12.0,
        "durationSeconds": 187.0,
        "playbackRate": 1.0,
        "volume": 0.8,
        "muted": False,
        "liked": False,
        "capabilities": ["play", "pause", "next", "searchSongs"],
    }
    state.update(overrides)
    return state


class Harness:
    def __init__(self, tmp_path):
        self.emitted: list[dict] = []
        self.commands: list[dict] = []
        self.artwork: list[tuple] = []
        self.page_reachable = True
        self.now = 1000.0
        self.history = SearchHistoryStore(tmp_path / "history.json")
        self.router = EmbeddedRouter(
            emit=self._emit,
            send_to_page=self._send,
            request_artwork=lambda *args: self.artwork.append(args),
            history=self.history,
            clock=lambda: self.now,
        )

    def _emit(self, msg):
        # Every message the router produces must satisfy the public schema.
        assert validate_message(msg) == [], msg
        self.emitted.append(msg)

    def _send(self, command):
        if not self.page_reachable:
            return False
        self.commands.append(command)
        return True

    def page(self, **msg):
        self.router.on_page_message(json.dumps(msg))

    def register(self, nonce="doc-1"):
        self.page(type="register", documentNonce=nonce, capabilities=["play"])
        return self.binding_token()

    def binding_token(self):
        bound = [m for m in self.emitted if m.get("event") == "binding"]
        return bound[-1].get("bindingToken") if bound else None

    def session_id(self):
        return self.emitted[-1]["sessionId"] if self.emitted else self._ping_session()

    def _ping_session(self):
        self.request("ping-0", "connection.ping")
        return self.emitted[-1]["sessionId"]

    def request(self, rid, method, params=None, *, binding=None, session=None):
        msg = {
            "protocolVersion": PROTOCOL_VERSION, "kind": "request", "id": rid,
            "method": method, "params": params or {},
        }
        if session is not None:
            msg["sessionId"] = session
        if binding is not None:
            msg["bindingToken"] = binding
        self.router.handle_request(msg)

    def bound_request(self, rid, method, params=None):
        self.request(rid, method, params, binding=self.binding_token(), session=self.session_id())

    def response(self, rid):
        matches = [m for m in self.emitted if m.get("kind") == "response" and m["id"] == rid]
        assert len(matches) == 1, f"expected one response for {rid}: {matches}"
        return matches[0]

    def events(self, name):
        return [m for m in self.emitted if m.get("kind") == "event" and m["event"] == name]


@pytest.fixture()
def h(tmp_path):
    return Harness(tmp_path)


def test_page_commands_wait_for_a_registered_document(h):
    h.request("r1", "player.play", binding="x", session="y")

    response = h.response("r1")
    assert response["ok"] is False
    assert response["error"]["code"] == "stale_target"
    assert "Show YT" in response["error"]["message"]
    assert h.commands == []


def test_registration_binds_and_state_is_stamped(h):
    token = h.register()
    h.page(type="state", documentNonce="doc-1", state=page_state(), artworkUrl=None)

    assert token
    state_event = h.events("state")[-1]
    assert state_event["bindingToken"] == token
    assert state_event["data"]["bindingToken"] == token

    h.request("s1", "state.get")
    snapshot = h.response("s1")
    assert snapshot["ok"] is True
    assert snapshot["bindingToken"] == token
    assert snapshot["result"]["track"]["title"] == "Amber Fade"


def test_state_get_before_any_page_returns_null(h):
    h.request("s0", "state.get")
    response = h.response("s0")
    assert response["ok"] is True
    assert response["result"] is None
    assert "bindingToken" not in response


def test_forwarded_command_carries_the_document_nonce(h):
    token = h.register()
    h.bound_request("r2", "player.pause")

    assert h.commands == [{
        "requestId": "r2", "method": "player.pause", "params": {}, "expectedNonce": "doc-1",
    }]
    h.page(type="reply", documentNonce="doc-1", requestId="r2", replayed=False,
           outcome={"ok": True, "result": {"observedStateRevision": 4}})

    response = h.response("r2")
    assert response["ok"] is True
    assert response["result"] == {"observedStateRevision": 4}
    assert response["bindingToken"] == token


def test_stale_binding_and_session_are_rejected(h):
    h.register()
    session = h.session_id()

    h.request("r3", "player.next", binding="old-token", session=session)
    h.request("r4", "player.next", binding=h.binding_token(), session="other-session")

    assert h.response("r3")["error"]["code"] == "stale_target"
    assert h.response("r4")["error"]["code"] == "disconnected"
    assert h.commands == []


def test_reload_settles_pending_commands_and_rebinds(h):
    first = h.register("doc-1")
    h.bound_request("r5", "player.play")

    second = h.register("doc-2")

    assert second and second != first
    response = h.response("r5")
    assert response["error"]["code"] == "stale_target"
    assert response["bindingToken"] == first
    # Late traffic from the old document is ignored.
    h.page(type="reply", documentNonce="doc-1", requestId="r5", replayed=False,
           outcome={"ok": True, "result": {}})
    h.page(type="state", documentNonce="doc-1", state=page_state(), artworkUrl=None)
    assert len([m for m in h.emitted if m.get("id") == "r5"]) == 1
    assert h.events("state") == []


@pytest.mark.parametrize("lose", ["unload", "lost"])
def test_losing_the_document_revokes_the_binding(h, lose):
    h.register()
    h.page(type="state", documentNonce="doc-1", state=page_state(), artworkUrl=None)
    h.bound_request("r6", "player.next")

    if lose == "unload":
        h.page(type="unload", documentNonce="doc-1")
    else:
        h.router.on_page_lost("YouTube Music page navigated to another site")

    assert h.response("r6")["error"]["code"] == "stale_target"
    revoked = h.events("binding")[-1]
    assert revoked["data"]["status"] == "revoked"
    assert "bindingToken" not in revoked
    assert h.events("connection")[-1]["data"]["component"] == "target"
    h.request("s2", "state.get")
    assert h.response("s2")["result"] is None
    assert not h.router.attached


def test_search_results_are_validated_and_recorded(h):
    h.register()
    h.bound_request("q1", "search.songs", {"query": "amber"})
    h.page(type="reply", documentNonce="doc-1", requestId="q1", replayed=False,
           outcome={"ok": True, "result": {"searchToken": "t1", "complete": True, "results": []}})

    assert h.response("q1")["ok"] is True
    assert h.history.get().queries == ("amber",)

    h.bound_request("q2", "search.songs", {"query": "broken"})
    h.page(type="reply", documentNonce="doc-1", requestId="q2", replayed=False,
           outcome={"ok": True, "result": {"searchToken": "", "results": "nope"}})

    response = h.response("q2")
    assert response["error"]["code"] == "internal_error"
    assert h.history.get().queries == ("amber",)


def test_adapter_errors_keep_known_codes_only(h):
    h.register()
    h.bound_request("e1", "player.play")
    h.bound_request("e2", "player.play")
    h.page(type="reply", documentNonce="doc-1", requestId="e1", replayed=False,
           outcome={"ok": False, "error": {"code": "pending_outcome", "message": "not seen"}})
    h.page(type="reply", documentNonce="doc-1", requestId="e2", replayed=False,
           outcome={"ok": False, "error": {"code": "made_up", "message": "x" * 5000}})

    assert h.response("e1")["error"] == {"code": "pending_outcome", "message": "not seen"}
    second = h.response("e2")["error"]
    assert second["code"] == "internal_error"
    assert len(second["message"]) == 1000


def test_invalid_state_is_not_stored(h):
    h.register()
    h.page(type="state", documentNonce="doc-1", state=page_state(volume=7), artworkUrl=None)

    assert h.events("state") == []
    h.request("s3", "state.get")
    assert h.response("s3")["result"] is None


def test_artwork_is_requested_once_per_track_and_replayed_on_state_get(h):
    h.register()
    url = "https://yt3.googleusercontent.com/cover"
    for position in (1.0, 2.0, 3.0):
        h.page(type="state", documentNonce="doc-1",
               state=page_state(positionSeconds=position), artworkUrl=url)

    assert h.artwork == [(url, "art-1", "occ-1")]
    h.request("s4", "state.get")
    assert h.artwork == [(url, "art-1", "occ-1")] * 2


def test_assets_follow_the_current_track_without_a_binding_token(h):
    h.register()
    h.page(type="state", documentNonce="doc-1", state=page_state(),
           artworkUrl="https://yt3.googleusercontent.com/cover")
    asset = {"artworkId": "art-1", "occurrenceId": None, "mime": "image/jpeg",
             "width": 1, "height": 1, "dataBase64": "AAAA"}

    h.router.on_asset(asset)
    h.router.on_asset({**asset, "artworkId": "art-old"})

    events = h.events("asset")
    assert len(events) == 1
    assert events[0]["data"]["occurrenceId"] == "occ-1"
    assert "bindingToken" not in events[0]


def test_artists_are_recorded_once_per_playing_occurrence(h):
    h.register()
    h.page(type="state", documentNonce="doc-1", state=page_state(status="paused"), artworkUrl=None)
    assert h.history.get().artists == ()

    for _ in range(3):
        h.page(type="state", documentNonce="doc-1", state=page_state(), artworkUrl=None)
    ad = page_state(contentKind="advertisement", track={
        **page_state()["track"], "occurrenceId": "occ-ad", "artists": ["Sponsor"],
    })
    h.page(type="state", documentNonce="doc-1", state=ad, artworkUrl=None)

    assert h.history.get().artists == ("Slow Decay",)


def test_history_methods(h):
    h.history.record_query("first")
    h.request("h1", "search.history")
    h.request("h2", "search.clearHistory")

    assert h.response("h1")["result"] == {"queries": ["first"], "artists": []}
    assert h.response("h2")["result"] == {"queries": [], "artists": []}


def test_unreachable_page_reports_disconnected(h):
    h.register()
    h.page_reachable = False
    h.bound_request("u1", "player.play")

    assert h.response("u1")["error"]["code"] == "disconnected"


def test_pending_table_is_bounded_and_expires(h):
    h.register()
    for i in range(MAX_PENDING):
        h.bound_request(f"p{i}", "player.next")
    h.bound_request("overflow", "player.next")
    assert h.response("overflow")["error"]["message"] == "Too many requests in flight."

    h.now += PENDING_TTL_SECONDS + 1
    h.bound_request("fresh", "player.next")
    assert h.commands[-1]["requestId"] == "fresh"
    # A reply for an expired entry no longer produces a response.
    h.page(type="reply", documentNonce="doc-1", requestId="p0", replayed=False,
           outcome={"ok": True, "result": {}})
    assert not [m for m in h.emitted if m.get("id") == "p0"]


@pytest.mark.parametrize("text", [
    "not json",
    "[]",
    json.dumps({"type": "register"}),
    json.dumps({"type": "register", "documentNonce": "n" * 129}),
    json.dumps({"type": "register", "documentNonce": "doc", "padding": "x" * (256 * 1024)}),
])
def test_malformed_page_messages_are_dropped(h, text):
    h.router.on_page_message(text)
    assert h.emitted == []


@pytest.mark.parametrize("method", ["targets.list", "browser.showPlayer"])
def test_methods_without_an_embedded_meaning_are_unsupported(h, method):
    h.register()
    h.bound_request("t1", method)
    assert h.response("t1")["error"]["code"] == "unsupported_operation"
