#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required for the browser cockpit. Install Node.js/npm, then rerun." >&2
  exit 1
fi

if [[ ! -d "$ROOT_DIR/web/node_modules" ]]; then
  npm --prefix "$ROOT_DIR/web" install
fi

npm --prefix "$ROOT_DIR/web" run typecheck
npm --prefix "$ROOT_DIR/web" run build

echo "Web cockpit built at $ROOT_DIR/web/dist"
