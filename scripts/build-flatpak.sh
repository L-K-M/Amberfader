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

echo "-- extracting $(basename "$DEB")"
rm -rf dist/flatpak
mkdir -p "$STAGE" "$BUILD" "$REPO"
dpkg-deb -x "$DEB" "$STAGE"

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
# Desktop file: app-id filename + Exec rewrites per flatpak rules.
if [[ -f "$STAGE/app/share/applications/ch.lkmc.amberfader.desktop" ]]; then
  sed -i 's/^Exec=.*/Exec=amberfader/' "$STAGE/app/share/applications/ch.lkmc.amberfader.desktop"
  mv "$STAGE/app/share/applications/ch.lkmc.amberfader.desktop" \
     "$STAGE/app/share/applications/$APP_ID.desktop"
fi
# The deb's system-wide host manifest does not belong inside the bundle —
# Flatpak Firefox registration is per-user via scripts/install-user.
rm -rf "$STAGE/app/lib/mozilla" "$STAGE/DEBIAN" 2>/dev/null || true

echo "-- flatpak-builder"
flatpak-builder --disable-rofiles-fuse --force-clean --repo="$REPO" \
  "$BUILD" "packaging/flatpak/$APP_ID.yml"

# Smoke: the manifest's command must exist under /app/bin and every bundled
# ELF (PySide6 .so tree included) must resolve its libraries inside the
# runtime — catches a bad /usr->/app remap or a missing runtime dep before
# the bundle ships. Ubuntu 24.04's flatpak-builder 1.4.2 has no --user flag
# on --run; plain --run resolves the user-installed runtime fine.
COMMAND_NAME="$(sed -n '/^command:[[:space:]]*/{s///;p;q}' "packaging/flatpak/$APP_ID.yml")"
[ -n "$COMMAND_NAME" ] || { echo "!! no command: key in manifest" >&2; exit 1; }
flatpak-builder --run "$BUILD" "packaging/flatpak/$APP_ID.yml" \
  sh -c 'bin="/app/bin/$1"; test -x "$bin" || { echo "missing $bin" >&2; ls -l /app/bin >&2; exit 1; }; bad="$(find /app -type f \( -name "*.so*" -o -path "/app/bin/$1" \) -exec ldd {} \; 2>/dev/null | grep "not found" | sort -u || true)"; [ -z "$bad" ] || { printf "unresolved libraries:\n%s\n" "$bad" >&2; exit 1; }' _ "$COMMAND_NAME"
VERSION="$(basename "$DEB" | sed -n 's/^amberfader_\(.*\)_.*\.deb/\1/p')"
OUT="dist/amberfader_${VERSION:-local}.flatpak"
flatpak build-bundle "$REPO" "$OUT" "$APP_ID"
echo "-- built $OUT"
