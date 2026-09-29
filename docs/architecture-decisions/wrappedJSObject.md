# ADR: Page-context access via `wrappedJSObject` — deferred, not impossible

## Status

Accepted (deferred)

## Context

Firefox content scripts can reach page JavaScript objects through the Xray
wrapper's `wrappedJSObject` escape hatch — a capability Chrome content
scripts do not have. The original spec phrased page-JS access as impossible;
that is inaccurate for Firefox specifically.

## Decision

All adapter interactions go through **ordinary DOM and media-element APIs
only** in v1. `wrappedJSObject` is reserved as the escape route if Phase 0
probing proves DOM access insufficient — the likeliest candidates are the
player's JS queue API (for richer next/previous semantics) and framework
internals that reject synthetic input.

## Why defer

- Page JS objects are undocumented internals: they change shape without
  notice and bypass the sanitization boundary the adapter enforces on
  page-derived data.
- Xray access still runs in the content-script sandbox, but everything read
  through it must pass the same `cleanText`/`cleanId` funnel as DOM reads —
  there is no "trusted" page object.
- DOM observation is enough for every control the spec requires: play/pause,
  seek, volume, mute, prev/next, search. Nothing in v1 scope needs internals.

## Revisit when

- A required control provably has no DOM affordance (Phase 0 finding).
- Volume/seek semantics need the player's own math rather than the media
  element's.

Any adoption must be recorded in a follow-up ADR with the exact page path
accessed and the probe evidence requiring it.
