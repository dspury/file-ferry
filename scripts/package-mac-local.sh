#!/usr/bin/env bash
#
# Local, UNSIGNED macOS package (Stage A1).
#
# `package:mac` uses desktop/build/electron-builder.yml with
# `notarize: true`, `hardenedRuntime: true`, and `dmg.sign: true`, which is
# the release path: it needs an Apple Developer ID and notarization
# credentials in the environment. This script must not touch it — the
# released config's defaults stay exactly as committed.
#
# This script derives a throwaway overlay for local development builds,
# which docs/RELEASE.md defines as unsigned ("local builds run unsigned
# for development"):
#   - notarize: false, hardenedRuntime: false, dmg.sign: false,
#     mac.identity: null (skip codesign entirely — there is no identity on
#     a machine without credentials)
# combined with CSC_IDENTITY_AUTO_DISCOVERY=false in package.json's
# `package:mac:local`. Gatekeeper will refuse the first open of the result
# ("cannot be opened because the developer cannot be verified");
# right-click -> Open gets past it, once per machine.
#
# Usage: scripts/package-mac-local.sh   (run from desktop/ by package:mac:local)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/desktop/build/electron-builder.yml"
OVERLAY_DIR="$(mktemp -d)"
OVERLAY="$OVERLAY_DIR/electron-builder.local.yml"

# Sed the release spec into unsigned form. Assert every substitution
# actually fired so a changed release config cannot silently re-enable
# signing here.
cp "$SRC" "$OVERLAY"
sed -i.bak \
  -e 's/^  notarize: true$/  notarize: false/' \
  -e 's/^  hardenedRuntime: true$/  hardenedRuntime: false/' \
  -e 's/^    sign: true$/    sign: false/' \
  "$OVERLAY"
rm "$OVERLAY".bak

if grep -E '^  (notarize|hardenedRuntime): true|^    sign: true' "$OVERLAY"; then
  echo "error: unsigned overlay still contains signing settings; the release config changed" >&2
  exit 1
fi
if ! grep -E '^  notarize: false|^  hardenedRuntime: false' "$OVERLAY"; then
  echo "error: overlay substitutions did not line up; the release config changed" >&2
  exit 1
fi

cd "$ROOT/desktop"

python3 - "$OVERLAY" <<'PY'
import re
import sys
path = sys.argv[1]
spec = open(path).read()
spec = spec.replace("mac:\n  category:", "mac:\n  identity: null\n  category:")
assert "  identity: null" in spec
open(path, "w").write(spec)
PY

export CSC_IDENTITY_AUTO_DISCOVERY=false
./node_modules/.bin/electron-builder --mac --config "$OVERLAY"
