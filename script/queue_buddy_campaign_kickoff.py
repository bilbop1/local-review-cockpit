#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from typing import Any, Dict, List

from clipping_ops_backend import database as db


REQUESTED_BY = "codex-buddy-bootstrap"


def _campaign_payload(slug: str) -> Dict[str, Any]:
    return {
        "campaign_slug": slug,
        "limit": 1,
        "style": db.CAMPAIGN_SHORT_PROFILE,
        "selection_mode": "fresh_best_candidate",
        "freshness_ladder_hours": list(db.FRESHNESS_LADDER_HOURS),
        "avoid_rejected_patterns": True,
        "quota_recovery_mode": False,
        "quota_recovery_policy": db.quota_recovery_policy(False),
        "learning_context": db.learning_context_for_campaign(slug, limit=8),
        "caption_alignment": "ensemble-retime",
        "starter_kickoff": True,
    }


def _planned_jobs(campaigns: List[str]) -> List[Dict[str, Any]]:
    planned: List[Dict[str, Any]] = [
        {
            "intent": "refresh_campaigns",
            "campaign_slug": "",
            "payload": {"starter_kickoff": True},
        }
    ]
    for slug in campaigns:
        planned.extend(
            [
                {
                    "intent": "refresh_campaign_project",
                    "campaign_slug": slug,
                    "payload": {"campaign_slug": slug, "starter_kickoff": True},
                },
                {
                    "intent": "discover_campaign_sources",
                    "campaign_slug": slug,
                    "payload": {
                        "campaign_slug": slug,
                        "freshness_ladder_hours": list(db.FRESHNESS_LADDER_HOURS),
                        "starter_kickoff": True,
                    },
                },
                {
                    "intent": "scheduled_campaign_review_build",
                    "campaign_slug": slug,
                    "payload": _campaign_payload(slug),
                },
            ]
        )
    planned.append(
        {
            "intent": "review_learning_summary",
            "campaign_slug": "",
            "payload": {"starter_kickoff": True},
        }
    )
    return planned


def queue_jobs(campaigns: List[str], *, dry_run: bool = False, force_new: bool = False) -> Dict[str, Any]:
    db.init_db()
    profile = db.hermes_profile()
    planned = _planned_jobs(campaigns)
    if dry_run:
        return {
            "status": "planned",
            "dry_run": True,
            "queued": [],
            "planned": planned,
            "campaigns": campaigns,
            "hermes_profile": profile,
        }

    queued: List[Dict[str, Any]] = []
    for item in planned:
        queued.append(
            db.create_job_intent(
                str(item["intent"]),
                dict(item["payload"]),
                campaign_slug=str(item["campaign_slug"]),
                requested_by=REQUESTED_BY,
                hermes_profile_name=profile,
                force_new=force_new,
            )
        )
    return {
        "status": "queued",
        "dry_run": False,
        "queued_count": len(queued),
        "queued": queued,
        "planned": planned,
        "campaigns": campaigns,
        "hermes_profile": profile,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "next_review_url": "http://127.0.0.1:8765/app/reviews",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Queue first-run Hermes campaign refresh/source/build jobs for a new local operator."
    )
    parser.add_argument("--campaign", action="append", default=[], help="Active campaign slug to queue. Repeatable.")
    parser.add_argument("--dry-run", action="store_true", help="Print the job plan without writing to SQLite.")
    parser.add_argument("--force-new", action="store_true", help="Queue fresh jobs even when matching active jobs exist.")
    parser.add_argument("--json", action="store_true", help="Print JSON output.")
    args = parser.parse_args()

    db.init_db()
    requested = [db.normalize_campaign_slug(slug) for slug in args.campaign]
    invalid = [slug for slug in args.campaign if not db.normalize_campaign_slug(slug)]
    if invalid:
        raise SystemExit(f"Unknown campaign slug(s): {', '.join(invalid)}")
    campaigns = requested or db.active_campaign_project_slugs()
    payload = queue_jobs(campaigns, dry_run=args.dry_run, force_new=args.force_new)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['status']}: campaigns={', '.join(campaigns)} planned={len(payload.get('planned', []))}")
        if payload["status"] == "queued":
            print(f"queued={payload.get('queued_count', 0)} hermes_profile={payload.get('hermes_profile', '')}")
            print(payload["next_review_url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
