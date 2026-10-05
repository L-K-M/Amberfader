#!/usr/bin/env bash
# Builds dist/amberfader_<version>_<arch>.deb.
#
# The deb layout:
#   /opt/amberfader/lib/              pip --target install of amberfader
#   /usr/bin/amberfader{,-face-editor} wrappers setting PYTHONPATH
#   /usr/share/applications/ch.lkmc.amberfader.desktop
#   /usr/share/icons/hicolor/96x96/apps/amberfader.png
# Depends: the launcher's Python ABI and libdbus for native menus. PySide6,
# including Qt WebEngine, arrives inside the pip --target tree.
#
# Usage: scripts/build-deb.sh <version> <dist-dir>
# Build the page scripts first (npm run build); the wheel build refuses to
# run without them.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${1:?usage: build-deb.sh <version> <dist-dir>}"
DIST="${2:?usage: build-deb.sh <version> <dist-dir>}"
STAGE="$DIST/deb/stage"
LIB="$STAGE/opt/amberfader/lib"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
BUILD_PYTHON="/usr/bin/python3"
PYTHON_VERSION="$("$BUILD_PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
IFS=. read -r PYTHON_MAJOR PYTHON_MINOR <<< "$PYTHON_VERSION"
if (( PYTHON_MAJOR < 3 || (PYTHON_MAJOR == 3 && PYTHON_MINOR < 11) )); then
  echo "error: $BUILD_PYTHON must be Python 3.11 or newer (found $PYTHON_VERSION)" >&2
  exit 1
fi
# Debian sorts a prerelease before its stable version; exclude that ABI too.
NEXT_PYTHON_VERSION="$PYTHON_MAJOR.$((PYTHON_MINOR + 1))~"

echo "-- staging .deb tree (version $VERSION, arch $ARCH)"
rm -rf "$DIST/deb"
mkdir -p "$LIB" "$STAGE/usr/bin" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/96x96/apps" \
  "$STAGE/DEBIAN"

# Resolve native wheels for the launcher's interpreter, not an active venv.
# The dependency interval below keeps its CPython ABI on the same minor.
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$BUILD_PYTHON" --target "$LIB" .
else
  "$BUILD_PYTHON" -m pip install --quiet --target "$LIB" .
fi
# Distutils metadata dirs are noise for end users; keep the code only.
find "$LIB" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cat > "$STAGE/usr/bin/amberfader" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/opt/amberfader/lib /usr/bin/python3 -m amberfader "$@"
EOF
cat > "$STAGE/usr/bin/amberfader-face-editor" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/opt/amberfader/lib /usr/bin/python3 -m amberfader.editor_app "$@"
EOF
chmod 755 "$STAGE/usr/bin/amberfader" "$STAGE/usr/bin/amberfader-face-editor"

cp packaging/icons/amberfader-96.png "$STAGE/usr/share/icons/hicolor/96x96/apps/amberfader.png"
cat > "$STAGE/usr/share/applications/ch.lkmc.amberfader.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Amberfader
Comment=Compact classic-style player for YouTube Music
Exec=amberfader
Icon=amberfader
Terminal=false
Categories=Audio;Music;Player;
StartupWMClass=amberfader
EOF

cat > "$STAGE/DEBIAN/control" <<EOF
Package: amberfader
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Maintainer: L-K-M
Depends: python3 (>= $PYTHON_VERSION), python3 (<< $NEXT_PYTHON_VERSION), libdbus-1-3
Description: Compact classic-style player for YouTube Music
 Plays YouTube Music in its own embedded browser (Qt WebEngine) and shows a
 small player with artwork, playback controls, song search and skinnable
 faces. Sign in once in the YouTube Music window.
EOF

OUT="$DIST/amberfader_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "-- built $OUT"
