#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHONPATH="$ROOT_DIR/backend" uv run --project "$ROOT_DIR/backend" python -m clipping_ops_backend.server --render-demo
