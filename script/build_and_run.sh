#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
APP_NAME="ClippingOpsCockpit"
DISPLAY_NAME="Clipping Ops Cockpit"
BUNDLE_ID="com.bilbop.ClippingOpsCockpit"
MIN_SYSTEM_VERSION="14.0"
WEB_URL="${CLIPPING_OPS_WEB_URL:-http://127.0.0.1:8765/app}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
APP_BUNDLE="$DIST_DIR/$DISPLAY_NAME.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_BINARY="$APP_MACOS/$APP_NAME"
INFO_PLIST="$APP_CONTENTS/Info.plist"

cd "$ROOT_DIR"

stage_app() {
  swift build
  BUILD_BINARY="$(swift build --show-bin-path)/$APP_NAME"

  rm -rf "$APP_BUNDLE"
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
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>$MIN_SYSTEM_VERSION</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSPrincipalClass</key>
  <string>NSApplication</string>
</dict>
</plist>
PLIST
}

case "$MODE" in
  --stage-only|stage|stage-only)
    stage_app
    exit 0
    ;;
  --legacy-swift|legacy-swift)
    "$ROOT_DIR/script/start_backend.sh" start
    stage_app
    /usr/bin/open -n "$APP_BUNDLE"
    exit 0
    ;;
esac

"$ROOT_DIR/script/start_backend.sh" start

build_web() {
  "$ROOT_DIR/script/build_web.sh"
}

case "$MODE" in
  run)
    build_web
    echo "Clipping Ops web cockpit is ready:"
    echo "$WEB_URL"
    ;;
  --open|open)
    build_web
    /usr/bin/open "$WEB_URL"
    ;;
  --dev|dev)
    "$ROOT_DIR/script/start_backend.sh" start
    npm --prefix "$ROOT_DIR/web" install
    echo "Vite dev server: http://127.0.0.1:5173/app"
    echo "Backend API: $WEB_URL"
    npm --prefix "$ROOT_DIR/web" run dev
    ;;
  --logs|logs)
    "$ROOT_DIR/script/start_backend.sh" start
    tail -f "$ROOT_DIR/.run/backend.log"
    ;;
  --verify|verify)
    build_web
    python3 - <<'PY'
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=10) as response:
    assert response.status == 200
with urllib.request.urlopen("http://127.0.0.1:8765/app", timeout=10) as response:
    body = response.read(4096).decode("utf-8", errors="replace")
    assert response.status == 200 and "<div id=\"root\">" in body
PY
    echo "Verified backend and web cockpit at $WEB_URL"
    ;;
  *)
    echo "usage: $0 [run|--open|--dev|--logs|--verify|--legacy-swift|--stage-only]" >&2
    exit 2
    ;;
esac
