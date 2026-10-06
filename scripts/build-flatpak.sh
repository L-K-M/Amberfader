#!/usr/bin/env bash
# Builds dist/amberfader_<version>.flatpak from the Amberfader wheel on
# Flathub's PySide BaseApp (packaging/flatpak/ch.lkmc.amberfader.yml explains
# why). The wheel's other dependencies are downloaded here as wheels for the
# runtime's Python, at the versions uv.lock pins; PySide6 comes from the
# BaseApp.
#
#   dist/flatpak/src/wheels/   amberfader + jsonschema and its dependencies
#   dist/flatpak/src/          desktop entry and hicolor icons
#
# Usage: scripts/build-flatpak.sh <path-to-amberfader.whl>
# Needs: flatpak, flatpak-builder, uv, network access (Flathub, PyPI).
set -euo pipefail
cd "$(dirname "$0")/.."

WHEEL="${1:?usage: build-flatpak.sh <path-to-amberfader.whl>}"
APP_ID="ch.lkmc.amberfader"
MANIFEST="packaging/flatpak/$APP_ID.yml"
SRC="dist/flatpak/src"
BUILD="dist/flatpak/build"
REPO="dist/flatpak/repo"
FLATHUB_REPO=https://dl.flathub.org/repo/flathub.flatpakrepo

for tool in flatpak flatpak-builder uv; do
  command -v "$tool" >/dev/null 2>&1 || { echo "!! $tool not installed" >&2; exit 1; }
done
[[ -f $WHEEL ]] || { echo "!! no wheel at $WHEEL" >&2; exit 1; }

manifest_value() { sed -n "s/^$1:[[:space:]]*['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}[[:space:]]*$/\1/p" "$MANIFEST"; }
RUNTIME="$(manifest_value runtime)//$(manifest_value runtime-version)"

echo "-- runtime $RUNTIME"
flatpak remote-add --user --if-not-exists flathub "$FLATHUB_REPO"
flatpak install --user --noninteractive -y flathub "$RUNTIME"
PYTHON_VERSION="$(flatpak run --command=python3 "$RUNTIME" -c \
  'import sys; print("%d.%d" % sys.version_info[:2])')"

echo "-- wheels for the runtime's Python $PYTHON_VERSION"
rm -rf dist/flatpak
mkdir -p "$SRC/wheels" "$BUILD" "$REPO"
cp "$WHEEL" "$SRC/wheels/"
# PySide6 and shiboken6 come from the BaseApp, built against its Qt. pip
# evaluates the lock's environment markers against the Python it runs on,
# so it runs on the runtime's version.
uv export --frozen --no-dev --no-hashes --no-emit-project --format requirements-txt |
  grep -viE '^(pyside6|shiboken6)' > "$SRC/requirements.txt"
uv tool run --python "$PYTHON_VERSION" pip download --quiet --only-binary=:all: --no-deps \
  --python-version "$PYTHON_VERSION" --implementation cp \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 \
  --platform manylinux2014_x86_64 \
  --dest "$SRC/wheels" -r "$SRC/requirements.txt"

cp packaging/linux/"$APP_ID".desktop "$SRC/"
cp -r packaging/icons/hicolor "$SRC/"

echo "-- flatpak-builder"
flatpak-builder --user --install-deps-from=flathub --disable-rofiles-fuse \
  --force-clean --repo="$REPO" "$BUILD" "$MANIFEST"

VERSION="$(basename "$WHEEL" | sed -n 's/^amberfader-\([^-]*\)-.*\.whl$/\1/p')"
OUT="dist/amberfader_${VERSION:-local}.flatpak"
flatpak build-bundle --runtime-repo="$FLATHUB_REPO" "$REPO" "$OUT" "$APP_ID"
echo "-- built $OUT"
