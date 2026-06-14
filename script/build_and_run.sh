#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-run}"
WEB_URL="${CLIPPING_OPS_WEB_URL:-http://127.0.0.1:8765/app}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$ROOT_DIR"

"$ROOT_DIR/script/start_backend.sh" start

build_web() {
  "$ROOT_DIR/script/build_web.sh"
}

case "$MODE" in
  run)
    build_web
    echo "Clipping Ops web cockpit is ready:"
    echo "$WEB_URL"
    ;;
  --open|open)
    build_web
    /usr/bin/open "$WEB_URL"
    ;;
  --dev|dev)
    "$ROOT_DIR/script/start_backend.sh" start
    npm --prefix "$ROOT_DIR/web" install
    echo "Vite dev server: http://127.0.0.1:5173/app"
    echo "Backend API: $WEB_URL"
    npm --prefix "$ROOT_DIR/web" run dev
    ;;
  --logs|logs)
    "$ROOT_DIR/script/start_backend.sh" start
    tail -f "$ROOT_DIR/.run/backend.log"
    ;;
  --verify|verify)
    build_web
    python3 - <<'PY'
import urllib.request
with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=10) as response:
    assert response.status == 200
with urllib.request.urlopen("http://127.0.0.1:8765/app", timeout=10) as response:
    body = response.read(4096).decode("utf-8", errors="replace")
    assert response.status == 200 and "<div id=\"root\">" in body
PY
    echo "Verified backend and web cockpit at $WEB_URL"
    ;;
  *)
    echo "usage: $0 [run|--open|--dev|--logs|--verify]" >&2
    exit 2
    ;;
esac
