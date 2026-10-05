# Manual test plan: live acceptance

Everything below needs Amberfader signed in to YouTube Music, on Linux and on
macOS. Synthetic tests cover the machinery; they cannot prove today's
selectors.

## Gate

Run the sign-in, persistence, playback, hidden playback, controls, reload and
memory checks in [`embedded-browser.md`](embedded-browser.md#gate) first.

## Selector evidence

Change a selector only with evidence from a live page:

1. Start Amberfader with `QTWEBENGINE_REMOTE_DEBUGGING=127.0.0.1:9222` in the
   environment.
2. Open `http://127.0.0.1:9222` in a Chromium-based browser and inspect the
   YouTube Music page.
3. Save a sanitized fixture (no account names, queries or tokens) under
   `web/tests/fixtures/`, and record the observation, its date and the
   session type in `docs/compatibility.md`.

## Acceptance matrix

- [ ] Start Amberfader with YouTube Music signed in. The player attaches after
      the page loads and shows the current track without waiting for a
      playback event.
- [ ] The player shows artwork, title, artist and album for the playing track.
      If the cover is absent, record the page image's origin.
- [ ] Pause playback, quit and relaunch. The same cover returns without a site
      playback event.
- [ ] While paused, change the player image's source or let its srcset image
      finish loading. The player updates when the image resolves.
- [ ] Artwork downloads slower than a position sample still finish. Changing
      tracks or switching to a cached cover never displays an older result.
- [ ] Launch Amberfader again from the desktop menu or Dock. The second launch
      raises the existing window only after an activation acknowledgement.
- [ ] Play, pause, previous, next each act exactly once per click and report
      honest failures (no silent double-fire, no fake success).
- [ ] Seek clamps to the seekable interval; a seek issued for a previous
      track is rejected `stale_target`.
- [ ] Volume drag reconciles against observed volume; mute toggles observed
      muted state.
- [ ] Search returns rows; playback is uninterrupted.
- [ ] Selecting a result starts that song; a re-render mid-search does not
      play the wrong row.
- [ ] Compare the heart with YouTube Music's Like button. Click to like, then
      unlike. Each request acts once and the icon changes only after
      `aria-pressed` confirms it. Unknown or conflicting controls disable the
      heart. Switch tracks while a request is pending.
- [ ] Search twice, close and reopen the search window, and restart
      Amberfader. The window shows the saved newest-first queries and played
      artists. Clicking either entry submits a search. **Clear recents**
      empties both lists until new activity.
- [ ] Use **Start mix** on a song result. Verify the correct row's menu opens,
      its mix playlist starts, and no Play/Shuffle action fires. Repeat after
      playing a result (the player page is open), with reordered results, a
      newer search, and a result that has no mix action.
- [ ] Leave an unrelated YouTube Music menu open, then request a mix. The
      player asks you to close it rather than using its actions. Slow or
      unconfirmed mix activation reports an uncertain outcome and never
      retries.
- [ ] Reload from the YouTube Music window's toolbar: the player reports the
      reload, then reattaches. Commands issued for the old page fail
      `stale_target`.
- [ ] Open the Google sign-in page: the player reports that YouTube Music is
      showing another page.
- [ ] Hide the YouTube Music window and keep listening. **Show YT** brings
      it back.
- [ ] No playback action is retried after an uncertain timeout; a pending
      outcome is surfaced instead.
- [ ] Closing the player quits Amberfader and stops the music.

## Soak

- [ ] 8-hour continuous listening with the player open. Record the combined
      RSS of Amberfader and its QtWebEngine processes at start and end (the
      command is in the gate), skip counts and any reattaches. Numbers go into
      `docs/compatibility.md`.

## Packaging

- [ ] The `.deb` installs; `amberfader` launches from the desktop menu and a
      terminal.
- [ ] Inspect the `.deb` with `dpkg-deb --field PACKAGE.deb Depends`. Its Python
      lower bound matches the bundled CPython wheel tags; the upper bound is
      the next minor. Confirm the target's `/usr/bin/python3` uses that minor.
- [ ] The `.flatpak` installs and launches; sign-in survives a restart.

## Linux Faces

Run these checks on both X11 and Wayland, including the Flatpak build. Offscreen
tests verify rendering and state preservation, not compositor integration.

- Open **☰ → Faces…**, or **Ctrl+,**. Preview and apply each bundled face.
  On Aureole and Viridian, check that covers fill their circular sockets and
  leave the original bezel visible. Focus and pending outlines follow the
  button shapes; clicking a transparent button corner does not issue a command.
  Opening the player or clicking a control leaves no focus outline; press Tab
  and check that an outline follows keyboard focus.
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
- Close the player and confirm Amberfader quits.

For Plasma's panel menus, follow the X11/Wayland and Flatpak checks in
[KDE global menu](global-menu.md#verification). Menu layout and editor checks
can run without YouTube Music; playback checks still need a live session.

## Audion face import

- On macOS and Linux, choose **File → Import Audion face…** in the editor.
  Browse a converted face folder, a collection folder, and a collection ZIP.
  Check filtering, original credits, conversion notes and the selected preview.
- Cancel importing with an edited document open, including uncommitted inspector
  text. Confirm the draft remains intact. Accept an import and save to a new
  folder; move the source away, reopen the saved copy and install it on Linux.
- Check original sprites, bitmap clocks and soft alpha edges at 1x, 1.5x and 2x.
  Move, resize and rotate the clock and a button in the editor. Check unavailable
  legacy fonts use a local fallback without a download prompt.
- In the player, test popup seek and volume, Escape cancellation, disabled
  controls, track changes during a gesture and switching back to bundled faces.
  Check the right-click menu exposes commands absent from the original artwork.
  Playback acceptance still requires the live YouTube Music session gate.
- In Flatpak, select the containing folder through the native file picker,
  then a ZIP. Verify access includes the selected face's images. An unreadable
  source must show an error and leave the existing document intact.
