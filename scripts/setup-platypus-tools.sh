#!/bin/bash
# One-time (per build machine) setup for scripts/build-mac-installer.sh.
#
# Platypus (BSD-licensed, https://github.com/sveinbjornt/Platypus) wraps a
# shell script in a real, signable/notarizable .app bundle — it's a
# build-time-only tool; testers downloading the finished SPOOL installer
# never see or need it. Its normal install path
# (Platypus.app/Contents/Resources/InstallCommandLineTool.sh) copies
# platypus_clt/ScriptExec/MainMenu.nib to /usr/local/share/platypus, which
# needs sudo. `platypus`'s CLI also accepts custom -e/-E paths for
# ScriptExec/MainMenu.nib, so this script instead extracts the exact same
# three files straight out of the downloaded .app bundle into
# .platypus-tools/ (gitignored — local build tooling, not committed) —
# confirmed byte-identical to what the sudo installer would have placed,
# just without needing root or touching anything outside this repo.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$DIR/.platypus-tools"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Looking up the latest Platypus release..."
RELEASE_URL=$(curl -sf https://api.github.com/repos/sveinbjornt/Platypus/releases/latest \
  | grep '"browser_download_url"' \
  | grep -v 'src\.zip' \
  | sed -E 's/.*"(https[^"]+)".*/\1/')
if [ -z "$RELEASE_URL" ]; then
  echo "Couldn't find the latest Platypus release asset — check" >&2
  echo "https://github.com/sveinbjornt/Platypus/releases by hand and adjust this script." >&2
  exit 1
fi

echo "Downloading $RELEASE_URL"
curl -sfL "$RELEASE_URL" -o "$TMP/platypus.zip"
unzip -q "$TMP/platypus.zip" -d "$TMP/extracted"

APP=$(find "$TMP/extracted" -iname "Platypus.app" -maxdepth 3 | head -1)
if [ -z "$APP" ]; then
  echo "Couldn't find Platypus.app inside the downloaded release zip." >&2
  exit 1
fi
RESOURCES="$APP/Contents/Resources"

mkdir -p "$OUT"
base64 -d -i "$RESOURCES/ScriptExec.b64" >"$OUT/ScriptExec"
chmod +x "$OUT/ScriptExec"
rm -rf "$OUT/MainMenu.nib"
cp -r "$RESOURCES/MainMenu.nib" "$OUT/MainMenu.nib"
cp "$RESOURCES/platypus_clt" "$OUT/platypus"
chmod +x "$OUT/platypus"

echo
echo "Done — $OUT now has platypus, ScriptExec, MainMenu.nib."
"$OUT/platypus" -v
