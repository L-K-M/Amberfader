# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Audion face import in the visual editor: preview converted JSON/PNG folders
  and ZIP collections, then edit a portable copy with original sprites, bitmap
  clocks, transparency and credits. Version 3 faces support compact layouts,
  optional controls and popup seek/volume controls.
- Experimental embedded QtWebEngine prototype (`npm run embedded:run`):
  YouTube Music in Amberfader's own window, driven by the unchanged site
  adapter through an in-process router. Requires the new `embedded` extra.
  Pending a manual gate; see docs/embedded-prototype.md.
- CI now repacks the .deb as a Flatpak bundle and smoke-checks the installed
  app in the real runtime (command exists in /app/bin; QApplication import
  probe loads the full PySide6/Qt chain). release.yml installs
  flatpak-builder instead of soft-skipping the flatpak artifact on every
  release.

### Fixed

- Start mix after playing a search result: YouTube Music's player page hid
  the results and their menus, so Start mix reported no action menu.
  Amberfader now closes the player page with the site's own toggle first, or
  asks you to close it when that layout has no toggle. Applies to both the
  extension and the embedded prototype.

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
