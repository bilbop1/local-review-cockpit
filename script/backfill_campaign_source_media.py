#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(ROOT / "script") not in sys.path:
    sys.path.insert(0, str(ROOT / "script"))

from clipping_ops_backend import database as db
from clipping_ops_backend.server import discover_campaign_sources, refresh_campaign_project
from build_evidence_review_kit import Candidate, ensure_local_media, validate_source_media


def route_for_clip(slug: str, clip: Dict[str, Any]) -> Dict[str, Any]:
    routes = db.rows(
        """
        SELECT *
        FROM source_routes
        WHERE risk_flags_json LIKE ?
        ORDER BY
          CASE availability_status WHEN 'verified' THEN 0 WHEN 'reachable' THEN 1 ELSE 2 END,
          updated_at DESC
        """,
        (f"%campaign_project_{slug}%",),
    )
    clip_url = str(clip.get("source_url", "")).lower()
    for route in routes:
        route_url = str(route.get("source_url", "")).lower()
        if route_url and (route_url == clip_url or route_url in clip_url or clip_url in route_url):
            return route
    if routes:
        return routes[0]
    return {
        "id": f"campaign-route-{slug}",
        "platform": str(clip.get("source_platform", "")),
        "creator_handle": slug,
        "source_url": str(clip.get("source_url", "")),
        "route_type": "manual_import",
        "availability_status": "indexed",
        "risk_flags": [f"campaign_project_{slug}"],
    }


def clip_source_ready(clip: Dict[str, Any]) -> bool:
    local_value = str(clip.get("local_media_path", "")).strip()
    return bool(local_value) and validate_source_media(Path(local_value))


def backfill_campaign(slug: str, limit: int) -> Dict[str, Any]:
    refresh_campaign_project(slug)
    discover_campaign_sources(slug)
    rules = db.campaign_rules_for_slug(slug)
    if not rules:
        return {"campaign": slug, "status": "blocked", "created": [], "blockers": ["campaign rules missing"]}
    created: List[Dict[str, Any]] = []
    blockers: List[str] = []
    candidates = [
        clip
        for clip in db.campaign_clips(slug)
        if str(clip.get("source_url", "")).strip()
        and not clip_source_ready(clip)
    ]
    for clip in candidates:
        if len(created) >= limit:
            break
        candidate = Candidate(clip=clip, route=route_for_clip(slug, clip), rules=rules)
        try:
            media_path = ensure_local_media(candidate)
            if not validate_source_media(media_path):
                raise RuntimeError("downloaded file did not validate as source media")
            created.append(
                {
                    "clip_id": str(clip.get("id", "")),
                    "campaign": slug,
                    "source_url": str(clip.get("source_url", "")),
                    "local_media_path": str(media_path),
                }
            )
        except Exception as exc:
            blockers.append(f"{clip.get('id', '')}: {exc}")
    status = "succeeded" if created else "blocked"
    db.create_job(
        f"{slug}-source-media-backfill",
        "media",
        status,
        "source-media" if created else "blocked",
        100 if created else 20,
        logs=f"Verified {len(created)} local media file(s) for {slug}.",
        error="; ".join(blockers)[:1200],
    )
    db.log_audit("worker", "backfill_campaign_source_media", "campaign_project", slug, status, "; ".join(blockers[:2]))
    return {"campaign": slug, "status": status, "created": created, "blockers": blockers[:8]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", action="append", choices=db.active_campaign_project_slugs())
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--download-timeout", type=int, default=180)
    args = parser.parse_args()

    db.init_db()
    os.environ["CLIPPING_OPS_YTDLP_TIMEOUT"] = str(max(30, args.download_timeout))
    campaigns = args.campaign or ["kalshi"]
    results = [backfill_campaign(slug, max(1, args.limit)) for slug in campaigns]
    print(json.dumps({"status": "succeeded" if any(item["created"] for item in results) else "blocked", "results": results}, indent=2))
    return 0 if any(item["created"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
