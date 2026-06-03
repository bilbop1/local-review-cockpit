#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$ROOT_DIR/script/install_backend_launch_agent.sh"
"$ROOT_DIR/script/install_app_launch_agent.sh"
"$ROOT_DIR/script/check_startup_agents.py"
