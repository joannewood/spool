#!/bin/bash
# Builds dist/SPOOL-Installer.dmg — a signed & notarized Mac installer for
# SPOOL, wrapping this repo's setup.sh in a real .app via Platypus
# (build-time-only tool, see scripts/setup-platypus-tools.sh). Run this by
# hand before cutting a release; testers only ever see the finished .dmg.
#
# One-time prerequisites (not automated here — see README.md):
#   - .platypus-tools/{platypus,ScriptExec,MainMenu.nib} — run
#     scripts/setup-platypus-tools.sh once to fetch these.
#   - A "Developer ID Application" certificate in your login keychain
#     (Xcode -> Settings -> Accounts -> Manage Certificates -> "+").
#   - `xcrun notarytool store-credentials "spool-notary" --apple-id <id>
#     --team-id <team> --password <app-specific password>` run once (get
#     an app-specific password at appleid.apple.com).
#   - rustup (not Homebrew's `rust` formula — it can't add cross-compile
#     targets) with both `aarch64-apple-darwin` and `x86_64-apple-darwin`
#     targets installed (`rustup target add x86_64-apple-darwin`), plus
#     Node/npm, for building desktop/'s universal binary below.
#
# Override the identity/profile via SPOOL_SIGNING_IDENTITY /
# SPOOL_NOTARY_PROFILE env vars if you're building under a different
# Apple Developer account.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$DIR"

SIGNING_IDENTITY="${SPOOL_SIGNING_IDENTITY:-Developer ID Application: Joanne Wood (U8NA3U6GZF)}"
NOTARY_PROFILE="${SPOOL_NOTARY_PROFILE:-spool-notary}"
APP_NAME="SPOOL Installer"
BUNDLE_ID="com.spool.installer"
APP_VERSION="${SPOOL_INSTALLER_VERSION:-1.0}"

PLATYPUS_DIR="$DIR/.platypus-tools"
PLATYPUS="$PLATYPUS_DIR/platypus"
SCRIPTEXEC="$PLATYPUS_DIR/ScriptExec"
NIB="$PLATYPUS_DIR/MainMenu.nib"

step() { echo; echo "==> $1"; }

for f in "$PLATYPUS" "$SCRIPTEXEC" "$NIB"; do
  if [ ! -e "$f" ]; then
    echo "Missing $f" >&2
    echo "Run scripts/setup-platypus-tools.sh once first." >&2
    exit 1
  fi
done

BUILD="$DIR/dist/build"
STAGE="$BUILD/staging"
rm -rf "$BUILD"
mkdir -p "$STAGE/spool-src"

# ---- 1. Export exactly the tracked repo ------------------------------------

step "Exporting tracked repo files"
git archive --format=tar HEAD | (cd "$STAGE/spool-src" && tar xf -)

TRACKED_COUNT=$(git ls-files | wc -l | tr -d ' ')
EXPORTED_COUNT=$(cd "$STAGE/spool-src" && find . -type f | wc -l | tr -d ' ')
if [ "$TRACKED_COUNT" != "$EXPORTED_COUNT" ]; then
  echo "Exported file count ($EXPORTED_COUNT) doesn't match git ls-files ($TRACKED_COUNT)" >&2
  exit 1
fi
echo "Exported $EXPORTED_COUNT files."

# ---- 2. Build, sign, notarize the desktop wrapper app ----------------------

step "Building the SPOOL desktop app (universal binary)"
( cd "$STAGE/spool-src/desktop" && npx --yes @tauri-apps/cli@latest build --target universal-apple-darwin --bundles app )
DESKTOP_APP_PATH="$STAGE/spool-src/desktop/src-tauri/target/universal-apple-darwin/release/bundle/macos/SPOOL.app"

step "Code-signing the desktop app"
find "$DESKTOP_APP_PATH" -name ".DS_Store" -delete
xattr -cr "$DESKTOP_APP_PATH"
codesign --deep --force --options runtime --sign "$SIGNING_IDENTITY" "$DESKTOP_APP_PATH"
codesign -dv --verbose=4 "$DESKTOP_APP_PATH"

step "Notarizing the desktop app (this can take several minutes)"
DESKTOP_ZIP_PATH="$BUILD/SPOOL-desktop.zip"
rm -f "$DESKTOP_ZIP_PATH"
ditto -c -k --keepParent "$DESKTOP_APP_PATH" "$DESKTOP_ZIP_PATH"
xcrun notarytool submit "$DESKTOP_ZIP_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
xcrun stapler staple "$DESKTOP_APP_PATH"

# Rust's build output (desktop/src-tauri/target, several GB) has no reason
# to ride along inside the installer payload — only the finished, signed
# SPOOL.app does. Moving it out of the src-tauri/target tree it was built
# into and deleting the rest keeps the installer's own git-archive-derived
# file-count assertion below meaningless to it (that check already ran,
# see step 1) while keeping dist/build's own disk footprint sane.
mkdir -p "$STAGE/spool-src/desktop/dist-app"
mv "$DESKTOP_APP_PATH" "$STAGE/spool-src/desktop/dist-app/SPOOL.app"
rm -rf "$STAGE/spool-src/desktop/src-tauri/target"

# ---- 3. Build the app icon from the SVG favicon ----------------------------

step "Building app icon"
ICON_WORK="$BUILD/icon"
mkdir -p "$ICON_WORK/icon.iconset"
sips -s format png "$STAGE/spool-src/services/api/spool_api/static/favicon.svg" \
  --out "$ICON_WORK/base.png" -Z 1024 >/dev/null
for spec in "16:icon_16x16" "32:icon_16x16@2x" "32:icon_32x32" "64:icon_32x32@2x" \
            "128:icon_128x128" "256:icon_128x128@2x" "256:icon_256x256" \
            "512:icon_256x256@2x" "512:icon_512x512" "1024:icon_512x512@2x"; do
  size="${spec%%:*}"
  name="${spec##*:}"
  sips -z "$size" "$size" "$ICON_WORK/base.png" --out "$ICON_WORK/icon.iconset/$name.png" >/dev/null
done
iconutil -c icns "$ICON_WORK/icon.iconset" -o "$ICON_WORK/spool-icon.icns"

# ---- 4. The wrapper script Platypus actually runs --------------------------

step "Writing installer wrapper script"
cat >"$BUILD/installer-wrapper.sh" <<'WRAPPER'
#!/bin/bash
# Runs inside the signed/notarized .app — copies the bundled repo snapshot
# to a fixed, stable install location and hands off to its own setup.sh.
# Deriving RESOURCES_DIR from BASH_SOURCE (not $RESOURCEPATH, which this
# Platypus version doesn't actually set) works regardless of how the app
# is launched.
set -uo pipefail
RESOURCES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/Applications/SPOOL"

if [ -d "$DEST" ]; then
  echo "Updating existing SPOOL install at $DEST..."
else
  echo "Installing SPOOL to $DEST..."
fi
mkdir -p "$DEST"

# --exclude '.env' is belt-and-suspenders — the bundled snapshot never
# contains one (git archive excludes it), so a re-run never touches an
# existing install's configuration either way.
rsync -a --exclude '.env' "$RESOURCES_DIR/spool-src/" "$DEST/"

cd "$DEST"
exec ./setup.sh
WRAPPER
chmod +x "$BUILD/installer-wrapper.sh"

# ---- 5. Build the .app via Platypus ----------------------------------------

step "Building $APP_NAME.app"
APP_PATH="$STAGE/$APP_NAME.app"
rm -rf "$APP_PATH"
"$PLATYPUS" \
  -a "$APP_NAME" \
  -o "Text Window" \
  -I "$BUNDLE_ID" \
  -u "SPOOL" \
  -V "$APP_VERSION" \
  -i "$ICON_WORK/spool-icon.icns" \
  -f "$STAGE/spool-src" \
  -e "$SCRIPTEXEC" \
  -E "$NIB" \
  -y \
  "$BUILD/installer-wrapper.sh" \
  "$APP_PATH"

# ---- 6. Sign ----------------------------------------------------------------

step "Code-signing $APP_NAME.app"
find "$APP_PATH" -name ".DS_Store" -delete
xattr -cr "$APP_PATH"
codesign --deep --force --options runtime --sign "$SIGNING_IDENTITY" "$APP_PATH"
codesign -dv --verbose=4 "$APP_PATH"

# ---- 7. Notarize + staple the .app -----------------------------------------

step "Notarizing $APP_NAME.app (this can take several minutes)"
ZIP_PATH="$BUILD/$APP_NAME.zip"
rm -f "$ZIP_PATH"
ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"
xcrun notarytool submit "$ZIP_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
xcrun stapler staple "$APP_PATH"

# ---- 8. Build the .dmg ------------------------------------------------------

step "Building .dmg"
mkdir -p "$DIR/dist"
DMG_PATH="$DIR/dist/SPOOL-Installer.dmg"
rm -f "$DMG_PATH"
hdiutil create -volname "$APP_NAME" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"

# ---- 9. Sign + notarize + staple the .dmg itself ---------------------------

step "Code-signing .dmg"
codesign --force --sign "$SIGNING_IDENTITY" "$DMG_PATH"

step "Notarizing .dmg (this can take several minutes)"
xcrun notarytool submit "$DMG_PATH" --keychain-profile "$NOTARY_PROFILE" --wait
xcrun stapler staple "$DMG_PATH"

# ---- 10. Verify --------------------------------------------------------------

step "Verifying Gatekeeper acceptance"
spctl -a -vvv --type execute "$APP_PATH"
spctl -a -vvv --type open --context context:primary-signature "$DMG_PATH"

echo
echo "Done: $DMG_PATH"
