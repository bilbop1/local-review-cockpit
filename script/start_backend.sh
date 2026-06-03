#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$ROOT_DIR/.run"
PID_FILE="$RUN_DIR/backend.pid"
LOG_FILE="$RUN_DIR/backend.log"
HOST="${CLIPPING_OPS_HOST:-127.0.0.1}"
PORT="${CLIPPING_OPS_PORT:-8765}"
LAUNCH_LABEL="com.bilbop.ClippingOpsCockpit.backend"
EXPECTED_API_VERSION="$(python3 - "$ROOT_DIR/backend/clipping_ops_backend/server.py" <<'PY'
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^API_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not match:
    raise SystemExit("API_VERSION not found")
print(match.group(1))
PY
)"
HEALTH_TIMEOUT_SECONDS="${CLIPPING_OPS_HEALTH_TIMEOUT_SECONDS:-3.0}"
USE_LAUNCHD=1
if [[ "${CLIPPING_OPS_NO_KEY:-0}" == "1" ]]; then
  USE_LAUNCHD=0
fi

mkdir -p "$RUN_DIR"

is_alive() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" >/dev/null 2>&1
}

kill_port_listeners() {
  if command -v lsof >/dev/null 2>&1; then
    while IFS= read -r pid; do
      [[ -z "$pid" ]] && continue
      command_line="$(ps -p "$pid" -o command= 2>/dev/null || true)"
      if [[ "$command_line" == *"clipping_ops_backend.server"* || "$command_line" == *"$ROOT_DIR"* ]]; then
        kill "$pid" >/dev/null 2>&1 || true
      else
        echo "Refusing to kill non-owned listener on port $PORT: pid=$pid command=$command_line" >&2
        return 1
      fi
    done < <(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)
  fi
}

api_is_current() {
  python3 - "$HOST" "$PORT" "$EXPECTED_API_VERSION" "$HEALTH_TIMEOUT_SECONDS" <<'PY' >/dev/null 2>&1
import json, sys, urllib.request
host, port, expected, timeout_seconds = sys.argv[1], sys.argv[2], sys.argv[3], float(sys.argv[4])
with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=timeout_seconds) as response:
    payload = json.load(response)
raise SystemExit(0 if response.status == 200 and payload.get("api_version") == expected else 1)
PY
}

case "${1:-start}" in
  start)
    if [[ "$USE_LAUNCHD" == "1" ]] && launchctl print "gui/$(id -u)/$LAUNCH_LABEL" >/dev/null 2>&1; then
      if api_is_current; then
        exit 0
      fi
      launchctl kickstart -k "gui/$(id -u)/$LAUNCH_LABEL" >/dev/null 2>&1 || true
      for _ in {1..20}; do
        if api_is_current; then
          exit 0
        fi
        sleep 0.25
      done
    fi
    if is_alive && api_is_current; then
      exit 0
    elif is_alive; then
      kill "$(cat "$PID_FILE")" >/dev/null 2>&1 || true
      rm -f "$PID_FILE"
    fi
    if ! api_is_current; then
      kill_port_listeners
    fi
    uv sync --project "$ROOT_DIR/backend" >/dev/null
    PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python3"
    nohup env PYTHONPATH="$ROOT_DIR/backend" \
      "$PYTHON_BIN" -m clipping_ops_backend.server --host "$HOST" --port "$PORT" \
      >"$LOG_FILE" 2>&1 </dev/null &
    echo $! >"$PID_FILE"
    for _ in {1..40}; do
      if api_is_current; then
        exit 0
      fi
      sleep 0.25
    done
    echo "Backend did not become healthy. See $LOG_FILE" >&2
    exit 1
    ;;
  stop)
    if [[ "$USE_LAUNCHD" == "1" ]] && launchctl print "gui/$(id -u)/$LAUNCH_LABEL" >/dev/null 2>&1; then
      launchctl kickstart -k "gui/$(id -u)/$LAUNCH_LABEL" >/dev/null 2>&1 || true
      echo "managed by launchd: $LAUNCH_LABEL"
      exit 0
    fi
    if is_alive; then
      kill "$(cat "$PID_FILE")" >/dev/null 2>&1 || true
    fi
    rm -f "$PID_FILE"
    ;;
  status)
    if [[ "$USE_LAUNCHD" == "1" ]] && launchctl print "gui/$(id -u)/$LAUNCH_LABEL" >/dev/null 2>&1; then
      echo "launchd $LAUNCH_LABEL"
    elif is_alive; then
      echo "running $(cat "$PID_FILE")"
    else
      echo "stopped"
      exit 1
    fi
    ;;
  *)
    echo "usage: $0 [start|stop|status]" >&2
    exit 2
    ;;
esac
