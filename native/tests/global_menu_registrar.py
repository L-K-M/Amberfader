"""Private test registrar and menu client, using Ubuntu's D-Bus bindings."""
from __future__ import annotations

import json
import sys

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

REGISTRAR = "com.canonical.AppMenu.Registrar"
REGISTRAR_PATH = "/com/canonical/AppMenu/Registrar"
MENU_INTERFACE = "com.canonical.dbusmenu"


class Registrar(dbus.service.Object):
    def __init__(self, bus) -> None:
        self._name = dbus.service.BusName(REGISTRAR, bus, do_not_queue=True)
        super().__init__(self._name, REGISTRAR_PATH)
        self.menus: dict[int, dict[str, str]] = {}

    @dbus.service.method(REGISTRAR, in_signature="uo", sender_keyword="sender")
    def RegisterWindow(self, window_id, path, sender=None) -> None:
        self.menus[int(window_id)] = {"service": str(sender), "path": str(path)}

    @dbus.service.method(REGISTRAR, in_signature="u")
    def UnregisterWindow(self, window_id) -> None:
        self.menus.pop(int(window_id), None)

    @dbus.service.method(REGISTRAR, in_signature="u", out_signature="so")
    def GetMenuForWindow(self, window_id):
        menu = self.menus[int(window_id)]
        return menu["service"], dbus.ObjectPath(menu["path"])

    @dbus.service.method(REGISTRAR, out_signature="a(uso)")
    def GetMenus(self):
        return [
            (dbus.UInt32(window_id), menu["service"], dbus.ObjectPath(menu["path"]))
            for window_id, menu in self.menus.items()
        ]


def _json_value(value):
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple | bytes):
        return [_json_value(item) for item in value]
    return value


def _reply(value: dict) -> None:
    print(json.dumps(value), flush=True)


def main() -> int:
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    registrar = Registrar(bus)
    loop = GLib.MainLoop()

    def command(_source, condition):
        if condition & GLib.IO_HUP:
            loop.quit()
            return False
        line = sys.stdin.readline()
        if not line:
            loop.quit()
            return False
        request = json.loads(line)
        try:
            operation = request["operation"]
            if operation == "menus":
                result = {str(key): value for key, value in registrar.menus.items()}
            elif operation == "stop":
                result = True
                loop.quit()
            else:
                menu = dbus.Interface(
                    bus.get_object(request["service"], request["path"], introspect=False),
                    MENU_INTERFACE,
                )

                def completed(*values):
                    result = list(values) if operation == "layout" else True
                    _reply({"id": request["id"], "ok": True, "result": _json_value(result)})

                def failed(error):
                    _reply({"id": request["id"], "ok": False, "error": str(error)})

                # Activation can create another window, whose native menubar
                # synchronously registers here. Keep this GLib loop available
                # while the Qt process handles our outgoing method call.
                if operation == "layout":
                    menu.GetLayout(
                        dbus.Int32(0), dbus.Int32(-1), dbus.Array([], signature="s"),
                        timeout=5, reply_handler=completed, error_handler=failed,
                    )
                elif operation == "event":
                    menu.Event(
                        dbus.Int32(request["item"]), dbus.String("clicked"),
                        dbus.Int32(0, variant_level=1), dbus.UInt32(0),
                        timeout=5, reply_handler=completed, error_handler=failed,
                    )
                else:
                    raise ValueError(f"Unknown operation: {operation}")
                return True
            _reply({"id": request["id"], "ok": True, "result": _json_value(result)})
        except Exception as exc:
            _reply({"id": request["id"], "ok": False, "error": str(exc)})
        return True

    GLib.io_add_watch(sys.stdin, GLib.IO_IN | GLib.IO_HUP, command)
    _reply({"ready": True})
    loop.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
