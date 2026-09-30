#!/usr/bin/env bash
# Repacks the .deb into a .flatpak bundle (LKM §4a): extract dpkg-deb -x into
# dist/flatpak/stage, remap /usr + /opt/amberfader to /app, rewrite Exec lines,
# then flatpak-builder builds from packaging/flatpak/ch.lkmc.amberfader.yml.
#
# Usage: scripts/build-flatpak.sh <path-to.deb>
set -euo pipefail
cd "$(dirname "$0")/.."

DEB="${1:?usage: build-flatpak.sh <path-to.deb>}"
STAGE="dist/flatpak/stage"
BUILD="dist/flatpak/build"
REPO="dist/flatpak/repo"
APP_ID="ch.lkmc.amberfader"

command -v flatpak-builder >/dev/null 2>&1 || {
  echo "!! flatpak-builder not installed" >&2; exit 1; }

FLATHUB_REPO=https://dl.flathub.org/repo/flathub.flatpakrepo

echo "-- extracting $(basename "$DEB")"
rm -rf dist/flatpak
mkdir -p "$STAGE" "$BUILD" "$REPO"
dpkg-deb -x "$DEB" "$STAGE"

# Any payload outside usr/, opt/amberfader/, DEBIAN would be silently dropped
# by the remap below — fail loudly instead of shipping a gutted bundle.
unexpected="$(find "$STAGE" -mindepth 1 -maxdepth 1 -printf '%f\n' | grep -vxE 'usr|opt|DEBIAN' || true)"
unexpected_opt="$(find "$STAGE/opt" -mindepth 1 -maxdepth 1 -printf '%f\n' 2>/dev/null | grep -vx 'amberfader' || true)"
if [[ -n $unexpected$unexpected_opt ]]; then
  printf '!! deb ships payload outside usr/ + opt/amberfader/:\n%s\n%s\n' \
    "$unexpected" "$unexpected_opt" >&2
  exit 1
fi

echo "-- remapping /usr and /opt/amberfader to /app"
mkdir -p "$STAGE/app"
[[ -d "$STAGE/usr" ]] && { cp -a "$STAGE/usr/." "$STAGE/app/"; rm -rf "$STAGE/usr"; }
[[ -d "$STAGE/opt/amberfader/lib" ]] && { cp -a "$STAGE/opt/amberfader/lib/." "$STAGE/app/lib/"; rm -rf "$STAGE/opt"; }
# Wrappers: the pip --target tree now lives at /app/lib.
mkdir -p "$STAGE/app/bin"
cat > "$STAGE/app/bin/amberfader" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/app/lib /usr/bin/python3 -m amberfader.app "$@"
EOF
cat > "$STAGE/app/bin/amberfader-helper" <<'EOF'
#!/bin/sh
exec env PYTHONPATH=/app/lib /usr/bin/python3 -m amberfader.helper "$@"
EOF
chmod 755 "$STAGE/app/bin/amberfader" "$STAGE/app/bin/amberfader-helper"
# Desktop file: app-id filename + Exec rewrites per flatpak rules. The deb
# already ships it app-id-named — rename only when it doesn't.
DESKTOP_DIR="$STAGE/app/share/applications"
DESKTOP_SRC="$(find "$DESKTOP_DIR" -maxdepth 1 -name '*.desktop' -print -quit 2>/dev/null || true)"
if [[ -n $DESKTOP_SRC ]]; then
  sed -i 's/^Exec=.*/Exec=amberfader/' "$DESKTOP_SRC"
  [[ $(basename "$DESKTOP_SRC") == "$APP_ID.desktop" ]] ||
    mv "$DESKTOP_SRC" "$DESKTOP_DIR/$APP_ID.desktop"
fi
# The deb's system-wide host manifest does not belong inside the bundle —
# Flatpak Firefox registration is per-user via scripts/install-user.
rm -rf "$STAGE/app/lib/mozilla" "$STAGE/DEBIAN" 2>/dev/null || true

echo "-- flatpak-builder"
flatpak remote-add --user --if-not-exists flathub "$FLATHUB_REPO"
flatpak-builder --user --install-deps-from=flathub --disable-rofiles-fuse \
  --force-clean --repo="$REPO" "$BUILD" "packaging/flatpak/$APP_ID.yml"

VERSION="$(basename "$DEB" | sed -n 's/^amberfader_\(.*\)_.*\.deb/\1/p')"
OUT="dist/amberfader_${VERSION:-local}.flatpak"
flatpak build-bundle --runtime-repo="$FLATHUB_REPO" "$REPO" "$OUT" "$APP_ID"

# Smoke: install the bundle and probe the real runtime — flatpak-builder
# --run only exercises the SDK build sandbox, which is a superset of the
# runtime and can mask a missing dep. Asserts the manifest's command exists
# under /app/bin, then imports the app's real Qt chain inside the sandbox:
# a genuine QApplication on the offscreen platform forces PySide6's binding
# .so + bundled Qt libs + platform plugin to load for real — strictly
# stronger than ldd, which can't tell the Essentials wheel's dead addon
# modules (WebEngine/Pdf/VirtualKeyboard/sql-driver/designer .so's the app
# never imports — flagged in CI) from live payload.
COMMAND_NAME="$(sed -n '/^command:[[:space:]]*/{s///;p;q}' "packaging/flatpak/$APP_ID.yml" | tr -d "\"'[:space:]")"
[ -n "$COMMAND_NAME" ] || { echo "!! no command: key in manifest" >&2; exit 1; }
flatpak install --user -y --noninteractive "$OUT"
flatpak run --env=QT_QPA_PLATFORM=offscreen --env=PYTHONPATH=/app/lib --command=sh "$APP_ID" -c \
  'test -x "/app/bin/$1" || { echo "missing /app/bin/$1" >&2; ls -l /app/bin >&2; exit 1; }; bad="$(find /app/bin -maxdepth 1 -type f -exec ldd {} \; 2>&1 | grep "not found" | sort -u || true)"; [ -z "$bad" ] || { printf "unresolved libs in /app/bin:\n%s\n" "$bad" >&2; exit 1; }; /usr/bin/python3 -c "import sys;from PySide6.QtWidgets import QApplication;a=QApplication(sys.argv);import amberfader.app,amberfader.helper"' \
  _ "$COMMAND_NAME"
echo "-- built $OUT"
