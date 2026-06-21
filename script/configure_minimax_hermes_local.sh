#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE="com.bilbop.ClippingOpsCockpit"
ACCOUNT="minimax.api_key"
PROFILE="${HERMES_PROFILE:-clipping-ops-minimax}"
MODEL="${MINIMAX_MODEL:-MiniMax-M3}"
PYTHON_BIN="$ROOT_DIR/backend/.venv/bin/python"
if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi
PROMPT_FOR_KEY=1

for arg in "$@"; do
  case "$arg" in
    --no-prompt)
      PROMPT_FOR_KEY=0
      ;;
    --prompt)
      PROMPT_FOR_KEY=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ "${CLIPPING_OPS_NO_KEY:-0}" == "1" ]]; then
  echo "CLIPPING_OPS_NO_KEY=1 is set; refusing to store a MiniMax key." >&2
  exit 2
fi

if ! command -v hermes >/dev/null 2>&1; then
  echo "Hermes is not on PATH. Install/configure Hermes locally first." >&2
  exit 1
fi

LOCAL_SECRET_VALUE="$(security find-generic-password -s "$SERVICE" -a "$ACCOUNT" -w 2>/dev/null || true)"
PROFILE_ENV="$HOME/.hermes/profiles/$PROFILE/.env"
if [[ -z "$LOCAL_SECRET_VALUE" && -f "$PROFILE_ENV" ]]; then
  LOCAL_SECRET_VALUE="$(sed -n 's/^MINIMAX_API_KEY=//p' "$PROFILE_ENV" | head -n 1)"
  if [[ -n "$LOCAL_SECRET_VALUE" ]]; then
    echo "Using existing MiniMax key from Hermes profile '$PROFILE'; no MiniMax prompt needed."
  fi
fi

if [[ -z "$LOCAL_SECRET_VALUE" ]]; then
  if [[ "$PROMPT_FOR_KEY" != "1" ]]; then
    echo "MiniMax key missing from local Keychain and Hermes profile '$PROFILE'. Re-run without --no-prompt to store it securely." >&2
    exit 1
  fi
  printf "Paste MiniMax key for local Keychain storage only. Input is hidden: " >&2
  IFS= read -r -s LOCAL_SECRET_VALUE
  printf "\n" >&2

  if [[ -z "$LOCAL_SECRET_VALUE" ]]; then
    echo "No key provided; nothing changed." >&2
    exit 1
  fi

  security add-generic-password -U -s "$SERVICE" -a "$ACCOUNT" -w "$LOCAL_SECRET_VALUE" >/dev/null
fi

if ! hermes profile list | awk '{print $1}' | grep -Fxq "$PROFILE"; then
  hermes profile create "$PROFILE" --no-alias --description "Clipping Ops MiniMax-only orchestration profile for local review factory jobs."
fi

hermes -p "$PROFILE" config set model.provider minimax >/dev/null
hermes -p "$PROFILE" config set model.default "$MODEL" >/dev/null

mkdir -p "$(dirname "$PROFILE_ENV")"
umask 077
{
  printf "MINIMAX_API_KEY=%s\n" "$LOCAL_SECRET_VALUE"
  printf "HERMES_PROFILE=%s\n" "$PROFILE"
  printf "HERMES_PROVIDER=minimax\n"
  printf "HERMES_MODEL=%s\n" "$MODEL"
} >"$PROFILE_ENV"
chmod 600 "$PROFILE_ENV"

"$PYTHON_BIN" - <<PY
from pathlib import Path
path = Path.home() / ".hermes" / "clipping_ops_minimax.env"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    "HERMES_PROFILE=$PROFILE\\n"
    "HERMES_PROVIDER=minimax\\n"
    "HERMES_MODEL=$MODEL\\n",
    encoding="utf-8",
)
path.chmod(0o600)
print(path)
PY
unset LOCAL_SECRET_VALUE

PYTHONPATH="$ROOT_DIR/backend" "$PYTHON_BIN" - <<PY
from clipping_ops_backend import database as db
db.init_db()
db.set_hermes_profile("$PROFILE")
print("Backend Hermes profile stored: $PROFILE")
PY

echo "MiniMax key is stored locally and profile '$PROFILE' is configured for provider=minimax / model=$MODEL."
echo "Run: ./script/verify_minimax_hermes.sh"
