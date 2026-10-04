# KDE global menu

The native player and face editor use [Qt's native menu
integration](https://doc.qt.io/qt-6/qmenubar.html#nativeMenuBar-prop). These
menus are available in updated source builds; v0.1.9 predates this change.

On Plasma, add the **Global Menu** widget to your panel, then start Amberfader.
If you enable the widget after starting the app, restart Amberfader so Qt can
discover the menu registrar. Each main window exports its own menu:

- Player: **File**, **Playback**, **View**, and **Window**. The menus open faces,
  the editor, search and cover view, control playback, show or hide YouTube
  Music, minimize the player, or close it.
- Face editor: **File**, **Edit**, and **View**, using the same actions as its
  toolbar. Undo/Redo availability follows your document.

Playback menu actions use the existing player command path. Their labels and
availability follow reported playback, capabilities, and pending requests.
The menu does not add playback retries or change the selected face.

The player keeps its shaped layout and its **☰** popup when a global menu is
available or absent. The editor retains its normal local menu on desktops
without native menu integration. macOS uses its system menu bar.

## Packaging and desktop integration

Qt exports menus through the session bus using
`com.canonical.AppMenu.Registrar` and `com.canonical.dbusmenu`.
The Debian package declares its D-Bus runtime library. The Flatpak grants only
`--talk-name=com.canonical.AppMenu.Registrar`; it does not grant the entire
session bus. Check the installed Flatpak permission with:

```sh
flatpak info --show-permissions ch.lkmc.amberfader
```

Its session-bus policy must include `com.canonical.AppMenu.Registrar=talk`.
Desktop or Qt platform-theme settings that disable native menus can prevent
export. No extra KDE platform-theme plugin is required by the bundled Qt
exporter.

On Wayland, Qt also associates each menu with its surface through the
compositor's app-menu protocol. Actual panel rendering and surface association
require a Plasma desktop check.

## Verification

CI starts a private D-Bus session and Xvfb, owns a test registrar before Qt
starts, and calls the actual exported menu's `GetLayout` and `Event` methods.
It checks activation, disabled actions, document Undo, separate player/editor
endpoints, unchanged face geometry, destruction cleanup, and the popup fallback
without a registrar. This exercises the Linux exporter with the shipped Qt
libraries. Offscreen unit tests cover action/state behavior and all face layouts.

The Linux protocol test can be run with the distro D-Bus bindings, Xvfb, and Qt
X11 libraries installed as in the CI configuration:

```sh
dbus-run-session -- xvfb-run -a env \
  QT_QPA_PLATFORM=xcb QT_QPA_PLATFORMTHEME=generic \
  AMBERFADER_REQUIRE_GLOBAL_MENU=1 \
  uv run pytest native/tests/test_global_menu_e2e.py -q -rs
```

Run these manual checks on Plasma X11 and Wayland, using both the Debian and
Flatpak builds. Record the desktop, session, Qt version, and results before
adding a tested-environment claim:

- Focus the player and editor in turn. Confirm the panel selects the appropriate
  menus. Also check focus transitions to Search, Faces, and Cover view.
- Activate Search, Faces, and Face editor from the panel. Open an editable face,
  make a change, then Undo/Redo through the panel.
- With a live YouTube Music session, use Play/Pause, Previous/Next and Like.
  Each action must issue one command; unavailable and pending actions stay
  disabled. Disconnect the target and confirm playback actions disable.
- Switch among rectangular and shaped faces at different scales. The global
  menu must not shift, stretch, or clip the face. Open the face's popup too.
- Start without the widget, then add or restart it while the app runs. Confirm
  the popup stays usable; restart Amberfader when registrar discovery requires it.
- For Flatpak, confirm the scoped permission above and examine
  `flatpak run --log-session-bus ch.lkmc.amberfader` for denied menu traffic.

The automated X11 protocol checks do not establish live Plasma panel rendering,
Wayland association, or Flatpak host-panel interaction. These remain manual gates.
