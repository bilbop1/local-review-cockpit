#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
HOST="${CLIPPING_OPS_HOST:-127.0.0.1}"
PORT="${CLIPPING_OPS_PORT:-8765}"

if [[ ! -f "$ROOT_DIR/web/dist/index.html" ]]; then
  "$ROOT_DIR/script/build_web.sh"
fi
"$ROOT_DIR/script/start_backend.sh" start
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python3"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
fi
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" - "$HOST" "$PORT" <<'PY'
import json
from pathlib import Path
import sys
import urllib.request

host, port = sys.argv[1], sys.argv[2]

def get(path, timeout=10):
    with urllib.request.urlopen(f"http://{host}:{port}{path}", timeout=timeout) as response:
        return json.load(response)

health = get("/api/health")
assert health["checks"]["database"]["ok"], health
assert health["checks"]["ffmpeg"]["ok"], health
assert health["checks"]["ffprobe"]["ok"], health
assert health["safety"]["autopublish"] == "locked_until_approved_confirmed", health
assert health["publish"]["provider"]["mode"] in {"dry_run", "live"}, health

req = urllib.request.Request(
    f"http://{host}:{port}/api/demo/render",
    data=json.dumps({"limit": 1}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=900) as response:
    demo = json.load(response)
assert demo["status"] == "succeeded", demo

created_paths = {item["review_video_path"] for item in demo["created"]}
assert len(created_paths) >= 3, demo
assert all(item.get("style_profile") != "selected-feeder-a" for item in demo["created"]), demo
for item in demo["created"]:
    path = Path(item["review_video_path"])
    assert path.exists(), item
    assert str(path).endswith("review.mp4")
    kit_dir = path.parent
    for name in ["ffprobe.json", "thumbnail.jpg", "contact_sheet.jpg", "style_critique.md"]:
        assert (kit_dir / name).exists(), f"missing {name} for {item['title']}"

visible_kits = get("/api/review-kits")
assert all(not kit.get("is_demo") for kit in visible_kits), visible_kits
assert created_paths.isdisjoint({item["review_video_path"] for item in visible_kits}), visible_kits

feeders = get("/api/sweeps/selected-feeders", timeout=180)
assert feeders["status"] in {"succeeded", "partial", "blocked"}, feeders

job_req = urllib.request.Request(
    f"http://{host}:{port}/api/jobs",
    data=json.dumps({"intent": "review_risk_sweep", "requested_by": "smoke", "payload": {}}).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(job_req, timeout=15) as response:
    job = json.load(response)
assert job["status"] in {"queued", "succeeded"}, job

gate_req = urllib.request.Request(f"http://{host}:{port}/api/campaign-gate/run", method="POST")
with urllib.request.urlopen(gate_req, timeout=10) as response:
    gate = json.load(response)
if gate["status"] == "qualified":
    assert gate["visible_campaign_count"] > 0, gate
    assert gate["selected_feeder_count"] > 0, gate
else:
    assert gate["status"] == "blocked", gate
    assert gate["blocker"], gate
print("backend smoke ok")
PY

PYTHONPATH=backend "$PYTHON_BIN" "$ROOT_DIR/script/hermes_job_dispatcher.py" --limit 1 --json

"$PYTHON_BIN" "$ROOT_DIR/script/web_app_smoke.py" "$HOST" "$PORT"
