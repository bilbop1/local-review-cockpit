#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OUT = ROOT / "artifacts" / "backend" / "backend-launchagent.json"
LABEL = "com.bilbop.ClippingOpsCockpit.backend"


def expected_api_version() -> str:
    text = (ROOT / "backend" / "clipping_ops_backend" / "server.py").read_text(encoding="utf-8")
    match = re.search(r'^API_VERSION\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else ""


def launchctl_print() -> tuple[int, str]:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"],
        text=True,
        capture_output=True,
        timeout=5,
    )
    return result.returncode, result.stdout + result.stderr


def api_version() -> str:
    for path, timeout in (("/api/version", 2), ("/api/health", 5)):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:8765{path}", timeout=timeout) as response:
                return str(json.load(response).get("api_version", ""))
        except Exception:
            continue
    return ""


def main() -> int:
    code, output = launchctl_print()
    state_match = re.search(r"state = ([^\n]+)", output)
    exit_match = re.search(r"last exit code = ([^\n]+)", output)
    version = api_version()
    state = state_match.group(1).strip() if state_match else "missing"
    last_exit = exit_match.group(1).strip() if exit_match else ""
    expected = expected_api_version()
    ok = code == 0 and state == "running" and version == expected
    payload = {
        "ok": ok,
        "label": LABEL,
        "state": state,
        "last_exit": last_exit,
        "api_version": version,
        "expected_api_version": expected,
        "blocker": "" if ok else "LaunchAgent is not running a healthy backend; script/start_backend.sh local fallback is required.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
