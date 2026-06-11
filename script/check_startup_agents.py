#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "startup" / "startup-agents.json"
BACKEND_LABEL = "com.bilbop.ClippingOpsCockpit.backend"
APP_LABEL = "com.bilbop.ClippingOpsCockpit.app"
WEB_APP = "http://127.0.0.1:8765/app"


def launchctl_state(label: str) -> dict[str, Any]:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        text=True,
        capture_output=True,
        timeout=8,
    )
    output = result.stdout + result.stderr
    state_match = re.search(r"state = ([^\n]+)", output)
    exit_match = re.search(r"last exit code = ([^\n]+)", output)
    return {
        "label": label,
        "installed": result.returncode == 0,
        "state": state_match.group(1).strip() if state_match else "missing",
        "last_exit": exit_match.group(1).strip() if exit_match else "",
    }


def backend_health() -> dict[str, Any]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=3) as response:
            payload = json.load(response)
        return {
            "ok": response.status == 200,
            "api_version": str(payload.get("api_version", "")),
            "database_ok": bool(payload.get("checks", {}).get("database", {}).get("ok")),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def web_app_health() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(WEB_APP, timeout=3) as response:
            body = response.read(4096).decode("utf-8", errors="replace")
        return {
            "ok": response.status == 200 and '<div id="root">' in body,
            "url": WEB_APP,
            "built_assets": "/app/assets/" in body,
        }
    except Exception as exc:
        return {"ok": False, "url": WEB_APP, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    backend_agent = launchctl_state(BACKEND_LABEL)
    app_agent = launchctl_state(APP_LABEL)
    backend = backend_health()
    app = web_app_health()
    ok = (
        backend_agent["installed"]
        and backend_agent["state"] == "running"
        and backend.get("ok")
        and app_agent["installed"]
        and app.get("ok")
    )
    payload = {
        "ok": bool(ok),
        "backend_agent": backend_agent,
        "app_agent": app_agent,
        "backend_health": backend,
        "web_app": app,
        "blocker": "" if ok else "Startup agents are not both healthy; reinstall with script/install_startup_agents.sh.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
