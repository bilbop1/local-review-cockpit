#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HERMES_PROFILE="${HERMES_PROFILE:-default}"

if ! command -v hermes >/dev/null 2>&1; then
  echo "Hermes is not on PATH." >&2
  exit 1
fi

create_job() {
  local name="$1"
  local schedule="$2"
  local prompt_file="$3"
  if hermes cron list | grep -Fq "Name:      $name"; then
    echo "✓ $name already exists"
    return
  fi
  local prompt
  prompt="$(<"$prompt_file")"
  hermes cron create "$schedule" "$prompt" --name "$name" --deliver local --workdir "$ROOT_DIR" --profile "$HERMES_PROFILE"
}

create_no_agent_job() {
  local name="$1"
  local schedule="$2"
  local script_path="$3"
  local prompt="$4"
  if hermes cron list | grep -Fq "Name:      $name"; then
    echo "✓ $name already exists"
    return
  fi
  hermes cron create "$schedule" "$prompt" --name "$name" --deliver local --workdir "$ROOT_DIR" --script "$script_path" --no-agent --profile "$HERMES_PROFILE"
}

mkdir -p "$HOME/.hermes/scripts"
DISPATCHER_SCRIPT="$HOME/.hermes/scripts/clipping_ops_job_dispatcher.sh"
cat >"$DISPATCHER_SCRIPT" <<SH
#!/usr/bin/env bash
set -euo pipefail
cd "$ROOT_DIR"
PYTHONPATH="$ROOT_DIR/backend" python3 "$ROOT_DIR/script/hermes_job_dispatcher.py" --limit 3 --json
SH
chmod 700 "$DISPATCHER_SCRIPT"

create_job "clip-ops daily brief" "every 24h" "$ROOT_DIR/hermes/clip-ops.prompt.md"
create_job "clip-research campaign gate sweep" "every 12h" "$ROOT_DIR/hermes/clip-research.prompt.md"
create_job "clip-review kit risk sweep" "every 6h" "$ROOT_DIR/hermes/clip-review.prompt.md"
create_no_agent_job "clip-ops job dispatcher" "every 10m" "$(basename "$DISPATCHER_SCRIPT")" "Claim and execute queued Clipping Ops Cockpit jobs. Deterministic worker only; live posting requires backend approval/provider/warm-up/final-confirmation gates and never mutates accounts."

echo "Hermes Clipping Ops jobs installed or already present with profile: $HERMES_PROFILE"
