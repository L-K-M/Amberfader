# Handoff: standalone app and release 0.2.0

Last updated: 2026-10-05, 20:00 UTC. Keep this file current; it is the
starting point for whoever continues the work.

## Goal

Ship Amberfader as a standalone app (YouTube Music in an embedded Qt WebEngine
browser), with the Firefox extension removed, as release 0.2.0 with Linux
(deb, Flatpak) and macOS (Apple silicon, unsigned `.dmg`) packages on GitHub
Releases. The full plan and the owner's decisions are in
[`standalone-plan.md`](standalone-plan.md):

| # | Decided by the owner |
| --- | --- |
| D1 | Remove the Firefox mode now, no overlap release |
| D2 | Mac app unsigned (ad-hoc signature), no notarization |
| D3 | Apple silicon only |
| D4 | Closing the player quits the app |
| D5 | Ad blocker and "continue playing" are needed; built in, since Qt WebEngine cannot enable extensions |
| D6 | GitHub Releases only |

## Where the work is

Branch `claude/busy-ramanujan-bqitel`, PR
[L-K-M/Amberfader#35](https://github.com/L-K-M/Amberfader/pull/35). The session may only push to
this branch, so finished steps stack on it as separate commits:

| Commit | Step | State |
| --- | --- | --- |
| `c03b4af` | Remove the Firefox mode; `amberfader` is the app; page code in `web/`; version source in `native/amberfader/__init__.py` | CI green |
| `7ef7d51` | Built-in ad blocking (request rules from EasyList + main-world `JSON.parse` filter as in uBlock Origin) and continue playing (YouTube NonStop technique) | local checks green; e2e covers both in real Qt WebEngine |
| `2b7a8ae` | macOS data in `~/Library/...` with a one-time move from the old XDG folders | local checks green |
| `25099d9` | Page scripts shipped in wheels (hatch artifacts + build hook); `amberfader --self-test` | local checks green; sandbox detection verified both ways (see below) |
| `5374ce8` | This file | |
| `4dd2452` | macOS target: `packaging/macos/amberfader.spec`, `scripts/build-macos.sh`, `build.sh macos`, CI job `macos` (macos-15, runs the frozen app's `--self-test`), release attaching the `.dmg`, README install steps | CI green; the frozen app's self-test passed on macos-15 (run 37345222617, `.dmg` artifact 11359883805, 227 MB) |
| next | Review round 1 fixes (see below) | local checks green |

Earlier PRs, all merged: #28 (prototype), #32 (macOS socket), #33 (Start
mix), #34 (plan).

## What remains, in order

1. **Drive PR #35 to merge.** Address review per `CLAUDE.md`/`AGENTS.md`
   (triage, steady state after two rounds without important findings, then
   squash-merge). Any push cancels a running GLM review, so batch fixes.
   Round 1 (GLM, on `4dd2452`, 27 findings) was answered in the next commit:
   - Applied: ad filter also hooks `Response#json` (fetch path); launcher
     reports unreadable page scripts instead of a traceback; `--self-test`
     always uses its scratch socket; self-test prints its verdict on
     unexpected errors; release reuses CI's `macos-dmg` instead of building
     twice; `build-macos.sh` uses `python3` and rejects non-arm64 hosts;
     numeric `CFBundleVersion` from any pre-release form; doc fixes (README
     upgrade note and dmg availability, compatibility rows, plan lifecycle
     and deferred items, privacy artwork hosts, DevTools port warning).
   - Refuted: deleted extension tests (the code they covered is deleted;
     the embedded app's artwork, binding and history have their own tests);
     stray socket peers (`LocalServer` already refuses a first frame that is
     not a second launch, `test_helper_hello_is_refused`); pytest
     `exc_type` (lock pins pytest 9.1, project requires >= 8.3); empty
     version in CI (`build-*.sh` reject it via `${1:?}`); self-test ad
     filter skip (self-test always runs with in-memory defaults, blocking
     on); `SettingsStore(None)` (both paths handled).
   - Declined: sdist-only hook exemption (a wheel built from such an sdist
     would ship without page scripts; `uv build` builds wheels from the
     sdist); directory fsync for settings (defaults are safe on loss);
     continue-playing sweep at start (the adapter starts at document load,
     long before the prompt can exist); fixtures without track titles
     (parser tests need realistic metadata; the privacy rule covers runtime
     diagnostics).
   - Deferred to step 2: deb `Depends` for Qt WebEngine's libraries.

   Round 2 (on `57eb98c`, no important findings; the first minor-only
   round): applied a hard error when the self-test has no scratch folder,
   a clear error for a non-numeric version in the spec, sdist contents
   checked in CI, and the release refusing to publish without a `.dmg`.
   Refuted: `if-no-files-found` is not a `download-artifact` input (a
   missing artifact already fails that step); the `Response#json` test is
   not vacuous (it failed with the hook removed, since `fakeWindow()` has
   its own `JSON` object). Declined: printing the exception message in the
   self-test (diagnostics name error kinds, never page content). If round 3
   has no important findings, the PR is at steady state: merge it.
2. **Linux packages** (plan Phase 2):
   - deb: today it installs `amberfader` (now incl. PySide6-Addons) into
     `/opt/amberfader/lib`, but `Depends` lacks Qt WebEngine's system
     libraries. CI's embedded job installs: `libnss3 libasound2t64
     libxkbfile1 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libgbm1
     libxcb-dri3-0 libgssapi-krb5-2`. Computed on 2026-10-05 from
     `readelf -d` over PySide6 6.11.2's Qt libraries, `QtWebEngineProcess`
     and platform plugins, minus libraries the wheel bundles, mapped with
     `ldconfig -p` + `dpkg -S` on Ubuntu 24.04: `libegl1 libgl1 libx11-6
     libx11-xcb1 libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2
     libxtst6 libasound2t64 libbrotli1 libdbus-1-3 libdrm2 libexpat1
     libfontconfig1 libfreetype6 libgbm1 libglib2.0-0t64 libgssapi-krb5-2
     libnspr4 libnss3 libudev1 libwayland-client0 libwayland-cursor0
     libwayland-egl1 libxcb1 libxcb-cursor0 libxcb-dri3-0 libxcb-glx0
     libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0
     libxcb-render0 libxcb-render-util0 libxcb-shape0 libxcb-shm0
     libxcb-sync1 libxcb-util1 libxcb-xfixes0 libxcb-xkb1 libxkbcommon0
     libxkbcommon-x11-0 libxkbfile1 zlib1g libzstd1` (libc, libstdc++ and
     libgcc are essential). For Debian 12 write `libasound2t64 | libasound2`
     and `libglib2.0-0t64 | libglib2.0-0`. Prove the list with
     `amberfader --self-test` in a clean `ubuntu:24.04` container.
   - **Open problem: Chromium's sandbox on Ubuntu 23.10+.** AppArmor
     restricts unprivileged user namespaces
     (`kernel.apparmor_restrict_unprivileged_userns=1`). Chromium's
     namespace sandbox is set up when the browser process launches the
     zygote, and in Qt WebEngine the browser process is the Python
     interpreter, so a profile attached to `QtWebEngineProcess` alone may
     not be enough. Not yet tested. Ubuntu's `apparmor` package may ship a
     `QtWebEngineProcess` profile for the system Qt path (unverified; the
     package download from this container 404'd). Find out in CI on
     `ubuntu-24.04` with the knob set to 1 before choosing. Never ship with
     the sandbox silently disabled; if no profile works, tell the owner.
   - Flatpak: add `--share=network`, `--socket=pulseaudio`; keep the
     `xdg-run/amberfader` share (single-instance socket). Chromium's sandbox
     inside Flatpak needs the spike described in the plan.
   - CI: separate `deb` and `flatpak` jobs; each runs `amberfader --self-test`
     on the installed package; the deb job sets the AppArmor knob to 1.
   - Desktop entry and hicolor icons from `media-sources/icon.png`.
3. **macOS target** (plan Phase 3): `4dd2452`; CI builds the `.dmg` and the
   frozen app's self-test passes on macos-15. The owner still has to install
   it and check sign-in, the data move, ad blocking and continue playing.
   Not done yet:
   thinning the universal2 Qt binaries to arm64 (size), and a one-hour
   hidden playback check from the frozen app (App Nap).
4. **Release 0.2.0**: `scripts/release.sh 0.2.0 --push` uses
   `L-K-M/release-tool` with `RELEASE_KIND=python` (version source
   `native/amberfader/__init__.py`). Tag pushes may need the owner if the
   session cannot push tags.
5. Later: pop-up windows, settings/diagnostics window, MPRIS and Now Playing,
   removing helper-only message kinds from `protocol/schemas`.

## Not yet verified live (needs the owner)

- Start mix after playing a result, in a signed-in session.
- Linux hidden playback and memory; macOS memory with the corrected command
  in `docs/embedded-browser.md`.
- Ad blocking against real YouTube Music ads, and the "Continue watching?"
  prompt (its selectors come from YouTube NonStop and are UNVERIFIED).

## How to work here

- `scripts/check.sh` before every commit (tsc, eslint, vitest, ruff, pytest,
  shellcheck if installed). `npm run build` builds `adapter.js` and
  `ad-filter.js` into `native/amberfader/embedded/web/` (git-ignored).
- End-to-end in real Qt WebEngine: `uv run pytest native/tests/test_embedded_e2e.py`
  (needs `npm run build`; the driver is `native/tests/embedded_e2e_driver.py`).
- In this container you run as root, so Chromium's sandbox cannot start:
  use `QTWEBENGINE_DISABLE_SANDBOX=1 QT_QPA_PLATFORM=offscreen`. To test with
  the sandbox, run as an unprivileged user from a world-readable venv:
  `uv venv /tmp/sbxvenv --python /usr/bin/python3.11`, `uv pip install
  --link-mode copy PySide6-Essentials PySide6-Addons jsonschema`,
  `chmod -R o+rX /tmp/sbxvenv`, `useradd -m sbx` (if missing),
  `install -d -o sbx -m 700 /tmp/sbxrun`, then `runuser -u sbx -- env -i
  HOME=/home/sbx XDG_RUNTIME_DIR=/tmp/sbxrun QT_QPA_PLATFORM=offscreen
  PYTHONPATH=/home/user/Amberfader/native /tmp/sbxvenv/bin/python -m
  amberfader --self-test`. Never `chmod` anything under `/root`.
- Renderer detection (`native/amberfader/embedded/selftest.py`): renderers
  keep the zygote's `--type=zygote` command line; with the namespace
  sandbox there is an init process between the browser and the zygote.
  A renderer is a sandboxed-zygote process forked by another one with no
  such child; sandbox on means `Seccomp: 2` for all of them.
- Shell heredocs: when editing files that contain `EOF` lines (the build
  scripts), use a different delimiter for the outer heredoc.
- Repo rules: no em dashes or emojis in new prose; commit subject imperative,
  at most 72 characters; selectors only with live evidence or marked
  UNVERIFIED; never claim live behavior verified by fixtures.
