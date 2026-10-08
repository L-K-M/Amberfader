"""The embedded browser end to end in real QtWebEngine (scripted test page).

Skips without Qt WebEngine or the built page scripts (npm run build),
unless AMBERFADER_REQUIRE_EMBEDDED=1 makes that a failure (CI sets it so the
job cannot pass by skipping). Fixtures prove the
bridge; they never prove that YouTube Music accepts an action.
"""
import importlib.util
import json
import os
import subprocess
import sys
from importlib import resources
from pathlib import Path

import pytest

DRIVER = Path(__file__).with_name("embedded_e2e_driver.py")


def _unavailable(reason):
    if os.environ.get("AMBERFADER_REQUIRE_EMBEDDED") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def test_embedded_stack_end_to_end():
    try:
        webengine = importlib.util.find_spec("PySide6.QtWebEngineWidgets")
    except ImportError:
        webengine = None
    if webengine is None:
        _unavailable("Qt WebEngine not installed (uv sync)")
    scripts = resources.files("amberfader.embedded") / "web"
    if not all((scripts / name).is_file() for name in ("adapter.js", "ad-filter.js")):
        _unavailable("page scripts not built (npm run build)")

    env = {
        **os.environ,
        # Native Cocoa exercises concealed-window rendering on macOS.
        "QT_QPA_PLATFORM": "cocoa" if sys.platform == "darwin" else "offscreen",
        # Chromium's sandbox needs user namespaces that CI runners and
        # containers often deny. The test page loads no remote content.
        "QTWEBENGINE_DISABLE_SANDBOX": "1",
    }
    try:
        run = subprocess.run(
            [sys.executable, str(DRIVER)],
            capture_output=True, text=True, timeout=180, env=env, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"driver timed out\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}")
    reports = [line for line in run.stdout.splitlines() if line.startswith("{")]
    assert reports, f"driver produced no report\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    report = json.loads(reports[-1])

    assert report["failures"] == [], report
    assert run.returncode == 0, (
        f"driver exited {run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    )
    for context in (
        "hidden start", "hiding", "closing the browser", "hidden reload", "renderer recovery",
    ):
        assert report["checks"][f"continue playing after {context}: prompt dismissed"]
        assert report["checks"][f"continue playing after {context}: browser stays hidden"]

    assert len(report["checks"]) >= 23


def test_self_test_reports_each_check_and_a_disabled_sandbox():
    """`amberfader --self-test` drives the real stack. With Chromium's sandbox
    disabled, as CI must, every functional check passes and the sandbox
    check fails, so the run fails. Package builds run it with the sandbox."""
    try:
        webengine = importlib.util.find_spec("PySide6.QtWebEngineWidgets")
    except ImportError:
        webengine = None
    if webengine is None:
        _unavailable("Qt WebEngine not installed (uv sync)")
    scripts = resources.files("amberfader.embedded") / "web"
    if not all((scripts / name).is_file() for name in ("adapter.js", "ad-filter.js")):
        _unavailable("page scripts not built (npm run build)")

    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QTWEBENGINE_DISABLE_SANDBOX": "1"}
    run = subprocess.run(
        [sys.executable, "-m", "amberfader", "--self-test"],
        capture_output=True, text=True, timeout=180, env=env, check=False,
    )
    lines = run.stdout.splitlines()
    expected = [
        "self-test: attach: ok", "self-test: player.play: ok", "self-test: player.pause: ok",
        "self-test: search.songs: ok", "self-test: search.playResult: ok",
        "self-test: ad filter: ok",
    ]
    assert lines[:len(expected)] == expected, run.stdout + run.stderr
    if sys.platform.startswith("linux"):
        assert "self-test: renderer sandbox: FAILED (off)" in lines
        assert lines[-1] == "amberfader self-test: FAILED"
        assert run.returncode == 1
