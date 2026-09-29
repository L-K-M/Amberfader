# Amberfader

> [!IMPORTANT]
> LLM disclosure: This codebase was written with substantial help from large language models: AI coding agents working from the [`AGENTS.md`](AGENTS.md) brief in this repo.

**Latest release:** v<!-- version -->0.1.0<!-- /version --> · [Download](https://github.com/L-K-M/Amberfader/releases/latest)

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
