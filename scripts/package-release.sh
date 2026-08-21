#!/usr/bin/env bash
#
# Build a packaged release (plan §10 Pkg9, §11.3).
#
# Steps:
#   1. Freeze the Python sidecar for the host arch (PyInstaller onefile).
#   2. Stamp release provenance (version, git commit, build time, arch)
#      into shared/release.ts (scripts/stamp-release.js).
#   3. Build the Electron renderer/main/preload.
#   4. Package with electron-builder (macOS DMG; win/linux when requested).
#
# Auto-update is intentionally NOT configured (plan §10 Pkg9 step 4):
# there is no `publish` block and no updater dependency, so a packaged
# app never self-updates. Updates ship as signed artifacts and are
# verified manually until update signing/rollback are proven.
#
# Usage:  ARCH=arm64 PLATFORM=mac scripts/package-release.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/desktop"

ARCH="${ARCH:-$(uname -m)}"
case "$ARCH" in
  x86_64) ARCH="x64" ;;
  aarch64|arm64) ARCH="arm64" ;;
esac
PLATFORM="${PLATFORM:-mac}"
VERSION="$(node -p "require('./package.json').version")"
COMMIT="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "==> freezing sidecar (arch=$ARCH)"
npm run build:sidecar

echo "==> stamping release provenance"
MM_VERSION="$VERSION" MM_COMMIT="$COMMIT" MM_BUILD_TIME="$BUILD_TIME" MM_ARCH="$ARCH" \
  node "$ROOT/scripts/stamp-release.js"

echo "==> building"
npm run build

echo "==> packaging ($PLATFORM/$ARCH)"
case "$PLATFORM" in
  mac) npm run package:mac ;;
  win) npm run package:win ;;
  linux) npm run package:linux ;;
  *) echo "unknown platform: $PLATFORM" >&2; exit 1 ;;
esac

echo "==> done. artifacts in desktop/release/"
