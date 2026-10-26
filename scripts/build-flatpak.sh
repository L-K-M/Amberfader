#!/usr/bin/env bash
# Builds dist/amberfader_<version>.flatpak from the Amberfader wheel on
# Flathub's PySide BaseApp (packaging/flatpak/ch.lkmc.amberfader.yml explains
# why). The wheel's other dependencies are downloaded here as wheels for the
# runtime's Python, at the versions uv.lock pins; PySide6 comes from the
# BaseApp.
#
#   dist/flatpak/src/wheels/   amberfader + jsonschema and its dependencies
#   dist/flatpak/src/          desktop entry, AppStream metainfo and hicolor icons
#
# Between building and exporting, it writes the license notices for the
# finished tree to /app/share/doc/amberfader/: Third-Party-Notices.txt,
# Rust-Licenses.html and SOURCES.txt.
#
# Usage: scripts/build-flatpak.sh <path-to-amberfader.whl>
# Needs: flatpak, flatpak-builder, uv, python3 (3.11+), network access
# (Flathub, PyPI).
set -euo pipefail
cd "$(dirname "$0")/.."

WHEEL="${1:?usage: build-flatpak.sh <path-to-amberfader.whl>}"
APP_ID="ch.lkmc.amberfader"
MANIFEST="packaging/flatpak/$APP_ID.yml"
SRC="dist/flatpak/src"
BUILD="dist/flatpak/build"
REPO="dist/flatpak/repo"
FLATHUB_REPO=https://dl.flathub.org/repo/flathub.flatpakrepo

for tool in flatpak flatpak-builder uv python3; do
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
cp packaging/flatpak/"$APP_ID".metainfo.xml "$SRC/"
cp -r packaging/icons/hicolor "$SRC/"

echo "-- flatpak-builder"
# Build and finish without exporting, so the notices below go in first.
flatpak-builder --user --install-deps-from=flathub --disable-rofiles-fuse \
  --force-clean "$BUILD" "$MANIFEST"

echo "-- license notices"
# The bundle carries Amberfader's wheels and both BaseApps it merges (PySide6,
# Qt WebEngine and their libraries); they keep their own licenses. Scan the
# tree after the BaseApp's cleanup, so only what ships is listed. The
# generator fails on a package without license text or with a version its
# overrides were not checked for. SOURCES.txt names every bundled module's
# exact source (flatpak-sources.py fails on an unpinned one).
DOC="$BUILD/files/share/doc/amberfader"
mkdir -p "$DOC"
SITE_ARGS=()
for site in "$BUILD"/files/lib/python3.*/site-packages; do SITE_ARGS+=(--path "$site"); done
python3 -I scripts/python-notices.py "${SITE_ARGS[@]}" --own amberfader \
  --overrides packaging/licenses/python-notices-flatpak.toml \
  --rust-licenses packaging/licenses/Rust-Licenses.html \
  --title "Amberfader's Flatpak bundles the software below, including what the io.qt.PySide.BaseApp and io.qt.qtwebengine.BaseApp it is built on add to /app." \
  --out "$DOC/Third-Party-Notices.txt"
python3 -I scripts/flatpak-sources.py "$BUILD/files" --app Amberfader --out "$DOC/SOURCES.txt"
# python-notices-flatpak.toml took the BaseApp libraries' texts at these
# versions; a BaseApp update must fail here until someone re-checks them.
for pin in "qtwebengine.git tag v6.11.1" "qtwebview.git tag v6.11.1" "pyside-setup.git tag v6.11.2" \
    krb5-1.22.2.tar.gz libevent-2.1.13-stable.tar.gz zlib-1.3.2.tar.gz \
    pciutils-3.15.0.tar.gz re2-2025-11-05.tar.gz "snappy.git tag 1.2.2"; do
  grep -qF "$pin" "$DOC/SOURCES.txt" ||
    { echo "!! BaseApp module changed ($pin): re-check packaging/licenses/python-notices-flatpak.toml" >&2; exit 1; }
done
[[ -e "$BUILD/files/lib/libLLVM.so.21.1" ]] ||
  { echo "!! BaseApp LLVM changed (no libLLVM.so.21.1): re-check packaging/licenses/python-notices-flatpak.toml" >&2; exit 1; }

echo "-- export"
flatpak-builder --user --disable-rofiles-fuse --export-only --repo="$REPO" "$BUILD" "$MANIFEST"

VERSION="$(basename "$WHEEL" | sed -n 's/^amberfader-\([^-]*\)-.*\.whl$/\1/p')"
OUT="dist/amberfader_${VERSION:-local}.flatpak"
flatpak build-bundle --runtime-repo="$FLATHUB_REPO" "$REPO" "$OUT" "$APP_ID"
echo "-- built $OUT"
