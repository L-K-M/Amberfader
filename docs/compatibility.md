# Compatibility

Status legend: **verified** = exercised on a real target; **expected** =
implemented to a documented API contract, awaiting live confirmation;
**unsupported** = known not to work. A partial live Phase 0 report was received
on 2026-10-02; remaining acceptance gates are *expected* unless noted.

## Live observations (2026-10-02)

These were made with the Firefox extension, which was removed in 0.2.0. The
site observations still apply to the embedded browser.

- The user confirmed the Amberfader Flatpak connects to Flatpak Zen
  (`app.zen_browser.zen`) after native-host registration and the documented
  `.mozilla` persistence/talk permissions. Browser version and session type
  were not recorded; other packaging combinations remain unverified.
- The probe found `ytmusic-player-bar img.image`: a complete 60×60 cover from
  `https://yt3.googleusercontent.com`. The sanitized artwork section is stored
  in `web/tests/fixtures/artwork-probe-2026-10-02.json`.
- The extension now grants access to that exact HTTPS host. The probe proves
  site-side image presence, not successful extension fetching or rendering;
  those remain a live acceptance gate.
- A console capture found the current-song Like button under both
  `ytmusic-player-bar` instances, inside `ytmusic-like-button-renderer` and
  `#button-shape-like`. It exposes `aria-label="Like"` and
  `aria-pressed="false"`. Liked/unliked click outcomes remain unverified.
- The user reports the radio action is labeled **Start mix**. Its captured
  `ytmusic-menu-navigation-item-renderer` has `role="menuitem"`,
  `aria-label="Start mix"`, `aria-disabled="false"`, and an
  `a#navigation-endpoint` pointing to `watch?playlist=...`. The menu includes
  album actions; song-result activation and playback remain unverified.
  The sanitized menu is in `web/tests/fixtures/mix-menu-2026-10-02.html`.

The 2026-10-03 screenshots show artwork missing in both Amberfader players
while YouTube Music displays its cover. Automated regressions now cover
empty image sources, delayed image loading, paused cover replay, and stale
snapshot responses. Successful fetching and rendering in that live Zen
session still require the artwork checks in `docs/manual-test-plan.md`.

## Live observations (2026-10-05)

- The embedded QtWebEngine prototype passed its gate on the user's Mac,
  including Google sign-in with QtWebEngine's default user agent. Details are
  in [`embedded-browser.md`](embedded-browser.md#results-so-far).
- In a signed-out session in a Linux container, playing a search result
  opened the player page (`ytmusic-app-layout[player-page-open]`), which
  hid the search results and every row's action menu. The player bar's
  `.toggle-player-page-button` closed it and the rows reappeared. One layout
  experiment had no such toggle. Sanitized record:
  `web/tests/fixtures/player-page-2026-10-05.json`. The full Start mix
  flow after this fix is not yet confirmed in a signed-in session.

## Platforms

| Platform | Install type | Status |
|---|---|---|
| Linux x86_64 | from a checkout | expected; the scripted test page passes in CI |
| Linux x86_64 | `.deb` | expected; package update in progress |
| Linux x86_64 | Flatpak | expected; package update in progress |
| macOS 13+ on Apple silicon | from a checkout | **verified** on 2026-10-05: sign-in, persistence, playback, hidden playback, controls, reload |
| macOS on Apple silicon | `.dmg` | expected; CI builds it and the frozen app's `--self-test` passes on macos-15 (2026-10-05); first released with 0.2.0 |
| macOS on Intel, Windows | not a target | unsupported |

## Desktop environments

| Environment | Status |
|---|---|
| X11 + any DE | expected |
| Wayland + any DE | expected (Qt `wayland`/`xcb` platform abstraction) |
| Linux without `$XDG_RUNTIME_DIR` | **unsupported**: the app refuses to start rather than placing its single-instance socket somewhere others can reach |
| macOS | the single-instance socket lives in the private `$TMPDIR` |

## Packaging

| Format | Status |
|---|---|
| `.deb` | expected: `scripts/build-deb.sh` |
| `.flatpak` | expected: `scripts/build-flatpak.sh` repacks the deb layout |
| macOS `.dmg` | expected: `scripts/build-macos.sh` (PyInstaller, ad-hoc signed) |
| AppImage / Snap | not planned |

The `.deb` resolves its bundled Python wheels with the build host's
`/usr/bin/python3` and requires that same Python minor version at runtime.
For example, a Python 3.12 build declares `python3 (>= 3.12), python3 (<< 3.13~)`.
The upper bound also excludes Python 3.13 prereleases with a different ABI.
Build a package on a matching host for distributions using a different minor.
Source installs keep the project's Python 3.11+ requirement.

## Resource budgets

| Metric | Budget | Measured |
|---|---|---|
| Total RSS (app + Qt WebEngine processes) | to be set after the first live measurement | scripted test page in a Linux container: about 454 MiB; live playback pending |
| Idle CPU | ~0% while paused (event-driven; 1 Hz position sampling while playing) | pending |

Pending means not yet measured, not "assumed fine".
