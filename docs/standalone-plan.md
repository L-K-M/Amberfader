# Plan: Amberfader as a standalone app on Linux and macOS

Status: decided 2026-10-05 (see [Decisions](#3-decisions)), in progress.
This plan takes Amberfader from "Firefox
extension plus native helper" to one desktop app that hosts YouTube Music in
QtWebEngine, and adds macOS build targets next to the Linux ones. It builds on
the prototype in [`embedded-browser.md`](embedded-browser.md) and
supersedes the Firefox-era [`PLAN.md`](../PLAN.md).

## 1. End state

Amberfader is one app. It signs in to YouTube Music in its own browser
profile, plays music itself, and shows the same player, faces, search and
face editor as today. Nothing has to be installed in Firefox.

```text
Amberfader process (Python, Qt)
  Player, search, faces, face editor, settings
  Tray (Linux) / Dock and menu bar (macOS)
  Media keys: MPRIS (Linux), Now Playing (macOS)
        |  same requests as the player buttons
  AmberfaderApp: deadlines, binding checks, truthful states
  EmbeddedRouter: protocol validation, search history, artwork fetching
  PageHost: persistent profile, navigation policy, permission denial
        |  QWebChannel, application world only
QtWebEngineProcess (Chromium renderer, sandboxed)
  music.youtube.com + the adapter bundle (selectors, executor, search)
```

Build targets at the end:

| Target | Built on | Output | Notes |
| --- | --- | --- | --- |
| `wheel` | Linux, macOS | `dist/amberfader-<ver>-py3-none-any.whl`, sdist | Includes the page bundle. For developers and `pipx` users. |
| `deb` | Linux (Ubuntu 24.04 in CI) | `dist/amberfader_<ver>_amd64.deb` | QtWebEngine inside, Chromium sandbox on, AppArmor profile for Ubuntu 23.10 and later. |
| `flatpak` | Linux | `dist/amberfader_<ver>.flatpak` | Built on Flathub's PySide BaseApp, renderer sandbox on; network and audio permissions. |
| `macos` | macOS (Apple silicon) | `dist/Amberfader-<ver>-macos-arm64.dmg` | `.app` frozen with PyInstaller, ad-hoc signed, not notarized (D2). |

## 2. Where things stand (2026-10-05)

Verified:

- On your Mac, the prototype passed sign-in (Google accepted QtWebEngine's
  default user agent), persistence, playback, hidden playback (macOS),
  controls except Start mix, and reload/navigation.
- The scripted test page runs end to end in real QtWebEngine in CI (Linux).
- PySide6 6.11.2 publishes macOS wheels as `universal2` for macOS 13 and
  later, and Linux wheels for x86_64 (glibc 2.34+) and aarch64 (glibc 2.39+).
  The Addons wheel that contains QtWebEngine is 332 MB on macOS and 175 MB on
  Linux, compressed.
- PyInstaller 6.22 ships hooks for `PySide6.QtWebEngineCore` that collect the
  `QtWebEngineProcess` helper app on macOS.

Open:

- Start mix after playing a result: fixed in
  [L-K-M/Amberfader#33](https://github.com/L-K-M/Amberfader/pull/33), needs
  your recheck in a signed-in session.
- Linux hidden playback and memory, and a macOS memory figure with the
  corrected command.
- Chrome extensions: Qt cannot enable them (see
  [Extensions](embedded-browser.md#extensions)), so D5 builds ad blocking and
  "continue playing" in.

## 3. Decisions

Decided by the owner on 2026-10-05. Where a decision differs from the
original recommendation, the phases below follow the decision.

| # | Decision | Decided |
| --- | --- | --- |
| D1 | How long the Firefox mode stays | Remove it now, with no overlap release |
| D2 | macOS signing | Release the Mac app unsigned (ad-hoc signature); no Developer ID or notarization |
| D3 | macOS architectures | Apple silicon only |
| D4 | What closing the player does | Quit the app and stop the music |
| D5 | Extensions | Ad blocking and "continue playing" are needed; both are built in, because Qt's extension API cannot enable extensions |
| D6 | Distribution | GitHub Releases only |

## 4. Rules that carry over, change, or go away

The AGENTS.md architecture rules are updated in Phase 1 (amendments) and
Phase 6 (removals).

| Rule today | After the move |
| --- | --- |
| Selectors only in `extension/src/adapter/`, marked UNVERIFIED until probed live | Unchanged. The adapter moves to `web/src/adapter/` in Phase 6. |
| One command path, no MPRIS in v1 | Amended: MPRIS, Now Playing, media keys, tray and menus are input surfaces. They issue the same `AmberfaderApp` requests as the player buttons and never touch the page themselves. |
| Extension permissions (no `<all_urls>`, optional `nativeMessaging`) | Replaced by the embedded policy: injection only into the top frame of `https://music.youtube.com`, navigation allowlist, every permission prompt denied, downloads cancelled, no user agent change without your decision. |
| Bounds (256 KiB messages, 500-char queries, 30 results, 5 s / 15 s deadlines, artwork limits) | Unchanged. The router enforces them. |
| Truthful states | Unchanged, and they apply to the new surfaces too: MPRIS and Now Playing show unknown as unknown, not as paused. |
| Helper stays PySide6-free and network-free | Removed with the helper in Phase 6. |
| GUI never spawns from the helper's process tree; closing the GUI never stops playback | Becomes: closing the player window never stops playback; only Quit does (D4). |
| Dedup of request IDs per document generation | Unchanged. The executor runs in the page. |
| Native messaging framing | Removed in Phase 6. The single-instance socket keeps its own framing. |
| Firefox package matrix, `install-user`, `doctor` | Removed in Phase 6. |
| Identities | Add bundle ID `ch.lkmc.amberfader` on macOS and the per-platform data folders. Remove the add-on ID and native host name in Phase 6. |

## 5. Phases

Phases 2 and 3 can run in parallel once Phase 1 is merged. Phase 4 needs
only the lifecycle work from Phase 1. Phase 5 depends on D5.

```text
P0 gate ─► P1 app shell ─┬─► P2 Linux packages ─┐
                         ├─► P3 macOS target ───┼─► P6 release, retire Firefox mode
                         └─► P4 media keys ─────┘
                 P5 content blocking (if D5) ───┘
```

### Phase 0: close the gate

You run these on your desktops; I prepare commands and record results.

- Recheck Start mix after playing a result (signed in, macOS).
- Linux: hidden playback for at least 10 minutes, then 5 minutes paused and
  resumed; memory with the corrected command from the runbook.
- macOS: memory with the corrected command.
- Answer D1 to D6.

I then write the decision record
`docs/architecture-decisions/embedded-browser.md`: what was decided,
alternatives considered (Firefox extension, WebKitGTK and WKWebView, Electron
or Tauri, Gecko), measured memory and size, and the consequences (Chromium
security updates arrive through PySide6 releases; a second browser next to
Firefox).

**Exit:** all gate items recorded in `embedded-browser.md`, decision record
merged.

### Phase 1: make the prototype the app

Everything here is platform-neutral code plus the hooks that packaging needs.

1. **Platform folders.** One Qt-free module returns data, config, cache and
   state folders per platform. Linux keeps the XDG folders used today. macOS
   moves to `~/Library/Application Support/Amberfader` (profile, faces,
   appearance, search history) and `~/Library/Caches/Amberfader` (HTTP
   cache). On first start on macOS, folders the face editor or prototype
   created under `~/.local/share/amberfader` are moved once, so faces and the
   Google sign-in carry over. Tests cover the move, a partial earlier move,
   and a destination that already exists (no overwrite).
2. **Lifecycle (D4).** Closing the player quits Amberfader and stops the
   music, as the prototype already does; there is no tray. Quit is also in
   the player menu and on Cmd+Q / Ctrl+Q. Launching Amberfader again while
   it runs raises the player instead of starting a second instance. SIGTERM
   and logout quit through Qt, so the sign-in cookies are flushed.
3. **Pop-up windows** (after 0.2.0, see section 10). Sign-in and YouTube Music pop-ups open in a separate
   short-lived window under the same navigation policy, instead of replacing
   the music page. Tested with `window.open` on the test page.
4. **Settings and diagnostics** (after 0.2.0, see section 10; replaces the
   extension options page):
   - Versions of Amberfader, Qt and Chromium, and the profile folder.
   - Whether the page is attached.
   - **Sign out and clear site data:** cookies, storage and HTTP cache.
   - **Copy diagnostics:** versions, states and error codes, never track
     names or queries.
5. **Entry points.** `amberfader` starts the standalone app, and the
   user-facing copy drops "prototype".
6. **Page bundle in the wheel.** `adapter.js` is a build output and is
   ignored by git, so hatch leaves it out today. Declare it as a hatch
   artifact. `scripts/build.sh wheel` builds the bundle first. CI fails if
   the built wheel lacks it.
7. **Self-test mode.** `amberfader --self-test` loads the scripted test page
   with Chromium's sandbox on and the real bundle. It checks attach, play,
   pause, search and play result, prints a marker and exits 0. It also
   checks from the app's side that the renderer sandbox is active and fails
   when it is not, so a silent fallback to no sandbox cannot pass. On Linux,
   every `QtWebEngineProcess` renderer must show `Seccomp: 2` and a nested
   PID namespace (`NSpid`) in `/proc/<pid>/status`; the macOS check is part of the Phase 3 work. Any
   failure or a 60 s timeout exits non-zero. Every package smoke test in Phases 2 and 3
   runs it, so CI proves the packaged app can start Chromium, inject the
   bundle and talk to it.
8. **Docs.** Make the README lead with the app instead of the extension.
   Rewrite the acceptance matrix in `manual-test-plan.md` for the app on both
   platforms. Rewrite `privacy.md`, covering:
   - What the profile stores: Google cookies, site storage, cache.
   - Where recent searches live.
   - Which hosts the app contacts.
   - That there is no telemetry.

   Amend AGENTS.md as in [section 4](#4-rules-that-carry-over-change-or-go-away).

**Exit:** `scripts/check.sh` green; the e2e test also runs on macOS in CI;
the self-test passes from a wheel installed into a fresh virtual environment
on Linux and macOS.

### Phase 2: Linux packages

**deb**

- Install `amberfader` with QtWebEngine into `/opt/amberfader/lib` as today.
  The PySide6 wheels are `abi3` for Python 3.10 and later, so the existing
  Python version pin can be relaxed to a lower bound.
- Trim the Addons payload to what QtWebEngine needs. Compute the keep-list
  from the shared-library closure of `QtWebEngineWidgets` and
  `QtWebEngineProcess` plus their plugins and resources; the self-test
  enforces it. Measure the installed size and record it in
  `compatibility.md`.
- Compute `Depends` with `dpkg-shlibdeps` on the staged tree instead of by
  hand. For reference, CI installs `libnss3`, `libasound2t64`, `libxkbfile1`,
  `libxcomposite1`, `libxdamage1`, `libxrandr2`, `libxtst6`, `libgbm1`,
  `libxcb-dri3-0` and `libgssapi-krb5-2` today.
- Keep Chromium's sandbox on. Ubuntu 23.10 and later restrict unprivileged
  user namespaces through AppArmor, which Chromium's sandbox needs. Ship an
  AppArmor profile for `QtWebEngineProcess` that allows `userns` (as Ubuntu's
  own profiles do for Chrome) and load it in `postinst` when AppArmor is
  present. Never fall back to `--no-sandbox`.
- Smoke in CI: install the deb on Ubuntu 24.04, set
  `kernel.apparmor_restrict_unprivileged_userns` to 1 (Ubuntu's default)
  and check that it reads 1 rather than trusting the runner image, then run
  `amberfader --self-test`. The self-test reports whether Chromium's
  sandbox is active, and the smoke fails if it is not.
- Desktop entry: new description, `desktop-file-validate` in CI. Install
  hicolor icons at 128, 256 and 512 px rendered from `media-sources/icon.png`
  (also for the Flatpak and the player window).

**Flatpak**

- Add `--share=network` and `--socket=pulseaudio`. Keep `--device=dri`,
  Wayland, X11 fallback and IPC.
- Keep single-instance working: each Flatpak instance has its own runtime
  folder, so the socket must live in a shared one. Keep the
  `xdg-run/amberfader` share for it, or move the socket to Flatpak's
  per-app runtime folder (`$XDG_RUNTIME_DIR/app/ch.lkmc.amberfader`).
  Every package smoke launches the app twice and checks that the second
  launch hands over to the first and exits.
- Chromium's own sandbox and Flatpak's sandbox interact. Spike before
  building:
  - (a) Keep the pip PySide6 wheels and find out whether QtWebEngine can
    sandbox its renderers inside Flatpak. If it can't, it has to run with
    its sandbox off and rely on Flatpak's sandbox.
  - (b) Build on Flathub's QtWebEngine BaseApp, with PySide6 built against
    the runtime's Qt.

  Pick (b) if it keeps renderer sandboxing at a reasonable build cost. If
  (a) means the sandbox is off, record that in `privacy.md` and the release
  notes.

  Outcome (2026-10-06, CI runs on scratch branches):
  - (a) Inside Flatpak, creating a user namespace fails with EPERM.
    Chromium from the pip wheels keeps running without its namespace
    layer, and the self-test reports `seccomp only`.
  - (b) costs no build of our own: Flathub's `io.qt.PySide.BaseApp//6.11`
    ships PySide6 6.11.2 built against `io.qt.qtwebengine.BaseApp//6.11`,
    whose Chromium is patched to start its sandboxed zygote through the
    Flatpak portal (`chromium-flatpak-add-initial-sandbox-support.patch`).
    Renderers then sit in a sub-sandbox with their own PID namespace and
    their own seccomp filter. All self-test checks pass.
  - Chosen: (b). The Flatpak is built from the wheel on the PySide BaseApp
    (KDE runtime 6.11; 6.8 is end of life) instead of repacking the deb.
    It needs `QTWEBENGINEPROCESS_PATH`, because Python is the browser
    process, and a session bus for the portal, which every desktop has.
- Replace the helper checks in the smoke probe with `amberfader --self-test`
  inside the installed bundle.

**CI**

- The `deb` job builds, installs and self-tests the deb with the AppArmor
  knob set to 1.
- A separate `flatpak` job builds the Flatpak from the wheel and
  self-tests it. Only this job relaxes the knob, which bubblewrap needs.

**Exit:** deb and Flatpak artifacts self-test green in CI. You confirm sign-in
and one hour of hidden playback from the installed deb or Flatpak on your
Linux desktop.

### Phase 3: macOS build target

**Freeze**

- `packaging/macos/amberfader.spec` (PyInstaller, one-folder `.app`,
  windowed).
- It collects the page bundle, schemas and built-in faces as package data.
  The existing PySide6 hooks bring the `QtWebEngineCore` framework with
  `QtWebEngineProcess.app`, its resources and locales.
- Build with a uv-managed CPython for arm64. The PySide6 wheels are
  `universal2`, so `lipo -thin arm64` the Qt binaries for an Apple-silicon-only
  build (D3), before freezing. Record the size before and after. Signing is
  the last step that changes the bundle: anything edited afterwards,
  including `Info.plist`, means signing again.
- `Info.plist`:
  - `CFBundleIdentifier` `ch.lkmc.amberfader`
  - `CFBundleShortVersionString` and `CFBundleVersion` from the numeric
    `X.Y.Z` part of the release version; a pre-release suffix such as
    `-rc1` is dropped there and kept in the `.dmg` name
  - `LSMinimumSystemVersion` 13.0 (the wheel's minimum)
  - `LSApplicationCategoryType` `public.app-category.music`
  - `NSHighResolutionCapable`

  Every permission prompt is denied before Chromium asks the system, so no
  microphone or camera usage strings are added. The smoke test confirms
  macOS does not stop the app for lacking them.
- Icon: render `media-sources/icon.png` (1254 px) to the `.iconset` sizes,
  up to 1024 px, and build an `.icns` with `iconutil`. The source has no
  transparency, so macOS shows it as a full square; a masked version with
  Apple's rounded-square margins would look native in the Dock.

**Signing (D2: unsigned)**

- Ad-hoc signature only (`codesign --sign -`), which Apple silicon needs to
  run any code. Check with `codesign --verify --deep --strict`.
- No Developer ID, hardened runtime or notarization. The README explains the
  one-time approval in System Settings > Privacy & Security, which each
  update repeats.

**Package**

- `scripts/build-macos.sh <version> <dist>` builds the `.app`, signs it when
  `AMBERFADER_SIGN_IDENTITY` is set, and creates
  `Amberfader-<ver>-macos-arm64.dmg` with an Applications link
  (`hdiutil create -format UDZO`) and a `.sha256`.
- `scripts/build.sh` gets a `macos` target. On Linux a default run skips it;
  naming it explicitly fails, like the other targets.

**macOS behavior**

- Uses the data folders from Phase 1, and the `$TMPDIR` socket (done).
- Dock click shows the player.
- Native menu bar with About, Settings and Quit in the app menu (Qt menu
  roles).
- Retest hidden playback for one hour from the frozen app to rule out App
  Nap throttling.
- Find a reliable way for `--self-test` to confirm the renderer sandbox on
  macOS. If there is none, record that this check runs on Linux only.

**CI**

- A `macos` job on an Apple silicon runner (`macos-15`): unit tests and the
  embedded e2e test, then an ad-hoc signed build (Apple silicon does not
  run unsigned code). `codesign --verify` must pass before the self-test.
- It runs `Amberfader.app/Contents/MacOS/Amberfader --self-test` and uploads
  the `.dmg`.
- The release workflow builds the ad-hoc signed `.dmg` and attaches it to the
  GitHub Release.

**Exit:** the CI artifact self-tests green. You install the `.dmg` on your Mac,
approve it once in System Settings > Privacy & Security, sign in and pass
the acceptance matrix.

### Phase 4: media keys and system controls

- **Spike first.** Find out whether QtWebEngine 6.11 forwards the page's
  Media Session to MPRIS or Now Playing by itself.
  - If it does, the page would take media keys directly, bypassing the
    adapter's observed outcomes. Turn it off if Qt lets us, so there is one
    command path.
  - If it doesn't (expected), implement the system controls below.
- **Linux, MPRIS.** Publish `org.mpris.MediaPlayer2.amberfader` over QtDBus,
  which is part of PySide6-Essentials on Linux.
  - Properties come from the player state.
  - Methods issue the existing `player.*` requests.
  - Unknown playback status maps to `Stopped` with controls disabled.
  - Artwork goes to a cache file for `mpris:artUrl`.
  - The Flatpak gets `--own-name=org.mpris.MediaPlayer2.amberfader`.
- **macOS, Now Playing and media keys.** Use `MPRemoteCommandCenter` and
  `MPNowPlayingInfoCenter` through `pyobjc-framework-MediaPlayer`, a
  macOS-only dependency with an environment marker. The spike also checks
  that macOS treats Amberfader as the app playing audio, since Chromium may
  play it from another process.
- Tests cover the state to MPRIS mapping and command dispatch with a session
  bus in CI, and the macOS mapping with a stub.

**Exit:** media keys, the desktop's media controls and the lock screen
control playback on both platforms, and failures show in the player as they
do for buttons.

### Phase 5: built-in ad blocking and "continue playing" (D5)

Real extensions cannot be used: Qt WebEngine's extension API crashes when
enabling one, and an extension loaded unpacked stays disabled. Both features
are therefore built into Amberfader, each with a switch in the player menu.

- **Ad blocking**, two layers:
  - A `QWebEngineUrlRequestInterceptor` blocks ad and tracking requests,
    using EasyList's YouTube rules (such as `youtube.com/pagead/`,
    `/api/stats/ads`, `/youtubei/v1/player/ad_break`) and the ad hosts
    (doubleclick.net, googlesyndication.com, googleadservices.com,
    imasdk.googleapis.com).
  - A main-world script removes `adPlacements`, `playerAds` and `adSlots`
    from the player data, the technique uBlock Origin's filters use on
    music.youtube.com. It runs before the page's scripts and keeps no bridge
    to the app.
  - YouTube changes its ad delivery often, so this can stop working. The
    switch lets you turn it off if it breaks the page.
- **Continue playing:** when YouTube Music shows its "Video paused. Continue
  watching?" prompt (`ytmusic-you-there-renderer`), the adapter closes it and
  resumes playback, as the YouTube NonStop extension does. The selectors come
  from that extension's source and stay UNVERIFIED until the prompt is seen
  live.

### Phase 6: release (D1)

There is no overlap release. The first PR after the decisions removes the
Firefox extension, the native helper and their tooling, moves the page code
to `web/`, makes `amberfader` start the standalone app, and moves the
version source to `native/amberfader/__init__.py` (the release tool's
`python` kind).

Release 0.2.0 ships the deb, the Flatpak and the macOS `.dmg`. Its release
notes cover migration: sign in again inside Amberfader; faces and appearance
carry over; recent searches from the extension do not; remove the extension
from Firefox yourself.

**Exit:** the release is published, CI is green on all targets, and the
acceptance matrix passed on Linux and macOS.

## 6. CI and release, end state

| Job | Runner | What it proves |
| --- | --- | --- |
| `typescript` | ubuntu-24.04 | tsc, eslint, vitest, page bundle builds |
| `python` | ubuntu-24.04 | ruff, pytest (offscreen), global menu over D-Bus, wheel contains the bundle |
| `embedded` | ubuntu-24.04 | Bridge end to end in real QtWebEngine against the test page |
| `deb` | ubuntu-24.04 | deb installs and self-tests with the sandbox on and the AppArmor restriction set |
| `flatpak` | ubuntu-24.04 | Flatpak builds from the wheel, installs, self-tests and hands a second launch over |
| `macos` | macos-15 | Unit and e2e tests, frozen `.app` self-tests, `.dmg` uploaded |
| `face-editor-macos` | macos-14 | Kept as is, or folded into `macos` |
| Release | same jobs | Publishes `.deb`, `.flatpak`, `.dmg`, wheel and checksums |

Dependency updates: Dependabot (or Renovate) watches `uv.lock` for PySide6.
Chromium security fixes reach Amberfader only through PySide6 releases, so a
PySide6 patch release with security fixes gets an Amberfader release within
a week.

## 7. Testing

- **Unit:** vitest for the adapter, executor, search and protocol; pytest
  for router, history, artwork, paths, lifecycle, MPRIS mapping, settings
  actions.
- **Integration:** the scripted test page in real QtWebEngine on Linux and
  macOS (CI), including pop-ups and sign-out.
- **Packages:** `--self-test` inside every built artifact with Chromium's
  sandbox on.
- **Live (manual, per release):** the acceptance matrix on Linux and macOS
  with your account, one hour of hidden playback on each, and an 8-hour soak
  before 0.2.0. Fixtures never prove that YouTube Music accepts an action.

## 8. Risks

| Risk | Mitigation |
| --- | --- |
| Google starts refusing sign-in from QtWebEngine | Sign-in is part of every release's live check. Changing the user agent stays your decision, not a silent fallback. |
| Chromium in Qt lags Chrome on security fixes | Track PySide6 releases (section 6); keep the navigation allowlist narrow so the browser only ever loads Google and YouTube pages. |
| Size: QtWebEngine adds roughly 200 to 450 MB installed, depending on trimming | Trim unused Qt modules; thin to arm64 on macOS; record sizes per release. |
| Chromium sandbox fails on some Linux setups | AppArmor profile in the deb, Flatpak spike, self-test with the sandbox on in CI. |
| Notarization rejects parts of a Python bundle | Sign every Mach-O, verify with `codesign --strict` and `spctl` in CI before submitting. |
| YouTube Music changes its page | Same as today: fixtures, honest errors, quick adapter releases. The app no longer waits for extension signing. |
| Memory above a Firefox tab | Measure in Phase 0 before tuning. Chromium process flags are a last resort and need a measured benefit. |
| No AAC in the PySide6 build | Playback passed on your Mac with this build, which supports Opus. Recheck if a track does not play. |

## 9. Out of scope for this plan

Windows (the PySide6 wheels exist, so it is possible later), Snap, the Mac
App Store (not evaluated; its sandbox and review rules fit an embedded
Chromium poorly), automatic updates
(Sparkle or similar), Intel Macs unless D3 changes, and Linux aarch64
packages (wheels exist for glibc 2.39 and later; a later CI runner can add
them).

## 10. Pull request sequence

Each entry is one PR through the usual review loop.

1. This plan (merged).
2. Remove the Firefox mode: `amberfader` starts the app, page code in
   `web/`, version source, docs, decision record.
3. Platform folders and macOS migration.
4. Built-in ad blocking and "continue playing".
5. `--self-test` and the page bundle in the wheel.
6. Linux packages: deb with Qt WebEngine and AppArmor, Flatpak.
7. macOS target: PyInstaller `.app`, unsigned `.dmg`, CI and release job.
8. Release 0.2.0.

Later: pop-up windows, settings and diagnostics, MPRIS and Now Playing.

Your parts:

- The remaining gate checks: Start mix, Linux hidden playback and memory.
- The live acceptance run before each release, including ad blocking and
  "continue playing".
