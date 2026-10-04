"""Desktop client in embedded mode: local window controls, host copy,
single-instance socket, and the in-process upstream."""
import socket as pysock

import pytest

pytest.importorskip(
    "amberfader.app",
    reason="GUI extra not installed or Qt unavailable",
    exc_type=ImportError,
)

from conftest import pump

from amberfader import PROTOCOL_VERSION
from amberfader.hosts import HOST_COPY, PlaybackHost
from amberfader.protocol import encode_frame

EMBEDDED_COPY = HOST_COPY[PlaybackHost.EMBEDDED]


def test_show_page_belongs_to_the_embedded_host(qapp, tmp_path):
    from amberfader.app import AmberfaderApp

    with pytest.raises(ValueError):
        AmberfaderApp(str(tmp_path / "a.sock"), host=PlaybackHost.EMBEDDED)
    with pytest.raises(ValueError):
        AmberfaderApp(str(tmp_path / "b.sock"), show_page=lambda _visible: True)


@pytest.fixture()
def embedded(qapp, tmp_path):
    from amberfader.app import AmberfaderApp

    calls = []
    outcome = {"ok": True}

    def show_page(visible):
        calls.append(visible)
        return outcome["ok"]

    app = AmberfaderApp(
        str(tmp_path / "embedded.sock"), host=PlaybackHost.EMBEDDED, show_page=show_page,
    )
    assert app.start()
    responses = []
    original = app.window.route_response

    def record(method, ok, payload):
        responses.append((method, ok, payload))
        original(method, ok, payload)

    app.window.route_response = record
    yield app, calls, outcome, responses
    app.window.close()
    app.close()


def test_window_controls_work_without_a_binding(embedded):
    app, calls, outcome, responses = embedded

    app.request("browser.showPlayer", {})
    outcome["ok"] = False
    app.request("browser.hidePlayer", {})

    assert calls == [True, False]
    assert responses == [
        ("browser.showPlayer", True, {}),
        ("browser.hidePlayer", False, {"message": "Could not change the YouTube Music window."}),
    ]
    assert app._pending == {}


def test_embedded_copy_replaces_firefox_wording(embedded):
    app, _calls, _outcome, responses = embedded

    app.request("player.play", {})

    assert responses == [("player.play", False, {"message": EMBEDDED_COPY.unbound})]
    assert app.window._btn_close.toolTip() == "Quit Amberfader; music stops"
    assert app.window._btn_show.toolTip() == EMBEDDED_COPY.show_tip
    assert "Firefox" not in app.window._artists.text()


def test_embedded_socket_turns_helpers_away(qapp, embedded):
    app = embedded[0]
    client = pysock.socket(pysock.AF_UNIX)
    client.connect(app.socket_path)
    client.sendall(encode_frame({
        "protocolVersion": PROTOCOL_VERSION, "kind": "hello",
        "component": "helper", "componentVersion": "0",
    }))
    client.setblocking(False)

    def closed_by_server():
        try:
            return client.recv(1) == b""
        except BlockingIOError:
            return False

    assert pump(qapp, closed_by_server)
    assert app.conn is None
    client.close()


def test_upstream_round_trip_reaches_the_window(qapp, embedded):
    from amberfader.embedded.upstream import EmbeddedUpstream

    app = embedded[0]
    upstream = EmbeddedUpstream()
    state = {
        "bindingToken": "token-1", "revision": 1,
        "track": {
            "occurrenceId": "occ-1", "providerId": None, "title": "Amber Fade",
            "artists": ["Slow Decay"], "album": None, "artworkId": None,
        },
        "status": "paused", "contentKind": "track", "positionSeconds": 0.0,
        "durationSeconds": 187.0, "playbackRate": 1.0, "volume": 0.5, "muted": False,
        "capabilities": ["play"],
    }

    def answer(request):
        upstream.deliver({
            "protocolVersion": PROTOCOL_VERSION, "kind": "response", "id": request["id"],
            "sessionId": "session-1", "bindingToken": "token-1", "ok": True, "result": state,
        })

    upstream.requested.connect(answer)
    app.attach_upstream(upstream)

    assert pump(qapp, lambda: (app.window._state or {}).get("track"))
    assert app.window._title.text() == "Amber Fade"
    assert app._binding_token == "token-1"


def test_main_window_reports_close(qapp):
    from amberfader.ui.main_window import MainWindow

    window = MainWindow(lambda _method, _params: None)
    closed = []
    window.closed.connect(lambda: closed.append(True))
    window.show()
    window.close()

    assert closed == [True]
