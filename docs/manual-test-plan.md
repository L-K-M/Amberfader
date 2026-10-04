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

- [ ] With YouTube Music already playing, install/reload Amberfader and open
      its player. The tab attaches without reloading or interrupting playback.
- [ ] Pause YouTube Music, then open Amberfader. The current track appears
      without waiting for a playback event.
- [ ] Open Amberfader before opening YouTube Music. The new tab is discovered.
- [ ] Restart the extension background event page. Reopen the player and
      verify that a fresh binding and snapshot restore controls.
- [ ] Deny YouTube Music site access. The player shows an actionable connection
      error rather than waiting indefinitely. Regrant access and reopen it.
- [ ] Both the extension player and GUI show artwork, title, artist, album for
      the playing track. Record the loaded player image's origin and the
      extension artwork request's status/content type if either cover is absent.
- [ ] Pause playback, close and reopen each player, then restart the native
      controller. The same cover returns without a site playback event.
- [ ] While paused, change the player image's source or let its srcset image
      finish loading. Both players update when the image resolves, including
      when an earlier matching player image has an empty source.
- [ ] Artwork downloads slower than a position sample still finish. Changing
      tracks or switching to a cached cover never displays an older result.
- [ ] **Run probes** completes and **Download report** saves readable JSON in
      Firefox/Zen. Record the actual artwork host before granting image access.
- [ ] After Flatpak installation, run the bundled host-side installer. Verify
      both GUI-first and browser-first startup share the same control socket.
- [ ] Native mode reports a missing host or sandbox permission in the options
      rather than implying the desktop connection is healthy.
- [ ] Launch from Discover and the desktop menu, then launch again. The second
      launch raises the existing window only after an activation acknowledgement.
- [ ] Native app opened during paused playback shows the snapshot immediately;
      play/pause requests carry the current session and binding token.
- [ ] Play, pause, previous, next each act exactly once per click and report
      honest failures (no silent double-fire, no fake success).
- [ ] Seek clamps to the seekable interval; a seek issued for a previous
      track is rejected `stale_target`.
- [ ] Volume drag reconciles against observed volume; mute toggles observed
      muted state.
- [ ] Search from the compact UI returns rows; playback is uninterrupted.
- [ ] Selecting a result starts that song; a re-render mid-search does not
      play the wrong row.
- [ ] In both players, compare the heart with YouTube Music's Like button.
      Click to like, then unlike. Each request acts once and the icon changes
      only after `aria-pressed` confirms it. Unknown or conflicting controls
      disable the heart. Switch tracks while a request is pending.
- [ ] Search twice, close/reopen both search windows, and restart the browser.
      Both windows show the saved newest-first queries and played artists.
      Clicking either entry submits a search. Clear recents in one window,
      reopen the other, and verify both lists are empty until new activity.
- [ ] Use **Start mix** on a song result. Verify the correct row's menu opens,
      its mix playlist starts, and no Play/Shuffle action fires. Repeat with
      reordered results, a newer search, and a result that has no mix action.
- [ ] Leave an unrelated YouTube Music menu open, then request a mix. The UI
      asks you to close it rather than using its actions. Slow or unconfirmed
      mix activation reports an uncertain outcome and never retries.
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
- [ ] Inspect the `.deb` with `dpkg-deb --field PACKAGE.deb Depends`. Its Python
      lower bound matches the bundled CPython wheel tags; the upper bound is
      the next minor. Confirm the target's `/usr/bin/python3` uses that minor.
- [ ] `.flatpak` installs; per-user registration via `scripts/install-user`
      works against Flatpak Firefox.
- [ ] `scripts/uninstall-user` removes only app-owned files.

## Linux Faces

Run these checks on both X11 and Wayland, including the Flatpak build. Offscreen
tests verify rendering and state preservation, not compositor integration.

- Open **☰ → Faces…**, or **Ctrl+,**. Preview and apply each bundled face.
  On Aureole and Viridian, check that covers fill their circular sockets and
  leave the original bezel visible. Focus and pending outlines follow the
  button shapes; clicking a transparent button corner does not issue a command.
  Check that utility/transport controls stay inside the metal panels and both
  sliders stay on the glass. Viridian's five readouts share the screen center;
  Aureole's readouts form a centered group in its oval. Check normal and long
  metadata, including unknown/pending/offline states. Open Cover view to see
  the complete image.
- Drag the header or empty metal drag region. Check that transparent cutouts do not intercept
  clicks, and that minimize, close, and second-instance activation work.
- Repeat with `--scale 1.0`, `--scale 1.5`, and `--scale 2.0`, including a small
  display. All controls must remain reachable, and fonts/slider endpoints must
  stay inside the same panel. Drag the declared empty area, including the
  upper empty glass on Viridian. Switch between centered and left-aligned
  faces; their typography must reset without changing playback.
- Switch faces while playing, while a like request is pending, and with search
  results open. Playback and queries must remain intact; the heart must wait
  for reported state; recents, play-result, and **Start mix** must still work.
- Click the cover. Change tracks and faces with Cover view open; check artwork
  updates and absent-artwork placeholders.
- Restart the app and verify the saved face. Remove its user-pack folder and
  restart; expect Amber Classic and an explicit face error.
- Install a local face folder through the native and Flatpak file choosers.
  Check saved paths, reject duplicate IDs, and remove the installed folder.
- Close the GUI and confirm YouTube Music keeps playing.
