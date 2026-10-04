"""Real Qt menu export on a private X11/session-bus test environment.

This proves the built-in D-Bus exporter, not Plasma's panel rendering or
Wayland association. CI supplies Xvfb, dbus-run-session and distro D-Bus
bindings; ordinary macOS and offscreen runs skip it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DRIVER = Path(__file__).with_name("global_menu_e2e_driver.py")
SYSTEM_PYTHON = "/usr/bin/python3"


def test_exported_mnemonic_lookup():
    from global_menu_e2e_driver import _find

    layout = [0, {}, [[1, {"label": "_Undo"}, []]]]
    assert _find(layout, "Undo")[0] == 1


@pytest.mark.parametrize(("exported", "displayed"), [
    ("_File", "File"),
    ("F_ile", "File"),
    ("Save__copy", "Save_copy"),
    ("_Save__copy", "Save_copy"),
    ("AT&T", "AT&T"),
    ("Finish_", "Finish_"),
])
def test_exported_mnemonic_label(exported, displayed):
    from global_menu_e2e_driver import _display_label

    assert _display_label(exported) == displayed


def test_exported_mnemonic_groups():
    from global_menu_e2e_driver import _display_label

    assert {_display_label(label) for label in ("_File", "_Edit", "_View")} == {
        "File", "Edit", "View",
    }


def test_menu_activation_waits_for_queued_action(qapp):
    from global_menu_e2e_driver import _wait_for
    from PySide6.QtCore import QObject, Qt, Signal
    from PySide6.QtGui import QAction

    class PlatformItem(QObject):
        activated = Signal()

    item = PlatformItem()
    action = QAction("Previous track")
    sent = []
    action.triggered.connect(lambda: sent.append("previous"))
    item.activated.connect(action.trigger, Qt.ConnectionType.QueuedConnection)

    item.activated.emit()
    assert sent == []
    assert _wait_for(qapp, lambda: sent == ["previous"])


def test_menu_activation_wait_has_deadline(qapp):
    from global_menu_e2e_driver import _wait_for

    assert not _wait_for(qapp, lambda: False, timeout_s=0.02)


def test_menu_client_close_preserves_registrar_crash(monkeypatch, tmp_path):
    import global_menu_e2e_driver as driver

    crashed_registrar = tmp_path / "crashed_registrar.py"
    crashed_registrar.write_text('print(\'{"ready": true}\', flush=True)\n')
    monkeypatch.setattr(driver, "SYSTEM_PYTHON", sys.executable)
    monkeypatch.setattr(driver, "REGISTRAR_SCRIPT", crashed_registrar)
    client = driver.MenuClient()
    client.process.wait(timeout=5)

    with pytest.raises(BrokenPipeError):
        client.request("menus", None)
    client.close()
    assert client.process.poll() is not None


def _unavailable(reason: str) -> None:
    if os.environ.get("AMBERFADER_REQUIRE_GLOBAL_MENU") == "1":
        pytest.fail(reason)
    pytest.skip(reason)


def _require_environment() -> None:
    if sys.platform != "linux" or os.environ.get("QT_QPA_PLATFORM") != "xcb":
        _unavailable("global-menu export requires Linux with QT_QPA_PLATFORM=xcb")
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        _unavailable("run inside dbus-run-session and xvfb-run")
    if importlib.util.find_spec("PySide6") is None:
        _unavailable("GUI extra is not installed")
    try:
        bindings = subprocess.run(
            [SYSTEM_PYTHON, "-c", "import dbus; from gi.repository import GLib"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _unavailable(f"distro D-Bus test bindings unavailable: {exc}")
    if bindings.returncode:
        _unavailable(f"install python3-dbus and python3-gi: {bindings.stderr}")


@pytest.mark.parametrize("mode", ["export", "fallback"])
def test_global_menu_protocol_and_face_layout(mode):
    _require_environment()
    try:
        run = subprocess.run(
            [sys.executable, str(DRIVER), mode],
            capture_output=True, text=True, timeout=90, check=False,
            env={**os.environ, "QT_QPA_PLATFORMTHEME": "generic"},
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"menu driver timed out\nstdout:\n{exc.stdout}\nstderr:\n{exc.stderr}")
    reports = [line for line in run.stdout.splitlines() if line.startswith("{")]
    assert reports, f"no driver report\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    report = json.loads(reports[-1])
    assert report["failures"] == [], (
        f"driver report:\n{json.dumps(report, indent=2)}\nstderr:\n{run.stderr}"
    )
    assert run.returncode == 0, (
        f"driver exited {run.returncode}\nstdout:\n{run.stdout}\nstderr:\n{run.stderr}"
    )
    assert len(report["checks"]) >= (12 if mode == "export" else 3), report
