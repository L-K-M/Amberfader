#!/usr/bin/env bash
# Runs every check the repo has, in both languages:
#   TS: tsc --noEmit, eslint, vitest; builds the embedded page bundle
#   Python: ruff (if present), pytest (via uv run or .venv)
#   shellcheck on scripts/* (if present)
#   schema sync: the bundled copy in native/amberfader/schema must be
#   byte-identical to protocol/schemas/envelope.schema.json
#
# Usage: scripts/check.sh
set -uo pipefail
cd "$(dirname "$0")/.."

FAILED=0
step() { echo; echo "==> $*"; }
run()  { if "$@"; then :; else echo "!! FAILED: $*"; FAILED=1; fi; }

step "TypeScript: typecheck + lint + unit tests"
run npm run typecheck
run npm run lint
run npm test

step "Freshness: versions + generated validators"
run npm run version:check
run npm run gen:validators:check

step "Schema sync (protocol/schemas -> native/amberfader/schema)"
if cmp -s protocol/schemas/envelope.schema.json native/amberfader/schema/envelope.schema.json; then
  echo "-- schema copies identical"
else
  echo "!! schema copies differ — copy protocol/schemas/envelope.schema.json into native/amberfader/schema/"
  FAILED=1
fi

step "Page bundle (lets the end-to-end test run)"
run npm run --silent build

step "Python: ruff + pytest"
if command -v uv >/dev/null 2>&1 && [[ -d .venv ]]; then
  run uv run ruff check native/ || true
  run uv run pytest -q
elif [[ -d .venv ]]; then
  run .venv/bin/ruff check native/ || true
  run .venv/bin/python -m pytest -q
else
  echo ".. no .venv — run 'uv sync' first (skipping python checks)"
fi

step "shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  for f in scripts/build.sh scripts/build-deb.sh scripts/build-flatpak.sh scripts/build-macos.sh scripts/check.sh scripts/release.sh; do
    [[ -f "$f" ]] && run shellcheck -x "$f"
  done
else
  echo ".. shellcheck not installed — skipping"
fi

echo
[[ $FAILED -eq 0 ]] && echo "==> check: all green" || { echo "==> check: failures above"; exit 1; }
