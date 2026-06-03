#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="ClippingOpsCockpit"
DISPLAY_NAME="Clipping Ops Cockpit"
BUNDLE_ID="com.bilbop.ClippingOpsCockpit"
MIN_SYSTEM_VERSION="14.0"
RELEASE_DIR="$ROOT_DIR/dist/release"
APP_BUNDLE="$RELEASE_DIR/$DISPLAY_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"
ENTITLEMENTS="$ROOT_DIR/Sources/ClippingOpsCockpit/Support/ClippingOpsCockpit.entitlements"
ZIP_PATH="$RELEASE_DIR/ClippingOpsCockpit-release.zip"
MODE="adhoc"

for arg in "$@"; do
  case "$arg" in
    --adhoc|--dev|--dev-adhoc)
      MODE="adhoc"
      ;;
    --customer-release|--customer)
      MODE="customer"
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      echo "Usage: $0 [--adhoc|--customer-release]" >&2
      exit 64
      ;;
  esac
done

cd "$ROOT_DIR"
mkdir -p "$RELEASE_DIR"

swift build -c release
BUILD_BINARY="$(swift build -c release --show-bin-path)/$APP_NAME"

rm -rf "$APP_BUNDLE" "$ZIP_PATH"
mkdir -p "$APP_MACOS"
cp "$BUILD_BINARY" "$APP_BINARY"
chmod +x "$APP_BINARY"

cat >"$INFO_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_ID</string>
  <key>CFBundleName</key>
  <string>$DISPLAY_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>$DISPLAY_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>0.1.0</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST

SIGN_IDENTITY="${CLIPPING_OPS_SIGN_IDENTITY:-}"
if [[ -z "$SIGN_IDENTITY" ]]; then
  SIGN_IDENTITY="$(security find-identity -v -p codesigning 2>/dev/null | awk -F'\"' '/Developer ID Application/ {print $2; exit}')"
fi
if [[ "$MODE" == "customer" && -z "$SIGN_IDENTITY" ]]; then
  echo "Customer release requires CLIPPING_OPS_SIGN_IDENTITY or an installed Developer ID Application identity." >&2
  "$ROOT_DIR/script/verify_release.sh" --mode customer "$APP_BUNDLE" "$ZIP_PATH" || true
  exit 65
fi
if [[ -z "$SIGN_IDENTITY" ]]; then
  SIGN_IDENTITY="-"
fi

if [[ "$SIGN_IDENTITY" == "-" ]]; then
  codesign --force --deep --options runtime --entitlements "$ENTITLEMENTS" --sign - "$APP_BUNDLE"
else
  codesign --force --deep --timestamp --options runtime --entitlements "$ENTITLEMENTS" --sign "$SIGN_IDENTITY" "$APP_BUNDLE"
fi

ditto -c -k --norsrc --keepParent "$APP_BUNDLE" "$ZIP_PATH"
"$ROOT_DIR/script/verify_release.sh" --mode "$MODE" "$APP_BUNDLE" "$ZIP_PATH"
