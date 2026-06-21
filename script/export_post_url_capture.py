#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from clipping_ops_backend import database as db  # noqa: E402
from clipping_ops_backend import publishing  # noqa: E402


CAPTURE_PLATFORMS = ("tiktok", "instagram", "youtube", "facebook", "x")


def parse_urls(raw: Any) -> Dict[str, str]:
    try:
        payload = json.loads(str(raw or "{}"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return {str(key).lower(): str(value) for key, value in payload.items() if str(value).strip()}


def platform_url(urls: Dict[str, str], platform: str) -> str:
    return urls.get(platform) or (urls.get("default") if platform == "tiktok" else "") or ""


def markdown_cell(value: Any) -> str:
    text = str(value or "").replace("\n", " ").replace("|", "\\|").strip()
    return text


def rows_for_window(window_start: datetime, window_end: datetime) -> List[Dict[str, Any]]:
    start = window_start.isoformat(timespec="seconds")
    end = window_end.isoformat(timespec="seconds")
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT
              p.id,
              p.mode,
              p.status,
              p.stage,
              p.platforms_json,
              p.title,
              p.scheduled_at,
              p.posted_at,
              p.post_urls_json,
              r.campaign_slug
            FROM publish_jobs p
            JOIN render_kits r ON r.id = p.kit_id
            WHERE r.campaign_slug != ''
              AND p.status NOT IN ('cancelled','failed')
              AND (
                (p.posted_at != '' AND p.posted_at >= ? AND p.posted_at < ?)
                OR (p.posted_at = '' AND p.scheduled_at != '' AND p.scheduled_at >= ? AND p.scheduled_at < ?)
              )
            ORDER BY COALESCE(NULLIF(p.posted_at, ''), NULLIF(p.scheduled_at, ''), p.created_at) ASC
            """,
            (start, end, start, end),
        ).fetchall()
    return [dict(row) for row in rows]


def build_markdown(window_days: float) -> str:
    db.init_db()
    generated_at = datetime.now().astimezone().replace(microsecond=0)
    window_start = generated_at
    window_end = generated_at + timedelta(days=window_days)
    rows = rows_for_window(window_start, window_end)
    by_campaign: Dict[str, List[Dict[str, Any]]] = {slug: [] for slug in db.active_campaign_project_slugs()}
    for row in rows:
        slug = db.normalize_campaign_slug(row.get("campaign_slug"))
        if slug:
            by_campaign.setdefault(slug, []).append(row)

    status = publishing.publish_status()
    lines = [
        "# Campaign Post URL Capture",
        "",
        f"Generated: {generated_at.isoformat(timespec='seconds')}",
        f"Window: {window_start.isoformat(timespec='seconds')} to {window_end.isoformat(timespec='seconds')}",
        f"Posting now: {', '.join(status.get('default_platforms', ['tiktok']))}",
        f"Runway: {status.get('runway', {}).get('scheduled_count', 0)} queued clips, about {status.get('runway', {}).get('estimated_days', 0)} days at {status.get('runway', {}).get('slots_per_day', 8)}/day",
        "",
        "Paste public post URLs into the blank cells after posting. TikTok rows fill automatically when Upload-Post returns a URL; Instagram, YouTube, Facebook, and X are manual capture rows until those accounts are enabled.",
        "",
    ]
    for slug in db.active_campaign_project_slugs():
        project = db.CAMPAIGN_PROJECTS[slug]
        campaign_rows = by_campaign.get(slug, [])
        lines.extend(
            [
                f"## {project['name']}",
                "",
                f"Campaign: {project.get('campaign_url', '')}",
                "",
                "| Scheduled/Posted | Status | Job | Title | TikTok URL | Instagram URL | YouTube URL | Facebook URL | X URL | Notes |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in campaign_rows:
            urls = parse_urls(row.get("post_urls_json"))
            lines.append(
                "| "
                + " | ".join(
                    [
                        markdown_cell(row.get("posted_at") or row.get("scheduled_at")),
                        markdown_cell(row.get("status")),
                        markdown_cell(row.get("id")),
                        markdown_cell(row.get("title")),
                        markdown_cell(platform_url(urls, "tiktok")),
                        "",
                        "",
                        "",
                        "",
                        "",
                    ]
                )
                + " |"
            )
        if not campaign_rows:
            lines.append("|  | manual |  |  |  |  |  |  |  |  |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a campaign-by-campaign Markdown sheet for public post URLs.")
    parser.add_argument("--window-days", type=float, default=4.0, help="Capture window in days from now. Default: 4.0")
    parser.add_argument("--output", type=Path, default=None, help="Markdown output path.")
    args = parser.parse_args()
    output = args.output
    if output is None:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d")
        output = ROOT / "artifacts" / "post-url-capture" / f"campaign-post-urls-{stamp}.md"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_markdown(max(0.5, args.window_days)), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
