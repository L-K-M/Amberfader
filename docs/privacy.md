# Privacy

## What leaves the machine

Nothing by design. Amberfader talks to exactly one remote service — YouTube
Music — and only inside the user's own Firefox tab, under the user's own
session, exactly as if they were using the site directly. There is no
telemetry, no analytics, no crash reporting, no update pinging in v1.

`data_collection_permissions` in the manifest is frozen to match this: the
extension collects nothing Mozilla's categories would require declaring.

## Data paths

| Data | Path |
|---|---|
| Track metadata (title/artist/album) | page DOM → adapter → background → GUI socket |
| Artwork | HTTPS fetch on an allowlisted image host, **no credentials**, normalized and downscaled before reaching any client |
| Search queries | typed by the user → socket → content script → site search field |
| Recent searches and artists | extension-local storage → background → either search window |
| Playback commands | socket → background → bound tab only |

- The Unix control socket lives in `$XDG_RUNTIME_DIR/amberfader` (mode 0700,
  owner-only socket). Other users on the machine cannot see it.
- The helper's stdout carries protocol frames only — no logging, no page
  content. Diagnostics go to stderr.
- Page-derived strings pass through `cleanText`/`cleanId` before crossing a
  boundary; artwork **URLs never reach the GUI** — only the normalized
  thumbnail bytes do.
- Search and track text may be logged nowhere; protocol logs name error
  codes and message kinds, never payloads.
- Recent searches and played artists are saved in this browser profile, with
  20 entries per list. Both windows share these lists. **Clear recents** in
  the search window removes them; the current track is not immediately re-added.

## Permissions audit

- Host access: `music.youtube.com` (adapter) + allowlisted artwork hosts.
- No `<all_urls>`, no cookies, no history, no webRequest, no clipboard, no
  geolocation.
- `nativeMessaging`, `tabHide` are **optional** permissions requested in the
  onboarding page with a user gesture — the extension works extension-only
  without them.

## Third-party surface

- `fetch` of artwork goes to Google-owned image CDNs on an explicit
  hostname allowlist; redirects are re-validated against the allowlist.
- Dependencies are dev-tooling only (esbuild, vitest, eslint, PySide6 wheel
  in the packaged tree). No runtime network SDKs.
