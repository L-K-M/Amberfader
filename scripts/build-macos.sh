#!/usr/bin/env bash
# Builds dist/Amberfader-<version>-macos-arm64.dmg: Amberfader.app frozen with
# PyInstaller, ad-hoc signed (the release is unsigned, see
# docs/standalone-plan.md D2), in a disk image with an Applications link.
#
# Usage: scripts/build-macos.sh <version> <dist-dir>
# Needs: macOS on Apple silicon, Xcode command line tools (iconutil, sips,
# codesign, hdiutil), a Python 3.11+ environment with PyInstaller and this
# project installed, and the page scripts built (npm run build).
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?usage: build-macos.sh <version> <dist-dir>}"
DIST="${2:?usage: build-macos.sh <version> <dist-dir>}"
[[ "$(uname -s)" == Darwin ]] || { echo "error: build-macos.sh runs on macOS" >&2; exit 1; }
[[ "$(uname -m)" == arm64 ]] || { echo "error: the app is built on Apple silicon" >&2; exit 1; }
for f in adapter.js ad-filter.js; do
  [[ -f native/amberfader/embedded/web/$f ]] ||
    { echo "error: page scripts missing; run npm run build" >&2; exit 1; }
done

WORK="$DIST/macos"
rm -rf "$WORK"
mkdir -p "$WORK/Amberfader.iconset"

echo "-- icon from media-sources/icon.png"
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" media-sources/icon.png \
    --out "$WORK/Amberfader.iconset/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  sips -z "$double" "$double" media-sources/icon.png \
    --out "$WORK/Amberfader.iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$WORK/Amberfader.iconset" -o "$WORK/Amberfader.icns"

echo "-- PyInstaller"
AMBERFADER_VERSION="$VERSION" AMBERFADER_ICNS="$PWD/$WORK/Amberfader.icns" \
  python3 -m PyInstaller --noconfirm --clean \
  --distpath "$WORK/dist" --workpath "$WORK/build" packaging/macos/amberfader.spec
APP="$WORK/dist/Amberfader.app"
[[ -d "$APP" ]] || { echo "error: PyInstaller did not produce $APP" >&2; exit 1; }

echo "-- verify the ad-hoc signature"
codesign --verify --deep --strict "$APP"
codesign -dv "$APP" 2>&1 | grep -q "Signature=adhoc" ||
  { echo "error: $APP is not ad-hoc signed" >&2; exit 1; }

echo "-- disk image"
STAGE="$WORK/dmg"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
OUT="$DIST/Amberfader-${VERSION}-macos-arm64.dmg"
rm -f "$OUT"
hdiutil create -volname Amberfader -srcfolder "$STAGE" -ov -format UDZO "$OUT" >/dev/null
(cd "$DIST" && shasum -a 256 "$(basename "$OUT")" > "$(basename "$OUT").sha256")
echo "-- built $OUT"
