"""Embedded prototype end to end in real QtWebEngine (scripted test page).

Skips without the `embedded` extra or the built page bundle
(npm run build), unless AMBERFADER_REQUIRE_EMBEDDED=1 makes that a
failure (CI sets it so the job cannot pass by skipping). Fixtures prove the
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
        _unavailable("embedded extra not installed (uv sync --extra gui --extra embedded)")
    bundle = resources.files("amberfader.embedded") / "web" / "adapter.js"
    if not bundle.is_file():
        _unavailable("page bundle not built (npm run build)")

    env = {
        **os.environ,
        "QT_QPA_PLATFORM": "offscreen",
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
    assert len(report["checks"]) >= 23
