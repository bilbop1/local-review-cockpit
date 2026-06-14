#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict


BASE_URL = "http://127.0.0.1:8765"


def post_tick(force_due: bool = False) -> Dict[str, Any]:
    body = json.dumps({"force_due": force_due}).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}/api/review-schedule/tick",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(description="Queue due Clipping Ops scheduled review builds.")
    parser.add_argument("--force-due", action="store_true", help="Bypass due-time guard for local simulations.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        payload = post_tick(force_due=args.force_due)
    except (urllib.error.URLError, TimeoutError) as exc:
        payload = {"status": "backend_unavailable", "error": str(exc)}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{payload.get('status', 'unknown')}: queued={len(payload.get('queued', []))}")
    return 0 if payload.get("status") != "backend_unavailable" else 1


if __name__ == "__main__":
    raise SystemExit(main())
