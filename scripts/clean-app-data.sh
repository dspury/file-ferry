#!/usr/bin/env bash
#
# Reset app data to a pristine first-run state (plan §10 Pkg9 step 3:
# clean-app-data test procedure).
#
# Deletes the user's media-mate app data so a packaged build can be tested
# for true first-run behavior (fresh migrations, no stale state). By
# default this is a DRY RUN that only prints what it would delete; pass
# --apply to actually remove it.
#
# Usage:  scripts/clean-app-data.sh [--apply]
set -euo pipefail

TARGETS=(
  "$HOME/.media-mate"                    # legacy config + audit db
  "$HOME/Library/Application Support/media-mate"  # Electron userData (receipts/logs/db)
)

APPLY=0
if [[ "${1:-}" == "--apply" ]]; then
  APPLY=1
fi

echo "==> clean-app-data (dry run)"
for t in "${TARGETS[@]}"; do
  if [[ -e "$t" ]]; then
    echo "  would remove: $t"
  else
    echo "  absent: $t"
  fi
done

if [[ "$APPLY" -ne 0 ]]; then
  for t in "${TARGETS[@]}"; do
    [[ -e "$t" ]] && rm -rf "$t" && echo "  removed: $t"
  done
  echo "==> app data cleared. Next launch is a pristine first run."
else
  echo "==> dry run only. Re-run with --apply to delete."
fi
