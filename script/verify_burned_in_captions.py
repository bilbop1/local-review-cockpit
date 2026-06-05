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
    DEFAULT_CAMPAIGN_CAPTION_VARIANT,
    PRODUCTION_CAPTION_VARIANTS,
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
    title_image = Image.open(title_card).convert("RGBA")
    alpha = title_image.getchannel("A")
    alpha_pixels = alpha.load()
    solid_points: List[tuple[int, int]] = []
    for y in range(title_image.height):
        for x in range(title_image.width):
            if alpha_pixels[x, y] >= 80:
                solid_points.append((x, y))
    bbox = None
    if solid_points:
        xs = [point[0] for point in solid_points]
        ys = [point[1] for point in solid_points]
        bbox = (min(xs), min(ys), max(xs) + 1, max(ys) + 1)
    if not bbox:
        return {"required": True, "ok": False, "reason": "title_card.png has no visible pixels"}
    left, top, right, bottom = bbox
    width = right - left
    height = bottom - top
    center_x = (left + right) / 2
    if abs(center_x - 541.5) > 8 or top < 330 or top > 342 or height < 138 or height > 166 or width < 795 or width > 895:
        return {
            "required": True,
            "ok": False,
            "reason": (
                f"top hook bbox {left},{top},{right},{bottom} does not match reference band "
                "centered at x 540, y=336, reference-like width 795-895, height 138-166 with shadow"
            ),
            "bbox": [left, top, right, bottom],
            "width": width,
            "height": height,
        }
    pixels = title_image.load()
    text_xs: List[int] = []
    text_ys: List[int] = []
    for y in range(top + 4, bottom - 4):
        for x in range(left + 4, right - 4):
            r, g, b, a = pixels[x, y]
            if a < 180:
                continue
            if r > 245 and g > 245 and b > 245:
                continue
            is_dark_text = max(r, g, b) < 112 and max(r, g, b) - min(r, g, b) < 72
            is_color_emoji = max(r, g, b) >= 120 and max(r, g, b) - min(r, g, b) >= 50
            if not (is_dark_text or is_color_emoji):
                continue
            text_xs.append(x)
            text_ys.append(y)
    if not text_xs:
        return {"required": True, "ok": False, "reason": "top hook card has no measurable text pixels", "bbox": [left, top, right, bottom]}
    text_left = min(text_xs)
    text_right = max(text_xs) + 1
    text_top = min(text_ys)
    text_bottom = max(text_ys) + 1
    left_pad = text_left - left
    right_pad = right - text_right
    top_pad = text_top - top
    bottom_pad = bottom - text_bottom
    content_height = text_bottom - text_top
    if left_pad < 32 or left_pad > 40 or right_pad < 30:
        return {
            "required": True,
            "ok": False,
            "reason": (
                f"top hook card padding left={left_pad}, right={right_pad} does not match reference-width card spacing"
            ),
            "bbox": [left, top, right, bottom],
            "text_bbox": [text_left, min(text_ys), text_right, max(text_ys) + 1],
            "left_pad": left_pad,
            "right_pad": right_pad,
        }
    if top_pad < 16 or top_pad > 24 or bottom_pad < 12 or bottom_pad > 32 or content_height < 96 or content_height > 134:
        return {
            "required": True,
            "ok": False,
            "reason": (
                f"top hook card vertical balance top={top_pad}, bottom={bottom_pad}, content_height={content_height} "
                "does not match the reference-style filled card typography"
            ),
            "bbox": [left, top, right, bottom],
            "text_bbox": [text_left, text_top, text_right, text_bottom],
            "top_pad": top_pad,
            "bottom_pad": bottom_pad,
            "content_height": content_height,
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
        "text_bbox": [text_left, text_top, text_right, text_bottom],
        "left_pad": left_pad,
        "right_pad": right_pad,
        "top_pad": top_pad,
        "bottom_pad": bottom_pad,
        "content_height": content_height,
        "frame": str(frame),
        "overlay": str(title_card),
    }


def reference_layout_check(kit_dir: Path) -> Dict[str, Any]:
    manifest_path = kit_dir / "render_text_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"required": True, "ok": False, "reason": f"render_text_manifest.json unreadable for layout audit: {exc}"}
    rendered = payload.get("rendered_text", {})
    layout = str(rendered.get("layout", "") if isinstance(rendered, dict) else "").strip().lower()
    profile = str(payload.get("profile", "")).strip()
    required = profile == db.CAMPAIGN_SHORT_PROFILE or layout == "summary_hook_caption"
    if not required:
        return {"required": False, "ok": True}
    composition = rendered.get("composition", {}) if isinstance(rendered, dict) else {}
    if not isinstance(composition, dict):
        return {"required": True, "ok": False, "reason": "rendered_text.composition is not an object"}
    frame = composition.get("foreground_frame", {})
    expected = {"x": 0, "y": 513, "width": 1080, "height": 607}
    if composition.get("layout_style") != "tiktok_reference_stacked" or frame != expected:
        return {
            "required": True,
            "ok": False,
            "reason": "campaign render is not using the TikTok reference stacked foreground/blur layout",
            "layout_style": composition.get("layout_style", ""),
            "foreground_frame": frame,
            "expected_foreground_frame": expected,
        }
    return {"required": True, "ok": True, "layout_style": "tiktok_reference_stacked", "foreground_frame": frame}


def reference_watermark_check(kit_dir: Path) -> Dict[str, Any]:
    manifest_path = kit_dir / "render_text_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"required": True, "ok": False, "reason": f"render_text_manifest.json unreadable for watermark audit: {exc}"}
    rendered = payload.get("rendered_text", {})
    layout = str(rendered.get("layout", "") if isinstance(rendered, dict) else "").strip().lower()
    profile = str(payload.get("profile", "")).strip()
    required = profile == db.CAMPAIGN_SHORT_PROFILE or layout == "summary_hook_caption"
    if not required:
        return {"required": False, "ok": True}
    visible_candidates = []
    reference_watermark = rendered.get("reference_watermark", {}) if isinstance(rendered, dict) else {}
    if isinstance(reference_watermark, dict) and reference_watermark.get("visible"):
        visible_candidates.append(("reference", reference_watermark, kit_dir / "reference_handle_watermark.png"))
    campaign_watermark = rendered.get("campaign_watermark", {}) if isinstance(rendered, dict) else {}
    if isinstance(campaign_watermark, dict) and rendered.get("watermark_visible") is True:
        visible_candidates.append(("campaign", campaign_watermark, Path(str(campaign_watermark.get("overlay_path", ""))) if campaign_watermark.get("overlay_path") else kit_dir / "campaign_watermark.png"))
    if not visible_candidates:
        return {"required": True, "ok": False, "reason": "lower reference-style identity watermark is missing from manifest"}
    if len(visible_candidates) > 1:
        return {
            "required": True,
            "ok": False,
            "reason": "campaign render has duplicate identity watermarks; reference requires one lower blurred-section handle",
            "watermarks": [name for name, _, _ in visible_candidates],
        }
    kind, watermark, overlay = visible_candidates[0]
    if str(watermark.get("position", "")) not in {"bottom_blur_center", ""}:
        return {
            "required": True,
            "ok": False,
            "reason": f"identity watermark position {watermark.get('position', '')!r} is not the lower reference band",
            "watermark": watermark,
        }
    if kind == "reference" and not str(watermark.get("text", "")).strip():
        return {"required": True, "ok": False, "reason": "reference handle watermark text is missing"}
    if kind == "campaign" and not str(watermark.get("asset_path", "")).strip():
        return {"required": True, "ok": False, "reason": "required campaign watermark asset path is missing"}
    if not overlay.exists():
        return {"required": True, "ok": False, "reason": f"{overlay.name} missing"}
    alpha = Image.open(overlay).convert("RGBA").getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return {"required": True, "ok": False, "reason": f"{overlay.name} has no visible pixels"}
    left, top, right, bottom = bbox
    if top < 1230 or top > 1325 or bottom < 1280 or bottom > 1415:
        return {
            "required": True,
            "ok": False,
            "reason": f"identity watermark bbox {left},{top},{right},{bottom} is outside lower blur band",
            "bbox": [left, top, right, bottom],
        }
    return {
        "required": True,
        "ok": True,
        "kind": kind,
        "text": watermark.get("text", ""),
        "asset_path": watermark.get("asset_path", ""),
        "bbox": [left, top, right, bottom],
    }


def campaign_caption_variant_check(kit_dir: Path) -> Dict[str, Any]:
    manifest_path = kit_dir / "render_text_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"required": True, "ok": False, "reason": f"render_text_manifest.json unreadable for caption variant audit: {exc}"}
    rendered = payload.get("rendered_text", {})
    layout = str(rendered.get("layout", "") if isinstance(rendered, dict) else "").strip().lower()
    profile = str(payload.get("profile", "")).strip()
    required = profile == db.CAMPAIGN_SHORT_PROFILE or layout == "summary_hook_caption"
    if not required:
        return {"required": False, "ok": True}
    style = rendered.get("caption_style", {}) if isinstance(rendered, dict) else {}
    variant = str(style.get("ab_variant", "") if isinstance(style, dict) else "").strip().upper()
    allowed_variants = [str(item).upper() for item in PRODUCTION_CAPTION_VARIANTS]
    ok = variant in allowed_variants
    return {
        "required": True,
        "ok": ok,
        "variant": variant,
        "default_variant": DEFAULT_CAMPAIGN_CAPTION_VARIANT,
        "allowed_variants": allowed_variants,
        "reason": "" if ok else f"campaign final uses caption variant {variant!r}; expected one of {allowed_variants!r}",
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
    layout_check = reference_layout_check(kit_dir)
    watermark_check = reference_watermark_check(kit_dir)
    variant_check = campaign_caption_variant_check(kit_dir)
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
        "reference_layout_check": layout_check,
        "reference_watermark_check": watermark_check,
        "campaign_caption_variant_check": variant_check,
        "ok": bool(
            required
            and ok_count >= required
            and hook_check.get("ok")
            and layout_check.get("ok")
            and watermark_check.get("ok")
            and variant_check.get("ok")
            and not timing_violations
            and not text_violations
        ),
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
