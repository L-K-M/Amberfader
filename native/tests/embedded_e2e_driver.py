"""End-to-end driver for the embedded browser, run by test_embedded_e2e.py.

Runs the real stack in QtWebEngine: page + injected scripts + QWebChannel +
router + AmberfaderApp + MainWindow, against the scripted test page (the
FakeAdapter). Proves the plumbing, not that YouTube Music accepts any
action. A subprocess is required because QtWebEngine must be
imported before any QApplication exists. Prints one JSON report line.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import sys
import tempfile
import time
from pathlib import Path

TIMEOUT_S = 30.0
# A stand-in for YouTube Music's "Continue watching?" prompt. Clicking its
# container closes it, as continue-playing expects of the real one. Opening
# and dismissing use rendering callbacks to expose hidden-page suspension.
PROMPT_SCRIPT = """(() => {
  window.__amberfaderPromptClosed = false;
  window.__amberfaderPromptOpened = false;
  const container = document.createElement('ytmusic-popup-container');
  const prompt = document.createElement('ytmusic-you-there-renderer');
  prompt.textContent = 'Video paused. Continue watching?';
  container.appendChild(prompt);
  container.addEventListener('click', () => {
    requestAnimationFrame(() => {
      prompt.remove();
      window.__amberfaderPromptClosed = true;
    });
  });
  document.body.appendChild(container);
  requestAnimationFrame(() => {
    window.__amberfaderPromptOpened = true;
    document.dispatchEvent(new CustomEvent('yt-popup-opened'));
  });
})()"""
AD_RESPONSE = (
    "JSON.stringify(JSON.parse('{\"adPlacements\":[1],"
    "\"playerResponse\":{\"playerAds\":[1],\"keep\":2},\"keep\":3}'))"
)


def main() -> int:
    from PySide6 import QtWebEngineWidgets  # noqa: F401
    from PySide6.QtCore import Qt
    from PySide6.QtWebEngineCore import QWebEngineScript
    from PySide6.QtWidgets import QApplication

    from amberfader import PROTOCOL_VERSION
    from amberfader.embedded import page as page_module
    from amberfader.embedded.page import (
        MIN_LAYOUT_WIDTH,
        PageMode,
        load_ad_filter,
        load_bundle,
    )
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
    ), load_bundle(), ad_filter=load_ad_filter())

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

    def desktop_layout():
        # YouTube Music hides its Like button in narrower layouts. One CSS
        # pixel of slack absorbs zoom rounding.
        width = main_world("innerWidth")
        return isinstance(width, int | float) and width >= MIN_LAYOUT_WIDTH - 1

    def zoom():
        return runtime.host.page.zoomFactor()

    def browser_hidden():
        # Qt keeps the view shown for rendering without mapping its window.
        return runtime.host.window.testAttribute(
            Qt.WidgetAttribute.WA_DontShowOnScreen,
        )

    def continue_playing(name):
        main_world(PROMPT_SCRIPT)
        check(f"{name}: prompt dismissed", pump(
            lambda: main_world("window.__amberfaderPromptClosed") is True, timeout=5,
        ))
        check(f"{name}: browser stays hidden", browser_hidden())

    def report():
        runtime.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
        failures = [name for name, passed in checks.items() if not passed]
        print(json.dumps({"checks": checks, "failures": failures}))
        return 0 if not failures else 1

    def run_checks():
        if not runtime.start():
            check("runtime started", False)
            return
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
            return  # every later step needs an attached page
        first_token = bound_tokens()[0]

        # The browser window was never shown, as with --background. A page
        # behind it would otherwise lay out 0 px wide.
        check("hidden start lays out at desktop width", desktop_layout())
        check("hidden start stays hidden", browser_hidden())
        continue_playing("continue playing after hidden start")

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
        check("show window", ok and runtime.host.window.isVisible() and not browser_hidden())

        # A narrow window zooms the page out, and zooming in stops at the
        # desktop width. A wide window returns to the zoom you chose.
        browser = runtime.host.window
        browser.resize(600, 700)
        check("narrow window keeps a desktop layout", pump(desktop_layout, timeout=5))
        runtime.host.page.setZoomFactor(2.0)  # as Ctrl+wheel does
        check("zooming in keeps a desktop layout", pump(desktop_layout, timeout=5))
        runtime.host.page.setZoomFactor(1.0)
        browser.resize(1300, 800)
        check("wide window shows the chosen zoom", pump(
            lambda: abs(zoom() - 1.0) < 1e-3
            and abs(main_world("innerWidth") - browser.view.width()) <= 1,
            timeout=5,
        ))
        browser.resize(1100, 800)

        _, ok, _ = call("browser.hidePlayer")
        check("hide window", ok and browser_hidden())

        # Page scripts run in the main world and must not reach the bridge.
        check("bridge isolated from page scripts", main_world(
            "typeof qt === 'undefined' && typeof QWebChannel === 'undefined'"
            " && typeof __AMBERFADER_EMBEDDED__ === 'undefined'"
        ) is True)

        # Both built-in features are on by default.
        check("ad filter strips player ads in the main world",
              main_world(AD_RESPONSE) == '{"playerResponse":{"keep":2},"keep":3}')
        continue_playing("continue playing after hiding")

        call("browser.showPlayer")
        browser.close()
        continue_playing("continue playing after closing the browser")

        # A reload is a new document: new binding, old token rejected.
        runtime.host.load()
        check("rebound after reload", pump(lambda: len(set(bound_tokens())) >= 2))
        new_token = bound_tokens()[-1]
        check("state after reload", pump(
            lambda: states() and states()[-1]["bindingToken"] == new_token,
        ))
        _, ok, _ = call("player.pause")
        check("command after reload", ok)
        continue_playing("continue playing after hidden reload")

        session = next(m["sessionId"] for m in messages if "sessionId" in m)
        runtime.upstream.send({
            "protocolVersion": PROTOCOL_VERSION, "kind": "request", "id": "stale-1",
            "sessionId": session, "bindingToken": first_token,
            "method": "player.play", "params": {},
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

        # Leave the window narrow, so the new renderer below must get the
        # fitted zoom as well as a size.
        call("browser.showPlayer")
        browser.resize(600, 700)
        pump(desktop_layout, timeout=5)
        call("browser.hidePlayer")

        # A renderer exit revokes the binding; reloading recovers.
        revoked_before = len([m for m in messages if m.get("event") == "binding"
                              and m["data"]["status"] == "revoked"])
        # pid 0 would signal the whole process group, this driver included.
        if renderer := runtime.host.page.renderProcessPid():
            os.kill(renderer, signal.SIGKILL)
        check("renderer exit revokes binding", pump(lambda: len([
            m for m in messages
            if m.get("event") == "binding" and m["data"]["status"] == "revoked"
        ]) > revoked_before))
        tokens_before = len(set(bound_tokens()))
        runtime.host.load()
        check("reattached after renderer exit", pump(
            lambda: len(set(bound_tokens())) > tokens_before,
        ))
        _, ok, _ = call("player.play")
        check("command after renderer exit", ok)
        # The new renderer loaded behind the hidden window.
        check("hidden reload lays out at desktop width", pump(desktop_layout, timeout=5))
        check("hidden reload stays hidden", browser_hidden())
        check("hidden reload keeps the fitted zoom", abs(zoom() - 600 / MIN_LAYOUT_WIDTH) < 1e-3)
        continue_playing("continue playing after renderer recovery")

        # The menu switches turn both features off from the next load.
        options = {action.text(): action for action in window._playback_menu.actions()}
        options["Block ads"].setChecked(False)
        options["Continue playing automatically"].setChecked(False)
        check("switches off", not runtime.settings.block_ads
              and not runtime.settings.continue_playing and not runtime.ad_requests.enabled)
        tokens_before = len(set(bound_tokens()))
        runtime.host.load()
        check("reattached after switching off", pump(
            lambda: len(set(bound_tokens())) > tokens_before,
        ))
        check("ad filter off after reload", main_world(
            "JSON.parse('{\"adPlacements\":[1]}').adPlacements.length",
        ) == 1)
        main_world(PROMPT_SCRIPT)
        check("prompt opens when continue playing is off", pump(
            lambda: main_world("window.__amberfaderPromptOpened") is True, timeout=5,
        ))
        pump(lambda: False, timeout=1)
        check("prompt left open when continue playing is off",
              main_world("window.__amberfaderPromptClosed") is False)

    try:
        run_checks()
    except Exception as exc:  # report what passed so far instead of dying silently
        check(f"driver crashed: {type(exc).__name__}: {exc}", False)
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
