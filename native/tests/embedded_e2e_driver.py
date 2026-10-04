"""End-to-end driver for the embedded prototype, run by test_embedded_e2e.py.

Runs the real stack in QtWebEngine: page + injected bundle + QWebChannel +
router + AmberfaderApp + MainWindow, against the scripted test page (the
extension's FakeAdapter). Proves the plumbing, not that YouTube Music
accepts any action. A subprocess is required because QtWebEngine must be
imported before any QApplication exists. Prints one JSON report line.
"""
from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

TIMEOUT_S = 30.0


def main() -> int:
    from PySide6 import QtWebEngineWidgets  # noqa: F401
    from PySide6.QtWebEngineCore import QWebEngineScript
    from PySide6.QtWidgets import QApplication

    from amberfader import PROTOCOL_VERSION
    from amberfader.embedded import page as page_module
    from amberfader.embedded.page import PageMode, load_bundle
    from amberfader.embedded.runtime import EmbeddedRuntime, RuntimeOptions

    # Never launch a real browser from a test: record the hand-off instead.
    handed_off: list[str] = []

    class _SystemBrowser:
        @staticmethod
        def openUrl(url):
            handed_off.append(url.toString())
            return True

    page_module.QDesktopServices = _SystemBrowser

    app = QApplication(sys.argv[:1])
    tmp = Path(tempfile.mkdtemp(prefix="amberfader-e2e-"))
    runtime = EmbeddedRuntime(RuntimeOptions(
        mode=PageMode.TEST_PAGE,
        socket_path=str(tmp / "embedded.sock"),
        history_path=tmp / "history.json",
        profile_storage=tmp / "profile",
        profile_cache=tmp / "cache",
    ), load_bundle())

    messages: list[dict] = []
    responses: list[tuple[str, bool, dict]] = []
    runtime.upstream.messageReceived.connect(messages.append)
    checks: dict[str, bool] = {}

    def pump(condition, timeout=TIMEOUT_S):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            value = condition()
            if value:
                return value
            time.sleep(0.01)
        return condition()

    def check(name, passed):
        checks[name] = bool(passed)

    def states():
        return [m["data"] for m in messages if m.get("event") == "state"]

    def bound_tokens():
        return [
            m["bindingToken"] for m in messages
            if m.get("event") == "binding" and m["data"]["status"] == "bound"
        ]

    def call(method, params=None):
        before = len(responses)
        runtime.amber.request(method, params or {})
        found = pump(lambda: [r for r in responses[before:] if r[0] == method])
        return found[0] if found else (method, False, {"message": "no response"})

    def main_world(script):
        result: list = []
        runtime.host.page.runJavaScript(
            script, int(QWebEngineScript.ScriptWorldId.MainWorld.value), result.append,
        )
        pump(lambda: result, timeout=5)
        return result[0] if result else None

    def report():
        runtime.shutdown()
        failures = [name for name, passed in checks.items() if not passed]
        print(json.dumps({"checks": checks, "failures": failures}))
        return 0 if not failures else 1

    if not runtime.start():
        check("runtime started", False)
        return report()
    window = runtime.amber.window
    record_original = window.route_response

    def record(method, ok, payload):
        responses.append((method, ok, payload))
        record_original(method, ok, payload)

    window.route_response = record

    # Attach: the page registers, the client learns the binding and state.
    check("attached", pump(lambda: bound_tokens() and any(s.get("track") for s in states())))
    check("client applied state", pump(lambda: (window._state or {}).get("track")))
    if not all(checks.values()):
        return report()  # every later step needs an attached page
    first_token = bound_tokens()[0]

    _, ok, _ = call("player.play")
    check("play ok", ok)
    check("observed playing", pump(lambda: states() and states()[-1]["status"] == "playing"))

    title = states()[-1]["track"]["title"]
    _, ok, _ = call("player.next")
    check("next ok", ok)
    check("observed next track", pump(lambda: states()[-1]["track"]["title"] != title))

    _, ok, found = call("search.songs", {"query": "amber"})
    rows = found.get("results") or []
    check("search ok", ok and rows)
    playable = [row for row in rows if row.get("supported")]
    if playable:
        _, ok, _ = call("search.playResult", {
            "searchToken": found["searchToken"], "resultId": playable[0]["resultId"],
        })
        check("play result ok", ok)
    _, ok, history = call("search.history")
    check("history recorded query", ok and history.get("queries") == ["amber"])

    occurrence = states()[-1]["track"]["occurrenceId"]
    _, ok, _ = call("player.setLiked", {"occurrenceId": occurrence, "liked": True})
    check("like ok", ok)
    check("observed liked", pump(lambda: states()[-1].get("liked") is True))

    _, ok, _ = call("browser.showPlayer")
    check("show window", ok and runtime.host.window.isVisible())
    _, ok, _ = call("browser.hidePlayer")
    check("hide window", ok and not runtime.host.window.isVisible())

    # Page scripts run in the main world and must not reach the bridge.
    check("bridge isolated from page scripts", main_world(
        "typeof qt === 'undefined' && typeof QWebChannel === 'undefined'"
        " && typeof __AMBERFADER_EMBEDDED__ === 'undefined'"
    ) is True)

    # A reload is a new document: new binding, old token rejected.
    runtime.host.load()
    check("rebound after reload", pump(lambda: len(set(bound_tokens())) >= 2))
    new_token = bound_tokens()[-1]
    check("state after reload", pump(
        lambda: states() and states()[-1]["bindingToken"] == new_token,
    ))
    _, ok, _ = call("player.pause")
    check("command after reload", ok)

    session = next(m["sessionId"] for m in messages if "sessionId" in m)
    runtime.upstream.send({
        "protocolVersion": PROTOCOL_VERSION, "kind": "request", "id": "stale-1",
        "sessionId": session, "bindingToken": first_token, "method": "player.play", "params": {},
    })
    stale = pump(lambda: [m for m in messages if m.get("id") == "stale-1"])
    check("old binding rejected", stale and stale[0]["error"]["code"] == "stale_target")

    # Page content cannot take the view elsewhere; web links go to the
    # system browser instead.
    main_world("location.href = 'https://www.example.org/artist'")
    check("foreign link handed to system browser", pump(
        lambda: "https://www.example.org/artist" in handed_off, timeout=10,
    ))
    check("view stayed on its page", runtime.host.on_home_origin())

    # A renderer exit revokes the binding; reloading recovers.
    revoked_before = len([m for m in messages if m.get("event") == "binding"
                          and m["data"]["status"] == "revoked"])
    os.kill(runtime.host.page.renderProcessPid(), signal.SIGKILL)
    check("renderer exit revokes binding", pump(lambda: len([
        m for m in messages
        if m.get("event") == "binding" and m["data"]["status"] == "revoked"
    ]) > revoked_before))
    tokens_before = len(set(bound_tokens()))
    runtime.host.load()
    check("reattached after renderer exit", pump(lambda: len(set(bound_tokens())) > tokens_before))
    _, ok, _ = call("player.play")
    check("command after renderer exit", ok)
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
