from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.server import validate_kit_artifacts


OUT_DIR = ROOT / "artifacts" / "review-kit-audit"
REQUIRED_FILES = [
    "review.mp4",
    "caption.txt",
    "transcript.txt",
    "checklist.md",
    "source.md",
    "risk.md",
    "ffprobe.json",
    "thumbnail.jpg",
    "contact_sheet.jpg",
    "style_critique.md",
    "render_text_manifest.json",
    "editorial_review.json",
]


@dataclass
class CandidateDecision:
    clip_id: str
    title: str
    source_platform: str
    source_url: str
    local_media_path: str
    provenance: str
    risk_flags: List[str]
    route_match: Dict[str, Any] | None
    transcript_ready: bool
    campaign_rules_ready: bool
    eligible: bool
    blockers: List[str]


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def selected_route_matches() -> List[Dict[str, Any]]:
    return db.rows(
        """
        SELECT *
        FROM source_routes
        WHERE availability_status IN ('verified','reachable')
          AND route_type IN ('official_api','authenticated_route','manual_import')
          AND (
            risk_flags_json LIKE '%selected_feeder_%'
            OR notes LIKE '%Selected feeder%'
          )
        ORDER BY updated_at DESC
        """
    )


def campaign_rules_by_slug() -> Dict[str, List[Dict[str, Any]]]:
    rows = db.rows(
        """
        SELECT campaign_id, title, source_url, notes, captured_at
        FROM campaign_evidence
        WHERE evidence_type='campaign_rules'
        ORDER BY captured_at DESC
        """
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["campaign_id"]).lower(), []).append(row)
    return grouped


def find_route_for_clip(clip: Dict[str, Any], routes: List[Dict[str, Any]]) -> Dict[str, Any] | None:
    source_url = str(clip.get("source_url", "")).lower()
    risk_flags = [str(flag).lower() for flag in clip.get("risk_flags", [])]
    for route in routes:
        handle = str(route.get("creator_handle", "")).lower()
        route_flags = [str(flag).lower() for flag in route.get("risk_flags", [])]
        if handle and handle in source_url:
            return route
        if set(route_flags) & set(risk_flags):
            return route
    return None


def rules_ready_for_clip(clip: Dict[str, Any], route: Dict[str, Any] | None, rules_by_slug: Dict[str, List[Dict[str, Any]]]) -> bool:
    slugs: List[str] = []
    source_url = str(clip.get("source_url", "")).lower()
    for slug in rules_by_slug:
        if slug and slug in source_url:
            slugs.append(slug)
    if route:
        handle = str(route.get("creator_handle", "")).strip().lower()
        if handle:
            slugs.append(handle)
        for flag in route.get("risk_flags", []):
            text = str(flag).lower()
            if text.startswith("selected_feeder_"):
                slugs.append(text.removeprefix("selected_feeder_"))
    for flag in clip.get("risk_flags", []):
        text = str(flag).lower()
        if text.startswith("selected_feeder_"):
            slugs.append(text.removeprefix("selected_feeder_"))
    return any(slug in rules_by_slug for slug in slugs)


def clip_candidates_report() -> List[CandidateDecision]:
    clips = db.rows("SELECT * FROM clip_candidates ORDER BY discovered_at DESC")
    routes = selected_route_matches()
    rules_by_slug = campaign_rules_by_slug()
    transcript_ids = {
        str(row["clip_candidate_id"])
        for row in db.rows("SELECT clip_candidate_id FROM transcripts WHERE status = 'succeeded'")
    }

    decisions: List[CandidateDecision] = []
    for clip in clips:
        route = find_route_for_clip(clip, routes)
        local_media_path = str(clip.get("local_media_path", "")).strip()
        transcript_ready = str(clip.get("id")) in transcript_ids
        rules_ready = rules_ready_for_clip(clip, route, rules_by_slug)
        blockers: List[str] = []
        if not str(clip.get("source_url", "")).strip():
            blockers.append("missing source URL")
        if not str(clip.get("provenance", "")).strip():
            blockers.append("missing provenance")
        if not route:
            blockers.append("missing selected-feeder source route")
        if route and str(route.get("availability_status", "")) not in {"verified", "reachable"}:
            blockers.append("source route is not available")
        if not local_media_path:
            blockers.append("missing local media")
        elif not Path(local_media_path).exists():
            blockers.append("local media path does not exist")
        if not transcript_ready:
            blockers.append("missing stored transcript")
        if not rules_ready:
            blockers.append("missing stored campaign rules")
        if str(clip.get("provenance", "")).strip().lower() == "local-demo":
            blockers.append("demo-only source")
        eligible = not blockers
        decisions.append(
            CandidateDecision(
                clip_id=str(clip["id"]),
                title=str(clip.get("title", "")),
                source_platform=str(clip.get("source_platform", "")),
                source_url=str(clip.get("source_url", "")),
                local_media_path=local_media_path,
                provenance=str(clip.get("provenance", "")),
                risk_flags=[str(flag) for flag in clip.get("risk_flags", [])],
                route_match=route,
                transcript_ready=transcript_ready,
                campaign_rules_ready=rules_ready,
                eligible=eligible,
                blockers=blockers,
            )
        )
    return decisions


def review_kit_report(limit: int = 10) -> List[Dict[str, Any]]:
    kits = db.rows("SELECT * FROM render_kits ORDER BY created_at DESC LIMIT ?", (limit,))
    report: List[Dict[str, Any]] = []
    for kit in kits:
        video_path = Path(str(kit.get("review_video_path", "")))
        kit_dir = video_path.parent
        present = {name: (kit_dir / name).exists() for name in REQUIRED_FILES}
        ok, detail = validate_kit_artifacts(kit)
        status = db.production_feeder_kit_status(kit)
        critique_status = str(status.get("critique_status", "unknown"))
        blockers = [str(item) for item in status.get("blockers", [])]
        if not ok:
            severity = "red"
        elif status.get("classification") == "ignored_study":
            severity = "ignored_study"
        elif status.get("classification") in {"green", "yellow", "red"}:
            severity = str(status["classification"])
        else:
            severity = "red"
        report.append(
            {
                "id": kit["id"],
                "title": kit["title"],
                "created_at": kit["created_at"],
                "review_status": kit["review_status"],
                "is_demo": bool(int(kit.get("is_demo", 0) or 0)),
                "severity": severity,
                "canonical_status": status,
                "critique_status": critique_status,
                "validation_ok": ok,
                "validation_detail": detail,
                "blockers": blockers,
                "kit_dir": str(kit_dir),
                "files_present": present,
            }
        )
    return report


def build_report() -> Dict[str, Any]:
    db.init_db()
    gate = db.latest_campaign_gate()
    readiness = db.readiness_report()
    kit_report = review_kit_report()
    candidate_report = clip_candidates_report()
    eligible = [item for item in candidate_report if item.eligible]
    return {
        "generated_at": db.utc_now(),
        "campaign_gate": gate,
        "readiness_overall": readiness["overall"],
        "latest_review_kits": kit_report,
        "clip_candidates": [
            {
                "clip_id": item.clip_id,
                "title": item.title,
                "source_platform": item.source_platform,
                "source_url": item.source_url,
                "local_media_path": item.local_media_path,
                "provenance": item.provenance,
                "risk_flags": item.risk_flags,
                "route_match": item.route_match,
                "transcript_ready": item.transcript_ready,
                "campaign_rules_ready": item.campaign_rules_ready,
                "eligible": item.eligible,
                "blockers": item.blockers,
            }
            for item in candidate_report
        ],
        "eligible_non_demo_candidates": [
            {
                "clip_id": item.clip_id,
                "title": item.title,
                "source_url": item.source_url,
                "local_media_path": item.local_media_path,
            }
            for item in eligible
            if item.provenance.lower() != "local-demo"
        ],
        "decision": {
            "can_render_non_demo": any(item.provenance.lower() != "local-demo" for item in eligible),
            "reason": (
                "At least one non-demo candidate has source URL, provenance, selected-feeder route, stored rules, transcript, and local media."
                if any(item.provenance.lower() != "local-demo" for item in eligible)
                else "No non-demo candidate currently has the full evidence package. Production kit rendering remains blocked."
            ),
        },
    }


def markdown_report(report: Dict[str, Any]) -> str:
    lines = [
        "# Review Kit Audit",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Decision",
        f"- Non-demo rendering allowed: `{report['decision']['can_render_non_demo']}`",
        f"- Reason: {report['decision']['reason']}",
        "",
        "## Campaign Gate",
        f"- Status: `{report['campaign_gate']['status']}`",
        f"- Visible campaigns: {report['campaign_gate']['visible_campaign_count']}",
        f"- Selected feeders: {report['campaign_gate']['selected_feeder_count']}",
        f"- Blocker: {report['campaign_gate']['blocker'] or 'none'}",
        "",
        "## Latest Review Kits",
    ]
    for kit in report["latest_review_kits"]:
        blocker_text = f"; blockers: {', '.join(kit['blockers'])}" if kit["blockers"] else ""
        lines.append(
            f"- `{kit['severity']}` {kit['title']} ({kit['review_status']})"
            f" [{kit['id']}] -> {kit['validation_detail']}{blocker_text}"
        )
    lines.extend(["", "## Candidate Audit"])
    for candidate in report["clip_candidates"]:
        blocker_text = ", ".join(candidate["blockers"]) if candidate["blockers"] else "none"
        lines.append(
            f"- `{ 'eligible' if candidate['eligible'] else 'blocked' }` {candidate['title']} [{candidate['clip_id']}]"
            f" provenance={candidate['provenance']} local_media={'yes' if candidate['local_media_path'] else 'no'}"
            f" transcript={'yes' if candidate['transcript_ready'] else 'no'} rules={'yes' if candidate['campaign_rules_ready'] else 'no'}"
            f"; blockers: {blocker_text}"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    report = build_report()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = OUT_DIR / "latest.json"
    md_path = OUT_DIR / "latest.md"
    write_text(json_path, json.dumps(report, indent=2) + "\n")
    write_text(md_path, markdown_report(report))
    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, indent=2))


if __name__ == "__main__":
    main()
