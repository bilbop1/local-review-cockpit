#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend import platforms


OUT_DIR = ROOT / "artifacts" / "research-run"
LATEST_JSON = OUT_DIR / "campaign-streamer-reindex.json"
LATEST_MD = OUT_DIR / "campaign-streamer-reindex.md"


CANDIDATES: list[dict[str, str]] = [
    {
        "slug": "yourrage",
        "name": "YourRAGE",
        "detail": "detail-08-yourrage.json",
        "handle": "yourragegaming",
        "brief": "",
        "why": "native streamer/react content, no stored requirements, 200K minimum",
    },
    {
        "slug": "plaqueboymax",
        "name": "PlaqueBoyMax",
        "detail": "detail-09-plaqueboymax.json",
        "handle": "plaqueboymax",
        "brief": "requirements-docs/plaqueboymax-14vQvB96.txt",
        "why": "high-velocity creator lane; watermark requirement but otherwise loose",
    },
    {
        "slug": "doublelift",
        "name": "Doublelift",
        "detail": "detail-11-doublelift.json",
        "handle": "doublelift",
        "brief": "requirements-docs/doublelift-1XNZxiDR.txt",
        "why": "gaming clips with 100K minimum; strong if budget/deadline refreshes",
    },
    {
        "slug": "jasontheween",
        "name": "JasonTheWeen",
        "detail": "detail-15-jasontheween.json",
        "handle": "jasontheween",
        "brief": "requirements-docs/jasontheween-1-PiU5Lk.txt",
        "why": "excellent social-native streamer supply; stored deadline is risky",
    },
    {
        "slug": "lacy",
        "name": "Lacy",
        "detail": "detail-03-lacy.json",
        "handle": "lacy",
        "brief": "requirements-docs/lacy-1gHf_Ae3-current.txt",
        "why": "strong creator supply, but brief is narrowly arrest/MIA constrained",
    },
    {
        "slug": "full-squad-gaming",
        "name": "Full Squad Gaming",
        "detail": "detail-31-full-squad-gaming.json",
        "handle": "fullsquadgaming",
        "brief": "",
        "why": "long-run low-minimum gaming backup, but no proven daily streamer source",
    },
    {
        "slug": "sketch",
        "name": "Sketch",
        "detail": "detail-34-sketch.json",
        "handle": "sketch",
        "brief": "requirements-docs/sketch-1rsxwXWh.txt",
        "why": "streamer content exists, but stored Clipping.net evidence says paused",
    },
    {
        "slug": "ohnepixel-clippers",
        "name": "ohnePixel clippers",
        "detail": "detail-33-ohnepixel-clippers.json",
        "handle": "ohnepixel",
        "brief": "",
        "why": "CS2 streamer supply is huge, but stored Clipping.net evidence says paused",
    },
]


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def parse_int(text: Any) -> int:
    match = re.search(r"(\d[\d,]*)", str(text or ""))
    return int(match.group(1).replace(",", "")) if match else 0


def min_views_from(card: dict[str, Any]) -> int:
    text = str(card.get("minViews") or card.get("text") or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([kKmM]?)\s+views", text)
    if not match:
        return parse_int(text)
    value = float(match.group(1))
    suffix = match.group(2).lower()
    if suffix == "m":
        value *= 1_000_000
    elif suffix == "k":
        value *= 1_000
    return int(value)


def days_left_from(card: dict[str, Any]) -> int | None:
    text = str(card.get("daysLeft") or "")
    if "0 days" in text.lower():
        return 0
    value = parse_int(text)
    return value if value else None


def captured_at(detail: dict[str, Any]) -> datetime | None:
    raw = str(detail.get("capturedAt") or "")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def estimated_days_left(detail: dict[str, Any]) -> int | None:
    card = detail.get("card") or {}
    captured_days = days_left_from(card)
    captured = captured_at(detail)
    if captured_days is None or captured is None:
        return None
    elapsed = max(0, (datetime.now(timezone.utc) - captured).days)
    return captured_days - elapsed


def brief_shape(text: str, slug: str) -> dict[str, Any]:
    lowered = text.lower()
    if not lowered and slug in {"yourrage", "full-squad-gaming"}:
        return {"kind": "none_or_inline", "penalty": 0, "notes": "Stored Clipping.net detail showed Requirements: None."}
    blockers: list[str] = []
    bonus = 0
    penalty = 0
    if "arrested or being missing in action" in lowered:
        penalty += 35
        blockers.append("narrow arrest/MIA requirement makes normal daily clips invalid")
    if "must use the watermark" in lowered or "must strictly feature" in lowered:
        penalty += 5
        blockers.append("watermark/strict source requirement")
    if "caption requirements:\n* none" in lowered or "caption requirements:\r\n* none" in lowered:
        bonus += 6
    if "preferred: big brain plays, funny moments" in lowered:
        bonus += 10
    if "provided content" in lowered and "twitch.tv" not in lowered:
        penalty += 12
        blockers.append("provided-content wording without a streamer source")
    return {
        "kind": "streamer_brief" if "twitch.tv" in lowered else "stored_brief",
        "bonus": bonus,
        "penalty": penalty,
        "notes": "; ".join(blockers) or "brief is compatible with streamer clipping",
    }


def twitch_supply(handle: str) -> dict[str, Any]:
    if not handle:
        return {"status": "not_applicable", "clips_returned": 0, "top_clip_views": 0, "top_clip": ""}
    users = platforms.twitch_get("users", {"login": handle})
    data = users.get("data", {}).get("data", []) if users.get("status") == "succeeded" else []
    if not data:
        return {"status": users.get("status", "blocked"), "clips_returned": 0, "top_clip_views": 0, "top_clip": "", "detail": users.get("detail", "")}
    broadcaster_id = str(data[0].get("id", ""))
    started_at = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(timespec="seconds").replace("+00:00", "Z")
    clips = platforms.twitch_get("clips", {"broadcaster_id": broadcaster_id, "first": 20, "started_at": started_at})
    clip_rows = clips.get("data", {}).get("data", []) if clips.get("status") == "succeeded" else []
    top = max(clip_rows, key=lambda item: int(item.get("view_count", 0) or 0), default={})
    return {
        "status": clips.get("status", "blocked"),
        "user_status": users.get("status"),
        "display_name": data[0].get("display_name", handle),
        "partner": data[0].get("broadcaster_type", ""),
        "clips_returned": len(clip_rows),
        "top_clip_views": int(top.get("view_count", 0) or 0),
        "top_clip": str(top.get("url", "")),
        "top_clip_title": str(top.get("title", "")),
        "lookback_days": 30,
        "check_ids": [users.get("check_id", ""), clips.get("check_id", "")],
    }


def score_candidate(spec: dict[str, str], detail: dict[str, Any], brief: dict[str, Any], supply: dict[str, Any]) -> dict[str, Any]:
    card = detail.get("card") or {}
    status_text = str(card.get("status", "")).lower()
    min_views = min_views_from(card)
    days_est = estimated_days_left(detail)
    top_views = int(supply.get("top_clip_views", 0) or 0)
    clips_returned = int(supply.get("clips_returned", 0) or 0)
    score = 0
    reasons: list[str] = []
    blockers: list[str] = []

    if spec.get("handle"):
        score += 25
        reasons.append("streamer-native source")
    if clips_returned >= 15:
        score += 20
        reasons.append("15+ recent clips returned")
    elif clips_returned >= 5:
        score += 14
        reasons.append("recent clips returned")
    elif clips_returned:
        score += 7
        reasons.append("limited recent clips returned")
    else:
        score -= 28
        blockers.append("no recent public Twitch clips returned")

    if top_views >= 500_000:
        score += 18
        reasons.append("top recent clip over 500K")
    elif top_views >= 300_000:
        score += 14
        reasons.append("top recent clip over 300K")
    elif top_views >= 100_000:
        score += 8
        reasons.append("top recent clip over 100K")

    if min_views and min_views <= 100_000:
        score += 12
        reasons.append("low 100K qualification bar")
    elif min_views and min_views <= 200_000:
        score += 9
        reasons.append("manageable 200K qualification bar")
    elif min_views and min_views <= 300_000:
        score += 5
        reasons.append("moderate 300K qualification bar")
    elif min_views >= 500_000:
        blockers.append("500K qualification bar")

    if brief.get("kind") == "none_or_inline":
        score += 12
        reasons.append("no narrow brief constraints")
    score += int(brief.get("bonus", 0) or 0)
    score -= int(brief.get("penalty", 0) or 0)
    if brief.get("penalty"):
        blockers.append(str(brief.get("notes", "")))

    if "paused" in status_text or "cycle ended" in str(detail.get("text", "")).lower():
        score -= 35
        blockers.append("stored Clipping.net evidence says paused/cycle-ended")
    elif days_est is None:
        score -= 4
        blockers.append("fresh Clipping.net status not confirmed")
    elif days_est < 0:
        score -= 25
        blockers.append(f"stored deadline implies expired {-days_est} day(s) ago")
    elif days_est <= 2:
        score += 2
        blockers.append(f"stored deadline implies only {days_est} day(s) left")
    else:
        score += 12
        reasons.append(f"stored deadline implies {days_est} day(s) left")

    if "budget\n99%" in str(detail.get("text", "")).lower() or "budget 99%" in str(card.get("text", "")).lower():
        score -= 18
        blockers.append("stored detail showed budget 99% filled")

    if spec["slug"] in {"kalshi", "dunkman", "haste"}:
        score -= 50
        blockers.append("not a streamer-native daily clip lane")

    if score >= 60 and clips_returned and not any("expired" in item or "paused" in item or "no recent public Twitch clips" in item for item in blockers):
        recommendation = "promote_now"
    elif score >= 40:
        recommendation = "watchlist_or_confirm_freshness"
    else:
        recommendation = "do_not_build_now"

    return {
        "slug": spec["slug"],
        "name": spec["name"],
        "campaign_url": (detail.get("card") or {}).get("href") or db.CAMPAIGN_PROJECTS.get(spec["slug"], {}).get("campaign_url", ""),
        "twitch_handle": spec.get("handle", ""),
        "score": score,
        "recommendation": recommendation,
        "why": spec["why"],
        "reasons": reasons,
        "blockers": [item for item in blockers if item],
        "stored_status": card.get("status", ""),
        "stored_days_left": card.get("daysLeft", ""),
        "estimated_days_left_today": days_est,
        "min_views": min_views,
        "brief": brief,
        "twitch_supply": supply,
    }


def write_markdown(payload: dict[str, Any], path: Path) -> None:
    lines = [
        "# Streamer-First Campaign Re-Index",
        "",
        f"Generated: {payload['generated_at']}",
        "",
        "This ranking deliberately favors daily streamer clip supply, loose briefs, and clips a viewer might actually choose to watch. Source-clean but low-virality campaigns are archived from the active review target set.",
        "",
        "## Ranked Targets",
        "",
    ]
    for index, item in enumerate(payload["ranked"], 1):
        blockers = "; ".join(item["blockers"]) or "none"
        reasons = "; ".join(item["reasons"]) or "no positive reasons recorded"
        lines.extend(
            [
                f"### {index}. [{item['name']}]({item['campaign_url']})",
                "",
                f"- Recommendation: `{item['recommendation']}`",
                f"- Score: `{item['score']}`",
                f"- Twitch: `{item['twitch_handle']}`; recent clips returned: `{item['twitch_supply'].get('clips_returned', 0)}`; top recent views: `{item['twitch_supply'].get('top_clip_views', 0)}`",
                f"- Stored status: `{item['stored_status']}`; stored days left: `{item['stored_days_left']}`; estimated days left today: `{item['estimated_days_left_today']}`",
                f"- Min views: `{item['min_views']}`",
                f"- Why it fits: {item['why']}",
                f"- Positive signals: {reasons}",
                f"- Blockers: {blockers}",
                "",
            ]
        )
    lines.extend(
        [
            "## Active Registry Result",
            "",
            "The code active review target set is now streamer-first:",
            "",
            *[f"- `{slug}`" for slug in payload["active_project_slugs"]],
            "",
            "Kalshi and Dunkman remain archived renderer/source-proof lanes. Haste remains excluded because content generation without linked source media is out of scope.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    db.init_db()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ranked: list[dict[str, Any]] = []
    for spec in CANDIDATES:
        detail = read_json(OUT_DIR / spec["detail"])
        brief_text = read_text(OUT_DIR / spec["brief"]) if spec.get("brief") else ""
        brief = brief_shape(brief_text, spec["slug"])
        supply = twitch_supply(spec.get("handle", ""))
        ranked.append(score_candidate(spec, detail, brief, supply))
    ranked.sort(key=lambda item: item["score"], reverse=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "basis": "stored signed-in Clipping.net evidence plus live Twitch Helix 30-day clip supply; fresh Clipping.net dashboard browser confirmation is still required when stored deadline risk is present",
        "active_project_slugs": db.active_campaign_project_slugs(),
        "ranked": ranked,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dated_json = OUT_DIR / f"campaign-streamer-reindex-{stamp}.json"
    dated_md = OUT_DIR / f"campaign-streamer-reindex-{stamp}.md"
    for path in (LATEST_JSON, dated_json):
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    for path in (LATEST_MD, dated_md):
        write_markdown(payload, path)
    db.create_campaign_evidence(
        {
            "campaign_id": "campaign-streamer-reindex",
            "evidence_type": "campaign_reindex",
            "title": "Streamer-first campaign re-index",
            "source_url": str(LATEST_MD),
            "extracted_text": json.dumps({"ranked": ranked[:8], "active_project_slugs": payload["active_project_slugs"]})[:6000],
            "confidence": 0.85,
            "notes": payload["basis"],
        }
    )
    db.log_audit("codex", "reindex_campaigns_for_streamer_supply", "campaign_reindex", "streamer-first", "succeeded", str(LATEST_MD))
    print(LATEST_JSON)
    print(LATEST_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
