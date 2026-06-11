#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export CLIPPING_OPS_NO_KEY=1
export CLIPPING_OPS_HOME="${CLIPPING_OPS_HOME:-$ROOT_DIR/.no-key-home}"
export CLIPPING_OPS_HOST="${CLIPPING_OPS_HOST:-127.0.0.1}"
export CLIPPING_OPS_PORT="${CLIPPING_OPS_PORT:-18765}"
unset TWITCH_CLIENT_ID TWITCH_CLIENT_SECRET TWITCH_APP_ACCESS_TOKEN
unset KICK_CLIENT_ID KICK_CLIENT_SECRET KICK_APP_ACCESS_TOKEN
unset UPLOAD_POST_API_KEY UPLOADPOST_API_KEY

echo "Clipping Ops incoming clone verification"
echo "Repo: $ROOT_DIR"
echo "Mode: no-key isolated verification"
echo

echo "1/5 No-key setup"
"$ROOT_DIR/script/setup_buddy_no_key.sh"

echo
echo "2/5 Swift build"
swift build

echo
echo "3/5 Backend unit tests"
PYTHONPATH=backend "$ROOT_DIR/backend/.venv/bin/python" -m unittest discover -s tests -v

echo
echo "4/5 Backend smoke"
"$ROOT_DIR/script/smoke_test.sh"

echo
echo "5/5 Security scan"
"$ROOT_DIR/backend/.venv/bin/python" "$ROOT_DIR/script/security_scan.py"

echo
echo "Incoming clone status"
python3 - "$CLIPPING_OPS_HOST" "$CLIPPING_OPS_PORT" <<'PY'
import json
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]

def get(path):
    with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=15) as response:
        return json.load(response)

health = get("/api/health")
readiness = get("/api/readiness")
agents = get("/api/agents")
publish = get("/api/publish/status")

print(f"- API version: {health.get('api_version')}")
print(f"- No-key mode: {health.get('auth', {}).get('no_key_mode')}")
print(f"- Readiness overall: {readiness.get('overall')}")
print(f"- Hermes status: {agents.get('status')} / profile={agents.get('selected_profile')}")
print(f"- Upload-Post: key={publish.get('provider', {}).get('api_key')} warmup={publish.get('provider', {}).get('warmup_complete')} live_ready={publish.get('provider', {}).get('live_ready')}")

missing = []
providers = health.get("auth", {}).get("providers", {})
if not providers.get("twitch", {}).get("ok"):
    missing.append("Add the local operator's Twitch credentials with ./script/store_credentials_keychain.sh.")
if not providers.get("kick", {}).get("ok"):
    missing.append("Add Kick credentials only if this operator needs Kick monitoring; Kick is not production source proof by default.")
if publish.get("provider", {}).get("api_key") == "missing":
    missing.append("Add Upload-Post key later, after account warm-up, for dry-run/live publish testing.")
if not agents.get("hermes_available"):
    missing.append("Install/configure local Hermes before expecting Hermes-native orchestration.")

print()
print("Expected missing operator actions:")
if missing:
    for item in missing:
        print(f"- {item}")
else:
    print("- None detected by no-key verification.")

print()
print("Do not call live posting ready until /api/publish/status shows key configured, warm-up complete, live mode, and a confirmed approved kit.")
PY

echo
echo "Incoming clone verification complete."
