"""amberfader --self-test: proves that an installed Amberfader can start Qt
WebEngine, inject its page scripts and drive them, without network access or
a Google account. Package smoke tests run it.

It loads the scripted test page, then checks attach, play, pause, search,
play result and the ad filter. On Linux it also requires Chromium's renderer
sandbox: every renderer process must run in a PID namespace of its own and
under a seccomp filter of its own, so a silent fallback to no sandbox fails
the test, also inside a container or Flatpak whose filter every process
inherits. macOS has no such check yet.

Prints one line per check and a final verdict; exit status 0 means passed.
"""
from __future__ import annotations

import os
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication
from PySide6.QtWebEngineCore import QWebEngineScript

from .runtime import EmbeddedRuntime

TIMEOUT_S = 60.0
STEP_TIMEOUT_S = 15.0
PASSED = "amberfader self-test: passed"
FAILED = "amberfader self-test: FAILED"
AD_PROBE = "JSON.stringify(JSON.parse('{\"adPlacements\":[1],\"keep\":1}'))"


def _parent_pid(proc: Path, pid: int) -> int | None:
    try:
        for line in (proc / str(pid) / "status").read_text().splitlines():
            if line.startswith("PPid:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _status(proc: Path, pid: int) -> dict[str, str]:
    """/proc/<pid>/status as fields, e.g. {"PPid": "1", "Seccomp": "2"};
    empty when the process is gone."""
    try:
        lines = (proc / str(pid) / "status").read_text().splitlines()
    except OSError:
        return {}
    return {
        key: value.strip()
        for key, sep, value in (line.partition(":") for line in lines) if sep
    }


def _pid_namespace_depth(status: dict[str, str]) -> int:
    # NSpid lists the PID in each namespace from /proc's down to the process's.
    return len(status.get("NSpid", "").split())


def _sandboxed(renderer: dict[str, str], argv: list[bytes], browser: dict[str, str]) -> str:
    """'on', 'off' or 'unknown' for one renderer. Both of Chromium's layers
    must show, measured against the browser process, because a container or
    Flatpak gives every process a seccomp filter and a PID namespace:
      layer 1, a PID namespace below the browser's (namespace sandbox);
      layer 2, a seccomp filter on top of the browser's (seccomp-bpf).
    Kernels before 5.9 do not count filters; a browser without a filter of
    its own still proves layer 2, a filtered one leaves it unknown."""
    if b"--no-sandbox" in argv or renderer.get("Seccomp") != "2":
        return "off"
    if _pid_namespace_depth(renderer) <= _pid_namespace_depth(browser):
        return "off"
    own, inherited = renderer.get("Seccomp_filters"), browser.get("Seccomp_filters")
    if own is not None and inherited is not None:
        return "on" if int(own) > int(inherited) else "off"
    return "on" if browser.get("Seccomp") == "0" else "unknown"


def _descends_from(proc: Path, pid: int, ancestor: int) -> bool:
    seen: set[int] = set()
    current: int | None = pid
    while current and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = _parent_pid(proc, current)
    return False


def _argv(proc: Path, pid: int) -> list[bytes]:
    try:
        return (proc / str(pid) / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return []


def _is_webengine(argv: list[bytes]) -> bool:
    return bool(argv) and argv[0].endswith(b"QtWebEngineProcess")


def renderer_sandbox(proc: Path = Path("/proc"), root_pid: int | None = None) -> str:
    """'on' when every Qt WebEngine renderer below `root_pid` is sandboxed
    (see _sandboxed), 'off' when one is not, 'unknown' when the kernel cannot
    tell, 'absent' when no renderer was found.

    Chromium forks renderers from its sandboxed zygote, and they keep the
    zygote's command line (`--type=zygote`). With the namespace sandbox the
    zygote also sits below an init process with that same command line. So a
    renderer is a sandboxed-zygote process whose parent is one too and that
    has no such child itself (observed with Qt WebEngine 6.11, with and
    without the sandbox). Processes started as `--type=renderer` count too.
    Call it once a page has loaded: before the first renderer exists, the
    zygote itself looks like one."""
    root_pid = os.getpid() if root_pid is None else root_pid
    pids = [int(e.name) for e in proc.iterdir() if e.name.isdigit()] if proc.is_dir() else []
    argvs = {pid: _argv(proc, pid) for pid in pids}
    parents = {pid: _parent_pid(proc, pid) for pid in pids}

    def sandboxed_zygote(pid: int | None) -> bool:
        argv = argvs.get(pid, []) if pid is not None else []
        return (_is_webengine(argv) and b"--type=zygote" in argv
                and b"--no-zygote-sandbox" not in argv)

    zygote_parents = {parents[pid] for pid in pids if sandboxed_zygote(pid)}
    renderers = [
        pid for pid, argv in argvs.items()
        if _descends_from(proc, pid, root_pid) and (
            (_is_webengine(argv) and b"--type=renderer" in argv)
            or (sandboxed_zygote(pid) and sandboxed_zygote(parents[pid])
                and pid not in zygote_parents)
        )
    ]
    if not renderers:
        return "absent"
    browser = _status(proc, root_pid)
    states = {_sandboxed(_status(proc, pid), argvs[pid], browser) for pid in renderers}
    for state in ("off", "unknown"):
        if state in states:
            return state
    return "on"


class SelfTest:
    def __init__(
        self, runtime: EmbeddedRuntime, out: Callable[[str], None] = print,
        platform: str = sys.platform,
    ) -> None:
        self._runtime = runtime
        self._out = out
        self._platform = platform
        self._messages: list[dict[str, Any]] = []
        self._responses: list[tuple[str, bool, dict[str, Any]]] = []
        self._deadline = time.monotonic() + TIMEOUT_S
        self._failed = False

    def run(self) -> int:
        runtime = self._runtime
        runtime.upstream.messageReceived.connect(self._messages.append)
        window = runtime.amber.window
        assert window is not None
        forward = window.route_response

        def record(method: str, ok: bool, payload: dict[str, Any]) -> None:
            self._responses.append((method, ok, payload))
            forward(method, ok, payload)

        window.route_response = record  # type: ignore[method-assign]
        try:
            self._checks()
        except _Expired:
            self._report("time limit", False, f"{TIMEOUT_S:.0f} s")
        except Exception as exc:  # the verdict line must still print
            self._report("unexpected error", False, type(exc).__name__)
        self._out(FAILED if self._failed else PASSED)
        return 1 if self._failed else 0

    def _checks(self) -> None:
        attached = self._wait(lambda: self._bound() and self._track())
        self._report("attach", bool(attached))
        if not attached:
            return

        for method, status in (("player.play", "playing"), ("player.pause", "paused")):
            ok = self._call(method)
            observed = ok and self._wait(lambda s=status: self._status() == s)
            self._report(method, bool(observed))

        ok, found = self._call_with("search.songs", {"query": "amber"})
        rows = [row for row in (found.get("results") or []) if row.get("supported")]
        self._report("search.songs", ok and bool(rows))
        if rows:
            self._report("search.playResult", self._call("search.playResult", {
                "searchToken": found["searchToken"], "resultId": rows[0]["resultId"],
            }))

        if self._runtime.settings.block_ads:
            self._report("ad filter", self._main_world(AD_PROBE) == '{"keep":1}')

        if self._platform.startswith("linux"):
            state = renderer_sandbox()
            self._report("renderer sandbox", state == "on", state)
        else:
            self._out("self-test: renderer sandbox: not checked on this platform")

    # ---- helpers ------------------------------------------------------------

    def _report(self, name: str, ok: bool, detail: str = "") -> None:
        if not ok:
            self._failed = True
        suffix = f" ({detail})" if detail else ""
        self._out(f"self-test: {name}: {'ok' if ok else 'FAILED'}{suffix}")

    def _wait(self, condition: Callable[[], Any], timeout: float = STEP_TIMEOUT_S) -> Any:
        end = min(self._deadline, time.monotonic() + timeout)
        while True:
            QCoreApplication.processEvents()
            value = condition()
            if value:
                return value
            if time.monotonic() >= self._deadline:
                raise _Expired
            if time.monotonic() >= end:
                return value
            time.sleep(0.01)

    def _states(self) -> list[dict[str, Any]]:
        return [m["data"] for m in self._messages if m.get("event") == "state"]

    def _bound(self) -> bool:
        return any(
            m.get("event") == "binding" and m["data"].get("status") == "bound"
            for m in self._messages
        )

    def _track(self) -> bool:
        return any(state.get("track") for state in self._states())

    def _status(self) -> str | None:
        states = self._states()
        return states[-1].get("status") if states else None

    def _call_with(self, method: str, params: dict[str, Any] | None = None
                   ) -> tuple[bool, dict[str, Any]]:
        before = len(self._responses)
        self._runtime.amber.request(method, params or {})
        found = self._wait(lambda: [r for r in self._responses[before:] if r[0] == method])
        if not found:
            return False, {}
        _, ok, payload = found[0]
        return ok, payload

    def _call(self, method: str, params: dict[str, Any] | None = None) -> bool:
        return self._call_with(method, params)[0]

    def _main_world(self, script: str) -> Any:
        page = self._runtime.host.page
        if page is None:
            return None
        result: list[Any] = []
        page.runJavaScript(
            script, int(QWebEngineScript.ScriptWorldId.MainWorld.value), result.append,
        )
        self._wait(lambda: result, timeout=5)
        return result[0] if result else None


class _Expired(Exception):
    pass
