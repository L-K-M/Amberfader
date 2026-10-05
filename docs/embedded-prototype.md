# Embedded QtWebEngine prototype

This prototype tests whether Amberfader should host YouTube Music in its own
QtWebEngine window instead of attaching to Firefox. It is experimental. The
Firefox extension and native helper are unchanged and remain the supported
path.

The decision depends on a manual gate that only your desktop can run: Google
sign-in, playback and memory with a real account. See [Gate](#gate).

## How it differs from Firefox mode

```text
Firefox mode
  YouTube Music tab -> content script -> background router -> controller page
    -> native messaging -> helper -> Unix socket -> desktop app

Embedded prototype (one process plus Chromium's helper processes)
  QtWebEngine page -> injected adapter (isolated world) -> QWebChannel
    -> EmbeddedRouter -> desktop app
```

Reused unchanged:

- The site adapter and its selectors (`extension/src/adapter/`), and the
  command executor with request-ID dedup (`extension/src/content/executor.ts`).
- The public protocol and its schema validation.
- The desktop client: `AmberfaderApp` deadlines and binding checks,
  `MainWindow`, faces, search window.

New:

- `extension/src/embedded/`: the page-side bridge, built into
  `native/amberfader/embedded/web/adapter.js` by `npm run embedded:build`.
- `native/amberfader/embedded/`: the router (binding per page document),
  page host, artwork fetcher, search history and navigation policy.

Not needed in this mode: native-messaging registration, the helper, Flatpak
talk permissions, extension permissions, tab discovery and extension signing.

## Run it

From a checkout:

```sh
npm ci
uv sync --extra gui --extra embedded
npm run embedded:run
```

`embedded:run` builds the page bundle and starts
`python -m amberfader.embedded`. Options:

| Option | Effect |
| --- | --- |
| `--background` | Start with the YouTube Music window hidden |
| `--test-page` | Drive a scripted local page instead of YouTube Music (no network, no sign-in) |
| `--scale 1.5` | Same scale factors as the Firefox-mode app |

- **Show YT** shows the YouTube Music window, and **Hide** hides it. Closing
  that window also only hides it.
- Closing the player quits Amberfader and stops the music, because playback
  runs in this process.
- Ctrl+C in the terminal quits cleanly.
- A second launch raises the running instance. Its socket is
  `$XDG_RUNTIME_DIR/amberfader/embedded.sock`, separate from Firefox mode.
  macOS has no `XDG_RUNTIME_DIR`, so there the socket goes in your private
  temporary folder, `$TMPDIR/amberfader/embedded.sock`, unless you have set
  `XDG_RUNTIME_DIR` yourself.

Amberfader targets Linux, but the prototype also starts on macOS. A Mac is
enough to test Google sign-in, persistence and the controls. Hidden playback
and memory results from macOS don't carry over to Linux, so check those on
Linux before deciding.

Where data lives:

| Data | Location |
| --- | --- |
| Profile: cookies and sign-in | `~/.local/share/amberfader/webengine` (delete it to sign out completely) |
| HTTP cache | `~/.cache/amberfader/webengine` |
| Recent searches and artists | `~/.local/state/amberfader/embedded-search-history.json` |

Faces and their preferences are shared with Firefox mode.

## Gate

Run these on your desktop and record each result in the PR or below.

- [ ] **Sign-in.** Press Show YT, choose Sign in and complete Google sign-in,
      including two-step verification. Record whether it is accepted or what
      Google shows instead, for example "This browser or app may not be
      secure". The toolbar shows the origin of the page you are on. If any
      step opens your system browser instead, record that address: the view
      only allows the hosts listed under [Security and privacy](#security-and-privacy).
- [ ] **Persistence.** Quit with the player's close button, relaunch, and
      check that YouTube Music is still signed in.
- [ ] **Playback.** Play several songs from Amberfader's search, including a
      track that YouTube Music plays as a music video. Note any track that
      does not play.
- [ ] **Hidden playback.** Hide the YouTube Music window and minimize the
      player. Playback continues for at least 10 minutes and the player keeps
      updating position and track changes. Pause for at least 5 minutes while
      hidden, then resume from the player.
- [ ] **Controls.** Play, pause, previous, next, seek, volume, like, search,
      play result and Start mix each act once and report failures honestly,
      as in the [acceptance matrix](manual-test-plan.md#acceptance-matrix).
- [ ] **Reload and navigation.** Reload from the window toolbar while
      playing: the player reports the reload, then reattaches. Opening the
      Google sign-in page makes the player report that YouTube Music is
      showing another page.
- [ ] **Memory.** After 5 minutes of playback, record the combined resident
      memory of Amberfader and its QtWebEngine processes:

      ```sh
      pid=$(pgrep -f 'amberfader.embedded' | head -1)
      ps -o rss= -p "$pid" $(pgrep -f QtWebEngineProcess) |
        awk '{s += $1} END {printf "%.0f MiB\n", s / 1024}'
      ```

      RSS counts shared pages more than once, so treat this as an upper
      bound. For comparison, Firefox's `about:processes` shows the YouTube
      Music tab's memory.

If sign-in fails, stay on Firefox and keep improving the bridge. If the gate
passes, the follow-up work is: packaging QtWebEngine (deb and Flatpak), a tray
or background mode so closing the player need not stop music, MPRIS media
keys, and retiring the extension and helper.

## Verified so far

These were checked in a Linux container, not on your desktop:

- PySide6 6.11.2 wheels ship QtWebEngine 6.11.2 on Chromium 140. Media
  Source Extensions are available, `audio/webm; codecs="opus"` is supported
  and `audio/mp4; codecs="mp4a.40.2"` (AAC) is not.
- The default user agent is
  `Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) QtWebEngine/6.11.2 Chrome/140.0.0.0 Safari/537.36`.
  Amberfader does not change it.
- The scripted test page runs end to end in real QtWebEngine: attach, play,
  next, search, play result, recent searches, like, show and hide, page
  scripts unable to reach the bridge, rebinding after a reload, and an old
  binding rejected. This is `native/tests/test_embedded_e2e.py`, run in CI by
  the "Embedded QtWebEngine prototype end to end" job.
- `PySide6-Addons` adds 438 MB installed. That covers every add-on module;
  `libQt6WebEngineCore.so` alone is 195 MB. Packaging would need to trim it,
  or use the Flatpak QtWebEngine base app.

Not verified: anything against live YouTube Music, Google sign-in, real
playback memory, and desktop X11 or Wayland behavior.

## Security and privacy

- The adapter bundle and Qt's `qwebchannel.js` run in QtWebEngine's
  application world, the equivalent of an extension content script. Page
  scripts run in the main world and cannot reach the bridge (tested).
- Injection is limited to the top frame of `https://music.youtube.com`, by
  `@match` and by an origin check in the bundle. The host also accepts page
  messages only while the top-level page is on that origin.
- Top-level navigation stays on YouTube Music, other `youtube.com` hosts,
  `google.com`, and the `accounts.` host of Google's country domains (such as
  `accounts.google.ch`), which sign-in can pass through. Other web links open
  in your system browser. Pop-ups never become a second window.
- Every permission prompt is denied (notifications, camera, microphone,
  location and others). Downloads are cancelled. WebRTC is limited to public
  network interfaces.
- Artwork is fetched without cookies on a separate network stack, with the
  same host allowlist and size limits as the extension.
- Page console output is discarded because it can contain track names.
- Chromium's sandbox stays enabled. Only the automated test disables it, for
  the offline test page.
- Security fixes for the embedded Chromium arrive only with new PySide6
  releases, so keep the environment updated.

## Known limitations

- Closing the player stops playback. There is no tray mode yet.
- A pop-up opened by sign-in or YouTube Music loads in the main view and
  replaces the music page.
- Not packaged. It runs from a checkout only.
- Recent searches are kept separately from Firefox mode's.
- No MPRIS or media keys.
- Google may refuse sign-in from QtWebEngine. Detecting that is the purpose
  of the gate. Changing the user agent to imitate Chrome might get past the
  check, but it disguises the app from a Google security control, so it is
  not done here and is your decision.
