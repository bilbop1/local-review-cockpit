#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict


BASE_URL = "http://127.0.0.1:8765"


def post_tick() -> Dict[str, Any]:
    request = urllib.request.Request(
        f"{BASE_URL}/api/publish/schedule/tick",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue due Clipping Ops publish work from approved review slots.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = post_tick()
    except (urllib.error.URLError, TimeoutError) as exc:
        payload = {"status": "backend_unavailable", "error": str(exc)}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{payload.get('status', 'unknown')}: queued={len(payload.get('queued', []))}")
    return 0 if payload.get("status") != "backend_unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
