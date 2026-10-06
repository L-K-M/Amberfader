# ADR: Host YouTube Music in an embedded browser

## Status

Accepted, 2026-10-05.

## Context

Amberfader started as a Firefox extension plus a native-messaging helper and
a PySide6 desktop app. That chain (content script, background router,
controller page, native messaging, helper, Unix socket, desktop app) failed in
many places that the user could not see or fix: extension permissions, native
host registration per browser package, Flatpak talk permissions, event-page
unloads and tab discovery.

A prototype hosted music.youtube.com in Qt WebEngine inside the app and reused
the site adapter unchanged. On the user's Mac it passed the gate on
2026-10-05: Google sign-in with QtWebEngine's default user agent, persistence,
playback, hidden playback, the controls, and reload handling.

## Decision

Amberfader hosts YouTube Music in its own Qt WebEngine profile. The Firefox
extension, the native helper and their install tooling are removed without an
overlap release. Packages ship for Linux (deb, Flatpak) and macOS on Apple
silicon (unsigned `.dmg`) through GitHub Releases. Closing the player quits
the app.

Alternatives considered:

- **Keep the Firefox extension.** Rejected: the integration chain above was
  the main source of failures.
- **WebKitGTK / WKWebView.** Two different engines and host bindings per
  platform, and no Python bindings comparable to PySide6's Qt WebEngine.
- **Electron or Tauri.** A rewrite of the player, faces and editor, which
  are Qt today.
- **Gecko or Servo.** No maintained embedding API for a desktop Python app.

## Consequences

- A second browser engine next to the user's browser, with its own memory
  cost (measured in `docs/compatibility.md`).
- Chromium security fixes reach Amberfader only through PySide6 releases.
- Chrome extensions cannot be used: Qt WebEngine's extension API crashes when
  enabling an extension (see `docs/embedded-browser.md`). Ad blocking and
  "continue playing" are built in instead.
- Google could start refusing sign-in from Qt WebEngine. Sign-in is part of
  every release's live checks; the user agent is not changed without the
  owner's decision.
