#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

APP_NAME="Camera Viewer"
DIST_DIR="dist"
APP_PATH="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/$APP_NAME.dmg"
STAGING="/tmp/camera-viewer-dmg-staging"

DEVELOPER_ID="Developer ID Application: Enzo Pellegrino (T4T6H838Y2)"
NOTARY_PROFILE="camera-viewer"
ENTITLEMENTS="entitlements.plist"
BUNDLE_ID="com.enzo.camera-viewer"

# ── 1. Build ───────────────────────────────────────────────────────────────────
echo "==> Building $APP_NAME.app ..."
.venv/bin/pyinstaller camera_viewer.spec --noconfirm

# ── 2. Remove quarantine ───────────────────────────────────────────────────────
echo "==> Removing quarantine attribute ..."
xattr -cr "$APP_PATH"

# ── 3. Deep sign with Developer ID + Hardened Runtime ─────────────────────────
echo "==> Signing with Developer ID ..."
# Sign all binaries inside the bundle first, then the bundle itself
find "$APP_PATH/Contents/MacOS" -type f | while read bin; do
    codesign --force --options runtime \
        --entitlements "$ENTITLEMENTS" \
        --sign "$DEVELOPER_ID" \
        "$bin" 2>/dev/null || true
done
find "$APP_PATH/Contents/Frameworks" -name "*.dylib" -o -name "*.so" 2>/dev/null | while read lib; do
    codesign --force --options runtime \
        --entitlements "$ENTITLEMENTS" \
        --sign "$DEVELOPER_ID" \
        "$lib" 2>/dev/null || true
done
# Sign the bundle itself
codesign --force --deep --options runtime \
    --entitlements "$ENTITLEMENTS" \
    --sign "$DEVELOPER_ID" \
    --identifier "$BUNDLE_ID" \
    "$APP_PATH"

codesign --verify --deep --strict "$APP_PATH" && echo "   Signature OK"

# ── 4. Notarize ────────────────────────────────────────────────────────────────
echo "==> Zipping for notarization ..."
ditto -c -k --keepParent "$APP_PATH" /tmp/camera-viewer-notarize.zip

echo "==> Submitting to Apple notarization (this takes 1–5 min) ..."
xcrun notarytool submit /tmp/camera-viewer-notarize.zip \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait \
    --timeout 600
rm /tmp/camera-viewer-notarize.zip

# ── 5. Staple ──────────────────────────────────────────────────────────────────
echo "==> Stapling notarization ticket ..."
xcrun stapler staple "$APP_PATH"
xcrun stapler validate "$APP_PATH" && echo "   Staple OK"

# ── 6. Create DMG ─────────────────────────────────────────────────────────────
echo "==> Creating DMG ..."
rm -rf "$STAGING"
mkdir -p "$STAGING"
cp -R "$APP_PATH" "$STAGING/"
ln -s /Applications "$STAGING/Applications"

hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$STAGING" \
    -ov \
    -format UDZO \
    "$DMG_PATH"

rm -rf "$STAGING"

# ── 7. Sign + notarize the DMG ────────────────────────────────────────────────
echo "==> Signing DMG ..."
codesign --force --sign "$DEVELOPER_ID" "$DMG_PATH"

echo "==> Notarizing DMG ..."
xcrun notarytool submit "$DMG_PATH" \
    --keychain-profile "$NOTARY_PROFILE" \
    --wait \
    --timeout 600

echo "==> Stapling DMG ..."
xcrun stapler staple "$DMG_PATH"

# ── 8. Sync config to Application Support (if not already configured) ─────────
APP_SUPPORT="$HOME/Library/Application Support/$APP_NAME"
BUNDLE_CONFIG="$APP_SUPPORT/config.json"
DEV_CONFIG="config.json"

mkdir -p "$APP_SUPPORT"
if [ -f "$DEV_CONFIG" ]; then
    if [ ! -f "$BUNDLE_CONFIG" ] || \
       python3 -c "import json,sys; d=json.load(open('$BUNDLE_CONFIG')); sys.exit(0 if d.get('cameras') else 1)" 2>/dev/null; then
        : # already has cameras, skip
    else
        echo "==> Copying dev config to Application Support ..."
        cp "$DEV_CONFIG" "$BUNDLE_CONFIG"
    fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "Done:"
echo "  App : $APP_PATH ($(du -sh "$APP_PATH" | cut -f1))"
echo "  DMG : $DMG_PATH ($(du -sh "$DMG_PATH" | cut -f1))"
echo ""
echo "Both are signed, notarized, and stapled — ready for distribution."
