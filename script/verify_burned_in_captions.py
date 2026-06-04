#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.caption_style import (
    CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS,
    CAPTION_SAFE_BAND_BOTTOM_Y,
    CAPTION_SAFE_BAND_TOP_Y,
    caption_display_window_seconds,
    caption_text_quality_violations,
)

OUT_DIR = ROOT / "artifacts" / "review-kit-audit" / "burned-caption-frames"
SUMMARY_PATH = ROOT / "artifacts" / "review-kit-audit" / "burned-caption-verification.json"


def run(command: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=90)


def parse_caption_times(caption_path: Path) -> List[Tuple[float, float, str]]:
    rows: List[Tuple[float, float, str]] = []
    for line in caption_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^-\s+([0-9.]+)-([0-9.]+):\s*(.+)$", line.strip())
        if not match:
            continue
        start = float(match.group(1))
        end = float(match.group(2))
        text = match.group(3).strip()
        if end > start and text:
            rows.append((start, end, text))
    return rows


def caption_timing_violations(beats: List[Tuple[float, float, str]]) -> List[str]:
    violations: List[str] = []
    previous_start = -1.0
    previous_end = -1.0
    for index, (start, end, text) in enumerate(beats, start=1):
        duration = end - start
        if duration < 0.12:
            violations.append(f"caption {index} is too short ({duration:.2f}s): {text}")
        max_duration = caption_display_window_seconds(text) + 0.08
        if duration > max_duration:
            violations.append(f"caption {index} stays on screen too long ({duration:.2f}s > {max_duration:.2f}s): {text}")
        if previous_start >= 0 and start < previous_start - 0.01:
            violations.append(f"caption {index} starts before the previous caption start: {start:.2f}s < {previous_start:.2f}s")
        if previous_end >= 0 and start < previous_end - 0.05:
            violations.append(f"caption {index} overlaps the previous caption: {start:.2f}s < {previous_end:.2f}s")
        previous_start = start
        previous_end = end
    return violations


def caption_manifest_timing_violations(kit_dir: Path) -> List[str]:
    manifest_path = kit_dir / "render_text_manifest.json"
    if not manifest_path.exists():
        return ["render_text_manifest.json missing for caption lead audit"]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"render_text_manifest.json unreadable for caption lead audit: {exc}"]
    rendered = payload.get("rendered_text", {})
    timeline = rendered.get("caption_timeline", []) if isinstance(rendered, dict) else []
    if not isinstance(timeline, list) or not timeline:
        return ["render_text_manifest.json has no caption timeline for lead audit"]
    violations: List[str] = []
    approved_anchor_sources = {
        "faster_whisper_distil_medium_en",
        "faster_whisper_medium_en",
        "mister_whisper_large_v3_turbo",
    }
    for index, item in enumerate(timeline, start=1):
        if not isinstance(item, dict):
            violations.append(f"caption timeline item {index} is not an object")
            continue
        try:
            start = float(item.get("start", 0) or 0)
            end = float(item.get("end", 0) or 0)
            source_end = float(item.get("source_end", item.get("end", 0)) or 0)
            sync_delay = float(item.get("audio_sync_delay_seconds", 0) or 0)
            lead = float(item.get("lead_seconds", max(0.0, source_end + sync_delay - start)) or 0)
            max_lead = float(item.get("max_pre_audio_lead_seconds", CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS) or CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS)
        except (TypeError, ValueError):
            violations.append(f"caption timeline item {index} has invalid timing fields")
            continue
        timing_mode = str(item.get("timing_mode", "")).strip().lower()
        if timing_mode == "ensemble_consensus":
            model_votes = int(item.get("model_votes", 0) or 0)
            vote_spread = float(item.get("vote_spread_seconds", 0) or 0)
            if model_votes < 3:
                violations.append(f"caption {index} has too few ensemble timing votes ({model_votes})")
            if vote_spread > 0.85:
                text = str(item.get("text", "")).strip()
                violations.append(f"caption {index} ensemble timing spread is too wide ({vote_spread:.2f}s): {text}")
            if end <= start:
                violations.append(f"caption {index} ensemble timing has invalid window ({start:.2f}-{end:.2f})")
            continue
        if timing_mode == "strong_model_anchor":
            text = str(item.get("text", "")).strip()
            anchor_source = str(item.get("anchor_source", "")).strip()
            model_votes = int(item.get("model_votes", 0) or 0)
            vote_spread = float(item.get("vote_spread_seconds", 0) or 0)
            duration = end - start
            max_duration = caption_display_window_seconds(text) + 0.08
            weak_anchor = anchor_source not in approved_anchor_sources and not (model_votes >= 2 and vote_spread <= 0.35)
            if weak_anchor:
                violations.append(f"caption {index} uses weak anchor source {anchor_source!r}: {text}")
            if model_votes < 2:
                violations.append(f"caption {index} has too few strong-anchor votes ({model_votes}): {text}")
            if vote_spread > 0.35:
                violations.append(f"caption {index} strong-anchor spread is too wide ({vote_spread:.2f}s): {text}")
            if end <= start:
                violations.append(f"caption {index} strong anchor timing has invalid window ({start:.2f}-{end:.2f}): {text}")
            if duration > max_duration:
                violations.append(
                    f"caption {index} strong anchor stays on screen too long ({duration:.2f}s > {max_duration:.2f}s): {text}"
                )
            continue
        calculated_lead = max(0.0, source_end + sync_delay - start)
        allowed = min(max_lead, CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS) + 0.015
        if lead > allowed or calculated_lead > allowed:
            text = str(item.get("text", "")).strip()
            violations.append(
                f"caption {index} starts too early ({max(lead, calculated_lead):.2f}s lead > {allowed:.2f}s): {text}"
            )
    return violations


def overlay_pixel_match_ratio(frame_path: Path, overlay_path: Path) -> float:
    frame = Image.open(frame_path).convert("RGB")
    overlay = Image.open(overlay_path).convert("RGBA")
    hits = 0
    visible_pixels = 0
    frame_pixels = frame.load()
    overlay_pixels = overlay.load()
    width, height = overlay.size
    for y in range(height):
        for x in range(width):
            r, g, b, a = overlay_pixels[x, y]
            if a < 210:
                continue
            if max(r, g, b) < 8 and a < 250:
                continue
            visible_pixels += 1
            fr, fg, fb = frame_pixels[x, y]
            if abs(fr - r) <= 95 and abs(fg - g) <= 95 and abs(fb - b) <= 95:
                hits += 1
    if visible_pixels == 0:
        return 0.0
    return hits / visible_pixels


def caption_overlay_bounds(overlay_path: Path) -> Dict[str, Any]:
    overlay = Image.open(overlay_path).convert("RGBA")
    alpha = overlay.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return {
            "ok": False,
            "reason": "caption overlay has no visible pixels",
            "safe_band_top_y": CAPTION_SAFE_BAND_TOP_Y,
            "safe_band_bottom_y": CAPTION_SAFE_BAND_BOTTOM_Y,
        }
    left, top, right, bottom = bbox
    ok = top >= CAPTION_SAFE_BAND_TOP_Y and bottom <= CAPTION_SAFE_BAND_BOTTOM_Y
    return {
        "ok": ok,
        "bbox": [left, top, right, bottom],
        "safe_band_top_y": CAPTION_SAFE_BAND_TOP_Y,
        "safe_band_bottom_y": CAPTION_SAFE_BAND_BOTTOM_Y,
        "reason": "" if ok else f"caption overlay bbox y={top}-{bottom} is outside safe band {CAPTION_SAFE_BAND_TOP_Y}-{CAPTION_SAFE_BAND_BOTTOM_Y}",
    }


def top_hook_check(kit_dir: Path, video: Path) -> Dict[str, Any]:
    manifest_path = kit_dir / "render_text_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"required": True, "ok": False, "reason": f"render_text_manifest.json unreadable for top hook audit: {exc}"}
    rendered = payload.get("rendered_text", {})
    layout = str(rendered.get("layout", "") if isinstance(rendered, dict) else "").strip().lower()
    profile = str(payload.get("profile", "")).strip()
    required = profile == db.CAMPAIGN_SHORT_PROFILE or layout == "summary_hook_caption"
    if not required:
        return {"required": False, "ok": True}
    if not isinstance(rendered, dict):
        return {"required": True, "ok": False, "reason": "rendered_text is not an object"}
    hook = str(rendered.get("hook_card", "")).strip()
    if not hook or rendered.get("hook_card_visible") is not True:
        return {"required": True, "ok": False, "reason": "campaign render has no visible top summary hook"}
    title_card = kit_dir / "title_card.png"
    if not title_card.exists():
        return {"required": True, "ok": False, "reason": "title_card.png missing"}
    alpha = Image.open(title_card).convert("RGBA").getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return {"required": True, "ok": False, "reason": "title_card.png has no visible pixels"}
    left, top, right, bottom = bbox
    if top < 70 or bottom > 330:
        return {
            "required": True,
            "ok": False,
            "reason": f"top hook bbox y={top}-{bottom} is outside upper safe hook band 70-330",
            "bbox": [left, top, right, bottom],
        }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    frame = OUT_DIR / f"{kit_dir.name}-top-hook.jpg"
    result = run([
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-ss",
        "1.00",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-update",
        "1",
        str(frame),
    ])
    if result.returncode != 0 or not frame.exists():
        return {"required": True, "ok": False, "reason": result.stderr[-500:] or "top hook frame extraction failed"}
    ratio = overlay_pixel_match_ratio(frame, title_card)
    return {
        "required": True,
        "ok": ratio >= 0.20,
        "hook": hook,
        "overlay_pixel_match_ratio": round(ratio, 3),
        "bbox": [left, top, right, bottom],
        "frame": str(frame),
        "overlay": str(title_card),
    }


def verify_kit(row: Dict[str, Any]) -> Dict[str, Any]:
    kit_dir = Path(str(row["review_video_path"])).parent
    video = kit_dir / "review.mp4"
    caption_path = kit_dir / "caption.txt"
    beats = parse_caption_times(caption_path)
    timing_violations = caption_timing_violations(beats) + caption_manifest_timing_violations(kit_dir)
    text_violations = caption_text_quality_violations(text for _, _, text in beats)
    checks = []
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for index, (start, end, text) in enumerate(beats[:6], start=1):
        overlay = kit_dir / f"caption_{index}.png"
        frame = OUT_DIR / f"{kit_dir.name}-caption-{index}.jpg"
        midpoint = (start + end) / 2
        if not overlay.exists():
            checks.append({"index": index, "ok": False, "text": text, "reason": "missing caption overlay png"})
            continue
        bounds = caption_overlay_bounds(overlay)
        result = run([
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-ss",
            f"{midpoint:.2f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-update",
            "1",
            str(frame),
        ])
        if result.returncode != 0 or not frame.exists():
            checks.append({"index": index, "ok": False, "text": text, "reason": result.stderr[-500:] or "frame extraction failed"})
            continue
        ratio = overlay_pixel_match_ratio(frame, overlay)
        checks.append({
            "index": index,
            "ok": ratio >= 0.28 and bool(bounds.get("ok")),
            "text": text,
            "midpoint": round(midpoint, 2),
            "overlay_pixel_match_ratio": round(ratio, 3),
            "safe_band_bounds": bounds,
            "frame": str(frame),
            "overlay": str(overlay),
        })
    ok_count = sum(1 for item in checks if item.get("ok"))
    required = min(3, len(checks))
    hook_check = top_hook_check(kit_dir, video)
    return {
        "kit_id": row.get("id", ""),
        "title": row.get("title", ""),
        "review_video_path": str(video),
        "caption_count": len(beats),
        "timing_violations": timing_violations,
        "text_violations": text_violations,
        "checked_caption_frames": len(checks),
        "ok_caption_frames": ok_count,
        "top_hook_check": hook_check,
        "ok": bool(required and ok_count >= required and hook_check.get("ok") and not timing_violations and not text_violations),
        "checks": checks,
    }


def main() -> None:
    db.init_db()
    kits = [kit for kit in db.visible_render_kits() if str(kit.get("review_status", "")) != "rejected_revision_requested"]
    results = [verify_kit(dict(row)) for row in kits]
    payload = {
        "ok": bool(results) and all(item["ok"] for item in results),
        "kit_count": len(results),
        "scope": "active_non_rejected_review_kits",
        "results": results,
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(SUMMARY_PATH)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
