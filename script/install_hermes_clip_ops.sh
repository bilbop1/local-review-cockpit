#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_PROFILE="${HERMES_PROFILE:-clipping-ops-minimax}"
ALLOW_LEGACY_DEFAULT_CLEANUP="${CLIPPING_OPS_ALLOW_LEGACY_DEFAULT_CRON_CLEANUP:-0}"

for arg in "$@"; do
  case "$arg" in
    --repair)
      ;;
    --cleanup-legacy-default)
      ALLOW_LEGACY_DEFAULT_CLEANUP=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ "$HERMES_PROFILE" != "clipping-ops-minimax" && "${CLIPPING_OPS_ALLOW_NON_MINIMAX_HERMES:-0}" != "1" ]]; then
  echo "Refusing to install Clipping Ops cron jobs under non-MiniMax profile: $HERMES_PROFILE" >&2
  echo "Set CLIPPING_OPS_ALLOW_NON_MINIMAX_HERMES=1 only for temporary local debugging." >&2
  exit 2
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "Hermes is not on PATH." >&2
  exit 1
fi

if ! hermes profile list | awk '{print $1}' | grep -Fxq "$HERMES_PROFILE"; then
  echo "Hermes profile '$HERMES_PROFILE' does not exist. Run ./script/configure_minimax_hermes_local.sh first." >&2
  exit 1
fi

echo "Installing Clipping Ops as a Hermes sidecar under profile: $HERMES_PROFILE"
echo "Existing default/other Hermes profiles and cron jobs will be left untouched."
if [[ "$ALLOW_LEGACY_DEFAULT_CLEANUP" == "1" ]]; then
  echo "Advanced cleanup enabled: legacy default-profile Clipping Ops cron jobs may be removed."
fi

job_id_for_name() {
  local name="$1"
  python3 - "$name" <<'PY'
import json
import sys
from pathlib import Path

name = sys.argv[1]
profile = "clipping-ops-minimax"
path = Path.home() / ".hermes" / "profiles" / profile / "cron" / "jobs.json"
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    payload = {"jobs": []}
for job in payload.get("jobs", []):
    if isinstance(job, dict) and job.get("name") == name:
        print(job.get("id", ""))
        raise SystemExit(0)
PY
}

remove_default_job() {
  local name="$1"
  if [[ "$ALLOW_LEGACY_DEFAULT_CLEANUP" != "1" ]]; then
    return 0
  fi
  python3 - "$name" <<'PY' | while IFS= read -r job_id; do
import json
import sys
from pathlib import Path

name = sys.argv[1]
path = Path.home() / ".hermes" / "cron" / "jobs.json"
try:
    payload = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    payload = {"jobs": []}
for job in payload.get("jobs", []):
    if isinstance(job, dict) and job.get("name") == name and not job.get("profile"):
        print(job.get("id", ""))
PY
    if [[ -n "$job_id" ]]; then
      hermes cron remove "$job_id" >/dev/null || true
      echo "✓ removed legacy default cron $name ($job_id)"
    fi
  done
}

create_job() {
  local name="$1"
  local schedule="$2"
  local prompt_file="$3"
  local prompt
  prompt="$(<"$prompt_file")"
  remove_default_job "$name"
  local job_id
  job_id="$(job_id_for_name "$name")"
  if [[ -n "$job_id" ]]; then
    hermes -p "$HERMES_PROFILE" cron edit "$job_id" --schedule "$schedule" --prompt "$prompt" --name "$name" --deliver local --workdir "$ROOT_DIR" --script "" --agent
    echo "✓ repaired $name ($job_id) with profile $HERMES_PROFILE"
  else
    hermes -p "$HERMES_PROFILE" cron create "$schedule" "$prompt" --name "$name" --deliver local --workdir "$ROOT_DIR"
    echo "✓ created $name with profile $HERMES_PROFILE"
  fi
}

create_no_agent_job() {
  local name="$1"
  local schedule="$2"
  local script_path="$3"
  local prompt="$4"
  remove_default_job "$name"
  local job_id
  job_id="$(job_id_for_name "$name")"
  if [[ -n "$job_id" ]]; then
    hermes -p "$HERMES_PROFILE" cron edit "$job_id" --schedule "$schedule" --prompt "$prompt" --name "$name" --deliver local --workdir "$ROOT_DIR" --script "$script_path" --no-agent
    echo "✓ repaired $name ($job_id) with profile $HERMES_PROFILE"
  else
    hermes -p "$HERMES_PROFILE" cron create "$schedule" "$prompt" --name "$name" --deliver local --workdir "$ROOT_DIR" --script "$script_path" --no-agent
    echo "✓ created $name with profile $HERMES_PROFILE"
  fi
}

PROFILE_HOME="$HOME/.hermes/profiles/$HERMES_PROFILE"
SCRIPT_DIR="$PROFILE_HOME/scripts"
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
APP_SUPPORT_DIR="$HOME/Library/Application Support/ClippingOpsCockpit"
mkdir -p "$SCRIPT_DIR"
DISPATCHER_SCRIPT="$SCRIPT_DIR/clipping_ops_job_dispatcher.sh"
cat >"$DISPATCHER_SCRIPT" <<SH
#!/usr/bin/env bash
set -euo pipefail
cd "$ROOT_DIR"
export CLIPPING_OPS_HOME="$APP_SUPPORT_DIR"
PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" "$ROOT_DIR/script/hermes_job_dispatcher.py" --limit 3 --json
SH
chmod 700 "$DISPATCHER_SCRIPT"

SCHEDULER_SCRIPT="$SCRIPT_DIR/clipping_ops_review_scheduler_tick.sh"
cat >"$SCHEDULER_SCRIPT" <<SH
#!/usr/bin/env bash
set -euo pipefail
cd "$ROOT_DIR"
export CLIPPING_OPS_HOME="$APP_SUPPORT_DIR"
PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" "$ROOT_DIR/script/review_schedule_tick.py" --json
SH
chmod 700 "$SCHEDULER_SCRIPT"

PUBLISH_SCHEDULER_SCRIPT="$SCRIPT_DIR/clipping_ops_publish_schedule_tick.sh"
cat >"$PUBLISH_SCHEDULER_SCRIPT" <<SH
#!/usr/bin/env bash
set -euo pipefail
cd "$ROOT_DIR"
export CLIPPING_OPS_HOME="$APP_SUPPORT_DIR"
PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" "$ROOT_DIR/script/publish_schedule_tick.py" --json
SH
chmod 700 "$PUBLISH_SCHEDULER_SCRIPT"

create_job "clip-ops daily brief" "every 24h" "$ROOT_DIR/hermes/clip-ops.prompt.md"
create_job "clip-research campaign gate sweep" "every 12h" "$ROOT_DIR/hermes/clip-research.prompt.md"
create_job "clip-review kit risk sweep" "every 6h" "$ROOT_DIR/hermes/clip-review.prompt.md"
create_job "clip-review learning summary" "every 24h" "$ROOT_DIR/hermes/clip-review.prompt.md"
create_no_agent_job "clip-ops scheduler tick" "every 15m" "$(basename "$SCHEDULER_SCRIPT")" "Queue due Clipping Ops review builds. Enforce 24/day global cap, 8/day/campaign cap, source gates, backlog guard, and MiniMax Hermes profile readiness."
create_no_agent_job "clip-ops publish schedule tick" "every 1m" "$(basename "$PUBLISH_SCHEDULER_SCRIPT")" "Queue due approved publish jobs at their :14 slots. If local auto-post is on and the selected platform is ready, due jobs become live Upload-Post work."
create_no_agent_job "clip-ops job dispatcher" "every 10m" "$(basename "$DISPATCHER_SCRIPT")" "Claim and execute queued Clipping Ops Cockpit jobs. Live posting requires backend approval, locked Upload-Post profile, provider key, platform warm-up, and local auto-post enablement."

echo "Hermes Clipping Ops jobs installed or already present with profile: $HERMES_PROFILE"
