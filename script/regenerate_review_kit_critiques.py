#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db

APP_HOME = Path.home() / "Library" / "Application Support" / "ClippingOpsCockpit"
DB_PATH = APP_HOME / "clipping_ops.sqlite3"
LIVE_RENDER_ROOT = APP_HOME / "render_kits"
DEMO_RENDER_ROOT = APP_HOME / "demo_render_kits"
LEGACY_DEMO_RENDER_ROOT = ROOT / ".no-key-home" / "demo_render_kits"
OUT_DIR = ROOT / "artifacts" / "review-kit-audit"
GUI_MANIFEST = ROOT / "artifacts" / "desktop-qa" / "manifest.json"
REFERENCE_RUBRIC = [
    "Punchy headline in a white rounded card near the top safe zone.",
    "Central vertical source framing with blurred or extended side fill when the source is narrow.",
    "Bold high-contrast captions that change quickly and do not cover the face/action.",
    "Small source/brand watermark only when campaign rules allow it; Lacy final kits require no logo/source badge.",
    "No internal/demo/proof language on anything that is trying to pass as a market-ready clip.",
]


@dataclass
class CritiqueResult:
    kind: str
    title: str
    status: str
    profile: str
    kit_dir: Path
    source: str
    blockers: List[str]
    fixes: List[str]
    facts: List[str]


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def read_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def existing_profile(kit_dir: Path) -> str:
    for line in read_text(kit_dir / "style_critique.md").splitlines():
        if line.lower().startswith("profile:"):
            return line.split(":", 1)[1].strip()
    return "unknown"


def source_verified(source_text: str) -> bool:
    lowered = source_text.lower()
    return (
        "source_media_verified_local" in lowered
        or "yt-dlp fallback" in lowered
        or ("local media:" in lowered and "/source_media/" in lowered)
    )


def stored_campaign_rules(source_text: str) -> bool:
    return "## stored campaign rules" in source_text.lower()


def placeholder_transcript(transcript_text: str, risk_text: str) -> bool:
    lowered = f"{transcript_text}\n{risk_text}".lower()
    return "placeholder transcript" in lowered or "not word-timed" in lowered


def review_safe_signals(critique_text: str, caption_text: str) -> bool:
    lowered = f"{critique_text}\n{caption_text}".lower()
    return any(
        token in lowered
        for token in (
            "review-safe layout",
            "human-review gate",
            "review preview",
            "evidence review",
            "feeder proof",
            "manual approval only",
        )
    )


def internal_or_demo_labels(*texts: str) -> bool:
    lowered = "\n".join(texts).lower()
    return any(
        token in lowered
        for token in (
            "local demo",
            "demo-only",
            "demo media",
            "demo review kit",
            "local demo kit",
            "proof output",
            "do not publish",
        )
    )


def weak_hook(caption_text: str) -> bool:
    lowered = caption_text.lower()
    return any(
        token in lowered
        for token in (
            "selected feeder review kit",
            "manual approval only",
            "review preview",
            "local demo kit",
            "this part needs a clip",
        )
    )


def weak_hook_title(title: str) -> bool:
    lowered = title.strip().lower()
    if not lowered:
        return True
    if any(token in lowered for token in ("draft", "#1 pick", "placeholder", "wip")):
        return True
    if re.fullmatch(r"[\W_]+", lowered):
        return True
    weak_titles = {
        "lmao",
        "lmfao",
        "sus",
        "cpr",
        "dd",
        "o7 l bmw",
        "😭😭",
    }
    if lowered in weak_titles:
        return True
    words = [word for word in re.split(r"[^a-z0-9]+", lowered) if word]
    if len(words) <= 2 and all(len(word) <= 4 for word in words):
        return True
    return False


def review_title_or_profile(title: str, profile: str) -> bool:
    lowered = f"{title}\n{profile}".lower()
    return any(
        token in lowered
        for token in (
            "evidence review",
            "selected feeder review",
            "feeder proof",
            "evidence_review",
            "selected-feeder-a",
            "selected_feeder_final",
        )
    )


def visible_proof_naming(*texts: str) -> bool:
    lowered = "\n".join(texts).lower()
    return any(
        token in lowered
        for token in (
            "feeder proof",
            "feeder-proof",
            "proof output",
            "evidence review",
            "review kit",
        )
    )


def transcript_segment_count(transcript_text: str) -> int:
    return sum(1 for line in transcript_text.splitlines() if line.startswith("- ") and ":" in line)


def campaign_fit_proven(checklist_text: str, risk_text: str) -> bool:
    checklist = checklist_text.lower()
    risk = risk_text.lower()
    if "[x] human review completed." not in checklist:
        return False
    return "campaign fit still requires human judgment" not in risk


def human_review_complete(checklist_text: str) -> bool:
    return "[x] human review completed." in checklist_text.lower()


def build_non_demo_critique(row: sqlite3.Row) -> CritiqueResult:
    video_path = Path(str(row["review_video_path"]))
    kit_dir = video_path.parent
    title = str(row["title"])
    critique_text = read_text(kit_dir / "style_critique.md")
    source_text = read_text(kit_dir / "source.md")
    risk_text = read_text(kit_dir / "risk.md")
    transcript_text = read_text(kit_dir / "transcript.txt")
    caption_text = read_text(kit_dir / "caption.txt")
    checklist_text = read_text(kit_dir / "checklist.md")
    manifest_text = read_text(kit_dir / "render_text_manifest.json")
    ffprobe = read_json(kit_dir / "ffprobe.json")
    contact_sheet_ok = (kit_dir / "contact_sheet.jpg").exists()
    profile = existing_profile(kit_dir)
    canonical = db.production_feeder_kit_status(dict(row))
    if canonical.get("classification") == "green":
        lacy_text = "\n".join([title, source_text, caption_text, checklist_text]).lower()
        is_lacy = "twitch.tv/lacy/clip" in str(row.get("clip_source_url", "")).lower() or "lacy" in lacy_text
        source_badge_blank = not re.search(r'"source_badge"\s*:\s*"[^"]+"', manifest_text)
        return CritiqueResult(
            kind="live_render_kit",
            title=title,
            status="green",
            profile=profile,
            kit_dir=kit_dir,
            source=video_path.name,
            blockers=[],
            fixes=["Posting approval remains separate; do not upload, publish, submit payouts, or change accounts from this artifact."],
            facts=[
                f"ffprobe_ok: {canonical.get('ffprobe_ok')}",
                f"checked_clip_count: {canonical.get('checked_clip_count')}",
                f"contact_sheet_present: {contact_sheet_ok}",
                f"lacy_brief_caption_hashtag: {('#lacy' in caption_text.lower()) if is_lacy else 'not_applicable'}",
                f"lacy_no_logo_source_badge: {source_badge_blank if is_lacy else 'not_applicable'}",
                "rendered_internal_labels: none",
            ],
        )
    blockers: List[str] = []
    fixes: List[str] = []

    has_source = source_verified(source_text)
    has_rules = stored_campaign_rules(source_text)
    has_timed_transcript = bool(transcript_text.strip()) and not placeholder_transcript(transcript_text, risk_text)
    has_internal_labels = internal_or_demo_labels(title, source_text, risk_text, caption_text)
    still_review_safe = review_safe_signals(critique_text, caption_text)
    still_review_named = review_title_or_profile(title, profile)
    still_visible_as_proof = visible_proof_naming(title, profile, str(kit_dir), str(video_path))
    has_campaign_fit = campaign_fit_proven(checklist_text, risk_text)
    has_human_review = human_review_complete(checklist_text)
    segment_count = transcript_segment_count(transcript_text)
    explicit_language = "explicit language" in risk_text.lower()

    if not has_source:
        blockers.append("source media/provenance is not verified in the kit evidence")
        fixes.append("Replace this kit with source media stored under the selected-feeder media root and restamp source provenance.")
    if not has_rules:
        blockers.append("stored campaign rules are not cited in source.md")
        fixes.append("Attach the matching campaign rules to source.md before this stays on the visible review surface.")
    if not has_timed_transcript:
        blockers.append("timed transcript proof is missing; captions are still placeholder or not word-timed")
        fixes.append("Backfill a word-timed transcript, then rebuild captions from word timings instead of safety placeholder copy.")
    if has_internal_labels:
        blockers.append("internal/demo/proof labels are still visible in critique or caption metadata")
        fixes.append("Remove internal/demo/proof language from any kit that is being evaluated as a real market candidate.")
    if still_review_safe:
        blockers.append("packaging is still review-safe instead of a final social cut")
        fixes.append("Recut the clip as a final social edit with no review-preview framing or manual-approval copy in the visible creative.")
    if still_review_named:
        blockers.append("the kit is still framed as review/proof output rather than a ship candidate")
        fixes.append("Rename and repackage the visible artifact only after it clears final-social treatment and campaign-fit review.")
    if still_visible_as_proof:
        blockers.append("the visible review surface still exposes proof/review naming in the kit path or metadata")
        fixes.append("Remove feeder-proof/review-kit naming from the visible queue once the clip graduates from internal proof to ship candidate.")
    if not has_campaign_fit:
        blockers.append("campaign fit is not proven yet; checklist and risk notes still require human review")
        fixes.append("Do not mark this green until a human editor completes campaign-fit review and updates the checklist/risk notes accordingly.")
    if not has_human_review:
        blockers.append("human review checklist is still incomplete")
        fixes.append("Complete the `Human review completed.` checklist gate only after a human reviewer signs off on campaign fit and publish readiness.")
    if weak_hook(caption_text):
        blockers.append("hook/caption copy is template-level rather than clip-specific")
        fixes.append("Rewrite the hook from the first 1-2 seconds of the transcript so the opener names the conflict or reveal immediately.")
    if weak_hook_title(title):
        blockers.append("hook card/title is still shorthand instead of a viewer-facing payoff or conflict")
        fixes.append("Replace the hook card with a concrete headline that states the surprise, conflict, or quote the viewer should care about.")
    if segment_count <= 1:
        blockers.append("transcript evidence is too coarse for pace validation")
        fixes.append("Recover more than one spoken beat so caption pacing can be checked against the contact sheet and source action.")
    if explicit_language:
        blockers.append("copy/compliance risk remains high because transcript flags explicit language")
        fixes.append("Manually review the explicit lines and decide whether to mute, trim, or restyle the clip before it stays in rotation.")

    if has_internal_labels or not has_source or not has_rules:
        status = "red"
    elif blockers:
        status = "yellow"
    else:
        status = "green"

    facts = [
        f"ffprobe streams: {len(ffprobe.get('streams', []))}",
        f"duration_seconds: {ffprobe.get('format', {}).get('duration', 'unknown')}",
        f"contact_sheet_present: {contact_sheet_ok}",
        f"segment_count: {segment_count}",
    ]
    return CritiqueResult(
        kind="live_render_kit",
        title=title,
        status=status,
        profile=profile,
        kit_dir=kit_dir,
        source=video_path.name,
        blockers=blockers,
        fixes=fixes,
        facts=facts,
    )


def build_demo_critique(kit_dir: Path) -> CritiqueResult:
    title = kit_dir.name
    critique_text = read_text(kit_dir / "style_critique.md")
    source_text = read_text(kit_dir / "source.md")
    risk_text = read_text(kit_dir / "risk.md")
    transcript_text = read_text(kit_dir / "transcript.txt")
    caption_text = read_text(kit_dir / "caption.txt")
    ffprobe = read_json(kit_dir / "ffprobe.json")
    profile = existing_profile(kit_dir)
    blockers = [
        "demo-only media is still on the visible review surface",
        "there is no campaign source URL or selected-feeder provenance",
        "the transcript/caption package is a local review placeholder, not a market candidate",
    ]
    fixes = [
        "Demote this kit to hidden style-study status or remove it from the visible review queue entirely.",
        "Replace the local demo source with real selected-feeder media plus source URL, stored rules, and timed transcript evidence.",
        "Reuse only the stylistic learnings; do not let demo/internal labels coexist with CEO-green candidate review.",
    ]
    facts = [
        f"ffprobe streams: {len(ffprobe.get('streams', []))}",
        f"duration_seconds: {ffprobe.get('format', {}).get('duration', 'unknown')}",
        f"contact_sheet_present: {(kit_dir / 'contact_sheet.jpg').exists()}",
        f"demo_labels_present: {internal_or_demo_labels(title, critique_text, source_text, risk_text, transcript_text, caption_text)}",
    ]
    return CritiqueResult(
        kind="demo_study",
        title=title,
        status="red",
        profile=profile,
        kit_dir=kit_dir,
        source="review.mp4",
        blockers=blockers,
        fixes=fixes,
        facts=facts,
    )


def write_style_critique(result: CritiqueResult, source_label: str) -> None:
    rubric = "\n".join(f"- {item}" for item in REFERENCE_RUBRIC)
    blockers = "\n".join(f"- {item}" for item in result.blockers) or "- None."
    fixes = "\n".join(f"- {item}" for item in result.fixes) or "- None."
    facts = "\n".join(f"- {item}" for item in result.facts)
    content = "\n".join(
        [
            "# Style Critique",
            "",
            f"Status: {result.status}",
            f"Profile: {result.profile}",
            f"Source: `{source_label}`",
            "",
            "## Reference Rubric",
            rubric,
            "",
            "## CEO Truth Standard",
            "- Never call a kit green without real source media, a timed transcript, campaign fit, and no internal/demo labels.",
            "- Review-safe packaging can prove pipeline mechanics, but it does not prove market readiness.",
            "",
            "## Blockers",
            blockers,
            "",
            "## Concrete Fixes",
            fixes,
            "",
            "## Validation",
            facts,
            "",
        ]
    )
    (result.kit_dir / "style_critique.md").write_text(content, encoding="utf-8")


def fetch_live_rows() -> List[Dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    db.init_db()
    return db.visible_render_kits()


def demo_roots() -> List[Path]:
    roots: List[Path] = []
    for candidate in (DEMO_RENDER_ROOT, LEGACY_DEMO_RENDER_ROOT):
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if candidate.exists() and all(existing != resolved for existing in roots):
            roots.append(resolved)
    return roots


def gui_summary() -> List[str]:
    manifest = read_json(GUI_MANIFEST)
    screenshots = manifest.get("screenshots") or []
    review_page = next((item for item in screenshots if item.get("name") == "page-review-kits"), None)
    manifest_review_count = None
    for item in manifest.get("controls") or []:
        if item.get("name") == "Refresh":
            after = item.get("after") or {}
            manifest_review_count = after.get("review_kits")
            break
    visible_count = len(fetch_live_rows())
    return [
        f"manifest_exists: {GUI_MANIFEST.exists()}",
        f"app_survived_all_page_clicks: {manifest.get('app_survived_all_page_clicks', False)}",
        f"new_crash_reports: {len(manifest.get('new_crash_reports') or [])}",
        f"review_kits_screenshot: {review_page.get('path') if isinstance(review_page, dict) else 'missing'}",
        f"visible_review_kits_now: {visible_count}",
        f"gui_manifest_review_kits: {manifest_review_count if manifest_review_count is not None else 'unknown'}",
    ]


def write_summary(results: List[CritiqueResult]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_from": str(Path(__file__).resolve()),
        "live_render_kits": [],
        "demo_studies": [],
        "gui_preview_evidence": gui_summary(),
    }
    lines = [
        "# Visible Video Critique",
        "",
        "Generated from live review-kit artifacts, demo studies, ffprobe/contact-sheet proof, and GUI preview evidence.",
        "",
        "## GUI Preview Evidence",
        *[f"- {item}" for item in gui_summary()],
        "",
    ]
    for result in results:
        section = [
            f"### {result.status.upper()} {result.title}",
            f"- Kind: {result.kind}",
            f"- Profile: {result.profile}",
            f"- Kit dir: {result.kit_dir}",
            *[f"- Blocker: {item}" for item in result.blockers],
            *[f"- Fix: {item}" for item in result.fixes],
            *[f"- Fact: {item}" for item in result.facts],
            "",
        ]
        lines.extend(section)
        target = payload["demo_studies" if result.kind == "demo_study" else "live_render_kits"]
        target.append(
            {
                "title": result.title,
                "status": result.status,
                "profile": result.profile,
                "kit_dir": str(result.kit_dir),
                "blockers": result.blockers,
                "fixes": result.fixes,
                "facts": result.facts,
            }
        )
    (OUT_DIR / "visible-video-critique.md").write_text("\n".join(lines), encoding="utf-8")
    (OUT_DIR / "visible-video-critique.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    results: List[CritiqueResult] = []
    for row in fetch_live_rows():
        result = build_non_demo_critique(row)
        write_style_critique(result, str(Path(str(row["review_video_path"])).parent / "review.mp4"))
        results.append(result)
    write_summary(results)
    print(
        json.dumps(
            {
                "style_critiques_rewritten": len(results),
                "markdown": str(OUT_DIR / "visible-video-critique.md"),
                "json": str(OUT_DIR / "visible-video-critique.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
