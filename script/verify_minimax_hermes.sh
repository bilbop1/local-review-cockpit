#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${HERMES_PROFILE:-clipping-ops-minimax}"
MODEL="${MINIMAX_MODEL:-MiniMax-M3}"
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

SERVICE = "com.bilbop.ClippingOpsCockpit"
ACCOUNT = "minimax.api_key"
PROFILE = "clipping-ops-minimax"
MODEL = "MiniMax-M3"

def keychain_key() -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
        text=True,
        capture_output=True,
        timeout=4,
    )
    return result.stdout.strip() if result.returncode == 0 else ""

def profile_env_key() -> str:
    path = Path.home() / ".hermes" / "profiles" / PROFILE / ".env"
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("MINIMAX_API_KEY="):
                return raw.split("=", 1)[1].strip()
    except Exception:
        return ""
    return ""

def model_list_ok(token: str) -> dict:
    if not token:
        return {"ok": False, "detail": "MiniMax key missing from local Keychain and Hermes profile .env"}
    request = urllib.request.Request(
        "https://api.minimax.io/v1/models",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detail": f"MiniMax model list HTTP {exc.code}"}
    except Exception as exc:
        return {"ok": False, "detail": f"MiniMax model list failed: {type(exc).__name__}"}
    ids = [str(item.get("id", "")) for item in payload.get("data", []) if isinstance(item, dict)]
    return {"ok": MODEL in ids, "detail": f"{MODEL} {'available' if MODEL in ids else 'missing'}; models_seen={len(ids)}"}

token = keychain_key()
source = "keychain" if token else ""
if not token:
    token = profile_env_key()
    source = "hermes_profile_env" if token else ""
result = model_list_ok(token)
print(json.dumps({"minimax_api": {**result, "key_source": source or "missing"}}, indent=2))
sys.exit(0 if result["ok"] else 1)
PY

echo "Hermes status summary:"
if command -v hermes >/dev/null 2>&1; then
  hermes -p "$PROFILE" status | awk '
    BEGIN {IGNORECASE=1}
    /^Profile:/ || /^Provider:/ || /^Model:/ || /^Gateway:/ {print}
  '
  hermes cron list | grep -E "clip-ops|clip-review|clip-research|Clipping" || true
else
  echo "hermes missing"
  exit 1
fi

PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" - <<PY
import json
import subprocess
from clipping_ops_backend import database as db
db.init_db()
profile = db.hermes_profile()
provider = ""
model = ""
status = subprocess.run(["hermes", "-p", profile, "status"], text=True, capture_output=True, timeout=8)
for line in status.stdout.splitlines():
    stripped = line.strip()
    if stripped.lower().startswith("provider:"):
        provider = stripped.split(":", 1)[1].strip()
    elif stripped.lower().startswith("model:"):
        model = stripped.split(":", 1)[1].strip()
status = db.minimax_hermes_status(
    selected_profile=profile,
    provider=provider,
    model=model,
    cron_jobs=db.clipping_hermes_cron_jobs(),
    available=status.returncode == 0,
    api_key_configured=db.minimax_profile_key_configured(profile),
)
print(json.dumps({
    "backend_profile": profile,
    "expected_profile": "$PROFILE",
    "expected_model": "$MODEL",
    "status": status["status"],
    "ready": status["ready"],
    "provider": status["provider"],
    "model": status["model"],
    "blockers": status["blockers"],
}, indent=2))
raise SystemExit(0 if status["ready"] else 1)
PY
