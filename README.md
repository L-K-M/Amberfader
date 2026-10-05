# Amberfader

> [!IMPORTANT]
> LLM disclosure: This codebase was written with substantial help from large language models: AI coding agents working from the [`AGENTS.md`](AGENTS.md) brief in this repo.

**Latest release:** v<!-- version -->0.1.9<!-- /version --> · [Download](https://github.com/L-K-M/Amberfader/releases/latest)

A compact classic-style player for YouTube Music, inspired by the small
focused interfaces of Audion and classic Winamp. Amberfader plays YouTube
Music in its own embedded browser (Qt WebEngine, based on Chromium) and shows
a small player with artwork, playback controls, likes, song search and
skinnable faces. You sign in once in the YouTube Music window; the page then
keeps running out of sight.

Amberfader runs on Linux (deb or Flatpak) and on macOS with Apple silicon.

### Install on macOS

The `.dmg` is attached to releases from 0.2.0 on.

1. Download `Amberfader-<version>-macos-arm64.dmg` from the
   [latest release](https://github.com/L-K-M/Amberfader/releases/latest),
   open it and drag **Amberfader** to **Applications**.
2. The app is not signed with an Apple Developer ID, so the first launch is
   blocked. Open **System Settings > Privacy & Security**, find the message
   about Amberfader and choose **Open Anyway**. Each update needs this once.
3. Sign in to YouTube Music with **Show YT**.

## Status

Early development. Site selectors in `web/src/adapter/selectors.ts` are
marked UNVERIFIED until they are observed in a live YouTube Music session;
see [`docs/manual-test-plan.md`](docs/manual-test-plan.md). The move from the
Firefox extension to the standalone app is planned in
[`docs/standalone-plan.md`](docs/standalone-plan.md).

### Upgrading from 0.1.x

0.2.0 replaces the Firefox extension and its native helper, so you can
remove the Amberfader add-on from Firefox. Upgrading the `.deb` removes the
old helper. If you installed 0.1.x with `scripts/install-user`, run
`scripts/uninstall-user` from that 0.1.9 checkout.

## Use it

- **Show YT** opens the YouTube Music window, for example to sign in or
  browse. **Hide** puts it away again; closing that window also only hides
  it.
- Closing the player quits Amberfader and stops the music.
- Launching Amberfader again while it runs brings the player to the front.

## Ad blocking and continue playing

Both are built in and on by default. Turn them off in **Playback** (or the
**☰** menu); a change applies fully the next time YouTube Music loads.

- **Block ads** stops requests to Google's ad hosts and YouTube's ad and
  ad-tracking endpoints (rules taken from EasyList), and removes ad data from
  YouTube Music's player responses the way uBlock Origin does. YouTube
  changes how it delivers ads, so this can stop working; if the page
  misbehaves, turn it off.
- **Continue playing automatically** closes YouTube Music's "Video paused.
  Continue watching?" prompt and resumes the track.

Neither has been confirmed against live YouTube Music yet.

Where your data lives. On macOS, everything except the cache is in
`~/Library/Application Support/Amberfader`, shown as *Support* below.

| Data | Linux | macOS |
| --- | --- | --- |
| Profile: cookies and sign-in (delete it to sign out completely) | `~/.local/share/amberfader/webengine` | *Support*`/webengine` |
| HTTP cache | `~/.cache/amberfader/webengine` | `~/Library/Caches/Amberfader/webengine` |
| Recent searches and artists | `~/.local/state/amberfader/embedded-search-history.json` | *Support*`/embedded-search-history.json` |
| Faces | `~/.local/share/amberfader/faces` | *Support*`/faces` |
| Appearance | `~/.config/amberfader/appearance.json` | *Support*`/appearance.json` |
| Ad blocking and continue playing switches | `~/.config/amberfader/settings.json` | *Support*`/settings.json` |

On macOS, the first start moves faces, appearance, recent searches and the
sign-in from the old `~/.local/share/amberfader`-style folders, without
overwriting anything already in the new place.

## Likes, recents and mixes

- Click the heart to like or unlike the current song. **♥** means liked,
  **♡** means unliked, and **♡?** means unknown. It changes only after the
  site confirms the state.
- Open **Search** to reuse recent queries or played artists. These lists are
  saved locally and limited to 20 entries each. **Clear recents** removes
  both lists.
- Search, then use **Start mix** for a result. Amberfader opens that row's
  YouTube Music action menu and activates its **Start mix** link. An
  unavailable control or unconfirmed outcome is reported instead of retried.

## Layout

| Path | What it is |
| --- | --- |
| `web/` | Page-side TypeScript: the YouTube Music adapter, command executor and QWebChannel bridge |
| `native/` | Python package: the app, embedded browser host, player windows, faces and face editor |
| `protocol/` | JSON Schemas + shared valid/invalid message examples |
| `scripts/` | build, check and release helpers |
| `packaging/` | deb and Flatpak packaging |
| `docs/` | plans, architecture decisions, compatibility record, test plan, privacy |

## Develop

Requires Node 22+ (`nvm install` reads `.nvmrc`) and Python 3.11+ with
[uv](https://docs.astral.sh/uv/).

```sh
npm ci                 # page bundle toolchain
uv sync                # python env incl. PySide6 and Qt WebEngine
npm start              # build the page bundle and run Amberfader
scripts/check.sh       # typecheck + lint + unit tests, both languages
scripts/build.sh       # wheel, .deb, .flatpak (skips what this machine can't build)
```

`npm start` passes no options; run `uv run python -m amberfader --help` for
the rest, such as `--background` (start with the YouTube Music window
hidden), `--test-page` (drive a scripted local page instead of YouTube
Music) and `--self-test` (check that an installation works, then exit; it
fails on Linux when Chromium's sandbox is off).

Wheels and packages include the page scripts, so build them first:
`scripts/build.sh` does, and a bare `uv build` stops with a reminder to run
`npm run build`.

See [`AGENTS.md`](AGENTS.md) for conventions,
[`docs/embedded-browser.md`](docs/embedded-browser.md) for how the embedded
browser works and what it allows, and
[`docs/compatibility.md`](docs/compatibility.md) for the tested-environment
record.

## Linux Faces

In the native app, choose **☰ → Faces…** or press **Ctrl+,**. Eighteen original
retro faces change the player's shape, layout and textures while keeping
artwork, likes, playback, search, recents and mixes. Your choice is saved locally.
Four of them are experimental sculptural faces: an orbital instrument, a manta ray,
a jellyfish and a headphone robot with transparent gaps around their controls.
Tangent, Keystone, Switchback and Vane add compact abstract instrument forms
in steel, navy glass, graphite and lime.
Aureole and Viridian add gold and green glass displays framed by silver curves.
Click the cover for **Cover view**.

Install additional JSON/PNG face plugins with **Install face folder…**.
See [Faces](docs/faces.md) for previews, installation paths and the versioned
plugin format.

## KDE global menu

The native player and face editor expose menus to Plasma's **Global Menu**
widget. Enable the widget before starting the app. The player's face and its
popup menu remain available on every desktop. See the
[global-menu guide](docs/global-menu.md) for setup and verification.

## Face editor for Mac and Linux

Create your own face with the visual editor:

```sh
uv sync
uv run amberfader-face-editor
uv run amberfader-face-editor path/to/your/face
```

Drag controls into place, resize and rotate them, adjust their appearance,
and save a portable JSON/PNG face folder. The editor works independently of
YouTube Music and playback. See the [editor guide](docs/face-editor.md).

Choose **File → Import Audion face…** to turn a converted Audion face folder or
collection ZIP into an editable copy, retaining its artwork and original credits.
