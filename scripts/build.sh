#!/usr/bin/env bash
# Builds every Amberfader target and stages results in dist/.
#
# Usage: scripts/build.sh [target...] [--clean] [--check]
#   targets: wheel deb flatpak   (default: all this machine can build)
#   A missing toolchain skips a target on a default run, but fails when the
#   target was named explicitly.
#
#   wheel    python wheel + sdist (uv build)            -> dist/*.whl, dist/*.tar.gz
#   deb      per-user .deb packaging                    -> dist/amberfader_<ver>_*.deb
#   flatpak  repack the .deb into a .flatpak bundle     -> dist/amberfader_<ver>.flatpak
#
#   --clean  remove dist/ first
#   --check  print the plan and exit
#
# Requirements: Python 3.11+ + uv (wheel), dpkg-deb (deb), flatpak-builder +
# org.kde.Platform//6.8 (flatpak, Linux only).
set -uo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  awk 'NR==1 && /^#!/ {next} /^#/ {sub(/^# ?/,""); print; next} {exit}' "$0"
  exit 0
fi

DIST="dist"
CLEAN=0
CHECK=0
EXPLICIT=""
TARGETS=()

for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    --check) CHECK=1 ;;
    --*) echo "!! unknown option: $arg (see --help)" >&2; exit 2 ;;
    *) TARGETS+=("$arg") ;;
  esac
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  TARGETS=(wheel deb flatpak)
else
  EXPLICIT=1
fi

VERSION="$(sed -n 's/^__version__ = "\([^"]*\)"/\1/p' native/amberfader/__init__.py)"

declare -a OK=() SKIPPED=() FAILED=()

skip_or_fail() { # target reason
  if [[ $EXPLICIT -eq 1 ]]; then
    echo "!! $1: $2"; FAILED+=("$1")
  else
    echo ".. skipping $1: $2"; SKIPPED+=("$1")
  fi
}

have() { command -v "$1" >/dev/null 2>&1; }

if [[ $CHECK -eq 1 ]]; then
  echo "==> plan"
  echo "-- targets:  ${TARGETS[*]}${EXPLICIT:+ (explicit)}"
  echo "-- version:  $VERSION"
  echo "-- staged:   $DIST/"
  for t in python3 uv dpkg-deb flatpak-builder; do
    printf -- "-- %-16s %s\n" "$t:" "$(command -v "$t" 2>/dev/null || echo missing)"
  done
  exit 0
fi

[[ $CLEAN -eq 1 ]] && { echo "==> cleaning"; rm -rf "$DIST"; }
mkdir -p "$DIST"

for target in "${TARGETS[@]}"; do
  case "$target" in
    wheel)
      echo "==> python wheel"
      if ! have uv; then skip_or_fail wheel "uv not found (https://docs.astral.sh/uv/)"; continue; fi
      if uv build --out-dir "$DIST"; then
        OK+=("wheel → $DIST/")
      else
        FAILED+=("wheel")
      fi
      ;;
    deb)
      echo "==> deb"
      if ! have dpkg-deb; then skip_or_fail deb "dpkg-deb not found"; continue; fi
      if scripts/build-deb.sh "$VERSION" "$DIST"; then
        OK+=("deb → $DIST/")
      else
        FAILED+=("deb")
      fi
      ;;
    flatpak)
      echo "==> flatpak (repack the .deb)"
      if [[ "$(uname -s)" != "Linux" ]]; then
        skip_or_fail flatpak "Flatpak builds run on Linux"; continue
      fi
      if ! have flatpak-builder; then
        skip_or_fail flatpak "flatpak-builder not installed"; continue
      fi
      deb="$(ls -t "$DIST"/amberfader_*_*.deb 2>/dev/null | head -1 || true)"
      if [[ -z "$deb" ]]; then
        if ! have dpkg-deb; then skip_or_fail flatpak "no .deb to repack and dpkg-deb missing"; continue; fi
        scripts/build-deb.sh "$VERSION" "$DIST" || { FAILED+=("flatpak"); continue; }
        deb="$(ls -t "$DIST"/amberfader_*_*.deb 2>/dev/null | head -1 || true)"
      fi
      if scripts/build-flatpak.sh "$deb"; then
        OK+=("flatpak → $DIST/")
      else
        FAILED+=("flatpak")
      fi
      ;;
    *)
      echo "!! unknown target: $target"
      FAILED+=("$target")
      ;;
  esac
done

echo
echo "Summary"
for x in ${OK[@]+"${OK[@]}"}; do echo "   ok      $x"; done
for x in ${SKIPPED[@]+"${SKIPPED[@]}"}; do echo "   skipped $x"; done
for x in ${FAILED[@]+"${FAILED[@]}"}; do echo "   FAILED  $x"; done
[[ ${#FAILED[@]} -eq 0 ]]
