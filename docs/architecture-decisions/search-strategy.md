# ADR: Same-tab controlled-input search

## Status

Accepted (provisional pending Phase 0 probes)

## Context

Amberfader must offer search without interrupting the track that is already
playing. YouTube Music keeps playback state inside the page; a navigation —
even to a search URL — tears the player down.

## Decision

Search runs **inside the playback tab, without navigation**:

1. The adapter locates the site's search input (provisional selectors,
   confirmed by Phase 0 probes before any selector is trusted).
2. Text is written via the **native `value` setter**, then dispatched as an
   `InputEvent` followed by `change` — frameworks ignore a bare
   `.value =` assignment because their model never observes it.
3. Submission uses an `Enter` key event sequence (`keydown`/`keypress`/
   `keyup`), not `location.href` and not `form.submit()`.
4. Completion is **observed**, not slept: a `MutationObserver` waits for the
   results container to change after submit. There are no fixed timeouts
   standing in for "the site rendered".
5. Each search carries a token; a newer search supersedes older ones and
   `stale_result` is reported instead of racing two result sets.
6. Results are capped at 30 rows. `complete: false` is reported when the
   result area is virtualized or paginated — the UI must not claim the list
   is exhaustive.
7. "Play this result" re-resolves the row by title+artist identity at click
   time. A saved DOM index would silently point at the wrong song after any
   re-render.

## Consequences

- The adapter is the only component holding search DOM knowledge; the
  protocol layer sees only normalized `SearchResultRow`s.
- If probes show the input is fully synthetic-event-immune, the fallback is
  site search via its own UI automation entry points — never a second
  hidden tab (that would violate single-tab binding).

## Rejected alternatives

- `location.assign` / opening a new search URL — interrupts playback.
- A second hidden tab for search — doubles the tab binding problem and the
  spec requires the player to stay put.
- YTM's internal API endpoints directly — undocumented, auth-bound, and
  would make the extension behave unlike the site.
