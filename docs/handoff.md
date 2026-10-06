# Handoff: standalone app and release 0.2.0

Last updated: 2026-10-06, 02:30 UTC. Keep this file current; it is the
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

The standalone app, ad blocking, continue playing, macOS folders,
`--self-test` and the macOS `.dmg` build merged to main on 2026-10-06 as
[L-K-M/Amberfader#35](https://github.com/L-K-M/Amberfader/pull/35)
(`4e6500d`). Its review triage is in the PR's commit messages. Deferred from
its review: `docs/privacy.md` could also tell readers to delete the HTTP
cache folder.

Current step: the Linux deb, on branch `claude/busy-ramanujan-bqitel` (the
session may only push to this branch; restart it from origin/main after
each merge). Its PR adds the computed `Depends`, a Python launcher, the
AppArmor profile (`packaging/linux/apparmor-amberfader`) and two CI steps:
a self-test in a clean `ubuntu:24.04` container (sandbox off, as root) and
a self-test of the installed deb on the runner with
`kernel.apparmor_restrict_unprivileged_userns=1`. Locally (no AppArmor in
this container) the installed deb passes its self-test with the sandbox on
as an unprivileged user. Whether the profile is enough under the
restriction is answered by that CI step; if it fails, see the open problem
below.

Earlier PRs, all merged: #28 (prototype), #32 (macOS socket), #33 (Start
mix), #34 (plan), #35 (standalone app).

CI note: on 2026-10-05 several ubuntu-24.04 jobs sat queued for 20 to 28
minutes without a runner and were then cancelled (`runner_id` 0). That is
not a test failure; a re-run (or the owner) got them through.

## What remains, in order

1. **Linux packages** (plan Phase 2):
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
2. **macOS target** (plan Phase 3): `4dd2452`; CI builds the `.dmg` and the
   frozen app's self-test passes on macos-15. The owner still has to install
   it and check sign-in, the data move, ad blocking and continue playing.
   Not done yet:
   thinning the universal2 Qt binaries to arm64 (size), and a one-hour
   hidden playback check from the frozen app (App Nap).
3. **Release 0.2.0**: `scripts/release.sh 0.2.0 --push` uses
   `L-K-M/release-tool` with `RELEASE_KIND=python` (version source
   `native/amberfader/__init__.py`). Tag pushes may need the owner if the
   session cannot push tags.
4. Later: pop-up windows, settings/diagnostics window, MPRIS and Now Playing,
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
