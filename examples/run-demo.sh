#!/usr/bin/env bash
# run-demo.sh — run a full file-ferry pipeline on the test dataset
#
# Requirements: ffmpeg on PATH, file-ferry installed (pip install -e .)
#
# This script:
#   1. Cleans up any previous run output
#   2. Probes the test media
#   3. Organizes into codec/resolution layout
#   4. Generates ProRes 422 Proxy files
#   5. Creates a DaVinci Resolve project manifest
#   6. Verifies the backup
#   7. Shows the audit log

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_DATASET="$SCRIPT_DIR/test-dataset"
RAW="$TEST_DATASET/raw"
OUT="$TEST_DATASET/output"

# Allow running from anywhere; cd to project root so ferry works
cd "$PROJECT_ROOT"

echo "========================================"
echo " file-ferry demo pipeline"
echo "========================================"
echo ""

# Fresh output dir
rm -rf "$OUT"

echo "--- Step 1: probe ---"
ferry probe "$RAW"
echo ""

echo "--- Step 2: organize ---"
ferry organize "$RAW" --root "$OUT/organized"
echo ""

echo "--- Step 3: proxy (ProRes 422 Proxy, 1080p) ---"
ferry proxy "$OUT/organized" --out "$OUT/proxies"
echo ""

echo "--- Step 4: resolve project ---"
ferry resolve create "$OUT/organized" \
    --project "Demo-Project" \
    --resolution 1080 \
    --fps 24 \
    --proxy-dir "$OUT/proxies" \
    --output "$OUT/Demo-Project.drp"
echo ""

echo "--- Step 5: verify ---"
ferry verify "$OUT/organized"
echo ""

echo "--- Audit log ---"
ferry log
echo ""

echo "========================================"
echo " Done. Output layout:"
echo "========================================"
find "$OUT" | sort | sed "s|$OUT|  |"
