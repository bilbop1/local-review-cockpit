#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Clipping Ops Cockpit no-key setup"
echo "Repo: $ROOT_DIR"
echo

export CLIPPING_OPS_NO_KEY=1
export CLIPPING_OPS_HOME="${CLIPPING_OPS_HOME:-$ROOT_DIR/.no-key-home}"
export CLIPPING_OPS_HOST="${CLIPPING_OPS_HOST:-127.0.0.1}"
export CLIPPING_OPS_PORT="${CLIPPING_OPS_PORT:-18765}"
unset TWITCH_CLIENT_ID TWITCH_CLIENT_SECRET TWITCH_APP_ACCESS_TOKEN KICK_CLIENT_ID KICK_CLIENT_SECRET KICK_APP_ACCESS_TOKEN

resolved_home="$(python3 - "$CLIPPING_OPS_HOME" <<'PY'
from pathlib import Path
import sys
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
case "$resolved_home" in
  ""|"/"|"$HOME"|"$ROOT_DIR")
    echo "Refusing to wipe unsafe CLIPPING_OPS_HOME: $resolved_home" >&2
    exit 66
    ;;
esac
if [[ "$resolved_home" != "$ROOT_DIR/.no-key-home"* && "${CLIPPING_OPS_ALLOW_EXTERNAL_NO_KEY_HOME:-0}" != "1" ]]; then
  echo "Refusing external CLIPPING_OPS_HOME without CLIPPING_OPS_ALLOW_EXTERNAL_NO_KEY_HOME=1: $resolved_home" >&2
  exit 66
fi
rm -rf "$CLIPPING_OPS_HOME"
mkdir -p "$CLIPPING_OPS_HOME"

missing=0
for cmd in swift uv ffmpeg ffprobe python3 hermes; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "✓ $cmd: $(command -v "$cmd")"
  else
    echo "✗ missing $cmd"
    missing=1
  fi
done

echo "• yt-dlp will be installed into the managed backend runtime with uv."

if [[ "$missing" -ne 0 ]]; then
  echo "Install missing dependencies before continuing." >&2
  exit 1
fi

echo
echo "Building Swift app..."
swift build

echo
echo "Starting backend and rendering demo kits..."
"$ROOT_DIR/script/start_backend.sh" start
"$ROOT_DIR/script/render_demo_kits.sh"
"$ROOT_DIR/script/start_backend.sh" start

python3 - "$CLIPPING_OPS_HOST" "$CLIPPING_OPS_PORT" <<'PY'
import json
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]

with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=10) as response:
    health = json.load(response)
assert health["auth"]["no_key_mode"] is True, health["auth"]
assert health["auth"]["providers"]["twitch"]["ok"] is False, health["auth"]
assert health["auth"]["providers"]["kick"]["ok"] is False, health["auth"]
assert health["publish"]["provider"]["api_key"] == "missing", health["publish"]
assert health["publish"]["provider"]["live_ready"] is False, health["publish"]
assert health["production_green"] is False, health
print("no-key credential isolation ok")
PY

echo
echo "Running smoke test..."
"$ROOT_DIR/script/smoke_test.sh"

mkdir -p "$ROOT_DIR/artifacts/no-key"
python3 - "$ROOT_DIR" "$CLIPPING_OPS_HOME" "$CLIPPING_OPS_HOST" "$CLIPPING_OPS_PORT" <<'PY'
import json
from pathlib import Path
import sys
import time
import urllib.request

root, home, host, port = sys.argv[1:5]
with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=10) as response:
    health = json.load(response)
with urllib.request.urlopen(f"http://{host}:{port}/api/readiness", timeout=10) as response:
    readiness = json.load(response)
with urllib.request.urlopen(f"http://{host}:{port}/api/agents", timeout=10) as response:
    agents = json.load(response)
payload = {
    "ok": health["auth"]["no_key_mode"] is True
    and health["auth"]["providers"]["twitch"]["ok"] is False
    and health["auth"]["providers"]["kick"]["ok"] is False
    and health["publish"]["provider"]["api_key"] == "missing"
    and health["publish"]["provider"]["live_ready"] is False
    and health["production_green"] is False,
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "clipping_ops_home": home,
    "host": host,
    "port": port,
    "no_key_mode": health["auth"]["no_key_mode"],
    "api_version": health["api_version"],
    "twitch_ok": health["auth"]["providers"]["twitch"]["ok"],
    "kick_ok": health["auth"]["providers"]["kick"]["ok"],
    "uploadpost_api_key": health["publish"]["provider"]["api_key"],
    "uploadpost_live_ready": health["publish"]["provider"]["live_ready"],
    "production_green": health["production_green"],
    "readiness_overall": readiness["overall"],
    "hermes_available": agents["hermes_available"],
    "hermes_status": agents["status"],
    "hermes_profile": agents["selected_profile"],
    "secrets_transferred": False,
}
path = Path(root) / "artifacts" / "no-key" / "no-key-installer.json"
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(path)
raise SystemExit(0 if payload["ok"] else 1)
PY

echo
echo "No-key setup complete. This script does not copy API keys, Upload-Post keys, Hermes auth, Discord tokens, .env files, or Keychain items."
echo "Run: ./script/build_and_run.sh"
