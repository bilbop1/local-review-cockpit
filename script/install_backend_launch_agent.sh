#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.bilbop.ClippingOpsCockpit.backend"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python3"
APP_SUPPORT="$HOME/Library/Application Support/ClippingOpsCockpit"
LOG_DIR="$APP_SUPPORT/logs"
BIN_DIR="$APP_SUPPORT/bin"
RUNNER="$BIN_DIR/backend_launch_agent_runner.sh"

mkdir -p "$LOG_DIR" "$BIN_DIR" "$HOME/Library/LaunchAgents"
uv sync --project "$ROOT_DIR/backend" >/dev/null

cat >"$RUNNER" <<RUNNER
#!/usr/bin/env bash
set -u
ROOT_DIR="$ROOT_DIR"
LOG_DIR="$LOG_DIR"
PYTHON_BIN="$PYTHON_BIN"
LABEL="$LABEL"
mkdir -p "\$LOG_DIR"
{
  echo "\$(date -u +%Y-%m-%dT%H:%M:%SZ) starting \$LABEL"
  echo "cwd=\$ROOT_DIR"
  echo "python=\$PYTHON_BIN"
  cd "\$ROOT_DIR" || exit 78
  export PYTHONPATH="\$ROOT_DIR/backend"
  export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  "\$PYTHON_BIN" -V
  "\$PYTHON_BIN" -c 'import clipping_ops_backend.server as s; print("api_version=" + s.API_VERSION)'
  if command -v lsof >/dev/null 2>&1; then
    listeners="\$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "\$listeners" ]]; then
      echo "port_8765_listeners_before_start=\$listeners"
    fi
  fi
  exec "\$PYTHON_BIN" -u -m clipping_ops_backend.server --host 127.0.0.1 --port 8765
} >>"\$LOG_DIR/backend.launchd.wrapper.log" 2>&1
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
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>
    <string>$ROOT_DIR/backend</string>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$HOME/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>
  <key>StandardOutPath</key>
  <string>$LOG_DIR/backend.launchd.log</string>
  <key>StandardErrorPath</key>
  <string>$LOG_DIR/backend.launchd.err.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
if command -v lsof >/dev/null 2>&1; then
  for _ in {1..20}; do
    pids="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
    [[ -z "$pids" ]] && break
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
      if [[ "$command_line" == *"clipping_ops_backend.server"* || "$command_line" == *"$ROOT_DIR"* ]]; then
        kill "$pid" >/dev/null 2>&1 || true
      else
        echo "Refusing to kill non-owned listener on port 8765: pid=$pid command=$command_line" >&2
        break 2
      fi
    done <<<"$pids"
    sleep 0.2
  done
fi
rm -f "$ROOT_DIR/.run/backend.pid"
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/$LABEL"
launchctl kickstart -k "gui/$(id -u)/$LABEL"

health_ready=0
for _ in {1..40}; do
  if python3 - <<'PY' >/dev/null 2>&1
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8765/api/version", timeout=2.0) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
  then
    health_ready=1
    break
  fi
  sleep 0.25
done

launchagent_ready=0
if [[ "$health_ready" == "1" ]]; then
  for _ in {1..40}; do
    if python3 "$ROOT_DIR/script/check_backend_launch_agent.py" >/dev/null 2>&1; then
      launchagent_ready=1
      break
    fi
    sleep 0.25
  done
fi

if [[ "$launchagent_ready" == "1" ]]; then
  echo "Backend LaunchAgent installed and healthy: $LABEL"
  exit 0
fi

echo "Backend LaunchAgent failed readiness. See artifacts/backend/backend-launchagent.json and $LOG_DIR/backend.launchd.wrapper.log" >&2
tail -n 80 "$LOG_DIR/backend.launchd.wrapper.log" >&2 || true
exit 1
