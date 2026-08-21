#!/usr/bin/env bash
#
# Validate a packaged build (plan §10 Pkg9 step 4, §11.3 release gates).
#
# Checks that the packaged .app:
#   - contains the frozen sidecar at Contents/Resources/sidecar/{arch}/
#   - the frozen sidecar launches and serves the JSON-RPC protocol
#   - app resources are present outside app.asar where required
#
# Usage:  scripts/verify-packaged.sh /path/to/media-mate.app
set -euo pipefail

APP="${1:-}"
if [[ -z "$APP" || ! -d "$APP" ]]; then
  echo "usage: $0 /path/to/media-mate.app" >&2
  exit 2
fi

FAIL=0
echo "==> verifying packaged app: $APP"

# 1. Sidecar executable present (the runtime resolves this path).
SIDECAR_DIR="$APP/Contents/Resources/sidecar"
echo "--- sidecar resources at $SIDECAR_DIR ---"
if [[ -d "$SIDECAR_DIR" ]]; then
  find "$SIDECAR_DIR" -name 'media-mate-service*' -type f
else
  echo "FAIL: no sidecar resources dir" >&2
  FAIL=1
fi

# 2. The frozen sidecar launches and serves the protocol.
echo "--- frozen sidecar smoke test ---"
SIDECAR="$(find "$SIDECAR_DIR" -name 'media-mate-service' -type f | head -1 || true)"
if [[ -n "$SIDECAR" && -x "$SIDECAR" ]]; then
  OUT="$(echo '{"jsonrpc":"2.0","v":1,"kind":"request","id":"v","method":"app.getCapabilities","params":{}}' \
    | "$SIDECAR" --once --db /tmp/mm-verify.db 2>/dev/null || true)"
  if [[ "$OUT" == *'"method":"app.getCapabilities"'* || "$OUT" == *'"methods"'* ]]; then
    echo "OK: frozen sidecar served app.getCapabilities"
  else
    echo "FAIL: frozen sidecar did not serve the protocol (got: ${OUT:0:120})" >&2
    FAIL=1
  fi
  rm -f /tmp/mm-verify.db
else
  echo "FAIL: no executable sidecar found" >&2
  FAIL=1
fi

# 3. Renderer build present (packaged index.html is under app.asar; the
#    sidecar is the resource that must live OUTSIDE asar — verified above).
echo "--- asar present (main+preload+renderer inside) ---"
if [[ -f "$APP/Contents/Resources/app.asar" ]]; then
  echo "OK: app.asar present"
else
  echo "FAIL: app.asar missing" >&2
  FAIL=1
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "==> VERIFY FAILED" >&2
  exit 1
fi
echo "==> VERIFY OK"
