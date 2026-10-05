# AGENTS.md — engineering guide for Amberfader

Amberfader is a compact classic-style player for YouTube Music. It hosts
music.youtube.com in its own Qt WebEngine (Chromium) profile, which owns
authentication, streaming, decoding and audio output. An injected page
adapter (TypeScript, `web/`) reads and drives the site's own player UI and
talks over QWebChannel to the Python app (`native/`, PySide6), which shows
the player, faces and search. Read
[`docs/standalone-plan.md`](docs/standalone-plan.md) for the current plan;
[`PLAN.md`](PLAN.md) is the original Firefox-era plan, kept for history.

## Critical honesty rule

Every YouTube Music selector in `web/src/adapter/selectors.ts` is marked
**UNVERIFIED** until it has been observed in a live session
(`docs/manual-test-plan.md`). Do not invent selectors from how the page is
"expected" to look, do not claim live behavior that was only tested against
fixtures, and keep `docs/compatibility.md` free of unverified claims. Fixture
tests prove parsing logic, not that YouTube Music accepts an action.

## Commands

```sh
scripts/check.sh        # the one command to run before committing: tsc + eslint +
                        # vitest, ruff + pytest, shellcheck
scripts/build.sh        # multi-target build → dist/ (wheel, deb, flatpak)
npm start               # build the page bundle and run the app
uv run amberfader-face-editor  # standalone face editor
```

Node 22+ (`.nvmrc`), Python 3.11+ via uv (`uv sync`). `uv.lock` and
`package-lock.json` are committed.

## Architecture rules (enforce them in review)

- **Selector ownership:** all YouTube Music selectors live in
  `web/src/adapter/`. Python code must never contain site selectors.
- **One command path:** the page adapter owns playback commands and search.
  Every input surface (player buttons, menus, keyboard, and later media keys)
  issues the same `AmberfaderApp` requests; none touches the page directly.
- **Embedded browser policy:** the adapter bundle is injected only into the
  top frame of `https://music.youtube.com`, in the application world; page
  scripts must not reach the bridge. The only main-world script is the ad
  filter (`web/src/adfilter/`), which must never get a bridge reference or
  send data anywhere. Top-level navigation stays on the
  allowlist in `native/amberfader/embedded/navigation.py`; every web
  permission prompt is denied and downloads are cancelled. Never change the
  user agent or disable Chromium's sandbox outside tests. Artwork hosts are
  added only for origins observed live.
- **Bounds:** 256 KiB transport messages, 500-char queries, 30 search results
  per batch, 5 s control / 15 s search deadlines, 2 MiB artwork input, 256 px /
  64 KiB thumbnails, 20 MiB artwork cache.
- **Truthful states:** explicit `play`/`pause` (no toggle-retry), report
  completion only after an observed outcome, `pending_outcome` on timeout,
  unknown states rendered as unknown, no blind fallback clicks.
- **Lifecycle:** playback runs in this process; closing the player quits the
  app. A second launch only raises the running instance; two processes must
  never share one browser profile.
- **Dedup:** the page executor dedups request IDs within a document
  generation; non-idempotent ops are never replayed after reconnect.
- **Framing:** the single-instance socket uses a 4-byte native-order length +
  UTF-8 JSON; `struct.pack("=I", len(encoded_bytes))`. Measure bytes, not
  characters.
- **Logging:** diagnostics go to stderr and name error codes and message
  kinds, never track names, queries or page content. Page console output is
  discarded.

## Platforms

Linux (deb and Flatpak) and macOS 13+ on Apple silicon. Snap, Intel Macs and
Windows are out of scope.

## Identities (keep stable)

| Item | Value |
| --- | --- |
| App and Flatpak ID, macOS bundle ID | `ch.lkmc.amberfader` |
| Single-instance socket | `$XDG_RUNTIME_DIR/amberfader/embedded.sock` (Linux), `$TMPDIR/amberfader/embedded.sock` (macOS) |
| Browser profile name | `amberfader-embedded` |
| Data folders | XDG base directories + `amberfader` (Linux); `~/Library/Application Support/Amberfader`, `~/Library/Caches/Amberfader` (macOS); see `native/amberfader/paths.py` |
| Desktop entry | `ch.lkmc.amberfader.desktop` |

## Testing

- `web/tests/unit` (vitest + jsdom): protocol vectors, dedup, the page bridge,
  search state machine, adapter parsing vs fixtures.
- `native/tests` (pytest): framing edge cases, the same protocol vectors
  (`protocol/examples/` is shared by both suites), router, artwork, player
  client, socket single-instance logic (Qt offscreen:
  `QT_QPA_PLATFORM=offscreen`), and the page bridge end to end in real Qt
  WebEngine against a scripted test page.
- Live YouTube Music behavior is a manual gate. Fixtures never prove the site
  accepts an action.

<!-- shared-rules:start -->

## Working practices

- Follow explicit task instructions over the default workflow below.
- Writing the code is not finishing the task. A task is finished when
  its changes are merged to main through a PR that passed CI and review,
  or when the user explicitly accepts a different end state.
- Start every task on current code. Fetch first, then cut the task
  branch from origin/main — never from a stale local branch or an old
  checkout. To continue existing work, rebase or merge the latest
  origin/main into it before editing. Never overwrite existing work to
  update.
- Resolve ambiguity before making consequential changes. State low-risk
  assumptions; ask when scope, safety, or expected behavior is unclear.
- Keep changes focused. Do not modify unrelated code, formatting, or comments.
- Prefer surgical edits over whole-file rewrites when the result is equivalent.
- Stage only intended files. Inspect the diff before committing.

## Communication

- Be concise, factual, and direct. Preserve necessary context and uncertainty.
- Avoid praise, motivational filler, emojis, and em dashes in new prose.
- Address the reader directly in user-facing copy.
- Report what was verified and what remains unverified. Never imply that an
  unavailable check passed.

## Code design

- Prefer early returns and shallow nesting. Separate logical blocks with
  blank lines.
- Use descriptive constants or enums for meaningful or repeated values.
  Use existing standard definitions for protocol/specification constants.
  Keep obvious, one-off values inline.
- Use enums for behavioral modes that would otherwise require ambiguous
  boolean arguments.
- Default members to private. Widen visibility only for required consumers,
  and review the change as an API design decision.
- Follow the repository's declared dependency boundaries. UI and controllers
  must use application services rather than directly accessing databases,
  subprocesses, sockets, or other low-level mechanisms.
- Encapsulate low-level mechanics behind domain-oriented interfaces.
- Reuse genuinely shared logic. Avoid speculative abstractions and layers
  that only forward calls.
- Prefer pure functions for business rules and immutable data where practical.
- Isolate side effects; document non-obvious state ownership or synchronization.
- Explain non-obvious intent, constraints, and tradeoffs in comments.
  Do not narrate obvious code. Add examples or diagrams when they clarify it.

## Validation and errors

- Validate untrusted input at entry points. Where practical, represent valid
  states in types and enforce persistent invariants in database schemas.
- Represent absence and failure explicitly.
- Use assertions for internal programming invariants, not external-input
  validation or required runtime error handling.
- Prefer explicit, actionable errors over silent failure or undocumented
  fallback. Document intentional recovery behavior.
- Never report a skipped or failed operation as successful.

## Bug fixes

1. Identify the root cause and define an observable success criterion.
2. Add a regression test and observe the relevant failure before fixing it.
3. Implement the fix and observe the test passing.
4. Check surrounding behavior for regressions and architectural consistency.

If an automated regression test is impractical, document the reproduction
and verification procedure. State any inability to reproduce the failure.

## Verification

- Run relevant tests and lint after changes.
- Choose coverage by affected behavior and risk, not patch size.
- Use integration or end-to-end tests for critical workflows and boundaries;
  test isolated business rules at the lowest effective level.
- Run broader suites for cross-cutting or high-risk changes, and the full
  required release checks before releasing.
- Validate the requested command, options, platform, and configuration.
  Unrelated green CI is not proof that the reported problem is fixed.
- Recheck after the final edit. Distinguish local checks from CI results.

## Commit messages

- Use a capitalized, imperative subject without a final period.
- Target 50 characters; never exceed 72.
- Separate the subject and body with one blank line.
- Wrap body text at 72 characters.
- Explain what changed and why. Leave implementation mechanics to the code.

## Implementation and review

Unless explicitly instructed otherwise:

1. Work on a focused branch cut from the latest origin/main and open a PR
   against main before reporting the task as done.
2. Inspect CI results and completed review feedback for the latest commit.
   A successful reviewer job does not mean the review found no problems.
3. Address important findings or explain why they do not apply. Handle minor
   findings according to the stopping rules below.
4. Evaluate each fix in the surrounding project, add regression coverage,
   and rerun affected checks before pushing.
5. Repeat until a stopping criterion is met.
6. Merge without asking again once the stopping criterion is met, required
   checks pass on the latest commit, and no unresolved blockers or required
   human review requests remain.

### Reviewer context limits

The automated PR reviewer does not see the user's original prompt or
conversation. It may suggest changes that go against or beyond what the
user asked for. Do not implement such suggestions. Note each conflict and
report it to the user at the end of the thread.

### Automated review stopping rules

Judge findings by verified impact, not the reviewer's severity label.
Important findings concern correctness, security, data loss, broken builds,
or materially degraded behavior/performance.

Track completed review rounds and consecutive rounds without important
findings. Reruns of the same revision and integration failures do not count.

- No applicable actionable feedback: finish immediately.
- First minor-only round: optionally fix worthwhile, low-risk findings.
  Do not manufacture another push merely to obtain another review.
- Two consecutive rounds without important findings: stop responding to
  automated nitpicks, even if actionable minor suggestions remain.
- Two consecutive rounds without important findings: stop responding to
  automated nitpicks, even if actionable minor suggestions remain.
- A confirmed important finding resets the minor-only streak. Address it
  and verify the fix before continuing.

After ten completed rounds, enter stabilization:

- Stop optional cleanup, refactoring, and nitpick fixes.
- One completed review without confirmed important findings is sufficient
  to finish, even if minor suggestions remain.
- Continue only for confirmed important defects. If resolving them stalls,
  report the blockers rather than continuing indefinitely.

These limits end optional automated-feedback work. They do not waive
confirmed blockers, unresolved human review requests, or required checks.

### Reviewer integration failures

After two consecutive reviewer-integration failures, stop and report the
review gap. Do not treat failures as approval. An explicit user instruction
may waive review; report that waiver rather than claiming review passed.

## Ending a task

- A task ends with its changes merged to main — not with code written,
  and not with a PR merely opened. An open PR is work in progress:
  monitor CI on the latest commit, address review findings per the
  stopping rules, and merge once the criteria are met.
- Never finish with uncommitted changes or unpushed commits in the
  worktree. Commit, push, and open or update the PR first.
- If a step is impossible (missing push access, CI failure, reviewer
  outage), report the exact blocker instead. Never present unreviewed or
  unmerged work as finished.
- Before finishing, confirm: the requested behavior is implemented
  without unrelated changes; relevant checks pass on the latest code;
  important review findings are addressed or rejected with reasons;
  deferred suggestions, remaining risks, and validation gaps are
  disclosed.
- The final response states where the work stands: branch, PR, CI
  status, review rounds completed, and whether it is merged.

<!-- shared-rules:end -->
