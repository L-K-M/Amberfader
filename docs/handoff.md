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
   - deb: PR #36 (Depends, Python launcher, AppArmor profile, two CI
     self-tests). Its first CI run showed the profile works: with
     `kernel.apparmor_restrict_unprivileged_userns=1` the installed deb
     reported `renderer sandbox: ok (on)`. Desktop launch on a real Ubuntu
     machine still needs the owner.
   - Flatpak: add `--share=network`, `--socket=pulseaudio`; keep the
     `xdg-run/amberfader` share (single-instance socket). Chromium's sandbox
     inside Flatpak needs the spike described in the plan.
   - CI: a `flatpak` job that runs `amberfader --self-test` on the
     installed bundle (the `deb` job already does this for the deb).
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
  such child; sandbox on means `Seccomp: 2` and a nested PID namespace
  (more than one id in `NSpid`) for all of them. Seccomp alone is reported
  as "seccomp only": Chromium keeps running with just the filter when the
  namespace layer is missing (`--disable-namespace-sandbox`, or Ubuntu's
  userns restriction without a profile).
- Shell heredocs: when editing files that contain `EOF` lines (the build
  scripts), use a different delimiter for the outer heredoc.
- Repo rules: no em dashes or emojis in new prose; commit subject imperative,
  at most 72 characters; selectors only with live evidence or marked
  UNVERIFIED; never claim live behavior verified by fixtures.
