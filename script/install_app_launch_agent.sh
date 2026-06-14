#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bilbop.ClippingOpsCockpit.web"
LEGACY_LABEL="com.bilbop.ClippingOpsCockpit.app"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LEGACY_PLIST="$HOME/Library/LaunchAgents/$LEGACY_LABEL.plist"
WEB_URL="${CLIPPING_OPS_WEB_URL:-http://127.0.0.1:8765/app}"
APP_SUPPORT="$HOME/Library/Application Support/ClippingOpsCockpit"
LOG_DIR="$APP_SUPPORT/logs"
BIN_DIR="$APP_SUPPORT/bin"
RUNNER="$BIN_DIR/app_launch_agent_runner.sh"

mkdir -p "$LOG_DIR" "$BIN_DIR" "$HOME/Library/LaunchAgents"
"$ROOT_DIR/script/build_web.sh" >/dev/null

cat >"$RUNNER" <<RUNNER
#!/usr/bin/env bash
set -u
ROOT_DIR="$ROOT_DIR"
WEB_URL="$WEB_URL"
LOG_DIR="$LOG_DIR"
mkdir -p "\$LOG_DIR"
{
  echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ) starting $LABEL"
  echo "cwd=\$ROOT_DIR"
  echo "url=\$WEB_URL"
  cd "\$ROOT_DIR" || exit 78
  export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  backend_ready=0
  for attempt in {1..60}; do
    if /usr/bin/curl -fsS --max-time 2 "http://127.0.0.1:8765/api/health" >/dev/null 2>&1; then
      backend_ready=1
      break
    fi
    if [[ "\$attempt" == "1" || "\$attempt" == "10" ]]; then
      launchctl kickstart -k "gui/\$(id -u)/com.bilbop.ClippingOpsCockpit.backend" >/dev/null 2>&1 || true
    fi
    sleep 1
  done
  if [[ "\$backend_ready" != "1" ]]; then
    echo "backend API did not become ready at login"
    exit 75
  fi
  if [[ ! -f "\$ROOT_DIR/web/dist/index.html" ]]; then
    echo "web build missing; run script/install_app_launch_agent.sh from the workspace to rebuild it"
    exit 78
  fi
  /usr/bin/open "\$WEB_URL"
} >>"\$LOG_DIR/app.launchd.wrapper.log" 2>&1
RUNNER
chmod +x "$RUNNER"

cat >"$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$RUNNER</string>
  </array>
  <key>WorkingDirectory</key>
  <string>$APP_SUPPORT</string>
  <key>RunAtLoad</key>
  <true/>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/app.launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/app.launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$LEGACY_PLIST" >/dev/null 2>&1 || true
rm -f "$LEGACY_PLIST"
launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

app_ready=0
for _ in {1..40}; do
  if /usr/bin/curl -fsS --max-time 2 "$WEB_URL" >/dev/null 2>&1; then
    app_ready=1
    break
  fi
  sleep 0.25
done

if [[ "$app_ready" == "1" ]]; then
  echo "Web cockpit LaunchAgent installed and reachable: $WEB_URL"
  exit 0
fi

echo "Web cockpit LaunchAgent failed readiness. See $LOG_DIR/app.launchd.wrapper.log" >&2
tail -n 80 "$LOG_DIR/app.launchd.wrapper.log" >&2 || true
exit 1
