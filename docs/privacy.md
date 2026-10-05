# Privacy

## What leaves the machine

Amberfader talks to YouTube Music and to Google's sign-in pages, from its own
embedded browser, under your own Google session, as if you used the site in
a browser. There is no telemetry, no analytics, no crash reporting and no
update check.

Navigation is limited to YouTube Music, other `youtube.com` hosts,
`google.com` and Google's `accounts.` country hosts. Other links open in your
system browser. See [Security and privacy](embedded-browser.md#security-and-privacy)
for the full policy.

## What stays on the machine

| Data | Where |
|---|---|
| Google cookies, site storage | Amberfader's own browser profile, `~/.local/share/amberfader/webengine` on Linux |
| HTTP cache | `~/.cache/amberfader/webengine` on Linux |
| Recent searches and played artists | `~/.local/state/amberfader/embedded-search-history.json` on Linux, 20 entries per list |
| Faces and appearance | `~/.local/share/amberfader/faces`, `~/.config/amberfader/appearance.json` |

Delete the profile folder to sign out completely. **Clear recents** in the
search window removes both recent lists; the current track is not
immediately re-added.

## Data paths inside the app

| Data | Path |
|---|---|
| Track metadata (title/artist/album) | page DOM → adapter → QWebChannel → router → player |
| Artwork | HTTPS fetch on an allowlisted image host, **no cookies**, normalized and downscaled before reaching the player |
| Search queries | search window → router → adapter → site search field |
| Playback commands | player → router → the one bound page document |

- The single-instance socket lives in `$XDG_RUNTIME_DIR/amberfader` on Linux
  and in the private `$TMPDIR/amberfader` on macOS (mode 0700, owner-only
  socket). It only lets a second launch raise the running player.
- Page-derived strings pass through `cleanText`/`cleanId` before leaving the
  page; artwork **URLs never reach the player windows**, only the normalized
  thumbnail bytes do.
- Page console output is discarded because it can contain track names.
  Diagnostics go to stderr and name error codes and message kinds, never
  track names, queries or page content.

## Permissions

- Every web permission prompt is denied (notifications, camera, microphone,
  location and others), downloads are cancelled, and WebRTC is limited to
  public network interfaces.
- Artwork is fetched only from Google-owned image hosts on an explicit
  allowlist; redirects are re-validated against it.
- Python dependencies: PySide6 (Qt, including Qt WebEngine) and jsonschema.
  No runtime network SDKs.
