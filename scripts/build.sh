#!/usr/bin/env bash
# Builds every Amberfader target and stages results in dist/.
#
# Usage: scripts/build.sh [target...] [--clean] [--check] [--install] [--run]
#   targets: wheel deb flatpak macos   (default: all this machine can build)
#   A missing toolchain skips a target on a default run, but fails when the
#   target was named explicitly.
#
#   wheel    python wheel + sdist (uv build)            -> dist/*.whl, dist/*.tar.gz
#   deb      per-user .deb packaging                    -> dist/amberfader_<ver>_*.deb
#   flatpak  the wheel on Flathub's PySide BaseApp      -> dist/amberfader_<ver>.flatpak
#   macos    Amberfader.app in an ad-hoc signed .dmg    -> dist/Amberfader-<ver>-macos-arm64.dmg
#
#   --clean    remove dist/ first
#   --check    print the plan and exit
#   --install  build the macOS apps and install them into /Applications, then
#              reveal them (implies the macos target)
#   --run      launch the installed/built app (implies the macos target)
#
# Requirements: Node 22+ (page scripts, every target), Python 3.11+ + uv
# (wheel), dpkg-deb (deb), flatpak + flatpak-builder + uv (flatpak, Linux
# only; it installs its runtime and BaseApp from Flathub).
set -uo pipefail
cd "$(dirname "$0")/.."

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  awk 'NR==1 && /^#!/ {next} /^#/ {sub(/^# ?/,""); print; next} {exit}' "$0"
  exit 0
fi

DIST="dist"
CLEAN=0
CHECK=0
INSTALL=0
RUN=0
EXPLICIT=""
TARGETS=()

for arg in "$@"; do
  case "$arg" in
    --clean) CLEAN=1 ;;
    --check) CHECK=1 ;;
    --install) INSTALL=1 ;;
    --run) RUN=1 ;;
    --*) echo "!! unknown option: $arg (see --help)" >&2; exit 2 ;;
    *) TARGETS+=("$arg") ;;
  esac
done

# --install/--run are about the macOS app: with no explicit targets they build
# just that, and with explicit targets they make sure `macos` is among them.
if [[ $INSTALL -eq 1 || $RUN -eq 1 ]]; then
  if [[ ${#TARGETS[@]} -eq 0 ]]; then
    TARGETS=(macos); EXPLICIT=1
  else
    found=0
    for t in "${TARGETS[@]}"; do [[ "$t" == macos ]] && found=1; done
    [[ $found -eq 0 ]] && TARGETS+=(macos)
  fi
fi

if [[ ${#TARGETS[@]} -eq 0 ]]; then
  TARGETS=(wheel deb flatpak macos)
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

# Every target ships the page scripts (npm run build); build them once.
PAGE_SCRIPTS=""
page_scripts() {
  [[ -n $PAGE_SCRIPTS ]] && { [[ $PAGE_SCRIPTS == ok ]]; return; }
  PAGE_SCRIPTS=failed
  if ! have node || ! have npm; then
    echo "!! page scripts: node/npm not found"; return 1
  fi
  if [[ ! -d node_modules ]]; then
    npm ci --no-audit --no-fund || return 1
  fi
  npm run --silent build || return 1
  PAGE_SCRIPTS=ok
}

if [[ $CHECK -eq 1 ]]; then
  echo "==> plan"
  echo "-- targets:  ${TARGETS[*]}${EXPLICIT:+ (explicit)}"
  echo "-- version:  $VERSION"
  echo "-- staged:   $DIST/"
  for t in node npm python3 uv dpkg-deb flatpak-builder; do
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
      page_scripts || { FAILED+=("wheel"); continue; }
      if uv build --out-dir "$DIST"; then
        OK+=("wheel → $DIST/")
      else
        FAILED+=("wheel")
      fi
      ;;
    deb)
      echo "==> deb"
      if ! have dpkg-deb; then skip_or_fail deb "dpkg-deb not found"; continue; fi
      page_scripts || { FAILED+=("deb"); continue; }
      if scripts/build-deb.sh "$VERSION" "$DIST"; then
        OK+=("deb → $DIST/")
      else
        FAILED+=("deb")
      fi
      ;;
    flatpak)
      echo "==> flatpak (the wheel on Flathub's PySide BaseApp)"
      if [[ "$(uname -s)" != "Linux" ]]; then
        skip_or_fail flatpak "Flatpak builds run on Linux"; continue
      fi
      if ! have flatpak || ! have flatpak-builder || ! have uv; then
        skip_or_fail flatpak "flatpak, flatpak-builder or uv not installed"; continue
      fi
      page_scripts || { FAILED+=("flatpak"); continue; }
      wheels="$(mktemp -d)"
      if uv build --wheel --out-dir "$wheels" && scripts/build-flatpak.sh "$wheels"/amberfader-*.whl; then
        OK+=("flatpak → $DIST/")
      else
        FAILED+=("flatpak")
      fi
      rm -rf "$wheels"
      ;;
    macos)
      echo "==> macOS app"
      if [[ "$(uname -s)" != "Darwin" ]]; then
        skip_or_fail macos "the macOS app builds on macOS"; continue
      fi
      if ! python3 -c "import PyInstaller" >/dev/null 2>&1; then
        skip_or_fail macos "PyInstaller not installed (pip install pyinstaller and this project)"; continue
      fi
      page_scripts || { FAILED+=("macos"); continue; }
      if scripts/build-macos.sh "$VERSION" "$DIST"; then
        OK+=("macos → $DIST/")
        APPS=("$DIST/macos/dist/Amberfader.app" "$DIST/macos/dist/Amberfader Face Editor.app")
        if [[ $INSTALL -eq 1 ]]; then
          INSTALLED=()
          for APP in "${APPS[@]}"; do
            name="$(basename "$APP")"
            exe="${name%.app}"
            if pgrep -x "$exe" >/dev/null; then
              echo "-- quitting running $exe"
              pkill -x "$exe"; sleep 1
            fi
            echo "-- installing /Applications/$name"
            if ! rm -rf "/Applications/$name"; then
              echo "!! cannot replace /Applications/$name (permissions?)" >&2
              FAILED+=("macos (install $name)"); continue
            fi
            # ditto preserves the signature, resource forks and permissions.
            if [[ -d "$APP" ]] && ditto "$APP" "/Applications/$name"; then
              OK+=("installed → /Applications/$name")
              INSTALLED+=("/Applications/$name")
            else
              FAILED+=("macos (install $name)")
            fi
          done
          if [[ ${#INSTALLED[@]} -gt 0 ]]; then
            if [[ $RUN -eq 1 ]]; then
              open "${INSTALLED[@]}"
            else
              open -R "${INSTALLED[@]}"
            fi
          fi
        elif [[ $RUN -eq 1 ]]; then
          if [[ -d "$DIST/macos/dist/Amberfader.app" ]]; then
            open "$DIST/macos/dist/Amberfader.app"
          else
            echo "!! nothing to run: $DIST/macos/dist/Amberfader.app missing" >&2
            FAILED+=("macos (run)")
          fi
        fi
      else
        FAILED+=("macos")
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
