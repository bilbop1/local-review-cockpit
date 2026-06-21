#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

RUN_NO_KEY=1
RUN_CREDENTIALS=1
RUN_LAUNCH_AGENTS=1
RUN_KICKOFF=1
DRY_RUN=0
UPLOADPOST_PROFILE="${UPLOADPOST_PROFILE:-}"
TIKTOK_WARMED="${CLIPPING_OPS_TIKTOK_WARMED:-}"
AUTO_POST="${CLIPPING_OPS_AUTO_POST_APPROVED:-}"

usage() {
  cat <<'USAGE'
Usage: ./script/codex_buddy_bootstrap.sh [options]

Guided first-machine install for a new local operator. It verifies the clone,
configures local Hermes/MiniMax and private credentials, locks one Upload-Post
profile into the backend, installs launch/Hermes jobs, and queues the first
campaign research/build wave.

Options:
  --dry-run                 Print the plan and run no setup commands.
  --skip-no-key             Skip the isolated no-key verification.
  --skip-credentials        Skip MiniMax/Twitch/Kick/Upload-Post prompts.
  --skip-launch-agents      Skip backend/web LaunchAgent installation.
  --skip-kickoff            Skip starter Hermes campaign jobs.
  --uploadpost-profile NAME Use this exact Upload-Post profile name.
  --tiktok-warmed           Mark TikTok warm-up complete for this local profile.
  --tiktok-not-warmed       Keep TikTok blocked.
  --auto-post               Turn on approved-kit auto-posting, only valid with warmed TikTok.
  --no-auto-post            Keep auto-post off.
  -h, --help                Show this help.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --skip-no-key)
      RUN_NO_KEY=0
      ;;
    --skip-credentials)
      RUN_CREDENTIALS=0
      ;;
    --skip-launch-agents)
      RUN_LAUNCH_AGENTS=0
      ;;
    --skip-kickoff)
      RUN_KICKOFF=0
      ;;
    --uploadpost-profile)
      shift
      UPLOADPOST_PROFILE="${1:-}"
      ;;
    --tiktok-warmed)
      TIKTOK_WARMED=1
      ;;
    --tiktok-not-warmed)
      TIKTOK_WARMED=0
      ;;
    --auto-post)
      AUTO_POST=1
      ;;
    --no-auto-post)
      AUTO_POST=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

run_step() {
  local label="$1"
  shift
  echo
  echo "==> $label"
  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'dry-run:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

ask_yes_no() {
  local prompt="$1"
  local default="${2:-n}"
  local answer
  local normalized
  local suffix="[y/N]"
  if [[ "$default" == "y" ]]; then
    suffix="[Y/n]"
  fi
  read -r -p "$prompt $suffix " answer
  answer="${answer:-$default}"
  normalized="$(printf '%s' "$answer" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    y|yes|true|1) echo "1" ;;
    *) echo "0" ;;
  esac
}

echo "Clipping Ops buddy bootstrap"
echo "Repo: $ROOT_DIR"
echo "Local URL after setup: http://127.0.0.1:8765/app"
echo
echo "Secrets stay in this Mac's Keychain/Hermes profile. Nothing here writes keys into the repo."

if [[ "$RUN_NO_KEY" == "1" ]]; then
  run_step "Verify fresh clone in no-key mode" "$ROOT_DIR/script/verify_incoming_clone.sh"
fi

run_step "Build and verify the local web cockpit" "$ROOT_DIR/script/build_and_run.sh" --verify

if [[ "$RUN_CREDENTIALS" == "1" ]]; then
  run_step "Configure MiniMax-backed Hermes profile" "$ROOT_DIR/script/configure_minimax_hermes_local.sh"
  run_step "Verify MiniMax-backed Hermes profile" "$ROOT_DIR/script/verify_minimax_hermes.sh"
  run_step "Store Twitch/Kick/Upload-Post credentials in macOS Keychain" "$ROOT_DIR/script/store_credentials_keychain.sh"
fi

if [[ -z "$UPLOADPOST_PROFILE" && "$DRY_RUN" != "1" ]]; then
  read -r -p "Exact Upload-Post profile name for this operator: " UPLOADPOST_PROFILE
fi
if [[ -z "$UPLOADPOST_PROFILE" ]]; then
  if [[ "$DRY_RUN" == "1" ]]; then
    UPLOADPOST_PROFILE="local-operator"
  else
    echo "Exact Upload-Post profile name is required." >&2
    exit 2
  fi
fi

if [[ -z "$TIKTOK_WARMED" && "$DRY_RUN" != "1" ]]; then
  TIKTOK_WARMED="$(ask_yes_no "Is the TikTok account on Upload-Post profile '$UPLOADPOST_PROFILE' warmed and safe to post now?" "n")"
fi
TIKTOK_WARMED="${TIKTOK_WARMED:-0}"

if [[ -z "$AUTO_POST" && "$DRY_RUN" != "1" ]]; then
  if [[ "$TIKTOK_WARMED" == "1" ]]; then
    AUTO_POST="$(ask_yes_no "Turn on automatic posting for approved TikTok clips on '$UPLOADPOST_PROFILE'?" "n")"
  else
    AUTO_POST=0
  fi
fi
AUTO_POST="${AUTO_POST:-0}"
if [[ "$TIKTOK_WARMED" != "1" && "$AUTO_POST" == "1" ]]; then
  echo "Refusing --auto-post while TikTok is not marked warmed." >&2
  exit 2
fi

echo
echo "==> Lock Upload-Post profile and platform gates"
if [[ "$DRY_RUN" == "1" ]]; then
  echo "dry-run: profile=$UPLOADPOST_PROFILE tiktok_warmed=$TIKTOK_WARMED auto_post=$AUTO_POST"
else
  PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" - "$UPLOADPOST_PROFILE" "$TIKTOK_WARMED" "$AUTO_POST" <<'PY'
import json
import sys

from clipping_ops_backend import database as db
from clipping_ops_backend import publishing

profile, tiktok_warmed, auto_post = sys.argv[1], sys.argv[2] == "1", sys.argv[3] == "1"
db.init_db()
status = publishing.set_publish_settings(
    {
        "user": profile,
        "mode": "live" if tiktok_warmed else "dry_run",
        "platform_warmup": {
            "tiktok": tiktok_warmed,
            "instagram": False,
            "youtube": False,
            "facebook": False,
        },
        "auto_post_approved": auto_post,
    }
)
print(json.dumps({
    "profile": status["provider"]["user"],
    "mode": status["provider"]["mode"],
    "auto_post_approved": status["auto_schedule"]["auto_post_approved"],
    "default_platforms": status["default_platforms"],
    "provider_blockers": status["provider"]["blockers"],
}, indent=2))
PY
fi

if [[ "$RUN_LAUNCH_AGENTS" == "1" ]]; then
  run_step "Install backend LaunchAgent" "$ROOT_DIR/script/install_backend_launch_agent.sh"
  run_step "Install web cockpit LaunchAgent" "$ROOT_DIR/script/install_app_launch_agent.sh"
fi

run_step "Install or repair Hermes Clipping Ops jobs" "$ROOT_DIR/script/install_hermes_clip_ops.sh" --repair
run_step "Start backend" "$ROOT_DIR/script/start_backend.sh" start

if [[ "$RUN_KICKOFF" == "1" ]]; then
  run_step "Queue starter campaign research and first review-kit builds" env PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" "$ROOT_DIR/script/queue_buddy_campaign_kickoff.py" --json --force-new
fi

echo
echo "Buddy bootstrap complete."
echo "Open: http://127.0.0.1:8765/app/reviews"
echo "Tell the operator to review the first kits in about 45-90 minutes if source credentials, Hermes, and media routes are healthy."
echo "Instagram, YouTube, Facebook, and X are capture columns only until warmed and explicitly enabled later."
