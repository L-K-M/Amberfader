#!/usr/bin/env bash
# Builds dist/amberfader_<version>_<arch>.deb.
#
# The deb layout:
#   /opt/amberfader/lib/              pip --target install of amberfader[gui]
#   /usr/bin/amberfader{,-helper}     wrappers setting PYTHONPATH
#   /usr/lib/mozilla/native-messaging-hosts/amberfader.json
#   /usr/share/applications/ch.lkmc.amberfader.desktop
#   /usr/share/icons/hicolor/96x96/apps/amberfader.png
# Depends: python3 only — PySide6 arrives inside the pip --target tree.
#
# Usage: scripts/build-deb.sh <version> <dist-dir>
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
NEXT_PYTHON_VERSION="$PYTHON_MAJOR.$((PYTHON_MINOR + 1))"

echo "-- staging .deb tree (version $VERSION, arch $ARCH)"
rm -rf "$DIST/deb"
mkdir -p "$LIB" "$STAGE/usr/bin" "$STAGE/usr/lib/mozilla/native-messaging-hosts" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons/hicolor/96x96/apps" \
  "$STAGE/DEBIAN"

# Resolve native wheels for the launcher's interpreter, not an active venv.
# The dependency interval below keeps its CPython ABI on the same minor.
if command -v uv >/dev/null 2>&1; then
  uv pip install --quiet --python "$BUILD_PYTHON" --target "$LIB" ".[gui]"
else
  "$BUILD_PYTHON" -m pip install --quiet --target "$LIB" ".[gui]"
fi
# Distutils metadata dirs are noise for end users; keep the code only.
find "$LIB" -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true

cat > "$STAGE/usr/bin/amberfader" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/opt/amberfader/lib /usr/bin/python3 -m amberfader.app "$@"
EOF
cat > "$STAGE/usr/bin/amberfader-helper" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/opt/amberfader/lib /usr/bin/python3 -m amberfader.helper "$@"
EOF
chmod 755 "$STAGE/usr/bin/amberfader" "$STAGE/usr/bin/amberfader-helper"

cat > "$STAGE/usr/lib/mozilla/native-messaging-hosts/amberfader.json" <<'EOF'
{
  "name": "amberfader",
  "description": "Amberfader native messaging host",
  "path": "/usr/bin/amberfader-helper",
  "type": "stdio",
  "allowed_extensions": ["amberfader@ch.lkmc"]
}
EOF

cp extension/icons/icon-96.png "$STAGE/usr/share/icons/hicolor/96x96/apps/amberfader.png"
cat > "$STAGE/usr/share/applications/ch.lkmc.amberfader.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Amberfader
Comment=Classic-style remote for YouTube Music in Firefox
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
Depends: python3 (>= $PYTHON_VERSION), python3 (<< $NEXT_PYTHON_VERSION)
Description: Classic-style remote for YouTube Music in Firefox
 Compact player for an existing music.youtube.com tab: playback control,
 artwork, and song search without bringing the browser forward. Registers a
 Firefox native-messaging host for deb/rpm-packaged Firefox; Flatpak Firefox
 is configured per-user via scripts/install-user.
EOF

OUT="$DIST/amberfader_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "-- built $OUT"
