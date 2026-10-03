# Amberfader

> [!IMPORTANT]
> LLM disclosure: This codebase was written with substantial help from large language models: AI coding agents working from the [`AGENTS.md`](AGENTS.md) brief in this repo.

**Latest release:** v<!-- version -->0.1.7<!-- /version --> · [Download](https://github.com/L-K-M/Amberfader/releases/latest)

A compact classic-style remote control for YouTube Music running in Firefox,
inspired by the small focused interfaces of Audion and classic Winamp.
Firefox stays responsible for authentication, streaming, decoding, and audio
output; the YouTube Music tab keeps running out of sight. Amberfader displays
artwork and track information, controls playback, and searches YouTube Music
from a detached extension window — and, once native mode is enabled, from a
small PySide6 desktop application connected through Firefox Native Messaging.

Linux only. Works with Firefox installed as a deb/rpm or as a Flatpak.

## Status

Early development. The browser adapter's YouTube Music selectors are marked
UNVERIFIED until the Phase 0 probes in [`docs/manual-test-plan.md`](docs/manual-test-plan.md)
are run against a live session — see [`PLAN.md`](PLAN.md) for the execution
plan and gate criteria.

## Layout

| Path | What it is |
| --- | --- |
| `protocol/` | JSON Schemas + shared valid/invalid message examples |
| `extension/` | Firefox MV3 extension (TypeScript, esbuild) |
| `native/` | Python package: native-messaging helper + PySide6 desktop app |
| `scripts/` | build, check, install, doctor, release helpers |
| `packaging/` | deb staging + Flatpak manifest |
| `docs/` | architecture decisions, compatibility record, test plan, privacy |

## Develop

Requires Node 22+ (`nvm install` reads `.nvmrc`) and Python 3.11+ with
[uv](https://docs.astral.sh/uv/).

```sh
npm install            # extension toolchain
uv sync --extra gui    # python env incl. PySide6 (omit --extra for helper-only)
scripts/check.sh       # typecheck + lint + unit tests, both languages
scripts/build.sh       # build extension bundle, wheel, .deb, .flatpak (skips what this machine can't build)
npm run ext:run        # build + web-ext run in a dedicated Firefox profile
```

Install for real use (per-user, no sudo):

```sh
scripts/install-user            # detects deb and Flatpak Firefox, installs both manifests
scripts/doctor                  # verify registration, permissions, socket, versions
scripts/uninstall-user          # remove app files (keeps preferences unless --purge)
```

See [`AGENTS.md`](AGENTS.md) for conventions and [`docs/compatibility.md`](docs/compatibility.md)
for the tested-environment record.

## Likes, recents and mixes

Upgrade the extension and desktop app together for these protocol additions.
Restart the browser and desktop app after updating.

- Click the heart to like or unlike the current song. **♥** means liked,
  **♡** means unliked, and **♡?** means unknown. It changes only after the
  site confirms the state.
- Open **Search** to reuse recent queries or played artists. These lists are
  shared by both windows, saved locally, and limited to 20 entries each.
  **Clear recents** removes both lists.
- Search, then use **Start mix** for a result. Amberfader opens that row's
  YouTube Music action menu and activates its **Start mix** link. An unavailable
  control or unconfirmed outcome is reported instead of retried.

## Linux Faces

In the native app, choose **☰ → Faces…** or press **Ctrl+,**. Eight original
retro faces change the player's shape, layout and textures while keeping
artwork, likes, playback, search, recents and mixes. Your choice is saved locally.
Click the cover for **Cover view**.

Install additional JSON/PNG face plugins with **Install face folder…**.
See [Faces](docs/faces.md) for previews, installation paths and the versioned
plugin format.

## Connect an installed Flatpak app

Installing the app does not register its helper with your browser. Run the
bundled installer on the host:

```sh
bash -o pipefail -c 'flatpak run --command=cat ch.lkmc.amberfader /app/share/amberfader/install-user | bash -s -- --app flatpak'
```

It detects native and Flatpak Firefox/Zen. For Flatpak browsers, follow any
printed permission command and restart the browser. Restart Amberfader, then
enable native mode or press **Reconnect** in the extension options.

From a checkout, use `scripts/install-user --app flatpak` instead. This uses
the installed app's helper without creating another Python environment.

The native-mode section reports helper errors, including missing registration.
For missing artwork, run **Run probes** and share the artwork host list; image
permissions are added only after the live origin is captured.
