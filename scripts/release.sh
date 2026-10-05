#!/usr/bin/env bash
# Cuts a release: bumps the version, commits, tags "v<version>", and with --push
# pushes branch + tag, which triggers .github/workflows/release.yml to test,
# then build and publish the .deb, .flatpak and macOS .dmg to the GitHub
# Release. native/amberfader/__init__.py (__version__) is the version source;
# RELEASE_POST_BUMP syncs package.json, pyproject.toml and uv.lock.
#
# Usage: scripts/release.sh [X.Y.Z] [--push]
# Shared engine: https://github.com/L-K-M/release-tool (this stub only sets config).
set -euo pipefail
export RELEASE_APP_NAME="Amberfader"
export RELEASE_KIND="python"
export RELEASE_VERSION_FILE="native/amberfader/__init__.py"
export RELEASE_POST_BUMP="node scripts/sync-versions.mjs"
export RELEASE_CI_NOTE="CI (release.yml) will now test, build the .deb, .flatpak and macOS .dmg, and publish the <tag> GitHub Release."
export RELEASE_INVOKED_AS="scripts/release.sh"
BIN="${LKM_RELEASE_BIN:-lkm-release}"
command -v "$BIN" >/dev/null 2>&1 || {
  echo "error: lkm-release not found — clone https://github.com/L-K-M/release-tool and run ./install.sh" >&2
  exit 1
}
exec "$BIN" "$@"
