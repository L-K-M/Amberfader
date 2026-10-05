# Plan: Amberfader as a standalone app on Linux and macOS

Status: proposed, 2026-10-05. This plan takes Amberfader from "Firefox
extension plus native helper" to one desktop app that hosts YouTube Music in
QtWebEngine, and adds macOS build targets next to the Linux ones. It builds on
the prototype in [`embedded-prototype.md`](embedded-prototype.md) and
supersedes the Firefox-specific parts of [`PLAN.md`](../PLAN.md) once
[Phase 0](#phase-0-close-the-gate) is done.

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
| `flatpak` | Linux | `dist/amberfader_<ver>.flatpak` | Network and audio permissions; sandbox approach decided in Phase 2. |
| `macos` | macOS (Apple silicon) | `dist/Amberfader-<ver>-macos-arm64.dmg` | `.app` frozen with PyInstaller, signed and notarized if you choose a Developer ID (D2). |
| `ext` | removed in Phase 6 | | Kept until the Firefox mode is retired. |

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
- Chrome extensions: blocked by a Qt crash (see
  [Extensions](embedded-prototype.md#extensions)). Depends on D5.

## 3. Decisions for you

Each has a recommendation. The phases below assume the recommendation until
you decide otherwise.

| # | Decision | Recommendation | Why |
| --- | --- | --- | --- |
| D1 | How long the Firefox mode stays | Ship one release with both modes, then remove the extension, helper and native messaging in the next | One release gives you a fallback while the packages settle. Keeping both long term doubles testing for every change. |
| D2 | macOS signing | Apple Developer ID, hardened runtime, notarization ($99 per year Apple Developer Program, plus GitHub secrets) | Without it, every user must allow the app in System Settings > Privacy & Security on first launch, and each update repeats that. |
| D3 | macOS architectures | Apple silicon only, Intel later if someone asks | Apple has said macOS 26 is the last release for Intel Macs. Universal builds roughly double the Qt payload. |
| D4 | What closing the player does | Hide the player and keep playing; Quit (menu, tray, Dock, Cmd+Q / Ctrl+Q) stops | Matches today's Firefox mode, where closing the player never stopped music, and macOS conventions. |
| D5 | Extensions | Tell me which extensions you need. If it is ad or tracker blocking, block requests natively (Phase 5) | Qt's extension API crashes today and covers only part of Chrome's APIs. |
| D6 | Distribution | GitHub Releases only for the first release; Flathub and a Homebrew cask later | Store listings add review cycles; they are easier once the packages are stable. |

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

**Exit:** all gate items recorded in `embedded-prototype.md`, decision record
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
2. **Lifecycle (D4).** Closing the player hides it while music continues.
   Quit is in the player menu, the tray menu (Linux), the Dock menu (macOS)
   and on Cmd+Q / Ctrl+Q. On Linux the tray icon uses `QSystemTrayIcon`. When
   no tray is available (GNOME without the AppIndicator extension),
   launching Amberfader again shows the running player through the
   single-instance socket. On macOS, clicking the Dock icon shows the player.
   SIGTERM and logout still quit through Qt, so the sign-in cookies are
   flushed.
3. **Pop-up windows.** Sign-in and YouTube Music pop-ups open in a separate
   short-lived window under the same navigation policy, instead of replacing
   the music page. Tested with `window.open` on the test page.
4. **Settings and diagnostics** (replaces the extension options page):
   - Versions of Amberfader, Qt and Chromium, and the profile folder.
   - Whether the page is attached.
   - **Sign out and clear site data:** cookies, storage and HTTP cache.
   - **Copy diagnostics:** versions, states and error codes, never track
     names or queries.
5. **Entry points.** `amberfader` starts the standalone app. During the
   overlap release (D1) the Firefox-mode desktop app is still available as
   `amberfader-firefox`. The user-facing copy drops "prototype", and the close
   tooltip says the music keeps playing.
6. **Page bundle in the wheel.** `adapter.js` is a build output and is
   ignored by git, so hatch leaves it out today. Declare it as a hatch
   artifact. `scripts/build.sh wheel` builds the bundle first. CI fails if
   the built wheel lacks it.
7. **Self-test mode.** `amberfader --self-test` loads the scripted test page
   with Chromium's sandbox on and the real bundle. It checks attach, play,
   pause, search and play result, prints a marker and exits 0. Any failure or
   a 60 s timeout exits non-zero. Every package smoke test in Phases 2 and 3
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
- Smoke in CI: install the deb into a clean Ubuntu 24.04 environment with the
  default AppArmor setting and run `amberfader --self-test`.
- Desktop entry: new description, `desktop-file-validate` in CI. Install
  hicolor icons at 128, 256 and 512 px rendered from `media-sources/icon.png`
  (also for the Flatpak and the player window).

**Flatpak**

- Add `--share=network` and `--socket=pulseaudio`. Keep `--device=dri`,
  Wayland, X11 fallback and IPC.
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
- Replace the helper checks in the smoke probe with `amberfader --self-test`
  inside the installed bundle.

**CI**

- The `deb` job builds, installs and self-tests the deb, then repacks and
  self-tests the Flatpak.
- The Flatpak steps relax the AppArmor knob; the deb smoke runs before they
  do or in its own job, so it tests the default setting.

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
  build (D3). Record the size before and after.
- `Info.plist`:
  - `CFBundleIdentifier` `ch.lkmc.amberfader`
  - `CFBundleShortVersionString` and `CFBundleVersion` from the release
    version
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

**Sign and notarize (D2)**

- Sign from the inside out with `codesign --options runtime --timestamp`:
  every `.so` and `.dylib`, the Qt frameworks, `QtWebEngineProcess.app`,
  then the app.
- Entitlements are the minimum that launches. Expect `allow-jit` for
  `QtWebEngineProcess`, where V8 runs. Add any other entitlement only after a
  hardened-runtime launch fails without it, and record why in the spec.
- Notarize with `xcrun notarytool submit --wait`, staple the app and the
  `.dmg`, and check with `spctl --assess` and `codesign --verify --deep --strict`.
- Secrets (App Store Connect API key, Developer ID certificate) live in a
  GitHub `release` environment with required reviewers. Local builds read a
  keychain profile.
- Without a Developer ID: ad-hoc signature, and the README explains the
  one-time approval in System Settings > Privacy & Security.

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

**CI**

- A `macos` job on an Apple silicon runner (`macos-15`): unit tests and the
  embedded e2e test, then an unsigned build.
- It runs `Amberfader.app/Contents/MacOS/Amberfader --self-test` and uploads
  the `.dmg`.
- The release workflow builds, signs and notarizes in the `release`
  environment and attaches the `.dmg` to the GitHub Release.

**Exit:** the CI artifact self-tests green. You install the `.dmg` on your Mac,
sign in and pass the acceptance matrix. With D2, Gatekeeper accepts it with
no warning.

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

### Phase 5: content blocking or extensions (depends on D5)

- **Ad or tracker blocking:** a `QWebEngineUrlRequestInterceptor` on the
  profile with a network filter list, plus a switch in Settings. This blocks
  trackers and third-party ads. It does not reliably remove YouTube's own
  in-stream ads, which come from the same hosts as the music. YouTube Music
  Premium is the dependable way to remove those.
- **Other extensions:**
  - File the Qt bug with the reproduction from the runbook, and watch PySide6
    releases.
  - When `setExtensionEnabled` stops crashing, add "Install extension from
    folder or zip" to Settings, listing the API limits there.
  - A tiny extension that only changes the page could instead be injected
    as another application-world script.

### Phase 6: release and retire the Firefox mode

1. **Overlap release 0.2.0 (D1):**
   - The standalone app is the default on Linux, and new on macOS.
   - The extension, helper and `amberfader-firefox` still ship.
   - Release notes cover migration:
     - Sign in again inside Amberfader.
     - Faces and appearance carry over.
     - Firefox-mode recent searches do not.
     - How to remove the extension from Firefox.
     - `scripts/uninstall-user` removes per-user native-messaging
       registrations; upgrading the deb removes the system one.
2. **Removal release 0.3.0:**
   - Delete the extension shell: background, controller, popup, options,
     probe, the content entry point, the manifest, locales and web-ext
     tooling.
   - Delete `helper.py`, the Firefox host copy and `PlaybackHost`,
     `install-user`, `uninstall-user` and `doctor` (diagnostics now live in
     Settings).
   - Delete the deb's native-messaging manifest and the Flatpak
     `xdg-run/amberfader` share.
   - Move the remaining TypeScript (adapter, executor, embedded bridge,
     protocol, shared) to `web/` with its tests.
   - Fold the `gui` and `embedded` extras into the base dependencies, since
     no Qt-free component remains.
   - Remove protocol messages only the helper used. Keep schema validation
     between page and router: it is still the boundary to code that runs in
     the page.
3. **Version source:** `extension/manifest.json` is the version source
   today. Move it to `pyproject.toml` and update `sync-versions.mjs` and the
   `release.yml` tag check. `scripts/release.sh` delegates to
   `L-K-M/release-tool` with `RELEASE_KIND=webext`; check that it supports a
   Python kind, or add one there (that is a separate repository).
4. **Docs:** AGENTS.md (rules, identities, commands), README, PLAN.md
   (archived as the Firefox-era plan), `compatibility.md`.

**Exit:** a release with only the standalone app, CI green on all targets,
acceptance matrix passed on Linux and macOS.

## 6. CI and release, end state

| Job | Runner | What it proves |
| --- | --- | --- |
| `typescript` | ubuntu-24.04 | tsc, eslint, vitest, page bundle builds |
| `python` | ubuntu-24.04 | ruff, pytest (offscreen), global menu over D-Bus, wheel contains the bundle |
| `embedded` | ubuntu-24.04 | Bridge end to end in real QtWebEngine against the test page |
| `linux-packages` | ubuntu-24.04 | deb installs and self-tests with the sandbox and default AppArmor; Flatpak installs and self-tests |
| `macos` | macos-15 | Unit and e2e tests, frozen `.app` self-tests, `.dmg` uploaded |
| `face-editor-macos` | macos-14 | Kept as is, or folded into `macos` |
| Release | same jobs | Adds signing and notarization in the `release` environment, publishes `.deb`, `.flatpak`, `.dmg`, wheel and checksums |

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

Each item is one PR through the usual review loop. Items on the same line
can run in parallel.

1. This plan.
2. Phase 0 results and the decision record (after your gate runs).
3. Platform folders and macOS migration.
4. Lifecycle: close hides, Quit, tray, Dock. Then pop-up windows.
5. Settings and diagnostics. Entry point switch, bundle in the wheel,
   `--self-test`.
6. deb with QtWebEngine, AppArmor and smoke test | macOS freeze, `build.sh
   macos`, unsigned CI build.
7. Flatpak (after the spike) | macOS signing, notarization and release job
   (after D2).
8. MPRIS | Now Playing (after the Phase 4 spike).
9. Content blocking or extensions (after D5).
10. Release 0.2.0 with both modes.
11. Remove the Firefox mode, move TypeScript to `web/`, version source,
    AGENTS.md and README; release 0.3.0.

Your parts:

- The Phase 0 gate runs.
- D1 to D6.
- An Apple Developer account and the release secrets (if D2).
- The live acceptance run before each release.
