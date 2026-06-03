#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
REQUIRE_INTERNAL_GREEN=0
REQUIRE_CUSTOMER_GREEN=0
for arg in "$@"; do
  case "$arg" in
    --require-green|--require-internal-green)
      REQUIRE_INTERNAL_GREEN=1
      ;;
    --require-customer-green)
      REQUIRE_INTERNAL_GREEN=1
      REQUIRE_CUSTOMER_GREEN=1
      ;;
  esac
done

cd "$ROOT_DIR"

swift build
PYTHONPATH=backend "$PYTHON_BIN" -m unittest discover -s tests -v
"$ROOT_DIR/script/smoke_test.sh"
"$PYTHON_BIN" "$ROOT_DIR/script/prune_irrelevant_review_surface.py" || true
"$PYTHON_BIN" "$ROOT_DIR/script/reconcile_source_media.py" || true
PYTHONPATH=backend "$PYTHON_BIN" - <<'PY' || true
from clipping_ops_backend import database as db
from clipping_ops_backend.server import refresh_campaign_project, discover_campaign_sources
for slug, project in db.CAMPAIGN_PROJECTS.items():
    if str(project.get("active", "")).lower() != "true":
        continue
    refresh_campaign_project(slug)
    discover_campaign_sources(slug)
PY
if ! "$PYTHON_BIN" - <<'PY' >/dev/null 2>&1
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8765/api/readiness", timeout=10) as response:
    readiness = json.load(response)
for feature in readiness.get("features", []):
    if feature.get("name") == "Campaign review render proof":
        raise SystemExit(0 if feature.get("status") == "green" else 1)
raise SystemExit(1)
PY
then
  echo "Campaign review proof remains blocked; not auto-rendering fallback kits in readiness suite." >&2
  echo "Use the GUI/Hermes Build Latest Reviews action for intentional active-campaign renders only." >&2
fi
"$PYTHON_BIN" "$ROOT_DIR/script/security_scan.py"
"$PYTHON_BIN" "$ROOT_DIR/script/verify_burned_in_captions.py"
"$ROOT_DIR/script/install_backend_launch_agent.sh" || true
"$PYTHON_BIN" "$ROOT_DIR/script/check_backend_launch_agent.py" || true
"$ROOT_DIR/script/package_codex_handoff.sh"
if [[ "$REQUIRE_CUSTOMER_GREEN" == "1" ]]; then
  "$ROOT_DIR/script/package_release.sh" --customer-release
else
  "$ROOT_DIR/script/package_release.sh" --adhoc || true
fi
"$ROOT_DIR/script/setup_buddy_no_key.sh"
"$PYTHON_BIN" "$ROOT_DIR/script/desktop_qa.py"
node "$ROOT_DIR/script/build_ceo_artifacts.mjs"
node "$ROOT_DIR/script/build_ceo_artifacts.mjs"

"$PYTHON_BIN" - "$REQUIRE_INTERNAL_GREEN" "$REQUIRE_CUSTOMER_GREEN" <<'PY'
import json
import sys
import urllib.request

require_internal_green = sys.argv[1] == "1"
require_customer_green = sys.argv[2] == "1"
with urllib.request.urlopen("http://127.0.0.1:8765/api/readiness", timeout=10) as response:
    readiness = json.load(response)
print(json.dumps({
    "overall": readiness.get("overall"),
    "milestones": readiness.get("milestones"),
}, indent=2))
milestones = readiness.get("milestones", {})
if require_internal_green and milestones.get("internal_local_ready", {}).get("status") != "green":
    raise SystemExit(1)
if require_internal_green and milestones.get("buddy_no_key_ready", {}).get("status") != "green":
    raise SystemExit(1)
if require_internal_green and milestones.get("codex_handoff_ready", {}).get("status") != "green":
    raise SystemExit(1)
if require_customer_green and milestones.get("customer_ship_ready", {}).get("status") != "green":
    raise SystemExit(1)
PY
