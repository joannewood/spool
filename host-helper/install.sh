#!/bin/bash
# Installs the SPOOL host-helper as a launchd agent that starts at login
# and keeps running. Safe to re-run (bootout before bootstrap, and each
# run re-copies host_helper.py so code changes take effect).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DEST="$HOME/Library/LaunchAgents/com.spool.hosthelper.plist"
LOG_DIR="$HOME/Library/Logs/spool"

# Same three host paths docker-compose.yml reads from .env, so the
# delete-allowlist in host_helper.py (ALLOWED_DELETE_ROOTS) matches what's
# actually mounted into the containers rather than being hardcoded to one
# machine's paths. Read with sed rather than `source .env` — a plain
# `source` word-splits unquoted values, and a real path like
# "/Users/you/Documents/3D Printing" (unquoted, same as docker-compose's
# own tolerant .env parsing already expects) breaks that immediately.
ENV_FILE="$DIR/../.env"
if [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found — copy .env.example to .env and set your real paths first" >&2
  exit 1
fi
read_env_var() {
  sed -n "s/^$1=//p" "$ENV_FILE" | head -n1
}
DROPFOLDER_HOST_PATH="$(read_env_var DROPFOLDER_HOST_PATH)"
LIBRARY_HOST_PATH="$(read_env_var LIBRARY_HOST_PATH)"
DOWNLOADS_HOST_PATH="$(read_env_var DOWNLOADS_HOST_PATH)"
for var in DROPFOLDER_HOST_PATH LIBRARY_HOST_PATH DOWNLOADS_HOST_PATH; do
  if [ -z "${!var:-}" ]; then
    echo "error: $var is not set in $ENV_FILE" >&2
    exit 1
  fi
done

# macOS's TCC privacy protection blocks a launchd-spawned python3 (not
# inherited from an already-authorized Terminal session) from even opening
# a script under ~/Documents — confirmed while building this: launchd's
# python3 failed with "Operation not permitted" reading the script straight
# out of this repo. Installing a copy under ~/Library/Application Support
# (not one of the TCC-protected folders) avoids the problem entirely,
# rather than requiring a manual Privacy & Security grant.
INSTALL_DIR="$HOME/Library/Application Support/spool-host-helper"

mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents" "$INSTALL_DIR"
cp "$DIR/host_helper.py" "$INSTALL_DIR/host_helper.py"

sed -e "s#__SCRIPT_PATH__#$INSTALL_DIR/host_helper.py#g" \
    -e "s#__LOG_DIR__#$LOG_DIR#g" \
    -e "s#__DROPFOLDER_HOST_PATH__#$DROPFOLDER_HOST_PATH#g" \
    -e "s#__LIBRARY_HOST_PATH__#$LIBRARY_HOST_PATH#g" \
    -e "s#__DOWNLOADS_HOST_PATH__#$DOWNLOADS_HOST_PATH#g" \
    "$DIR/com.spool.hosthelper.plist" > "$PLIST_DEST"

launchctl bootout "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

echo "host-helper installed and running (launchd label: com.spool.hosthelper)"
echo "script: $INSTALL_DIR/host_helper.py"
echo "logs: $LOG_DIR/host-helper.log / host-helper.error.log"
echo "re-run this script after editing host_helper.py to pick up changes"
