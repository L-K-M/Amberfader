# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Amberfader is now a standalone app. It plays YouTube Music in its own
  embedded browser (Qt WebEngine) and needs no Firefox, extension or native
  helper. Sign in once in the YouTube Music window. `amberfader` starts the
  app; PySide6 and Qt WebEngine are regular dependencies (`uv sync`).
- The page-side TypeScript moved from `extension/` to `web/`, and the
  version source moved from the extension manifest to
  `native/amberfader/__init__.py`.

### Added (standalone app)

- The Flatpak runs the standalone app with Chromium's renderer sandbox on.
  It is built from the wheel on Flathub's PySide BaseApp, whose Qt
  WebEngine sandboxes renderers through Flatpak's own sandbox, instead of
  repacking the deb, whose Qt WebEngine cannot. It moves to the KDE 6.11
  runtime (6.8 is end of life) and gains network and audio access. CI
  self-tests the installed bundle and checks that a second launch hands
  over to the first.
- The `.deb` declares the system libraries Qt WebEngine needs and ships an
  AppArmor profile, so Chromium's sandbox can start on Ubuntu 23.10 and
  later, which restrict unprivileged user namespaces.
- Linux packages install Amberfader's icon for the desktop entry, rendered
  from `media-sources/icon.png` at 128, 256 and 512 px. The player window
  reports the entry's ID (`ch.lkmc.amberfader`), so Wayland docks can match
  the window to it.
- Built-in ad blocking: blocks Google's ad hosts and YouTube's ad and
  ad-tracking endpoints (EasyList rules) and removes ad data from player
  responses, the technique uBlock Origin's filters use on music.youtube.com.
- Continue playing: closes YouTube Music's "Video paused. Continue
  watching?" prompt and resumes playback, as the YouTube NonStop extension
  does.
- Both are on by default, with switches in the Playback and ☰ menus, saved
  in `settings.json`. Neither is confirmed against live YouTube Music yet.

- macOS keeps Amberfader's files in `~/Library/Application Support/Amberfader`
  and `~/Library/Caches/Amberfader`. The first start moves faces, appearance,
  recent searches and the sign-in from the old XDG-style folders, never
  overwriting newer files.

- `amberfader --self-test` checks an installation on the scripted test
  page: attach, playback, search, the ad filter and, on Linux, Chromium's
  renderer sandbox.
- Wheels and sdists now include the page scripts; building a wheel without
  them fails with a reminder to run `npm run build`.

### Removed

- The Firefox extension, the native-messaging helper (`amberfader-helper`),
  `scripts/install-user`, `scripts/uninstall-user` and `scripts/doctor`.
  Remove the extension from Firefox yourself; recent searches from the
  extension are not carried over. Faces and appearance settings are kept.

### Added

- Audion face import in the visual editor: preview converted JSON/PNG folders
  and ZIP collections, then edit a portable copy with original sprites, bitmap
  clocks, transparency and credits. Version 3 faces support compact layouts,
  optional controls and popup seek/volume controls.
- Experimental embedded QtWebEngine prototype (`npm run embedded:run`):
  YouTube Music in Amberfader's own window, driven by the unchanged site
  adapter through an in-process router. Requires the new `embedded` extra.
  Pending a manual gate; see docs/embedded-browser.md.

### Fixed

- Start mix after playing a search result: YouTube Music's player page hid
  the results and their menus, so Start mix reported no action menu.
  Amberfader now closes the player page with the site's own toggle first, or
  asks you to close it when that layout has no toggle.

## [0.1.0] - Unreleased

### Added

- Firefox MV3 extension: background router with sender-role validation,
  selected-tab binding tokens, and storage-backed recovery; YouTube Music site
  adapter (selectors pending Phase 0 verification); fake adapter for offline
  development and tests.
- Detached extension player window and separate search window (Stage A
  prototype UI).
- Controller extension page owning the `connectNative` port plus the artwork
  fetch/normalize service.
- Python native-messaging helper relaying framed JSON between Firefox stdio
  and a per-user Unix socket; PySide6 desktop application with single-instance
  activation.
- Versioned JSON message protocol with dual-language schema validation and
  shared example vectors.
- Per-user installer covering both deb/rpm and Flatpak Firefox native-host
  registration (Flatpak via `flatpak-spawn --host`), plus `doctor` diagnostics
  and `uninstall-user`.
- Phase 0 probe tooling for live YouTube Music validation.
