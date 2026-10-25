#!/bin/bash
# ============================================================================
# with-secrets.sh - Keychain-based secret injection for nba-props
# ============================================================================
# Reads only the secrets nba-props needs from the macOS Keychain
# (service: "autopilot") and exports them, then exec's the given command.
#
# Used by Earnest on the Mac Mini to run the daily capture without exposing
# the full 1Password stack. Lifted from shadow-leaderboard/scripts/with-secrets.sh.
#
# Master secret management lives in ~/autopilot/scripts/keychain-sync.sh.
# This wrapper only READS - it does not add/update secrets.
#
# Usage (from Earnest's scheduler, launchd, cron, or interactively on the Mini):
#   cd /Users/<user>/nba-props && scripts/with-secrets.sh \
#       uv run python -m nbaprops.capture
#
# On the laptop (dev), use 1Password instead:
#   op run --env-file=.env.template -- uv run python -m nbaprops.capture
# ============================================================================

set -euo pipefail

KEYCHAIN_SERVICE="autopilot"

# Only the secrets nba-props itself reads.
SECRETS=(
  ODDS_API_KEY
)

FAILED=()
for SECRET in "${SECRETS[@]}"; do
  VALUE=$(security find-generic-password -s "$KEYCHAIN_SERVICE" -a "$SECRET" -w 2>/dev/null) || true
  if [ -z "$VALUE" ]; then
    FAILED+=("$SECRET")
  else
    export "$SECRET"="$VALUE"
  fi
done

if [ ${#FAILED[@]} -gt 0 ]; then
  echo "[with-secrets] WARNING: Missing Keychain secrets: ${FAILED[*]}" >&2
  echo "[with-secrets] Set them with: ~/autopilot/scripts/keychain-sync.sh <KEY> <VALUE>" >&2
fi

exec "$@"
