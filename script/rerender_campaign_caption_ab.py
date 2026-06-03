#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.caption_style import PRODUCTION_CAPTION_VARIANTS
from build_evidence_review_kit import build_review_kit


OUT_PATH = ROOT / "artifacts" / "review-kit-audit" / "caption-ab-rerender.json"


def clip_id_for_kit(kit: Dict[str, Any]) -> str:
    if str(kit.get("clip_id", "")).strip():
        return str(kit["clip_id"]).strip()
    nomination = db.one("SELECT * FROM render_nominations WHERE id = ?", (str(kit.get("nomination_id", "")),))
    ids = db._clip_ids_for_nomination(nomination)
    return ids[0] if ids else ""


def main() -> int:
    db.init_db()
    kits = [
        kit
        for kit in db.visible_render_kits()
        if str(kit.get("campaign_slug", "")).strip() in db.active_campaign_project_slugs()
        and str(kit.get("review_status", "")) != "approved_manual_prep"
    ]
    kits.sort(key=lambda item: (str(item.get("campaign_slug", "")), str(item.get("created_at", "")), str(item.get("id", ""))))

    variants = list(PRODUCTION_CAPTION_VARIANTS)
    results: List[Dict[str, Any]] = []
    for index, kit in enumerate(kits):
        clip_id = clip_id_for_kit(kit)
        if not clip_id:
            results.append({"kit_id": kit.get("id", ""), "status": "blocked", "blocker": "clip id missing"})
            continue
        variant = variants[index % len(variants)]
        result = build_review_kit(
            clip_id=clip_id,
            profile=db.CAMPAIGN_SHORT_PROFILE,
            campaign_slug=str(kit.get("campaign_slug", "")),
            force=True,
            caption_variant=variant,
        )
        result["requested_caption_variant"] = variant
        results.append(result)

    payload = {
        "generated_at": db.utc_now(),
        "status": "succeeded" if all(item.get("status") == "succeeded" for item in results) else "blocked",
        "excluded_variant": "C",
        "variants": variants,
        "kit_count": len(results),
        "results": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
