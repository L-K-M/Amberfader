"""Exercise exported menus through an independent D-Bus process."""
from __future__ import annotations

import json
import select
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path

REGISTRAR_SCRIPT = Path(__file__).with_name("global_menu_registrar.py")
SYSTEM_PYTHON = "/usr/bin/python3"
TIMEOUT_SECONDS = 10
ACTIVATION_TIMEOUT_SECONDS = 5


class MenuClient:
    def __init__(self) -> None:
        self.process = subprocess.Popen(
            [SYSTEM_PYTHON, str(REGISTRAR_SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        self._serial = 0
        try:
            if self._read() != {"ready": True}:
                raise RuntimeError("The private registrar did not become ready")
        except Exception:
            self.close()
            raise

    def _read(self, app=None):
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if app is not None:
                app.processEvents()
            if select.select([self.process.stdout], [], [], 0.01)[0]:
                line = self.process.stdout.readline()
                if line:
                    return json.loads(line)
                raise RuntimeError(f"Registrar stopped: {self.process.stderr.read()}")
            if self.process.poll() is not None:
                raise RuntimeError(f"Registrar failed: {self.process.stderr.read()}")
        raise TimeoutError("The private registrar did not answer within 10 seconds")

    def request(self, operation: str, app, **params):
        self._serial += 1
        self.process.stdin.write(json.dumps({
            "id": self._serial, "operation": operation, **params,
        }) + "\n")
        self.process.stdin.flush()
        response = self._read(app)
        if response.get("id") != self._serial or response.get("ok") is not True:
            raise RuntimeError(f"Menu protocol call failed: {response}")
        return response["result"]

    def close(self) -> None:
        # A crashed child can leave failed writes buffered. Its pipe flush
        # must not replace the original driver failure report.
        with suppress(OSError):
            self.process.stdin.close()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def _items(layout):
    _, properties, children = layout
    yield layout[0], properties
    for child in children:
        yield from _items(child)


def _display_label(label: str) -> str:
    """Decode D-Bus menu mnemonics without removing literal underscores."""
    characters = []
    index = 0
    while index < len(label):
        character = label[index]
        if character != "_":
            characters.append(character)
            index += 1
        elif index + 1 < len(label) and label[index + 1] == "_":
            characters.append("_")
            index += 2
        elif index + 1 < len(label):
            index += 1
        else:
            characters.append("_")
            index += 1
    return "".join(characters)


def _find(layout, label: str):
    matches = [
        (item, properties) for item, properties in _items(layout)
        if _display_label(properties.get("label", "")) == label
    ]
    if len(matches) != 1:
        raise AssertionError(f"Expected one exported {label!r}, found {matches}")
    return matches[0]


def _wait_for(app, condition, *, timeout_s: float = ACTIVATION_TIMEOUT_SECONDS) -> bool:
    """Observe one menu event's queued QAction without replaying the event."""
    deadline = time.monotonic() + timeout_s
    while True:
        app.processEvents()
        if condition():
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(0.01, remaining))


def _state(capabilities):
    return {
        "bindingToken": "menu-test-binding", "revision": 1,
        "track": {
            "occurrenceId": "menu-test-track", "providerId": None,
            "title": "Menu test", "artists": ["Test artist"], "album": None,
            "artworkId": None,
        },
        "status": "paused", "contentKind": "track", "positionSeconds": 0,
        "durationSeconds": 120, "playbackRate": 1, "volume": 0.5, "muted": False,
        "liked": False, "capabilities": capabilities,
    }


def main(mode: str) -> int:
    # The registrar must exist before Qt constructs the first native menubar:
    # QGenericUnixTheme caches its initial availability check.
    client = MenuClient() if mode == "export" else None
    checks: dict[str, bool] = {}

    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtDBus import QDBusConnection
    from PySide6.QtWidgets import QApplication, QMessageBox

    from amberfader.face_library import FaceLibrary
    from amberfader.ui.main_window import MainWindow

    app = QApplication([])
    # Failure cleanup must also be noninteractive after an editor is opened.
    QMessageBox.warning = lambda *args: QMessageBox.StandardButton.Discard
    temporary = tempfile.TemporaryDirectory(prefix="af-global-menu-")
    directory = Path(temporary.name)
    sent = []
    player = None
    editor = None

    def check(name, passed) -> None:
        checks[name] = bool(passed)
        if not passed:
            raise AssertionError(name)

    def layout(endpoint):
        return client.request("layout", app, **endpoint)[1]

    try:
        if mode == "fallback":
            check("private bus has no registrar", not QDBusConnection.sessionBus().interface()
                  .isServiceRegistered("com.canonical.AppMenu.Registrar").value())
        player = MainWindow(
            lambda method, params: sent.append((method, params)),
            faces=FaceLibrary(directory / "installed", directory / "appearance.json"),
        )
        player.show()
        app.processEvents()
        bar = player.menuBar()
        check("player menu stays hidden", bar.isHidden())
        check("face occupies unchanged player geometry", player._surface.geometry().x() == 0
              and player._surface.geometry().y() == 0
              and player._surface.size() == player.size())
        if mode == "fallback":
            check("unsupported native menu falls back", not bar.isNativeMenuBar())
            player._menu.popup(player.mapToGlobal(player.rect().center()))
            app.processEvents()
            check("face popup remains available", player._menu.isVisible())
            player._menu.hide()
        else:
            check("player uses native exporter", bar.isNativeMenuBar())
            endpoints = client.request("menus", app)
            player_endpoint = endpoints[str(int(player.winId()))]
            player_layout = layout(player_endpoint)
            labels = {
                _display_label(child[1].get("label", ""))
                for child in player_layout[2]
            }
            check("player exports complete menu groups", labels == {
                "File", "Playback", "View", "Window",
            })
            check("disconnected transport is disabled", not bool(
                _find(player_layout, "Previous track")[1].get("enabled", True),
            ))

            player.apply_state(_state(["previous", "play", "next"]))
            app.processEvents()
            previous, properties = _find(layout(player_endpoint), "Previous track")
            check("observed capability enables exported action", bool(
                properties.get("enabled", True),
            ))
            client.request("event", app, **player_endpoint, item=previous)
            # Qt queues platform-menu activation to QAction::trigger. The
            # D-Bus Event reply confirms receipt, before this queued outcome.
            check("D-Bus activation reaches command callback", _wait_for(
                app, lambda: sent == [("player.previous", {})],
            ))

            player.apply_state(_state([]))
            app.processEvents()
            check("capability loss disables exported action", not bool(
                _find(layout(player_endpoint), "Previous track")[1].get("enabled", True),
            ))
            client.request("event", app, **player_endpoint, item=previous)
            app.processEvents()
            check("disabled exported action cannot send playback work", sent == [
                ("player.previous", {}),
            ])
            player._menu.popup(player.mapToGlobal(player.rect().center()))
            app.processEvents()
            check("face popup coexists with native export", player._menu.isVisible())
            player._menu.hide()
            face_editor, _ = _find(layout(player_endpoint), "Face editor…")
            client.request("event", app, **player_endpoint, item=face_editor)
            check("D-Bus activation opens independent editor", _wait_for(
                app, lambda: player._face_editor is not None and player._face_editor.isVisible(),
            ))
            editor = player._face_editor
            check("editor uses native exporter", editor.menuBar().isNativeMenuBar())
            app.processEvents()
            endpoints = client.request("menus", app)
            editor_endpoint = endpoints[str(int(editor.winId()))]
            check("windows export distinct menu endpoints", editor_endpoint != player_endpoint)
            editor_layout = layout(editor_endpoint)
            editor_labels = {
                _display_label(child[1].get("label", ""))
                for child in editor_layout[2]
            }
            check("editor exports its menus", editor_labels == {
                "File", "Edit", "View", "Element", "Face", "Window", "Help",
            })
            check("clean editor undo is disabled", not bool(
                _find(editor_layout, "Undo")[1].get("enabled", True),
            ))
            original = editor.document.manifest["controls"]["play"]
            editor.document.set_rotation("play", 15)
            editor._changed()
            app.processEvents()
            undo, properties = _find(layout(editor_endpoint), "Undo")
            check("document edit enables exported Undo", bool(properties.get("enabled", True)))
            client.request("event", app, **editor_endpoint, item=undo)
            check("D-Bus Undo restores document", _wait_for(
                app, lambda: editor.document.manifest["controls"]["play"] == original
                and not editor.document.manifest.get("controlRotations", {}).get("play"),
            ))
            check("Undo does not issue playback work", sent == [("player.previous", {})])
            check("Undo disabled after undoing only edit", not bool(
                _find(layout(editor_endpoint), "Undo")[1].get("enabled", True),
            ))
            app.setActiveWindow(player)
            app.processEvents()
            check("focus keeps each window's menu association", client.request("menus", app)
                  == endpoints)
            check("face geometry survives editor and focus", player._surface.size() == player.size()
                  and player._surface.geometry().y() == 0 and bar.isHidden())

            # Closing hides retained widgets. Destruction releases their native
            # bars and must unregister both window endpoints from the registrar.
            editor.close()
            editor.deleteLater()
            player._face_editor = None
            player.close()
            player.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            editor = player = None
            check("destroyed windows unregister endpoints", client.request("menus", app) == {})
    except Exception as exc:
        checks[f"driver failed: {type(exc).__name__}: {exc}"] = False
    finally:
        if editor is not None:
            editor.hide()
        if player is not None:
            player.close()
        if client is not None:
            client.close()
        temporary.cleanup()
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failures": failures}), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
