#!/bin/bash
# Stops and removes the SPOOL host-helper launchd agent.
set -euo pipefail

PLIST_DEST="$HOME/Library/LaunchAgents/com.spool.hosthelper.plist"
INSTALL_DIR="$HOME/Library/Application Support/spool-host-helper"

launchctl bootout "gui/$(id -u)" "$PLIST_DEST" 2>/dev/null || true
rm -f "$PLIST_DEST"
rm -rf "$INSTALL_DIR"

echo "host-helper stopped and uninstalled"
