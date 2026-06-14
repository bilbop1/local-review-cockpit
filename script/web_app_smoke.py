#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request


def fetch_text(url: str, timeout: int = 15) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise SystemExit(f"{url} returned HTTP {response.status}")
        return response.read().decode("utf-8", errors="replace")


def fetch_json(url: str, timeout: int = 15) -> object:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        if response.status != 200:
            raise SystemExit(f"{url} returned HTTP {response.status}")
        return json.load(response)


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = sys.argv[2] if len(sys.argv) > 2 else "8765"
    base = f"http://{host}:{port}"
    html = fetch_text(f"{base}/app")
    if '<div id="root">' not in html:
        raise SystemExit("/app did not return the React shell")
    if "/app/assets/" not in html:
        raise SystemExit("/app did not reference built Vite assets")
    for route in ["reviews", "campaigns", "readiness", "settings", "advanced"]:
        route_html = fetch_text(f"{base}/app/{route}")
        if '<div id="root">' not in route_html:
            raise SystemExit(f"/app/{route} did not return SPA fallback")
    api_paths = {
        "/api/health": 15,
        "/api/review-kits": 30,
        "/api/campaign-projects": 30,
        "/api/readiness": 45,
        "/api/publish/status": 15,
    }
    for path, timeout in api_paths.items():
        fetch_json(f"{base}{path}", timeout=timeout)
    print(json.dumps({"ok": True, "app": f"{base}/app", "routes": 6}, indent=2))


if __name__ == "__main__":
    main()
