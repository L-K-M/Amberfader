#!/usr/bin/env bash
# Builds dist/amberfader_<version>_<arch>.deb.
#
# The deb layout:
#   /opt/amberfader/lib/              pip --target install of amberfader
#   /usr/bin/amberfader               Python launcher (AppArmor attaches to it)
#   /usr/bin/amberfader-face-editor   wrapper setting PYTHONPATH
#   /etc/apparmor.d/amberfader        lets Chromium's sandbox use user namespaces
#   /usr/share/applications/ch.lkmc.amberfader.desktop
#   /usr/share/icons/hicolor/<n>x<n>/apps/ch.lkmc.amberfader.png (scripts/render_icons.py)
# Depends: the launcher's Python ABI, libdbus for native menus, and the system
# libraries Qt WebEngine links against. PySide6, including Qt WebEngine,
# arrives inside the pip --target tree.
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
mkdir -p "$LIB" "$STAGE/usr/bin" "$STAGE/etc/apparmor.d" \
  "$STAGE/usr/share/applications" "$STAGE/usr/share/icons" \
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

# A Python script rather than a shell wrapper: the AppArmor profile attaches
# to this path, and the interpreter keeps it, because no further exec follows.
cat > "$STAGE/usr/bin/amberfader" <<'EOF'
#!/usr/bin/python3
import runpy
import sys

sys.path.insert(0, "/opt/amberfader/lib")
runpy.run_module("amberfader", run_name="__main__", alter_sys=True)
EOF
cat > "$STAGE/usr/bin/amberfader-face-editor" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/opt/amberfader/lib /usr/bin/python3 -m amberfader.editor_app "$@"
EOF
chmod 755 "$STAGE/usr/bin/amberfader" "$STAGE/usr/bin/amberfader-face-editor"

cp -r packaging/icons/hicolor "$STAGE/usr/share/icons/"

cp packaging/linux/apparmor-amberfader "$STAGE/etc/apparmor.d/amberfader"
echo /etc/apparmor.d/amberfader > "$STAGE/DEBIAN/conffiles"
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
# Load the profile now, so the sandbox works without a reboot.
if [ "$1" = configure ] && command -v apparmor_parser >/dev/null 2>&1 &&
    [ -d /sys/kernel/security/apparmor ]; then
  apparmor_parser -r -T -W /etc/apparmor.d/amberfader ||
    echo "amberfader: could not load /etc/apparmor.d/amberfader" >&2
fi
exit 0
EOF
cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = remove ] && command -v apparmor_parser >/dev/null 2>&1 &&
    [ -d /sys/kernel/security/apparmor ] && [ -f /etc/apparmor.d/amberfader ]; then
  apparmor_parser -R /etc/apparmor.d/amberfader || true
fi
exit 0
EOF
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# Qt WebEngine's system libraries: readelf -d over PySide6's Qt libraries,
# QtWebEngineProcess and platform plugins, minus what the wheels bundle,
# mapped to Ubuntu 24.04 packages (docs/handoff.md). CI installs the deb in
# a clean ubuntu:24.04 container and self-tests it.
QT_DEPENDS="libegl1, libgl1, libx11-6, libx11-xcb1, libxcomposite1, libxdamage1, \
libxext6, libxfixes3, libxrandr2, libxtst6, libasound2t64 | libasound2, libbrotli1, \
libdrm2, libexpat1, libfontconfig1, libfreetype6, libgbm1, \
libglib2.0-0t64 | libglib2.0-0, libgssapi-krb5-2, libnspr4, libnss3, libudev1, \
libwayland-client0, libwayland-cursor0, libwayland-egl1, libxcb1, libxcb-cursor0, \
libxcb-dri3-0, libxcb-glx0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, \
libxcb-randr0, libxcb-render0, libxcb-render-util0, libxcb-shape0, libxcb-shm0, \
libxcb-sync1, libxcb-util1, libxcb-xfixes0, libxcb-xkb1, libxkbcommon0, \
libxkbcommon-x11-0, libxkbfile1, zlib1g, libzstd1"
cat > "$STAGE/usr/share/applications/ch.lkmc.amberfader.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Amberfader
Comment=Compact classic-style player for YouTube Music
Exec=amberfader
Icon=ch.lkmc.amberfader
Terminal=false
Categories=AudioVideo;Audio;Music;Player;
StartupWMClass=amberfader
EOF

cat > "$STAGE/DEBIAN/control" <<EOF
Package: amberfader
Version: $VERSION
Section: sound
Priority: optional
Architecture: $ARCH
Maintainer: L-K-M
Depends: python3 (>= $PYTHON_VERSION), python3 (<< $NEXT_PYTHON_VERSION), libdbus-1-3, $QT_DEPENDS
Description: Compact classic-style player for YouTube Music
 Plays YouTube Music in its own embedded browser (Qt WebEngine) and shows a
 small player with artwork, playback controls, song search and skinnable
 faces. Sign in once in the YouTube Music window.
EOF

# dpkg-deb keeps the staged modes, and installer caches can hand out
# owner-only files; everything must be world-readable once installed.
chmod -R u+rwX,go+rX,go-w "$STAGE"

OUT="$DIST/amberfader_${VERSION}_${ARCH}.deb"
dpkg-deb --root-owner-group --build "$STAGE" "$OUT"
echo "-- built $OUT"
