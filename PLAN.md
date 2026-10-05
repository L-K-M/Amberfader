# Classic Music Remote — Execution Plan

> [!NOTE]
> [`docs/standalone-plan.md`](docs/standalone-plan.md) plans the move to a
> standalone app with an embedded browser on Linux and macOS. Once its Phase 0
> gate is done, it replaces the Firefox-specific parts of this plan.

Derived from `firefox-youtube-music-classic-player-implementation-plan.md` (uploaded
2026-09-29, "the spec"). The spec remains the design authority; this document is the
executable task breakdown plus a review delta.

**Spec status:** Approved with amendments (see §1). The spec's strict sequential phases
are reorganized into parallel workstreams so all work that does not require a live
YouTube Music session proceeds immediately.

## 1. Review delta — amendments to fold into the spec

| # | Amendment | Spec section affected |
| --- | --- | --- |
| A1 | Reorganize phases into parallel workstreams; only site-adapter work is gated on Phase 0 | §11 |
| A2 | Phase 0 probe list additions: controlled-input fill technique (native setter + `InputEvent`), `tabs.hide()` last-visible-tab edge case, hidden controller tab vs. `tabs.discard()`, actual artwork host list, `play()`/`volume` via media element vs. site controls | §5, §11 Phase 0 |
| A3 | Record ADR: `window.wrappedJSObject` is available in Firefox content scripts; page-context access is deferred, not impossible | §2 |
| A4 | Pin tooling: ajv (TS) + `jsonschema` (Py) validating shared examples; vitest; pytest + ruff; uv-managed venv; `install-user` script as the sole v1 packaging; toolbar action launches the detached prototype window | §2, §9, §10 |
| A5 | Protocol additions: artwork bytes are base64 in a named asset field; `hello` carries component name/version + profile/install ID; add `connection.ping` liveness to distinguish dead-helper from dead-Firefox | §7, §8 |
| A6 | Record compat limitation: native messaging on Flatpak/Snap Firefox is out of scope for v1; sandbox detection belongs in `doctor` and onboarding | §8 |

Everything else in the spec stands, including: DOM-first adapter strategy, binding
tokens + document generation, hidden controller page owning the native port, no MPRIS
command path, artwork fetched extension-side with a narrow origin allowlist, and all
resource/security limits.

## 2. Workstreams

Dependency rule: **W0 → everything**. W1, W2, W4 run in parallel. W3 requires W2 gate.
W5 requires W4 gate.

```text
W0 scaffold ──┬─► W1 extension foundation (fake adapter) ─┐
              ├─► W2 Phase 0 probes [LIVE GATE] ──► W3 real adapter ─┤
              └─► W4 native helper + desktop app (mock upstream) ────┴─► W5 hardening + release
```

`[LIVE GATE]` = requires the user's desktop: signed-in Firefox, real YTM account.

### W0 — Repository scaffold (no live dependency)

Layout per spec §10. Tasks:

- `package.json` (private, workspaces not needed): TypeScript strict, esbuild bundle
  scripts per entry point (background, content-script adapter, controller, popup,
  options), vitest, eslint. Pin all versions; commit lockfile.
- `pyproject.toml` (uv or venv+pip): PySide6 pinned, pytest, ruff, jsonschema.
  `native/` package `classic_music_remote`; helper kept free of PySide6 imports.
- `protocol/schemas/`: JSON Schema files for every message type in spec §7 plus A5
  additions (`connection.ping`, hello fields, artwork asset). `protocol/examples/`:
  paired valid/invalid vectors consumed by both test suites.
- `scripts/`: `build`, `check` (typecheck+lint+tests both languages), `run-ext`
  (web-ext), `package-ext`, `doctor`, `install-user`, `uninstall-user` — all
  documented in README.
- `extension/manifest.json`: MV3, `background.scripts`, gecko ID
  `classic-music-remote@<domain TBD>`, host permission `music.youtube.com` only,
  `storage`, optional `nativeMessaging` + `tabHide`, toolbar action.
- `.gitignore`, README with verified-command list.

**Done when:** `scripts/check` passes on empty stubs; `web-ext lint` accepts the
manifest.

### W1 — Extension foundation against a fake adapter (spec Phase 1)

- `protocol` TS client + validators (ajv, compiled schemas).
- Background router: sender-role validation (UI page vs content script vs native),
  target listing/selection, binding-token issuance, document-generation tracking via
  `sender.documentId`, request-ID dedup, storage-backed recovery, top-level listener
  registration only.
- Fake adapter module satisfying the adapter interface (scripted states, controllable
  failure modes) registered in place of the real site adapter for tests/dev.
- Detached prototype window (plain HTML/CSS, `windows.create` popup type, reuse/focus
  semantics) rendering `PlayerState`; disabled/pending/error states per spec §9.
- Options/onboarding page: host-permission check, optional-permission requests,
  diagnostics panel, Reconnect action.
- Tests: schema vector conformance (both languages), router unit tests with a fake
  `browser` API, two-tab disambiguation, malformed-message rejection, restart/recovery.

**Done when:** spec Phase 1 exit gate — fake adapter drives prototype; two music tabs
not confusable; malformed messages rejected; router restart preserves reconnect
ability. All verifiable offline.

### W2 — Phase 0 live probes [requires user]

Deliverable is a probe extension + checklist; the user runs it in their Firefox with
an active YTM session. I write everything; the user executes and pastes results.

Probe list (spec §11 Phase 0 + A2):

- [ ] Player DOM: identify controls, metadata containers, media element(s); capture
      sanitized fixtures.
- [ ] Controlled input: does the search box accept native-setter + `InputEvent`
      dispatch? Does site search navigate SPA-style (media element survives)?
- [ ] 20-query search gate incl. empty, non-ASCII, rapid replacement, slow response.
- [ ] `play()`/`pause()`: media-element calls vs. site buttons; autoplay rejection
      behavior; volume via `media.volume` vs. site slider sync.
- [ ] Artwork: actual image hosts; fetchability without credentials; sizes.
- [ ] `tabs.hide()`: eligibility incl. last-visible-tab and only-tab-in-window cases;
      controller-tab hiding; does a hidden tab get discarded and kill a native port?
- [ ] Native messaging round trip: minimal helper ↔ controller page ↔ local socket,
      including a ≥30 min paused interval and event-page unload.
- [ ] Environment record: Firefox version + package type (deb/rpm/Flatpak/Snap),
      desktop session (X11/Wayland), Qt/Python versions.

Outputs: `docs/compatibility.md`, sanitized fixtures in `extension/tests/fixtures/`,
ADR `docs/architecture-decisions/search-strategy.md`, A3 ADR for `wrappedJSObject`.

**Gate (spec):** controls work, artwork retrievable, search non-interrupting, native
round trip verified or explicitly deferred to extension-only v1.

### W3 — Real adapter (spec Phase 2, gated on W2)

- `extension/src/adapter/`: selectors/parsers from W2 fixtures only; capability
  detection; media-event subscription + scoped MutationObservers; ~1 Hz position
  sampling; state revision/occurrence tracking per spec §4.
- Commands with observed-outcome confirmation; seek clamped to seekable range +
  occurrence check; volume desired-vs-observed reconcile; serialized conflicting
  actions; dedup cache.
- Search: site-UI-driven submit, results-bound-to-token wait, normalized song rows
  (cap 30, `complete` flag), `playResult` by re-resolved identity.
- Artwork service on controller page: origin allowlist from W2, HTTPS-only,
  no-credentials fetch, redirect validation, 2 MiB input / 256px / 64 KiB output caps,
  20 MiB cache, bounded concurrency.

**Done when:** spec Phase 2 exit gate — live acceptance cases pass without coordinate
automation, reloads, or private APIs.

### W4 — Native helper + desktop app (spec Phase 4, not live-gated)

Buildable entirely against mocks: loopback socket stands in for the browser; fake
upstream produces `PlayerState` streams.

- `helper.py`: stdio framing (`struct.pack("=I", n)` on *bytes*), exact-length reads,
  partial writes, UTF-8 + size checks, EOF termination; stderr-only diagnostics;
  Unix-socket client to `$XDG_RUNTIME_DIR/classic-music-remote/control.sock` with
  bounded backoff; bounded queues; non-deadlocking duplex.
- Controller extension page: `connectNative` owner, artwork service host, reconnect
  protocol, created inactive/hidden per spec §3.
- Desktop app: QLocalServer (`UserAccessOption`, `0700` dir), single-instance with
  activate-and-exit, protocol client, PySide6 main window (360×150 layout per spec §9)
  + separate search window, keyboard map, slider gesture rules, scale factors.
- `install-user`/`uninstall-user`/`doctor` scripts; native-host manifest generation
  with matching `allowed_extensions`.
- Tests (pytest + fake transports): framing edge cases (truncated, multibyte UTF-8,
  multiple frames/read, oversize), every startup-order/failure row in spec §8's table,
  single-instance, stale-socket removal, GUI state transitions.

**Done when:** spec Phase 4 exit gate, using the loopback mock; live browser
verification folded into W5.

### W5 — Hardening, signing, packaging (spec Phase 5)

- Full live acceptance matrix (spec §12) on the declared target machine; 8-hour soak;
  resource-budget measurements recorded in `compatibility.md`.
- `web-ext sign` (unlisted/self-distributed OK); freeze `gecko.id`, host name,
  `data_collection_permissions` against actual data flow; `strict_min_version` =
  lowest tested Firefox.
- Idempotent per-user install; no `sudo pip`; uninstall removes only app-owned files.
- Fill `docs/manual-test-plan.md`, `privacy.md`, final compat record — no unverified
  claims.

## 3. Cross-cutting rules (from spec, restated as checklist items)

- No site selectors outside `extension/src/adapter/`; no selectors in Python at all.
- No `<all_urls>`, cookies, history, web-request permissions.
- Everything bounded: 256 KiB messages, 500-char queries, 30 results, 5 s/15 s
  deadlines, capped caches and queues.
- Explicit `play`/`pause` (never toggle-retry); observed outcome before reporting
  success; timeout returns pending-outcome error, never silent retry of non-idempotent
  ops.
- Unknown states rendered as unknown; no guessed metadata; no blind fallback clicks.
- Logs carry request IDs/error codes/versions — never song names, queries, or HTML.
- GUI never spawns from the helper's process tree; GUI close never stops playback.

## 4. Decisions needed from the user

1. **Firefox package on the target machine** (deb/rpm vs Flatpak/Snap) — determines
   whether native mode is in scope or v1 ships extension-prototype-only.
2. **gecko add-on ID domain** for `browser_specific_settings.gecko.id` and the
   native-host `allowed_extensions`.
3. **Python env tooling**: uv (recommended) vs plain venv+pip.
4. **Run the W2 probes yourself** and paste results, or grant interactive access to
   your Firefox session (probe extension is loaded via `web-ext run` in a dedicated
   dev profile — never your everyday profile).
5. AMO account for `web-ext sign` at W5 (can defer; prototype + native app run
   unsigned only in dev/Temporary Add-on contexts otherwise).

## 5. Immediate next actions (no user input required)

1. W0 scaffold: package.json/pyproject/manifest/scripts/protocol dirs — fully
   automatable now.
2. Draft JSON Schemas + example vectors for the spec §7 message set + A5 additions.
3. Write the W2 probe extension + runbook so it's ready the moment Firefox access is
   available.
4. W4 helper framing + socket plumbing with loopback tests — independent of the
   browser entirely.
