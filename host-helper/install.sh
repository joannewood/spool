#!/bin/bash
# Installs the SPOOL host-helper as a launchd agent that starts at login
# and keeps running. Safe to re-run (bootout before bootstrap, and each
# run re-copies host_helper.py so code changes take effect).
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_DEST="$HOME/Library/LaunchAgents/com.spool.hosthelper.plist"
LOG_DIR="$HOME/Library/Logs/spool"

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
    "$DIR/com.spool.hosthelper.plist" > "$PLIST_DEST"

launchctl bootout "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DEST"

echo "host-helper installed and running (launchd label: com.spool.hosthelper)"
echo "script: $INSTALL_DIR/host_helper.py"
echo "logs: $LOG_DIR/host-helper.log / host-helper.error.log"
echo "re-run this script after editing host_helper.py to pick up changes"
