# Compatibility

Status legend: **verified** = exercised on a real target; **expected** =
implemented to a documented API contract, awaiting live confirmation;
**unsupported** = known not to work. A partial live Phase 0 report was received
on 2026-10-02; remaining acceptance gates are *expected* unless noted.

## Live observations (2026-10-02)

- The user confirmed the Amberfader Flatpak connects to Flatpak Zen
  (`app.zen_browser.zen`) after native-host registration and the documented
  `.mozilla` persistence/talk permissions. Browser version and session type
  were not recorded; other packaging combinations remain unverified.
- The probe found `ytmusic-player-bar img.image`: a complete 60×60 cover from
  `https://yt3.googleusercontent.com`. The sanitized artwork section is stored
  in `extension/tests/fixtures/artwork-probe-2026-10-02.json`.
- The extension now grants access to that exact HTTPS host. The probe proves
  site-side image presence, not successful extension fetching or rendering;
  those remain a live acceptance gate.

## Browsers

| Browser | Install type | Native messaging | Status |
|---|---|---|---|
| Firefox | deb / rpm | `~/.mozilla/native-messaging-hosts` + system manifest | expected |
| Firefox | Flatpak | per-user manifest in the Flatpak data dir | expected |
| Zen | native Linux | `~/.mozilla/native-messaging-hosts` | expected |
| Zen | Flatpak (`app.zen_browser.zen` / `io.github.zen_browser.zen`) | per-app `.mozilla/native-messaging-hosts`; persist `.mozilla` and allow `flatpak-spawn` | expected |
| Firefox | Snap | confined — no host-path access | **unsupported in v1** |
| Firefox | macOS/Windows | not a target | unsupported |

`strict_min_version`: set after Phase 0 identifies the oldest working
Firefox. `tabs.hide()` requires Firefox ≥ 61 and the `tabHide` optional
permission; `background.scripts` event-page behavior requires a Firefox MV3
release. The probe checklist records the tested version in the environment
row of the acceptance matrix.

## Desktop environments

| Environment | Status |
|---|---|
| X11 + any DE | expected |
| Wayland + any DE | expected (Qt `wayland`/`xcb` platform abstraction) |
| No `$XDG_RUNTIME_DIR` | **unsupported** — the app refuses to start rather
than placing the control socket somewhere world-readable |

## Packaging

| Format | Status |
|---|---|
| `.deb` | expected — `scripts/build-deb.sh` |
| `.flatpak` | expected — `scripts/build-flatpak.sh` repacks the deb layout |
| AppImage / Snap | not planned |

The Flatpak bundle ships a host-side registration script, not a native-host
manifest. `scripts/install-user --app flatpak` registers a launcher running
`flatpak run --command=amberfader-helper ch.lkmc.amberfader`. A Flatpak browser
uses `flatpak-spawn --host` to invoke that launcher.

Gecko's native-host directory is `.mozilla`, independent of Zen's `.zen`
profile directory. The installer prints the required `.mozilla` persistence
and talk-permission command for Flatpak Zen. The user-reported connection above
covers `app.zen_browser.zen`; the other combinations remain unverified.

## Known environment gaps

- Snap-confined Firefox cannot reach the host's native-messaging directory.
  `scripts/doctor` detects a Snap Firefox and says so instead of failing
  mysteriously (records compat limitation A6).
- A Flatpak **browser** talking to a **deb-installed** helper, or vice versa,
  is a registered combination, not a verified one — the per-user manifest
  path differs per browser package type and `install-user` covers the
  combinations it knows how to express.

## Resource budgets (to be measured during the W5 soak)

| Metric | Budget | Measured |
|---|---|---|
| Helper RSS | ≤ 20 MiB steady state | pending |
| GUI RSS | ≤ 150 MiB steady state | pending |
| Idle CPU | ~0% (event-driven; 1 Hz position sampling while playing) | pending |
| Socket traffic | bounded by 256 KiB frame cap; state events ~1 Hz max | pending |

Pending means not yet measured — not "assumed fine".
