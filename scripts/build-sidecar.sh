#!/usr/bin/env bash
#
# Freeze the Python sidecar into a platform-matched executable that
# Electron launches in packaged builds (plan §10.6.3).
#
# Output:
#   desktop/sidecar/{arch}/ferry-service        (macOS/Linux)
#   desktop/sidecar/{arch}/ferry-service.exe    (Windows)
#
# electron-builder's extraResources copies `sidecar/{arch}` to
# `Contents/Resources/sidecar/{arch}` in the packaged app, which is
# exactly where electron/sidecar-command.ts looks for it.
#
# Requires a virtualenv with the package installed (`pip install -e .`)
# and PyInstaller. Usage:  scripts/build-sidecar.sh [arch]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ARCH="${1:-$(uname -m)}"
if [[ "$ARCH" == "x86_64" ]]; then ARCH="x64"; fi
if [[ "$ARCH" == "aarch64" || "$ARCH" == "arm64" ]]; then ARCH="arm64"; fi

OUT_DIR="$ROOT/desktop/sidecar/$ARCH"
SPEC="$ROOT/scripts/sidecar.spec"
WORK_DIR="$ROOT/build/pyinstaller-work"
VENV_PY="$ROOT/.venv/bin/python"

if [[ ! -x "$VENV_PY" ]]; then
  echo "error: no venv python at $VENV_PY; create .venv and pip install -e ." >&2
  exit 1
fi

# Ensure PyInstaller is present.
if ! "$VENV_PY" -m PyInstaller --version >/dev/null 2>&1; then
  echo "error: PyInstaller not installed in .venv (pip install pyinstaller)" >&2
  exit 1
fi

echo "building sidecar for arch=$ARCH"
rm -rf "$OUT_DIR" "$WORK_DIR"
mkdir -p "$OUT_DIR" "$WORK_DIR"

"$VENV_PY" -m PyInstaller \
  --distpath "$OUT_DIR" \
  --workpath "$WORK_DIR" \
  --clean \
  --noconfirm \
  "$SPEC"

echo "done: $OUT_DIR/ferry-service"
