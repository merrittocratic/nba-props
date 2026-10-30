#!/bin/bash
# ============================================================================
# pull-from-mini.sh - copy the Mac Mini's captured data to the laptop
# ============================================================================
# One way only, Mini -> laptop, into data/mini/ (gitignored). It mirrors the
# Mini's data/ folder: raw/, manifest.csv, logs/. Never deletes anything on
# either side and never writes to the Mini. The laptop's own data/ (dev runs,
# probes) is left untouched. Only new or changed files are copied, so rerunning
# is cheap; run it whenever you want fresh data.
#
# The manifest's `path` column holds the Mini's absolute paths. On the laptop,
# map them by keeping everything from "raw/" on, under data/mini/.
#
# Uses plain SSH as merrittocracyclaw, the account Earnest runs under: you'll
# be asked for that account's Mini password unless you've set up SSH keys.
#
# Usage, on the laptop from anywhere:
#   scripts/pull-from-mini.sh            # copy
#   scripts/pull-from-mini.sh --dry-run  # list what would be copied
#
# Override with env vars if needed:
#   NBA_PROPS_MINI       user@host of the Mini
#                        (default: merrittocracyclaw@Stephens-mac-mini.local)
#   NBA_PROPS_MINI_DIR   repo path on the Mini,
#                        relative to that user's home (default: nba-props)
# ============================================================================

set -euo pipefail

HOST="${NBA_PROPS_MINI:-merrittocracyclaw@Stephens-mac-mini.local}"
REMOTE_DIR="${NBA_PROPS_MINI_DIR:-nba-props}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEST="$REPO/data/mini/"

FLAGS="-az --partial --stats --exclude=.DS_Store"
if [ "${1:-}" = "--dry-run" ]; then
  FLAGS="$FLAGS -n -v"
fi

mkdir -p "$DEST"
echo "[pull] $HOST:$REMOTE_DIR/data/ -> $DEST"
# shellcheck disable=SC2086  # FLAGS is a list of rsync options
if ! rsync $FLAGS "$HOST:$REMOTE_DIR/data/" "$DEST"; then
  echo "[pull] rsync failed: check NBA_PROPS_MINI (user@host) and NBA_PROPS_MINI_DIR" >&2
  exit 1
fi
if [ -f "$DEST/manifest.csv" ]; then
  echo "[pull] done; manifest rows: $(($(wc -l < "$DEST/manifest.csv") - 1))"
fi
