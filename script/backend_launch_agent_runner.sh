#!/usr/bin/env bash
set -u
ROOT_DIR="/Users/bilbop/Documents/Codex/CLippentAgent"
LOG_DIR="/Users/bilbop/Documents/Codex/CLippentAgent/.run"
PYTHON_BIN="/Users/bilbop/Documents/Codex/CLippentAgent/backend/.venv/bin/python3"
LABEL="com.bilbop.ClippingOpsCockpit.backend"
mkdir -p "$LOG_DIR"
{
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) starting $LABEL"
  echo "cwd=$ROOT_DIR"
  echo "python=$PYTHON_BIN"
  cd "$ROOT_DIR" || exit 78
  export PYTHONPATH="$ROOT_DIR/backend"
  export PATH="/opt/homebrew/bin:/usr/local/bin:/Users/bilbop/.local/bin:/Users/bilbop/.cargo/bin:/usr/bin:/bin:/usr/sbin:/sbin"
  "$PYTHON_BIN" -V
  "$PYTHON_BIN" -c 'import clipping_ops_backend.server as s; print("api_version=" + s.API_VERSION)'
  if command -v lsof >/dev/null 2>&1; then
    listeners="$(lsof -tiTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "$listeners" ]]; then
      echo "port_8765_listeners_before_start=$listeners"
    fi
  fi
  exec "$PYTHON_BIN" -u -m clipping_ops_backend.server --host 127.0.0.1 --port 8765
} >>"$LOG_DIR/backend.launchd.wrapper.log" 2>&1
