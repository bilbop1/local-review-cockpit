#!/usr/bin/env python3
"""Rerender needs-review campaign kits whose top cards need replacement."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
SCRIPT_ROOT = ROOT / "script"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.hook_quality import HookQualityError, hook_quality_violations
from build_evidence_review_kit import build_review_kit, viewer_hook


OUT_PATH = ROOT / "artifacts" / "review-kit-audit" / "top-card-repair.json"


def _clip_id_for_kit(kit: Dict[str, Any]) -> str:
    clip_id = str(kit.get("clip_id", "")).strip()
    if clip_id:
        return clip_id
    nomination = db.one("SELECT * FROM render_nominations WHERE id = ?", (str(kit.get("nomination_id", "")),))
    clip_ids = db._clip_ids_for_nomination(nomination)
    return str(clip_ids[0]) if clip_ids else ""


def _manifest_for_kit(kit: Dict[str, Any]) -> Dict[str, Any]:
    path = Path(str(kit.get("review_video_path", ""))).parent / "render_text_manifest.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _current_hook(kit: Dict[str, Any]) -> str:
    manifest = _manifest_for_kit(kit)
    rendered = manifest.get("rendered_text", {}) if isinstance(manifest, dict) else {}
    if isinstance(rendered, dict):
        return str(rendered.get("hook_card", "")).strip()
    return ""


def _hook_quality_payload(kit: Dict[str, Any]) -> Dict[str, Any]:
    manifest = _manifest_for_kit(kit)
    rendered = manifest.get("rendered_text", {}) if isinstance(manifest, dict) else {}
    payload = rendered.get("hook_quality", {}) if isinstance(rendered, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _target_kits(
    campaign_slug: str,
    *,
    only_failing: bool,
    kit_id: str = "",
    clip_id: str = "",
) -> List[Dict[str, Any]]:
    visible = [dict(item) for item in db.rows("SELECT * FROM render_kits ORDER BY created_at DESC")]
    targets: List[Dict[str, Any]] = []
    for kit in visible:
        enriched = db.enrich_render_kit_with_clip_metadata(kit, verify_video=False)
        if str(kit.get("review_status", "")) != "needs_review":
            continue
        if int(kit.get("is_demo", 0) or 0) == 1:
            continue
        if kit_id and str(kit.get("id", "")) != kit_id:
            continue
        enriched_clip_id = str(enriched.get("clip_id", "")).strip()
        if clip_id and enriched_clip_id != clip_id:
            continue
        slug = str(enriched.get("campaign_slug") or kit.get("campaign_slug", "")).strip()
        if not slug or not db.is_active_campaign_project(slug):
            continue
        if campaign_slug and slug != campaign_slug:
            continue
        hook = _current_hook(kit)
        exact_target = bool(kit_id or clip_id)
        if only_failing and not exact_target and not hook_quality_violations(hook):
            continue
        enriched["campaign_slug"] = slug
        targets.append(dict(enriched))
    return targets


def _preview_result(kit: Dict[str, Any]) -> Dict[str, Any]:
    clip_id = _clip_id_for_kit(kit)
    clip = db.one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,)) if clip_id else None
    transcript = db._latest_success_transcript(clip_id) if clip_id else {}
    transcript_text = str((transcript or {}).get("full_text", ""))
    campaign_slug = str(kit.get("campaign_slug", "")).strip()
    handle = campaign_slug or str((clip or {}).get("creator_id", ""))
    proposed = viewer_hook(str((clip or {}).get("title", "") if clip else ""), handle, transcript_text=transcript_text, clip_id=clip_id)
    return {
        "kit_id": str(kit.get("id", "")),
        "clip_id": clip_id,
        "campaign_slug": campaign_slug,
        "status": "preview",
        "before_hook": _current_hook(kit),
        "before_violations": hook_quality_violations(_current_hook(kit)),
        "before_hook_quality": _hook_quality_payload(kit),
        "proposed_hook": proposed,
        "proposed_violations": hook_quality_violations(
            proposed,
            clip_title=str((clip or {}).get("title", "") if clip else ""),
            handle=handle,
            campaign_slug=campaign_slug,
            transcript_text=transcript_text,
        ),
    }


def _rerender_result(kit: Dict[str, Any], *, quota_recovery: bool) -> Dict[str, Any]:
    preview = _preview_result(kit)
    if not preview["clip_id"]:
        return {**preview, "status": "blocked", "blocker": "clip id missing"}
    try:
        result = build_review_kit(
            clip_id=preview["clip_id"],
            profile=db.CAMPAIGN_SHORT_PROFILE,
            campaign_slug=preview["campaign_slug"],
            force=True,
            quota_recovery=quota_recovery,
        )
    except HookQualityError as exc:
        return {**preview, "status": "blocked", "blocker": "blocked_hook_quality", "payload": exc.payload}
    except Exception as exc:
        return {**preview, "status": "blocked", "blocker": str(exc)[:1800]}

    updated = db.one("SELECT * FROM render_kits WHERE id = ?", (str(result.get("kit_id", "")),))
    after_hook = _current_hook(dict(updated or kit))
    return {
        **preview,
        "status": str(result.get("status", "succeeded")),
        "after_hook": after_hook,
        "after_violations": hook_quality_violations(after_hook),
        "result": result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair top cards for unreviewed campaign kits only.")
    parser.add_argument("--apply", action="store_true", help="Rerender target kits. Without this flag the script only previews changes.")
    parser.add_argument("--campaign-slug", default="", choices=["", *db.active_campaign_project_slugs()])
    parser.add_argument("--kit-id", default="", help="Repair one render kit id, even if it is not currently visible in the GUI list.")
    parser.add_argument("--clip-id", default="", help="Repair the needs-review kit for one clip id.")
    parser.add_argument("--limit", type=int, default=0, help="Maximum kits to process. Zero means all targets.")
    parser.add_argument("--only-failing", action="store_true", help="Only target kits whose current hook fails the quality gate.")
    parser.add_argument("--quota-recovery", action="store_true", help="Use quota-recovery candidate policy while rerendering.")
    args = parser.parse_args()

    db.init_db()
    targets = _target_kits(
        args.campaign_slug,
        only_failing=args.only_failing,
        kit_id=args.kit_id.strip(),
        clip_id=args.clip_id.strip(),
    )
    if args.limit > 0:
        targets = targets[: args.limit]

    results = [
        _rerender_result(kit, quota_recovery=args.quota_recovery) if args.apply else _preview_result(kit)
        for kit in targets
    ]
    payload = {
        "generated_at": db.utc_now(),
        "status": "succeeded" if all(item.get("status") in {"preview", "succeeded"} for item in results) else "blocked",
        "mode": "apply" if args.apply else "preview",
        "campaign_slug": args.campaign_slug,
        "kit_id": args.kit_id.strip(),
        "clip_id": args.clip_id.strip(),
        "only_failing": bool(args.only_failing),
        "target_count": len(targets),
        "results": results,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if payload["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
