#!/usr/bin/env bash
# Cuts a release: bumps the version, commits, tags "v<version>", and with --push
# pushes branch + tag — which triggers .github/workflows/release.yml to test,
# then build and publish the extension package, .deb and .flatpak to the GitHub
# Release. extension/manifest.json is the version source; package.json moves in
# lockstep (webext kind) and RELEASE_POST_BUMP syncs pyproject.toml +
# native/amberfader/__init__.py.
#
# Usage: scripts/release.sh [X.Y.Z] [--push]
# Shared engine: https://github.com/L-K-M/release-tool (this stub only sets config).
set -euo pipefail
export RELEASE_APP_NAME="Amberfader"
export RELEASE_KIND="webext"
export RELEASE_MANIFEST="extension/manifest.json"
export RELEASE_POST_BUMP="node scripts/sync-versions.mjs"
export RELEASE_CI_NOTE="CI (release.yml) will now test, build the extension package + deb + flatpak, and publish the <tag> GitHub Release. Extension signing (web-ext sign) is a manual step — see docs/compatibility.md."
export RELEASE_INVOKED_AS="scripts/release.sh"
BIN="${LKM_RELEASE_BIN:-lkm-release}"
command -v "$BIN" >/dev/null 2>&1 || {
  echo "error: lkm-release not found — clone https://github.com/L-K-M/release-tool and run ./install.sh" >&2
  exit 1
}
exec "$BIN" "$@"
