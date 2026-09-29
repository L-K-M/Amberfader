# Manual test plan — live acceptance

Everything below needs a real Firefox with a signed-in YouTube Music session.
Synthetic tests cover the machinery; they cannot prove today's selectors.

## Phase 0 — probe battery

Run `extension` options → "Run probes" on a live `music.youtube.com` tab and
save the report. Verify:

- [ ] Media element: one `<video>` drives playback; `paused`/`currentTime`/
      `volume`/`muted`/`seekable` all readable.
- [ ] Transport controls resolvable by selector **and** by ARIA label.
- [ ] Search input accepts the native-setter + `InputEvent` pattern; Enter
      submits; results render into an observable container.
- [ ] Artwork URLs enumerate the real host set (update allowlist + host
      permissions from captured evidence, not guesses).
- [ ] `tabs.hide()`: works on the music tab in a multi-tab window; behavior
      recorded for last-visible-tab and only-tab cases.
- [ ] Hidden controller tab survives discard (`tabs.discard`) without losing
      the `connectNative` port.
- [ ] `play()`/`pause()` via the media element work, or the button-click path
      is the required route — record which.
- [ ] Environment row: Firefox version, package type (deb/rpm/Flatpak/Snap),
      session (X11/Wayland), Qt version.

## Acceptance matrix

- [ ] GUI shows artwork, title, artist, album for the playing track.
- [ ] Play, pause, previous, next each act exactly once per click and report
      honest failures (no silent double-fire, no fake success).
- [ ] Seek clamps to the seekable interval; a seek issued for a previous
      track is rejected `stale_target`.
- [ ] Volume drag reconciles against observed volume; mute toggles observed
      muted state.
- [ ] Search from the compact UI returns rows; playback is uninterrupted.
- [ ] Selecting a result starts that song; a re-render mid-search does not
      play the wrong row.
- [ ] Two music tabs: nothing is auto-bound; explicit target selection is
      required and persists.
- [ ] Tab navigates away or closes → binding revoked; commands fail
      `stale_target`.
- [ ] Content-script reload (tab reload) → old commands cannot execute
      against the new document (nonce check).
- [ ] GUI closed and reopened → single instance raises; helper reconnects.
- [ ] Helper killed → GUI shows disconnected honestly; restart restores.
- [ ] Firefox restart → extension re-registers, controller re-attaches,
      state rebuilds.
- [ ] Hidden playback tab keeps playing; "Show YouTube Music" recovers it.
- [ ] No playback action is retried after an uncertain timeout — pending
      outcome is surfaced instead.

## Soak

- [ ] 8-hour continuous listening: play queue, GUI open, helper attached.
      Record RSS of helper + GUI + controller tab at start/end, skip counts,
      any reconnects. Numbers go into `docs/compatibility.md`.

## Signing / packaging

- [ ] `web-ext sign` (unlisted) produces an installable `.xpi`.
- [ ] `.deb` installs on the target; `amberfader` launches; native host
      manifest lands in `~/.mozilla/native-messaging-hosts`.
- [ ] `.flatpak` installs; per-user registration via `scripts/install-user`
      works against Flatpak Firefox.
- [ ] `scripts/uninstall-user` removes only app-owned files.
