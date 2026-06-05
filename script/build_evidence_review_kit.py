#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from PIL import Image, ImageDraw, ImageFont, ImageStat

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.caption_style import (
    CAPTION_AUDIO_SYNC_DELAY_SECONDS,
    CAPTION_FONT_SIZE,
    CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS,
    CAPTION_MAX_WORDS_PER_LINE,
    CAPTION_TARGET_MAX_LINE_CHARS,
    CAPTION_MAX_CENTER_Y,
    DEFAULT_CAMPAIGN_CAPTION_VARIANT,
    FONT_DIR,
    apply_caption_audio_sync_delay,
    caption_variant_for_key,
    caption_center_y_for_source,
    caption_display_window_seconds,
    caption_display_text,
    caption_font,
    caption_lines,
    caption_start_for_group,
    caption_style_manifest,
    caption_text_quality_violations,
    clean_timed_words_for_caption,
    normalize_caption_variant,
    timed_caption_groups,
)
from clipping_ops_backend.renderer import extract_contact_sheet, extract_thumbnail, validate_video, write_json


APP_HOME = db.app_support_dir()
DOWNLOAD_ROOT = APP_HOME / "source_media"
KIT_ROOT = db.render_root()
YT_DLP = ROOT / "backend" / ".venv" / "bin" / "yt-dlp"
INTERNAL_RENDER_TEXT_TOKENS = (
    "selected feeder",
    "feeder proof",
    "evidence review",
    "review kit",
    "human review",
    "manual review",
    "local demo",
    "demo only",
    "proof",
)
NATIVE_STREAM_FORMAT = "best[format_id!*=portrait][height>=720]/best[format_id!*=portrait]/best"


@dataclass
class Candidate:
    clip: Dict[str, Any]
    route: Dict[str, Any]
    rules: List[Dict[str, Any]]


def run(command: Sequence[str], timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def source_dimensions(media_path: Path) -> tuple[float, float]:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(media_path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return (0.0, 0.0)
    try:
        streams = json.loads(result.stdout or "{}").get("streams", [])
        stream = streams[0] if streams else {}
        return (float(stream.get("width", 0) or 0), float(stream.get("height", 0) or 0))
    except Exception:
        return (0.0, 0.0)


def source_duration(media_path: Path) -> float:
    result = run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(media_path),
        ],
        timeout=30,
    )
    if result.returncode != 0:
        return 0.0
    try:
        return float((result.stdout or "0").strip() or 0)
    except ValueError:
        return 0.0


def is_twitch_clip_url(value: Any) -> bool:
    lowered = str(value or "").lower()
    return "twitch.tv/" in lowered and "/clip/" in lowered


def is_mobile_portrait_source(media_path: Path) -> bool:
    width, height = source_dimensions(media_path)
    return width > 0 and height > 0 and height > width and width <= 720


def font(size: int):
    return caption_font(size)


def top_hook_font(size: int) -> ImageFont.ImageFont:
    for candidate in [
        FONT_DIR / "TikTokSans36pt-ExtraBold.ttf",
        FONT_DIR / "TikTokSans36pt-Black.ttf",
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ]:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    return font(size)


def top_hook_card_font(size: int) -> ImageFont.ImageFont:
    candidates: List[tuple[Path, str | None, int | None]] = [
        (FONT_DIR / "TikTokSans36pt-Bold.ttf", None, None),
        (FONT_DIR / "TikTokSans36pt-SemiBold.ttf", None, None),
        (Path("/System/Library/Fonts/Avenir Next.ttc"), None, 2),
        (Path("/System/Library/Fonts/SFNS.ttf"), "Semibold", None),
        (FONT_DIR / "TikTokSans36pt-ExtraBold.ttf", None, None),
        (FONT_DIR / "TikTokSans36pt-Black.ttf", None, None),
        (Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"), None, None),
        (Path("/System/Library/Fonts/Supplemental/Arial.ttf"), None, None),
    ]
    for candidate, variation_name, collection_index in candidates:
        if candidate.exists():
            try:
                kwargs = {"index": collection_index} if collection_index is not None else {}
                loaded = ImageFont.truetype(str(candidate), size=size, **kwargs)
                if variation_name:
                    loaded.set_variation_by_name(variation_name)
                return loaded
            except OSError:
                continue
    return top_hook_font(size)


def top_hook_emoji_font(size: int) -> ImageFont.ImageFont | None:
    candidate = Path("/System/Library/Fonts/Apple Color Emoji.ttc")
    if not candidate.exists():
        return None
    supported_sizes = (20, 26, 32, 40, 48, 52, 64, 96)
    nearest = min(supported_sizes, key=lambda item: abs(item - size))
    try:
        return ImageFont.truetype(str(candidate), size=nearest)
    except OSError:
        return None


def text_size(draw: ImageDraw.ImageDraw, text: str, style_font: ImageFont.ImageFont, stroke_width: int = 0) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=style_font, stroke_width=stroke_width)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def text_bbox(draw: ImageDraw.ImageDraw, text: str, style_font: ImageFont.ImageFont, stroke_width: int = 0) -> tuple[int, int, int, int]:
    return draw.textbbox((0, 0), text, font=style_font, stroke_width=stroke_width)


def draw_text_visual_top(
    draw: ImageDraw.ImageDraw,
    text: str,
    left: int,
    top: int,
    style_font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    stroke_fill: tuple[int, int, int, int] | None = None,
    stroke_width: int = 0,
) -> None:
    bbox = text_bbox(draw, text, style_font, stroke_width=stroke_width)
    kwargs: Dict[str, Any] = {"font": style_font, "fill": fill}
    if stroke_fill is not None and stroke_width:
        kwargs.update({"stroke_width": stroke_width, "stroke_fill": stroke_fill})
    draw.text((left - bbox[0], top - bbox[1]), text, **kwargs)


def is_emoji_char(char: str) -> bool:
    code = ord(char)
    return (
        0x1F000 <= code <= 0x1FAFF
        or 0x2600 <= code <= 0x27BF
        or code in {0xFE0F, 0x200D}
    )


def mixed_text_runs(text: str) -> List[tuple[bool, str]]:
    runs: List[tuple[bool, str]] = []
    current = ""
    current_is_emoji: bool | None = None
    for char in str(text):
        char_is_emoji = is_emoji_char(char)
        if current and char_is_emoji != current_is_emoji:
            runs.append((bool(current_is_emoji), current))
            current = char
        else:
            current += char
        current_is_emoji = char_is_emoji
    if current:
        runs.append((bool(current_is_emoji), current))
    return runs


def mixed_text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    style_font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
) -> tuple[int, int]:
    width = 0
    height = 0
    for is_emoji, run_text in mixed_text_runs(text):
        run_font = emoji_font if is_emoji and emoji_font is not None else style_font
        bbox = draw.textbbox((0, 0), run_text, font=run_font)
        width += bbox[2] - bbox[0]
        height = max(height, bbox[3] - bbox[1])
    return width, height


def draw_mixed_text_visual_top(
    draw: ImageDraw.ImageDraw,
    text: str,
    left: int,
    top: int,
    style_font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
    fill: tuple[int, int, int, int],
) -> None:
    x = left
    emoji_y_offset = -5
    for is_emoji, run_text in mixed_text_runs(text):
        run_font = emoji_font if is_emoji and emoji_font is not None else style_font
        bbox = draw.textbbox((0, 0), run_text, font=run_font)
        if is_emoji and emoji_font is not None:
            emoji_top = top + emoji_y_offset
            try:
                draw.text((x - bbox[0], emoji_top - bbox[1]), run_text, font=run_font, embedded_color=True)
            except TypeError:
                draw.text((x - bbox[0], emoji_top - bbox[1]), run_text, font=run_font, fill=fill)
        else:
            draw.text((x - bbox[0], top - bbox[1]), run_text, font=run_font, fill=fill)
        x += bbox[2] - bbox[0]


def stretch_visible_overlay_y(image: Image.Image, scale_y: float) -> Image.Image:
    if scale_y == 1.0:
        return image
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return image
    left, top, right, bottom = bbox
    cropped = image.crop((left, top, right, bottom))
    new_height = max(1, int(round((bottom - top) * scale_y)))
    stretched = cropped.resize((right - left, new_height), Image.Resampling.BICUBIC)
    output = Image.new("RGBA", image.size, (0, 0, 0, 0))
    output.paste(stretched, (left, top), stretched)
    return output


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def route_candidates(campaign_slug: str = "") -> List[Dict[str, Any]]:
    if campaign_slug:
        return db.rows(
            """
            SELECT *
            FROM source_routes
            WHERE route_type IN ('official_api','authenticated_route','manual_import')
              AND risk_flags_json LIKE ?
            ORDER BY
              CASE availability_status WHEN 'verified' THEN 0 WHEN 'reachable' THEN 1 ELSE 2 END,
              updated_at DESC
            """,
            (f"%campaign_project_{campaign_slug}%",),
        )
    return db.rows(
        """
        SELECT *
        FROM source_routes
        WHERE availability_status IN ('verified','reachable')
          AND route_type IN ('official_api','authenticated_route','manual_import')
          AND risk_flags_json LIKE '%selected_feeder_%'
        ORDER BY updated_at DESC
        """
    )


def rules_by_slug() -> Dict[str, List[Dict[str, Any]]]:
    items = db.rows(
        """
        SELECT campaign_id, title, source_url, extracted_text, notes, captured_at
        FROM campaign_evidence
        WHERE evidence_type='campaign_rules'
        ORDER BY captured_at DESC
        """
    )
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(str(item["campaign_id"]).lower(), []).append(item)
    return grouped


def match_route(clip: Dict[str, Any], routes: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    source_url = str(clip.get("source_url", "")).lower()
    clip_flags = {str(flag).lower() for flag in clip.get("risk_flags", [])}
    for route in routes:
        handle = str(route.get("creator_handle", "")).lower()
        route_flags = {str(flag).lower() for flag in route.get("risk_flags", [])}
        if handle and handle in source_url:
            return route
        if clip_flags & route_flags:
            return route
    return None


def resolve_rules(clip: Dict[str, Any], route: Dict[str, Any], grouped_rules: Dict[str, List[Dict[str, Any]]], campaign_slug: str = "") -> List[Dict[str, Any]]:
    slugs: List[str] = []
    if campaign_slug:
        slugs.append(campaign_slug)
    direct_slug = db.campaign_slug_for_clip(clip)
    if direct_slug:
        slugs.append(direct_slug)
    source_url = str(clip.get("source_url", "")).lower()
    for slug in grouped_rules:
        if slug and slug in source_url:
            slugs.append(slug)
    handle = str(route.get("creator_handle", "")).strip().lower()
    if handle:
        slugs.append(handle)
    for flag in list(route.get("risk_flags", [])) + list(clip.get("risk_flags", [])):
        text = str(flag).lower()
        if text.startswith("selected_feeder_"):
            slugs.append(text.removeprefix("selected_feeder_"))
    for slug in slugs:
        if slug in grouped_rules:
            return grouped_rules[slug]
    return []


def pick_candidate(clip_id: str = "", campaign_slug: str = "") -> Candidate:
    if campaign_slug:
        clips = db.campaign_clips(campaign_slug)
    else:
        clips = db.rows("SELECT * FROM clip_candidates ORDER BY view_count DESC, discovered_at DESC")
    routes = route_candidates(campaign_slug)
    grouped = rules_by_slug()

    shortlisted: List[Candidate] = []
    editorial_rejections: List[str] = []
    for clip in clips:
        if clip_id and str(clip["id"]) != clip_id:
            continue
        provenance = str(clip.get("provenance", "")).strip().lower()
        if provenance == "local-demo":
            continue
        if not str(clip.get("source_url", "")).strip():
            continue
        route = match_route(clip, routes)
        if campaign_slug and not route:
            route = {
                "id": f"campaign-route-{campaign_slug}",
                "platform": str(clip.get("source_platform", "")),
                "creator_handle": campaign_slug,
                "source_url": str(clip.get("source_url", "")),
                "route_type": "manual_import",
                "availability_status": "indexed",
                "risk_flags": [f"campaign_project_{campaign_slug}"],
            }
        if not route:
            continue
        rules = resolve_rules(clip, route, grouped, campaign_slug)
        if not rules:
            continue
        gate = db.editorial_candidate_gate(clip, campaign_slug)
        if gate.get("status") != "green" and os.environ.get("CLIPPING_OPS_ALLOW_WEAK_EDITORIAL_PICK", "").strip().lower() not in {"1", "true", "yes"}:
            editorial_rejections.append(f"{clip.get('id', '')}: {'; '.join(str(item) for item in gate.get('blockers', [])[:3])}")
            continue
        shortlisted.append(Candidate(clip=clip, route=route, rules=rules))

    if not shortlisted:
        if campaign_slug:
            detail = "; ".join(editorial_rejections[:5])
            raise RuntimeError(f"No {campaign_slug} clip candidate has stored source, rules, and a green editorial gate." + (f" Rejected: {detail}" if detail else ""))
        detail = "; ".join(editorial_rejections[:5])
        raise RuntimeError("No non-demo clip candidate has stored source, route, rules, and a green editorial gate." + (f" Rejected: {detail}" if detail else ""))

    return shortlisted[0]


def media_path_for(clip_id: str, source_url: str) -> Path:
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    return DOWNLOAD_ROOT / f"{clip_id}.mp4"


def promote_valid_partial_download(output: Path) -> bool:
    partial = Path(f"{output}.part")
    if not partial.exists() or partial.stat().st_size < 500_000:
        return False
    if not validate_source_media(partial):
        return False
    if output.exists():
        output.unlink()
    shutil.move(str(partial), str(output))
    return output.exists()


def validate_source_media(path: Path) -> bool:
    if not path.exists() or path.stat().st_size < 500_000:
        return False
    try:
        probe = run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"], timeout=120)
    except subprocess.TimeoutExpired:
        return False
    return probe.returncode == 0 and not probe.stderr.strip()


def direct_download_with_curl(source_url: str, output: Path) -> bool:
    if not YT_DLP.exists():
        return False
    try:
        resolved = run([str(YT_DLP), "-f", "720/best", "-g", source_url], timeout=45)
    except subprocess.TimeoutExpired:
        return False
    if resolved.returncode != 0:
        return False
    direct_url = next((line.strip() for line in resolved.stdout.splitlines() if line.strip().startswith("http")), "")
    if not direct_url:
        return False
    temp = Path(f"{output}.download")
    if temp.exists():
        temp.unlink()
    try:
        curl = run(
            [
                "curl",
                "-L",
                "--fail",
                "--retry",
                "3",
                "--connect-timeout",
                "20",
                "--max-time",
                "240",
                "-o",
                str(temp),
                direct_url,
            ],
            timeout=270,
        )
    except subprocess.TimeoutExpired:
        if temp.exists():
            temp.unlink()
        return False
    if curl.returncode != 0 or not validate_source_media(temp):
        if temp.exists():
            temp.unlink()
        return False
    if output.exists():
        output.unlink()
    shutil.move(str(temp), str(output))
    return True


def ensure_local_media(candidate: Candidate) -> Path:
    clip = candidate.clip
    existing = Path(str(clip.get("local_media_path", "")).strip()) if str(clip.get("local_media_path", "")).strip() else None
    needs_native_stream = is_twitch_clip_url(clip.get("source_url", ""))
    if existing and validate_source_media(existing):
        if not (needs_native_stream and is_mobile_portrait_source(existing)):
            return existing
    if existing and existing.exists():
        existing.unlink()
    if not YT_DLP.exists():
        raise RuntimeError(f"yt-dlp is missing at {YT_DLP}")

    download_timeout = int(float(os.environ.get("CLIPPING_OPS_YTDLP_TIMEOUT", "210") or 210))
    output = media_path_for(str(clip["id"]), str(clip["source_url"]))
    clip_start = float(clip.get("clip_start_seconds", 0) or 0)
    clip_end = float(clip.get("clip_end_seconds", 0) or 0)
    has_time_slice = clip_end > clip_start >= 0
    if not has_time_slice and direct_download_with_curl(str(clip["source_url"]), output):
        db.update_clip_media(
            str(clip["id"]),
            output,
            "yt_dlp_direct_url",
            [str(flag) for flag in clip.get("risk_flags", [])] + ["local_media_downloaded", "source_media_verified_local"],
        )
        clip["local_media_path"] = str(output)
        return output

    command = [
        str(YT_DLP),
        "--no-warnings",
        "--no-progress",
        "--force-overwrites",
        "--continue",
        "--concurrent-fragments",
        "8",
        "--retries",
        "3",
        "--fragment-retries",
        "3",
        "--socket-timeout",
        "30",
        "-f",
        os.environ.get("CLIPPING_OPS_YTDLP_FORMAT", NATIVE_STREAM_FORMAT),
        "--merge-output-format",
        "mp4",
        "--remux-video",
        "mp4",
    ]
    if has_time_slice:
        command.extend(["--download-sections", f"*{clip_start:.2f}-{clip_end:.2f}", "--force-keyframes-at-cuts"])
        if output.exists():
            output.unlink()
        for stale in [
            Path(f"{output}.part"),
            Path(f"{output}.webm"),
            Path(f"{output}.webm.part"),
            Path(f"{output}.download"),
        ]:
            if stale.exists():
                stale.unlink()
    command.extend(["-o", str(output), str(clip["source_url"])])
    try:
        result = run(command, timeout=download_timeout)
    except subprocess.TimeoutExpired as exc:
        if not promote_valid_partial_download(output):
            raise RuntimeError(f"yt-dlp timed out before producing a valid source media file: {exc}") from exc
        result = subprocess.CompletedProcess(command, 0, "", "promoted valid partial download after timeout")
    if (result.returncode != 0 or not output.exists()) and not promote_valid_partial_download(output):
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "yt-dlp download failed")

    risk_flags = [str(flag) for flag in clip.get("risk_flags", []) if str(flag) != "metadata_only_no_download"]
    for extra in ["local_media_downloaded", "source_media_verified_local"]:
        if extra not in risk_flags:
            risk_flags.append(extra)
    db.execute(
        """
        UPDATE clip_candidates
        SET local_media_path=?, risk_flags_json=?, discovered_at=?
        WHERE id=?
        """,
        (str(output), json.dumps(risk_flags), db.utc_now(), str(clip["id"])),
    )
    clip["local_media_path"] = str(output)
    clip["risk_flags"] = risk_flags
    return output


def transcript_for_clip(clip_id: str) -> Dict[str, Any] | None:
    return db.one(
        """
        SELECT *
        FROM transcripts
        WHERE clip_candidate_id = ?
          AND status = 'succeeded'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (clip_id,),
    )


def word_timings_from(transcript: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not transcript:
        return []
    raw = transcript.get("word_timings")
    if not isinstance(raw, list):
        try:
            raw = json.loads(str(transcript.get("word_timings_json", "[]")))
        except json.JSONDecodeError:
            raw = []
    timings = [item for item in raw if isinstance(item, dict) and str(item.get("word", "")).strip()]
    if timings:
        return timings
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        try:
            segments = json.loads(str(transcript.get("segments_json", "[]")))
        except json.JSONDecodeError:
            segments = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        for word in segment.get("words") or []:
            if isinstance(word, dict) and str(word.get("word", "")).strip():
                timings.append(
                    {
                        "word": str(word.get("word", "")).strip(),
                        "start": round(float(word.get("start", segment.get("start", 0)) or 0), 2),
                        "end": round(float(word.get("end", segment.get("end", 0)) or 0), 2),
                        "probability": round(float(word.get("probability", 0) or 0), 4),
                    }
                )
    return timings


def segments_from_transcript(transcript: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not transcript:
        return []
    segments = transcript.get("segments")
    if not isinstance(segments, list):
        try:
            segments = json.loads(str(transcript.get("segments_json", "[]")))
        except json.JSONDecodeError:
            segments = []
    return [item for item in segments if isinstance(item, dict) and str(item.get("text", "")).strip()]


def transcript_is_word_timed(transcript: Dict[str, Any] | None) -> bool:
    if not transcript:
        return False
    provider = str(transcript.get("provider", "")).lower()
    text = str(transcript.get("full_text", "")).strip().lower()
    return (
        bool(text)
        and "placeholder" not in provider
        and "placeholder transcript" not in text
        and bool(clean_timed_words_for_caption(word_timings_from(transcript), provider))
    )


def transcribe_media(media_path: Path) -> tuple[str, List[Dict[str, Any]], List[Dict[str, Any]], float]:
    from faster_whisper import WhisperModel

    model = WhisperModel("small.en", device="cpu", compute_type="int8")
    segments_iter, info = model.transcribe(str(media_path), vad_filter=True, beam_size=5, word_timestamps=True)
    segments: List[Dict[str, Any]] = []
    word_timings: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    for segment in segments_iter:
        text = " ".join(str(segment.text).split())
        if not text:
            continue
        text_parts.append(text)
        words: List[Dict[str, Any]] = []
        for word in getattr(segment, "words", []) or []:
            word_text = str(getattr(word, "word", "")).strip()
            if not word_text:
                continue
            item = {
                "word": word_text,
                "start": round(float(getattr(word, "start", segment.start) or 0), 2),
                "end": round(float(getattr(word, "end", segment.end) or 0), 2),
                "probability": round(float(getattr(word, "probability", 0) or 0), 4),
            }
            words.append(item)
            word_timings.append(item)
        segments.append(
            {
                "start": round(float(segment.start), 2),
                "end": round(float(segment.end), 2),
                "text": text,
                "words": words,
            }
        )
    return " ".join(text_parts).strip(), segments, word_timings, float(getattr(info, "language_probability", 0.0) or 0.0)


def ensure_transcript(candidate: Candidate, media_path: Path) -> Dict[str, Any]:
    clip_id = str(candidate.clip["id"])
    existing = transcript_for_clip(clip_id)
    if transcript_is_word_timed(existing):
        return existing

    text, segments, word_timings, confidence = transcribe_media(media_path)
    if not text:
        raise RuntimeError("Local transcription produced no text; review kit stays blocked.")
    if not word_timings:
        raise RuntimeError("Local transcription produced no word timings; final proof stays blocked.")
    transcript_id = db.new_id("transcript")
    db.execute(
        """
        INSERT INTO transcripts
          (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
        VALUES (?, ?, 'faster_whisper', 'en', ?, ?, ?, ?, 'succeeded', ?)
        """,
        (transcript_id, clip_id, confidence, text, json.dumps(segments), json.dumps(word_timings), db.utc_now()),
    )
    return db.one("SELECT * FROM transcripts WHERE id = ?", (transcript_id,)) or {}


def _emphasize_hook_words(text: str) -> str:
    emphasis = {
        "shocked",
        "caught",
        "dropped",
        "remembered",
        "missed",
        "realized",
        "texting",
        "driving",
        "seatbelt",
        "stole",
        "hungry",
        "speed",
        "speeds",
    }
    words = []
    for word in text.split():
        core = re.sub(r"[^A-Za-z0-9]", "", word).lower()
        words.append(word.upper() if core in emphasis else word)
    return " ".join(words)


HOOK_OVERRIDES = {
    "clip_d0c9d184f75c": "Lacy admits he wanted TRUMP for MONEY",
    "clip_5e00817c52c2": "Lacy begged for CPR after the fall",
    "clip_041a51eedd5e": "Lacy promised 100 gifted subs for RETWEETS",
    "clip_598d2f160515": "Lacy couldn't see while Drew kept calling",
    "clip_aaad914f4538": "Lacy heard Savage CRASHED in last place",
    "clip_a1e493aa552b": "Lacy watched them climb before security came",
    "clip_42cbaa5686b0": "Lacy realized he's HIM mid-clip",
    "clip_82ec1decd290": "YourRAGE got stuck repeating the same line",
    "clip_3b0737d91f70": "Jason heard chat say something way too risky",
    "clip_0b33758d13dd": "Jason got tired of fake rumor math",
    "clip_b200319459a7": "Jason saw something coming from the hill and panicked",
    "clip_9ab0d5a77ced": "Emily came back and somehow won free Chipotle",
    "clip_e31cf9a9ec51": "Max got Lucki talking about turning thirty",
    "clip_76572c1f77a8": "Max got roasted for his fresh barrel twists",
    "clip_58fa65245afb": "Max realized the song was already about his stream",
    "clip_5663dce40340": "YourRAGE got tired of the Agent and Emily jokes",
    "clip_c34ba7160d61": "YourRAGE pictured Agent dancing exactly like this",
    "clip_3c2685fa51d2": "Jason tried the windup and instantly regretted it",
    "clip_114cbd99f552": "Jason had to explain why his friend was there",
}

MIN_CAPTION_BEAT_DURATION = 0.16
CAPTION_BEAT_GAP = 0.03


def weak_title(text: str) -> bool:
    lowered = " ".join(str(text).split()).lower()
    if not lowered:
        return True
    if lowered in {"dd", "lmao", "lmfao", "sus", "cpr", "o7 l bmw", "😭😭", "leaked", "corny"}:
        return True
    if any(token in lowered for token in ("draft", "#1 pick", "placeholder", "wip")):
        return True
    words = [word for word in re.split(r"[^a-z0-9]+", lowered) if word]
    return len(words) <= 2 and all(len(word) <= 5 for word in words)


def hook_from_transcript(transcript_text: str, handle: str) -> str:
    clean = " ".join(str(transcript_text).split())
    name = streamer_display_name(handle)
    if not clean:
        return f"{name} had the whole chat watching"
    first = re.split(r"(?<=[.!?])\s+", clean)[0].strip()
    words = first.split()[:9]
    if len(words) < 3:
        words = clean.split()[:9]
    excerpt = " ".join(words).strip(" -")
    return _emphasize_hook_words(f"{name} said: {excerpt}")


def streamer_display_name(handle: str) -> str:
    normalized = re.sub(r"[^a-z0-9]", "", str(handle or "").lower())
    names = {
        "yourrage": "YourRAGE",
        "yourragegaming": "YourRAGE",
        "plaqueboymax": "Max",
        "jasontheween": "Jason",
        "lacy": "Lacy",
    }
    if normalized in names:
        return names[normalized]
    clean = str(handle or "").strip().lstrip("@")
    return clean[:1].upper() + clean[1:] if clean else "Streamer"


def _strip_hook_prefixes(text: str, handle: str) -> str:
    clean = " ".join(str(text).split())
    clean = clean.replace(" - Feeder Proof", "")
    clean = clean.replace("Selected Feeder Review -", "")
    clean = re.sub(r"\b(?:selected feeder|feeder proof|evidence review|review kit|proof|demo)\b", "", clean, flags=re.IGNORECASE)
    speaker_names = {
        streamer_display_name(handle),
        handle,
        "YourRAGE",
        "PlaqueBoyMax",
        "JasonTheWeen",
        "Jason",
        "Max",
        "Lacy",
    }
    for name in sorted({item for item in speaker_names if item}, key=len, reverse=True):
        clean = re.sub(rf"^\s*{re.escape(name)}\s*[:\-|]\s*", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^[#@\s:\-|]+", "", clean)
    return " ".join(clean.split()).strip(" \"'`")


def _hook_words(text: str) -> List[str]:
    return [word for word in re.split(r"\s+", str(text).strip()) if word]


def _trim_hook(text: str, max_words: int = 14) -> str:
    words = _hook_words(text)
    if len(words) > max_words:
        words = words[:max_words]
    while words and re.sub(r"[^a-z0-9]", "", words[-1].lower()) in {"a", "an", "the", "to", "of", "and", "or", "but", "with"}:
        words.pop()
    trimmed = " ".join(words).strip(" ,;:-")
    return trimmed[:1].upper() + trimmed[1:] if trimmed else ""


def non_spoiler_summary_hook(title: str, handle: str, transcript_text: str = "") -> str:
    name = streamer_display_name(handle)
    clean = _strip_hook_prefixes(title, handle)
    lowered = clean.lower()
    haystack = f"{lowered}\n{str(transcript_text).lower()}"

    if "green screen" in haystack or "greenscreen" in haystack:
        if "silky" in haystack or "jason" in haystack:
            return "Max got tired of Jason and Silky green screening his stream"
        return f"{name} got tired of the green screen bit"
    if "phone" in haystack or "text" in haystack or "call" in haystack:
        return f"{name} shut down a phone call question on stream"
    if "friend" in haystack:
        return f"{name} got asked an awkward friendship question"
    if "chicken" in haystack:
        return f"{name} got stuck on a wild chicken comment"
    if "mind" in haystack or "train" in haystack or "impress" in haystack:
        return f"{name} found a wild brain training take"
    if "argument" in haystack or "debate" in haystack:
        return f"{name} turned a stream moment into a debate"
    if "laugh" in haystack or "funny" in haystack:
        return f"{name} could not hold it together on stream"
    if weak_title(clean):
        fallback = _strip_hook_prefixes(hook_from_transcript(transcript_text, handle), handle)
        return _trim_hook(f"{name} had chat locked in over this moment" if weak_title(fallback) else fallback)

    quote_like = re.match(r"^(?:i|i'm|im|you|your|what|why|how|if|bro|ray|chat|nah|no)\b", lowered)
    if quote_like:
        return _trim_hook(f"{name} had chat locked in over this moment")
    return _trim_hook(clean)


def viewer_hook(title: str, handle: str, transcript_text: str = "", clip_id: str = "") -> str:
    if clip_id in HOOK_OVERRIDES:
        return HOOK_OVERRIDES[clip_id]
    clean = _strip_hook_prefixes(title, handle)
    lowered = clean.lower()
    if handle.lower() == "lacy":
        if "arrest" in lowered:
            return "Lacy gets ARRESTED live on stream"
        if "pull" in lowered and "over" in lowered:
            return "Lacy gets PULLED OVER on stream"
        if "searched" in lowered or "search" in lowered:
            return "Lacy gets SEARCHED live on stream"
        if "cop" in lowered or "police" in lowered:
            return "COPS pulled up on Lacy's stream"
        if "handcuff" in lowered:
            return "Lacy got exposed by the HANDCUFFS"
    if "texting" in lowered and "seatbelt" in lowered:
        name = streamer_display_name(handle)
        return f"{name} was TEXTING and DRIVING without a SEATBELT"
    if weak_title(clean):
        return hook_from_transcript(transcript_text, handle)
    if not clean:
        return f"{streamer_display_name(handle)} had the whole chat watching"
    hook = _emphasize_hook_words(non_spoiler_summary_hook(clean, handle, transcript_text))
    if len(re.findall(r"[a-z0-9]{2,}", hook.lower())) < 5:
        return f"{streamer_display_name(handle)} had chat locked in over this moment"
    return hook


def _wrapped_lines(draw: ImageDraw.ImageDraw, text: str, style_font: ImageFont.ImageFont, max_width: int, max_lines: int = 3) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or text_size(draw, candidate, style_font)[0] <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        remaining_words = words[sum(len(line.split()) for line in lines) :]
        current = " ".join(remaining_words) if remaining_words else current
        while text_size(draw, current, style_font)[0] > max_width and len(current) > 8:
            current = current[:-2].rstrip()
        lines.append(current)
    return [line for line in lines if line]


def _top_hook_wrapped_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    style_font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
    max_width: int,
    max_lines: int = 2,
) -> List[str]:
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or mixed_text_size(draw, candidate, style_font, emoji_font)[0] <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        remaining_words = words[sum(len(line.split()) for line in lines) :]
        current = " ".join(remaining_words) if remaining_words else current
        lines.append(current)
    return [line for line in lines if line]


def _balanced_top_hook_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    style_font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
    max_width: int,
) -> List[str]:
    words = text.split()
    if len(words) <= 4 and mixed_text_size(draw, text, style_font, emoji_font)[0] <= max_width:
        return [text]
    best: tuple[float, List[str]] | None = None
    for split in range(1, len(words)):
        lines = [" ".join(words[:split]), " ".join(words[split:])]
        widths = [mixed_text_size(draw, line, style_font, emoji_font)[0] for line in lines]
        if any(width > max_width for width in widths):
            continue
        word_balance_penalty = abs(split - (len(words) - split)) * 18
        score = abs(widths[0] - widths[1]) + word_balance_penalty
        if best is None or score < best[0]:
            best = (score, lines)
    if best is not None:
        return best[1]
    return _top_hook_wrapped_lines(draw, text, style_font, emoji_font, max_width, max_lines=2)


def _reference_top_hook_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    style_font: ImageFont.ImageFont,
    emoji_font: ImageFont.ImageFont | None,
    max_width: int,
) -> List[str]:
    greedy = _top_hook_wrapped_lines(draw, text, style_font, emoji_font, max_width, max_lines=2)
    if len(greedy) == 2:
        widths = [mixed_text_size(draw, line, style_font, emoji_font)[0] for line in greedy]
        if min(widths) / max(1, max(widths)) >= 0.55:
            return greedy
    return _balanced_top_hook_lines(draw, text, style_font, emoji_font, max_width)


def reference_top_hook_text(hook: str) -> str:
    clean = " ".join(str(hook).split()).strip(" ,.;:-")
    if not clean:
        return ""
    has_emoji = any(is_emoji_char(char) for char in clean)
    if not has_emoji:
        clean = f"{clean} 🤣🤣"
    return clean


def headline_card(path: Path, title: str, handle: str, transcript_text: str = "", clip_id: str = "", *, show: bool = True) -> str:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    if not show:
        image.save(path)
        return ""
    hook = reference_top_hook_text(viewer_hook(title, handle, transcript_text=transcript_text, clip_id=clip_id))

    # TikTok's built-in text card is authored in the source 720x1280 design
    # space and then upscaled with the video. Drawing natively at 1080 makes
    # the same font look too crisp and blocky, so keep this card in that
    # source-scale coordinate system and upscale the transparent overlay.
    logical = Image.new("RGBA", (720, 1280), (0, 0, 0, 0))
    draw = ImageDraw.Draw(logical, "RGBA")
    max_card_width = 588
    card_top = 224
    text_top = 238
    text_max_width = 550
    title_font = top_hook_card_font(34)
    emoji_font = top_hook_emoji_font(40)
    lines: List[str] = []
    for font_size in (34, 33, 32, 31, 30, 29, 28):
        candidate_font = top_hook_card_font(font_size)
        candidate_emoji_font = top_hook_emoji_font(40)
        candidate_lines = _reference_top_hook_lines(draw, hook, candidate_font, candidate_emoji_font, text_max_width)
        widths = [mixed_text_size(draw, line, candidate_font, candidate_emoji_font)[0] for line in candidate_lines]
        same_text = " ".join(candidate_lines).strip() == hook
        if candidate_lines and len(candidate_lines) <= 2 and all(width <= text_max_width for width in widths) and same_text:
            title_font = candidate_font
            emoji_font = candidate_emoji_font
            lines = candidate_lines
            break
    if not lines:
        title_font = top_hook_card_font(28)
        emoji_font = top_hook_emoji_font(40)
        lines = _balanced_top_hook_lines(draw, hook, title_font, emoji_font, text_max_width)
    if not lines:
        image.save(path)
        return ""
    line_heights = [mixed_text_size(draw, line, title_font, emoji_font)[1] for line in lines]
    line_widths = [mixed_text_size(draw, line, title_font, emoji_font)[0] for line in lines]
    # Long hooks should reach the reference card width, but shorter hooks
    # need to fit their longest line so the white card does not look empty.
    if len(lines) == 2:
        card_width = min(max_card_width, max(460, max(line_widths) + 44))
    else:
        card_width = min(max_card_width, max(347, max(line_widths) + 47))
    card_left = int(round((720 - card_width) / 2))
    text_left = card_left + 22
    gap = 10
    text_block_height = sum(line_heights) + max(0, len(line_heights) - 1) * gap
    card_height = max(64, min(105, text_block_height + 16))
    draw.rounded_rectangle(
        (card_left + 2, card_top + 3, card_left + card_width + 2, card_top + card_height + 3),
        radius=14,
        fill=(0, 0, 0, 28),
    )
    draw.rounded_rectangle(
        (card_left, card_top, card_left + card_width, card_top + card_height),
        radius=14,
        fill=(255, 255, 255, 255),
    )
    y = text_top
    for line, line_height in zip(lines, line_heights):
        draw_mixed_text_visual_top(draw, line, text_left, y, title_font, emoji_font, (7, 7, 7, 255))
        y += line_height + gap
    image = logical.resize((1080, 1920), Image.Resampling.LANCZOS)
    image = stretch_visible_overlay_y(image, 1.015)
    # The TikTok reference card is a compressed platform overlay, not a
    # razor-crisp native app layer. A tiny post-resize softening keeps the
    # same geometry while matching that optical edge quality more closely.
    image = image.resize((540, 960), Image.Resampling.BICUBIC).resize((1080, 1920), Image.Resampling.BICUBIC)
    image.save(path)
    return hook


def source_badge(path: Path, platform: str, handle: str, *, show: bool = True) -> str:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    if not show:
        image.save(path)
        return ""
    draw = ImageDraw.Draw(image, "RGBA")
    prefix = "TWITCH" if platform.lower() == "twitch" else platform.upper()
    suffix = f".TV/{handle.upper()}" if platform.lower() == "twitch" else f".COM/{handle.upper()}"
    text = f"{prefix}{suffix}"
    style_font = font(64)
    width_prefix, _ = text_size(draw, prefix, style_font, stroke_width=5)
    width_suffix, height = text_size(draw, suffix, style_font, stroke_width=5)
    left = (1080 - width_prefix - width_suffix) // 2
    top = 1682
    color = (145, 70, 255, 255) if platform.lower() == "twitch" else (55, 220, 62, 255)
    draw.text((left, top), prefix, font=style_font, fill=color, stroke_width=5, stroke_fill=(0, 0, 0, 235))
    draw.text((left + width_prefix, top), suffix, font=style_font, fill=(245, 245, 245, 255), stroke_width=5, stroke_fill=(0, 0, 0, 235))
    image.save(path)
    return text


def reference_handle_watermark(path: Path, platform: str, handle: str, *, show: bool = True) -> Dict[str, Any]:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    clean_handle = str(handle or "").strip().lstrip("@")
    if not show or not clean_handle:
        image.save(path)
        return {}
    draw = ImageDraw.Draw(image, "RGBA")
    text = f"@{clean_handle.lower()}"
    style_font = top_hook_font(40)
    text_width, text_height = text_size(draw, text, style_font, stroke_width=3)
    icon_size = 32
    gap = 7
    total_width = icon_size + gap + text_width
    left = (1080 - total_width) // 2
    top = 1276
    color = (145, 70, 255, 255) if str(platform).lower() == "twitch" else (55, 220, 62, 255)
    draw.rounded_rectangle((left + 2, top + 2, left + icon_size + 2, top + icon_size + 2), radius=7, fill=(0, 0, 0, 120))
    draw.rounded_rectangle((left, top, left + icon_size, top + icon_size), radius=7, fill=color)
    bubble = (left + 8, top + 8, left + 25, top + 21)
    draw.rounded_rectangle(bubble, radius=2, outline=(255, 255, 255, 255), width=3)
    draw.polygon([(left + 14, top + 21), (left + 14, top + 27), (left + 21, top + 21)], fill=(255, 255, 255, 255))
    text_left = left + icon_size + gap
    text_top = top - 6
    draw_text_visual_top(draw, text, text_left, text_top, style_font, (255, 255, 255, 255), (0, 0, 0, 245), 3)
    image.save(path)
    return {
        "visible": True,
        "text": text,
        "position": "bottom_blur_center",
        "x": left,
        "y": top,
        "width": total_width,
        "height": max(icon_size, text_height + 14),
    }


def draw_capsule_caption(
    draw: ImageDraw.ImageDraw,
    line: str,
    top: int,
    style_font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    background: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
) -> None:
    width, height = text_size(draw, line, style_font)
    pad_x = 28
    pad_y = 18
    left = (1080 - width) // 2 - pad_x
    rect = (left, top - pad_y, left + width + pad_x * 2, top + height + pad_y)
    draw.rounded_rectangle(rect, radius=14, fill=background)
    if outline:
        draw.rounded_rectangle(rect, radius=14, outline=outline, width=3)
    draw_text_visual_top(draw, line, (1080 - width) // 2, top, style_font, fill)


def draw_keyword_caption(draw: ImageDraw.ImageDraw, line: str, top: int, style_font: ImageFont.ImageFont) -> None:
    words = line.split()
    if len(words) != 2:
        width, _ = text_size(draw, line, style_font, stroke_width=6)
        draw_text_visual_top(draw, line, (1080 - width) // 2, top, style_font, (255, 224, 0, 255), (0, 0, 0, 245), 6)
        return
    gap = 16
    first_w, _ = text_size(draw, words[0], style_font, stroke_width=6)
    second_w, _ = text_size(draw, words[1], style_font, stroke_width=6)
    left = (1080 - first_w - gap - second_w) // 2
    draw_text_visual_top(draw, words[0], left, top, style_font, (255, 255, 255, 255), (0, 0, 0, 245), 6)
    draw_text_visual_top(draw, words[1], left + first_w + gap, top, style_font, (255, 224, 0, 255), (0, 0, 0, 245), 6)


def caption_overlay(path: Path, text: str, center_y: int, variant: str) -> None:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    style_font = font(CAPTION_FONT_SIZE if len(text) <= 12 else CAPTION_FONT_SIZE - 6)
    lines = caption_lines(draw, text, style_font, 930, max_lines=1)
    if not lines:
        lines = [str(text).strip().upper()]
    total_height = sum(text_size(draw, line, style_font, stroke_width=7)[1] for line in lines) + max(0, len(lines) - 1) * 12
    top = min(center_y, CAPTION_MAX_CENTER_Y) - total_height // 2
    for line in lines:
        width, height = text_size(draw, line, style_font, stroke_width=7)
        left = max(42, (1080 - width) // 2)
        if variant == "B":
            draw_keyword_caption(draw, line, top, style_font)
        elif variant == "D":
            draw_capsule_caption(draw, line, top, style_font, (12, 12, 12, 255), (255, 255, 255, 245), (0, 0, 0, 44))
        elif variant == "E":
            draw_text_visual_top(draw, line, left, top + 4, style_font, (0, 210, 255, 120), (255, 0, 112, 100), 4)
            draw_text_visual_top(draw, line, left, top, style_font, (255, 255, 255, 255), (0, 0, 0, 245), 5)
            underline_width, underline_height = text_size(draw, line, style_font, stroke_width=5)
            underline_left = (1080 - underline_width) // 2
            draw.rounded_rectangle((underline_left, top + underline_height + 11, underline_left + underline_width, top + underline_height + 18), radius=4, fill=(0, 210, 255, 220))
        else:
            draw_text_visual_top(draw, line, left, top, style_font, (255, 255, 255, 255), (0, 0, 0, 245), 6)
        top += height + 12
    image.save(path)


def campaign_watermark_overlay(path: Path, watermark_path: Path) -> Dict[str, Any]:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    watermark = Image.open(watermark_path).convert("RGBA")
    alpha_box = watermark.getbbox()
    if alpha_box:
        watermark = watermark.crop(alpha_box)
    max_width = 270
    max_height = 92
    scale = min(max_width / max(1, watermark.width), max_height / max(1, watermark.height), 1.0)
    target_size = (max(1, int(watermark.width * scale)), max(1, int(watermark.height * scale)))
    watermark = watermark.resize(target_size, Image.Resampling.LANCZOS)
    left = (1080 - watermark.width) // 2
    top = 1270
    shadow = Image.new("RGBA", watermark.size, (0, 0, 0, 0))
    shadow_alpha = watermark.getchannel("A").point(lambda value: min(130, int(value * 0.55)))
    shadow.putalpha(shadow_alpha)
    image.alpha_composite(shadow, (left + 4, top + 5))
    image.alpha_composite(watermark, (left, top))
    image.save(path)
    return {
        "asset_path": str(watermark_path),
        "overlay_path": str(path),
        "position": "bottom_blur_center",
        "x": left,
        "y": top,
        "width": watermark.width,
        "height": watermark.height,
    }


def extract_layout_frame(media_path: Path, kit_dir: Path, offset: float, index: int) -> Path | None:
    path = kit_dir / f"layout_probe_{index}.jpg"
    result = run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{max(0.0, offset):.2f}",
            "-i",
            str(media_path),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(path),
        ],
        timeout=45,
    )
    if result.returncode != 0 or not path.exists():
        return None
    return path


def skin_ratio(image: Image.Image) -> float:
    sample = image.convert("YCbCr").resize((96, 54))
    raw = sample.tobytes()
    if not raw:
        return 0.0
    skin = 0
    count = len(raw) // 3
    for index in range(0, len(raw), 3):
        y, cb, cr = raw[index], raw[index + 1], raw[index + 2]
        if 72 <= cb <= 142 and 128 <= cr <= 202 and y >= 45:
            skin += 1
    return skin / count if count else 0.0


def region_activity(image: Image.Image) -> float:
    sample = image.convert("L").resize((96, 54))
    variance = float(ImageStat.Stat(sample).var[0] or 0)
    return min(1.0, variance / 3600.0)


def facecam_candidate_score(image: Image.Image, rect: tuple[float, float, float, float]) -> float:
    width, height = image.size
    x, y, w, h = rect
    box = (
        int(max(0, x * width)),
        int(max(0, y * height)),
        int(min(width, (x + w) * width)),
        int(min(height, (y + h) * height)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        return 0.0
    crop = image.crop(box)
    return skin_ratio(crop) * 4.0 + region_activity(crop) * 0.35


def detect_facecam_rect(media_path: Path, kit_dir: Path, source_width: float, source_height: float) -> Dict[str, Any]:
    duration = source_duration(media_path)
    offsets = [1.25, max(1.0, duration * 0.35), max(1.0, duration * 0.68)]
    candidates = {
        "top_left": (0.0, 0.0, 0.25, 0.30),
        "top_right": (0.75, 0.0, 0.25, 0.30),
        "bottom_left": (0.0, 0.66, 0.25, 0.34),
        "bottom_right": (0.75, 0.66, 0.25, 0.34),
    }
    scores = {name: [] for name in candidates}
    frames: List[str] = []
    for index, offset in enumerate(offsets, start=1):
        frame = extract_layout_frame(media_path, kit_dir, offset, index)
        if not frame:
            continue
        frames.append(str(frame))
        try:
            image = Image.open(frame).convert("RGB")
        except Exception:
            continue
        for name, rect in candidates.items():
            scores[name].append(facecam_candidate_score(image, rect))
    averaged = {name: (sum(values) / len(values) if values else 0.0) for name, values in scores.items()}
    best_name = max(averaged, key=lambda name: averaged[name]) if averaged else ""
    best_score = averaged.get(best_name, 0.0)
    threshold = 2.35 if best_name.startswith("bottom_") else 0.18
    detected = bool(best_name and best_score >= threshold)
    rect = candidates.get(best_name, (0.0, 0.0, 0.0, 0.0))
    x = int(round(rect[0] * source_width))
    y = int(round(rect[1] * source_height))
    w = int(round(rect[2] * source_width))
    h = int(round(rect[3] * source_height))
    return {
        "detected": detected,
        "position": best_name if detected else "",
        "confidence": round(best_score, 3),
        "source_rect": {"x": x, "y": y, "width": w, "height": h} if detected else {},
        "candidate_scores": {name: round(score, 3) for name, score in averaged.items()},
        "probe_frames": frames,
    }


def streamer_composition_plan(media_path: Path, kit_dir: Path, platform: str, source_width: float, source_height: float) -> Dict[str, Any]:
    aspect = source_width / source_height if source_width and source_height else 0.0
    streamer_source = str(platform or "").lower() in {"twitch", "kick"} or aspect >= 1.45
    if not streamer_source:
        return {"mode": "standard_portrait_or_non_streamer", "reason": "source is not a landscape streamer layout"}
    if aspect < 1.25:
        return {
            "mode": "portrait_source_facecam_unrecoverable",
            "reason": "source media is already portrait; native facecam/screen regions cannot be recovered from this file",
        }
    facecam = detect_facecam_rect(media_path, kit_dir, source_width, source_height)
    if not facecam.get("detected"):
        return {
            "mode": "streamer_center_screen_no_facecam_detected",
            "reason": "landscape streamer source detected, but no confident facecam corner was found",
            "facecam_detection": facecam,
        }
    allow_split = os.environ.get("CLIPPING_OPS_ALLOW_FACE_CAM_SPLIT", "").strip().lower() in {"1", "true", "yes"}
    if not allow_split:
        return {
            "mode": "streamer_center_preserve_source",
            "reason": "facecam was detected, but split-facecam layout is disabled by default; source frame is preserved to avoid needless top-band crops",
            "facecam_detection": facecam,
        }
    confidence = float(facecam.get("confidence", 0) or 0)
    if confidence < 2.75:
        return {
            "mode": "streamer_center_preserve_source",
            "reason": f"facecam candidate confidence {confidence:.2f} is not high enough to justify split-facecam layout",
            "facecam_detection": facecam,
        }
    return {
        "mode": "streamer_split_facecam_top",
        "reason": "landscape streamer source with detected facecam; facecam is lifted to the top band and screen/action remains centered below",
        "facecam_detection": facecam,
        "facecam_band_height": 520,
        "main_y": 520,
        "main_height": 1400,
    }


def standard_layout_filter() -> str:
    return (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=18:2,eq=brightness=-0.10:saturation=0.90,setsar=1[bg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,setsar=1[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base]"
    )


def reference_stacked_layout_filter() -> str:
    return (
        "[0:v]split=2[src_bg][src_fg];"
        "[src_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=24:2,eq=brightness=-0.10:saturation=0.90,setsar=1[bg];"
        "[src_fg]scale=1080:607:force_original_aspect_ratio=increase,crop=1080:607,setsar=1[fg];"
        "[bg][fg]overlay=0:513[base]"
    )


def streamer_split_layout_filter(plan: Dict[str, Any]) -> str:
    rect = dict((plan.get("facecam_detection") or {}).get("source_rect") or {})
    x = int(rect.get("x", 0))
    y = int(rect.get("y", 0))
    width = max(16, int(rect.get("width", 0)))
    height = max(16, int(rect.get("height", 0)))
    facecam_h = int(plan.get("facecam_band_height", 520) or 520)
    main_y = int(plan.get("main_y", facecam_h) or facecam_h)
    main_h = int(plan.get("main_height", 1920 - main_y) or (1920 - main_y))
    return (
        "[0:v]split=3[src_bg][src_main][src_face];"
        "[src_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
        "boxblur=18:2,eq=brightness=-0.14:saturation=0.82,setsar=1[bg];"
        f"[src_main]scale=1080:{main_h}:force_original_aspect_ratio=increase,crop=1080:{main_h},setsar=1[main];"
        f"[src_face]crop={width}:{height}:{x}:{y},scale=1080:{facecam_h}:force_original_aspect_ratio=increase,"
        f"crop=1080:{facecam_h},setsar=1[face];"
        f"[bg][main]overlay=0:{main_y}[base_main];"
        "[base_main][face]overlay=0:0[base]"
    )


def caption_beats(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    max_beats = 80
    all_timed_words: List[Dict[str, Any]] = []
    for segment in segments:
        text = " ".join(str(segment.get("text", "")).split())
        if not text:
            continue
        start = float(segment["start"])
        end = float(segment["end"])
        words = [word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’%$.-]*", text) if word.strip()]
        if not words:
            continue
        duration = max(0.75, end - start)
        step = duration / max(1, len(words))
        segment_timed_words = [
            {
                "word": word,
                "start": start + step * index,
                "end": min(end, start + step * (index + 1)),
            }
            for index, word in enumerate(words)
        ]
        all_timed_words.extend(segment_timed_words)
        if len(all_timed_words) >= max_beats * CAPTION_MAX_WORDS_PER_LINE:
            break
    groups = timed_caption_groups(all_timed_words, max_groups=max_beats)
    raw_beats: List[Dict[str, Any]] = []
    for index, group in enumerate(groups):
        clean = caption_display_text(" ".join(str(item["word"]) for item in group).strip())
        if not clean:
            continue
        raw_end = max(float(item["end"]) for item in group)
        beat_start = caption_start_for_group(float(group[0]["start"]), raw_end, clean)
        next_start = float(groups[index + 1][0]["start"]) if index + 1 < len(groups) else raw_end + 0.45
        beat_end = min(raw_end + 0.02, next_start - 0.02, beat_start + caption_display_window_seconds(clean))
        if beat_end <= beat_start:
            beat_end = beat_start + max(0.16, 0.16 * len(group))
        raw_beats.append(
            {
                "start": beat_start,
                "end": beat_end,
                "text": clean,
                "source_start": float(group[0]["start"]),
                "source_end": raw_end,
            }
        )
    return normalize_caption_beat_timings(raw_beats)


def normalize_caption_beat_timings(beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    readable: List[Dict[str, Any]] = []
    previous_end = -1.0
    for beat in beats:
        text = str(beat.get("text", "")).strip().upper()
        if not text:
            continue
        try:
            raw_start = float(beat.get("start", 0) or 0)
            raw_end = float(beat.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        try:
            source_start = float(beat.get("source_start", raw_start) or raw_start)
            source_end = float(beat.get("source_end", raw_end) or raw_end)
        except (TypeError, ValueError):
            source_start = raw_start
            source_end = raw_end
        delayed_start, delayed_end = apply_caption_audio_sync_delay(raw_start, raw_end)
        start = max(delayed_start, previous_end + CAPTION_BEAT_GAP if previous_end >= 0 else delayed_start)
        end = max(delayed_end, start + MIN_CAPTION_BEAT_DURATION)
        if end <= start:
            end = start + MIN_CAPTION_BEAT_DURATION
        delayed_source_end = source_end + CAPTION_AUDIO_SYNC_DELAY_SECONDS
        clean = {
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "source_start": round(source_start, 3),
            "source_end": round(source_end, 3),
            "audio_sync_delay_seconds": CAPTION_AUDIO_SYNC_DELAY_SECONDS,
            "lead_seconds": round(max(0.0, delayed_source_end - start), 3),
            "max_pre_audio_lead_seconds": CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS,
        }
        readable.append(clean)
        previous_end = clean["end"]
    return readable


def caption_beats_from_transcript(transcript: Dict[str, Any]) -> List[Dict[str, Any]]:
    provider = str(transcript.get("provider", "")).lower()
    if "ensemble_timestamp_consensus" in provider:
        consensus_beats: List[Dict[str, Any]] = []
        previous_end = -1.0
        for segment in segments_from_transcript(transcript):
            if not bool(segment.get("caption_beat")):
                continue
            text = caption_display_text(str(segment.get("text", "")))
            if not text:
                continue
            try:
                raw_start = max(0.0, float(segment.get("start", 0) or 0))
                raw_end = float(segment.get("end", 0) or 0)
            except (TypeError, ValueError):
                continue
            start, end = apply_caption_audio_sync_delay(raw_start, raw_end)
            if previous_end >= 0 and start < previous_end + CAPTION_BEAT_GAP:
                start = previous_end + CAPTION_BEAT_GAP
            end = max(end, start + MIN_CAPTION_BEAT_DURATION)
            try:
                source_start = float(segment.get("source_start", raw_start) or raw_start)
                source_end = float(segment.get("source_end", raw_end) or raw_end)
            except (TypeError, ValueError):
                source_start = raw_start
                source_end = raw_end
            consensus_beats.append(
                {
                    "start": round(start, 3),
                    "end": round(end, 3),
                    "text": text,
                    "source_start": round(source_start, 3),
                    "source_end": round(source_end, 3),
                    "audio_sync_delay_seconds": CAPTION_AUDIO_SYNC_DELAY_SECONDS,
                    "lead_seconds": round(max(0.0, source_end + CAPTION_AUDIO_SYNC_DELAY_SECONDS - start), 3),
                    "max_pre_audio_lead_seconds": CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS,
                    "timing_mode": str(segment.get("timing_mode", "ensemble_consensus")),
                    "anchor_source": str(segment.get("anchor_source", "")),
                    "model_votes": int(segment.get("model_votes", 0) or 0),
                    "model_names": list(segment.get("model_names", [])) if isinstance(segment.get("model_names"), list) else [],
                    "vote_spread_seconds": round(float(segment.get("vote_spread_seconds", 0) or 0), 3),
                }
            )
            previous_end = consensus_beats[-1]["end"]
        if consensus_beats:
            return consensus_beats

    words = []
    provider = str(transcript.get("provider", ""))
    raw_words = word_timings_from(transcript)
    for item in clean_timed_words_for_caption(raw_words, provider):
        word = re.sub(r"\s+", " ", str(item.get("word", "")).strip())
        if not word:
            continue
        words.append(
            {
                "start": float(item.get("start", 0) or 0),
                "end": float(item.get("end", 0) or 0),
                "word": word,
            }
        )
    if not words and not raw_words:
        return caption_beats(list(transcript.get("segments", [])))
    if not words:
        return []

    groups = timed_caption_groups(words, max_groups=80)

    raw_beats: List[Dict[str, Any]] = []
    for index, group in enumerate(groups[:80]):
        text = caption_display_text(" ".join(str(item["word"]) for item in group).strip())
        if not text:
            continue
        raw_end = max(float(item["end"]) for item in group)
        start = caption_start_for_group(float(group[0]["start"]), raw_end, text)
        next_start = float(groups[index + 1][0]["start"]) if index + 1 < len(groups) else raw_end + 0.55
        end = min(raw_end + 0.02, next_start - 0.02, start + caption_display_window_seconds(text))
        if end - start < 0.24:
            end = min(start + 0.34, next_start - 0.02)
        if end <= start:
            end = max(start + 0.16, raw_end)
        raw_beats.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "source_start": float(group[0]["start"]),
                "source_end": raw_end,
            }
        )
    return normalize_caption_beat_timings(raw_beats)


def best_caption_beats_for_transcript(transcript: Dict[str, Any]) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    provider = str(transcript.get("provider", "")).lower()
    if "ensemble_timestamp_consensus" in provider:
        consensus_beats = caption_beats_from_transcript(transcript)
        return consensus_beats, {
            "source": "ensemble_timestamp_consensus",
            "model_count": max((int(beat.get("model_votes", 0) or 0) for beat in consensus_beats), default=0),
            "timing_mode": "ensemble_or_strong_anchor",
            "word_timing_quality_issues": [],
            "segment_quality_issues": [],
        }

    word_beats = caption_beats_from_transcript(transcript)
    word_issues = caption_text_quality_violations(beat["text"] for beat in word_beats)
    segment_beats = caption_beats(segments_from_transcript(transcript))
    segment_issues = caption_text_quality_violations(beat["text"] for beat in segment_beats)
    if word_issues and segment_beats and len(segment_issues) < len(word_issues):
        return segment_beats, {
            "source": "segment_text_fallback",
            "word_timing_quality_issues": word_issues[:20],
            "segment_quality_issues": segment_issues[:20],
        }
    return word_beats, {
        "source": "word_timings",
        "word_timing_quality_issues": word_issues[:20],
        "segment_quality_issues": segment_issues[:20],
    }


def render_review_video(
    media_path: Path,
    kit_dir: Path,
    title: str,
    handle: str,
    platform: str,
    beats: List[Dict[str, Any]],
    transcript_text: str = "",
    clip_id: str = "",
    profile: str = "",
    caption_variant: str = "",
    campaign_slug: str = "",
) -> tuple[Path, Dict[str, Any]]:
    review_video = kit_dir / "review.mp4"
    stale_header = kit_dir / "header.png"
    if stale_header.exists():
        stale_header.unlink()
    title_card_path = kit_dir / "title_card.png"
    source_badge_path = kit_dir / "source_badge.png"
    reference_watermark_path = kit_dir / "reference_handle_watermark.png"
    caption_only_profile = profile == db.CAMPAIGN_SHORT_PROFILE
    campaign_slug = db.normalize_campaign_slug(campaign_slug)
    watermark_asset = db.campaign_watermark_asset_path(campaign_slug) if caption_only_profile and campaign_slug else ""
    if caption_only_profile and db.campaign_watermark_required(campaign_slug) and not watermark_asset:
        raise RuntimeError(db.campaign_watermark_blocker(campaign_slug))
    hook_text = headline_card(
        title_card_path,
        title,
        handle,
        transcript_text=transcript_text,
        clip_id=clip_id,
        show=True,
    )
    source_text = source_badge(
        source_badge_path,
        platform,
        handle,
        show=(not caption_only_profile and handle.lower() != "lacy"),
    )
    reference_watermark_info = reference_handle_watermark(
        reference_watermark_path,
        platform,
        handle,
        show=caption_only_profile and not watermark_asset,
    )

    source_width, source_height = source_dimensions(media_path)
    composition = streamer_composition_plan(media_path, kit_dir, platform, source_width, source_height)
    caption_center_y = caption_center_y_for_source(source_width, source_height)
    if caption_only_profile:
        caption_variant = normalize_caption_variant(caption_variant or DEFAULT_CAMPAIGN_CAPTION_VARIANT)
    else:
        caption_variant = normalize_caption_variant(caption_variant or caption_variant_for_key(clip_id or title))
    caption_paths: List[Path] = []
    for index, beat in enumerate(beats, start=1):
        path = kit_dir / f"caption_{index}.png"
        caption_overlay(path, beat["text"], caption_center_y, caption_variant)
        caption_paths.append(path)
    watermark_info: Dict[str, Any] = {}
    watermark_overlay_path: Path | None = None
    if watermark_asset:
        watermark_overlay_path = kit_dir / "campaign_watermark.png"
        watermark_info = campaign_watermark_overlay(watermark_overlay_path, Path(watermark_asset))

    if caption_only_profile:
        composition = {
            **composition,
            "layout_style": "tiktok_reference_stacked",
            "foreground_frame": {"x": 0, "y": 513, "width": 1080, "height": 607},
            "background_style": "blurred_fullscreen_source",
            "reason": (
                str(composition.get("reason", "")).strip()
                + "; campaign final uses reference stacked layout: hook over blurred top band, full-width sharp source below."
            ).strip("; "),
        }
        base_layout = reference_stacked_layout_filter()
    else:
        base_layout = (
            streamer_split_layout_filter(composition)
            if composition.get("mode") == "streamer_split_facecam_top"
            else standard_layout_filter()
        )
    title_overlay_enable = "" if caption_only_profile else ":enable='between(t,0,3.00)'"
    filters = [
        f"{base_layout};"
        f"[base][1:v]overlay=0:0:format=auto{title_overlay_enable}[title];"
        "[title][2:v]overlay=0:0:format=auto[v0]"
    ]
    current = "v0"
    next_input_index = 3
    if reference_watermark_info:
        filters.append(f"[{current}][{next_input_index}:v]overlay=0:0:format=auto[refwm]")
        current = "refwm"
        next_input_index += 1
    if watermark_overlay_path:
        filters.append(f"[{current}][{next_input_index}:v]overlay=0:0:format=auto[campaignwm]")
        current = "campaignwm"
        next_input_index += 1
    caption_input_start = next_input_index
    for index, beat in enumerate(beats, start=1):
        next_label = f"cap{index}"
        input_index = caption_input_start + index - 1
        filters.append(
            f"[{current}][{input_index}:v]overlay=0:0:format=auto:enable='between(t,{beat['start']:.2f},{beat['end']:.2f})'[{next_label}]"
        )
        current = next_label
    filters.append(f"[{current}]null[v]")

    command = ["ffmpeg", "-y", "-i", str(media_path), "-i", str(title_card_path), "-i", str(source_badge_path)]
    if reference_watermark_info:
        command.extend(["-i", str(reference_watermark_path)])
    if watermark_overlay_path:
        command.extend(["-i", str(watermark_overlay_path)])
    for caption_path in caption_paths:
        command.extend(["-i", str(caption_path)])
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[v]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "21",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            str(review_video),
        ]
    )
    result = run(command, timeout=1800)
    if result.returncode != 0 or not review_video.exists():
        raise RuntimeError(result.stderr[-4000:] or "ffmpeg render failed")
    rendered_text = {
        "layout": "summary_hook_caption" if caption_only_profile else "headline_caption",
        "hook_card_visible": bool(hook_text),
        "hook_card": hook_text,
        "hook_card_position": "top_safe_summary",
        "hook_card_persistent": bool(caption_only_profile and hook_text),
        "source_badge_visible": bool(source_text),
        "source_badge": source_text,
        "caption_beats": [str(beat["text"]) for beat in beats],
        "caption_timeline": [
            {
                "start": round(float(beat["start"]), 3),
                "end": round(float(beat["end"]), 3),
                "text": str(beat["text"]),
                "source_start": round(float(beat.get("source_start", beat["start"])), 3),
                "source_end": round(float(beat.get("source_end", beat["end"])), 3),
                "audio_sync_delay_seconds": round(float(beat.get("audio_sync_delay_seconds", 0)), 3),
                "lead_seconds": round(float(beat.get("lead_seconds", 0)), 3),
                "max_pre_audio_lead_seconds": round(float(beat.get("max_pre_audio_lead_seconds", 0)), 3),
                "timing_mode": str(beat.get("timing_mode", "style_late_pop")),
                "anchor_source": str(beat.get("anchor_source", "")),
                "model_votes": int(beat.get("model_votes", 0) or 0),
                "model_names": list(beat.get("model_names", [])) if isinstance(beat.get("model_names"), list) else [],
                "vote_spread_seconds": round(float(beat.get("vote_spread_seconds", 0) or 0), 3),
            }
            for beat in beats
        ],
        "caption_style": {
            **caption_style_manifest(),
            "constraint": f"max {CAPTION_MAX_WORDS_PER_LINE} words and about {CAPTION_TARGET_MAX_LINE_CHARS} characters per caption beat",
            "media_detected_width": source_width,
            "media_detected_height": source_height,
            "caption_center_y": caption_center_y,
            "ab_variant": caption_variant,
        },
        "composition": composition,
        "reference_watermark": reference_watermark_info,
        "reference_watermark_visible": bool(reference_watermark_info),
        "campaign_watermark": watermark_info,
        "watermark_visible": bool(watermark_info),
    }
    lowered = "\n".join([hook_text, source_text, *rendered_text["caption_beats"]]).lower()
    blocked = [token for token in INTERNAL_RENDER_TEXT_TOKENS if token in lowered]
    if blocked:
        raise RuntimeError(f"internal render text would be visible in video: {', '.join(blocked)}")
    return review_video, rendered_text


def create_nomination(candidate: Candidate, transcript: Dict[str, Any], beats: List[Dict[str, Any]], target_style: str) -> str:
    clip = candidate.clip
    route = candidate.route
    campaign_slug = db.campaign_slug_for_clip(clip)
    existing = db.one(
        """
        SELECT id
        FROM render_nominations
        WHERE clip_candidate_ids_json = ?
          AND nomination_type = 'single'
          AND target_style = ?
          AND campaign_slug = ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (json.dumps([str(clip["id"])]), target_style, campaign_slug),
    )
    if existing:
        return str(existing["id"])

    transcript_text = str(transcript.get("full_text", "")).strip()
    if target_style == db.CAMPAIGN_SHORT_PROFILE:
        project_name = db.CAMPAIGN_PROJECTS.get(campaign_slug, {}).get("name", "Campaign")
        score_reason = (
            f"{project_name} campaign source with stored rules, local media, and word-timed transcript. "
            f"Views={int(clip.get('view_count', 0) or 0)} duration={float(clip.get('duration', 0) or 0):.1f}s."
        )
    else:
        score_reason = (
            f"Selected feeder clip with stored campaign rules, reachable source route, local media, and transcript. "
            f"Views={int(clip.get('view_count', 0) or 0)} duration={float(clip.get('duration', 0) or 0):.1f}s."
        )
    payload = {
        "opening_hook": beats[0]["text"] if beats else title_case(str(clip.get("title", ""))),
        "clip_order": [str(clip["id"])],
        "caption_beats": beats,
        "crop_focus": "preserve the natural streamer source frame by default; only use split facecam layout when explicitly enabled and visually justified",
        "music_policy": "preserve source audio in review preview",
        "risk_notes": "Evidence-backed campaign edit. Posting approval remains separate from render validation.",
        "why_this_can_hit": score_reason,
        "transcript_excerpt": transcript_text[:240],
        "campaign_slug": campaign_slug,
    }
    if target_style != db.CAMPAIGN_SHORT_PROFILE:
        payload["selected_feeder"] = str(route.get("creator_handle", ""))
    nomination_id = db.new_id("nom")
    db.execute(
        """
        INSERT INTO render_nominations
          (id, campaign_slug, clip_candidate_ids_json, nomination_type, score_reason, edit_plan_json, target_style, status, created_at)
        VALUES (?, ?, ?, 'single', ?, ?, ?, 'rendered_non_demo', ?)
        """,
        (nomination_id, campaign_slug, json.dumps([str(clip["id"])]), score_reason, json.dumps(payload), target_style, db.utc_now()),
    )
    return nomination_id


def title_case(text: str) -> str:
    return " ".join(part.capitalize() for part in text.split())


def campaign_kit_title(clip: Dict[str, Any], campaign_slug: str, transcript: Dict[str, Any]) -> str:
    project_name = db.CAMPAIGN_PROJECTS.get(campaign_slug, {}).get("name", title_case(campaign_slug) if campaign_slug else "Campaign")
    raw_title = " ".join(str(clip.get("title", "")).split())
    hook = raw_title.split(" - ", 1)[1].strip() if " - " in raw_title else ""
    if not hook and ":" in raw_title:
        hook = raw_title.split(":", 1)[1].strip()
    hook_words = hook.split()
    last_word = hook_words[-1].strip(" ,.;:-").lower() if hook_words else ""
    if weak_title(hook) or last_word in {"a", "an", "the", "to", "of", "and", "or", "would", "b"}:
        transcript_text = " ".join(str(transcript.get("full_text", "")).split())
        hook = re.split(r"(?<=[.!?])\s+", transcript_text)[0].strip()
    if not hook:
        hook = raw_title or "New captioned clip"
    hook = hook.rstrip(" ,;:-")
    hook = re.sub(r"^(?:you know|okay|so|and|but|like)\s+", "", hook, flags=re.IGNORECASE).strip()
    if hook:
        hook = hook[0].upper() + hook[1:]
    if len(hook) > 92:
        hook = hook[:89].rstrip(" ,;:-") + "..."
    return f"{project_name}: {hook}"


def has_explicit_language(text: str) -> bool:
    lowered = text.lower()
    flagged = ["fuck", "fucking", "whore", "bitch", "shit", "nigga", "nigger"]
    return any(token in lowered for token in flagged)


def write_artifacts(
    candidate: Candidate,
    transcript: Dict[str, Any],
    kit_dir: Path,
    review_video: Path,
    beats: List[Dict[str, Any]],
    profile: str,
    rendered_text: Dict[str, Any],
) -> Dict[str, Path]:
    clip = candidate.clip
    route = candidate.route
    rules = candidate.rules
    campaign_slug = db.campaign_slug_for_clip(clip)
    project_name = db.CAMPAIGN_PROJECTS.get(campaign_slug, {}).get("name", title_case(campaign_slug) if campaign_slug else "")
    is_campaign_profile = profile == db.CAMPAIGN_SHORT_PROFILE
    title = str(clip.get("title", "")).strip() or "Untitled review kit"
    transcript_text = str(transcript.get("full_text", "")).strip()
    transcript_segments = transcript.get("segments", [])
    raw_word_timings = word_timings_from(transcript)
    word_timings = clean_timed_words_for_caption(raw_word_timings, transcript.get("provider", ""))
    confidence = float(transcript.get("confidence", 0) or 0)
    clip_flags = [str(flag).lower() for flag in clip.get("risk_flags", [])]
    handle = str(route.get("creator_handle", "")).strip().lower()
    is_lacy = not is_campaign_profile and (handle == "lacy" or "selected_feeder_lacy" in clip_flags)
    lacy_brief_text = "\n".join(
        str(item.get("extracted_text", ""))
        for item in rules
        if str(item.get("campaign_id", "")).lower() == "lacy"
    ).strip()
    lacy_theme_terms = ("arrest", "arrested", "cops", "cop ", "police", "pulled over", "searched", "handcuff", "handcuffs", "missing in action")
    lacy_theme_haystack = f"{title}\n{transcript_text}".lower()
    lacy_theme_hits = [term for term in lacy_theme_terms if term in lacy_theme_haystack]
    lacy_fit = is_lacy and (db.LACY_CAMPAIGN_FIT_FLAG in clip_flags or bool(lacy_theme_hits))
    caption = kit_dir / "caption.txt"
    transcript_path = kit_dir / "transcript.txt"
    checklist = kit_dir / "checklist.md"
    source_path = kit_dir / "source.md"
    risk_path = kit_dir / "risk.md"
    ffprobe_path = kit_dir / "ffprobe.json"
    thumbnail = kit_dir / "thumbnail.jpg"
    contact_sheet = kit_dir / "contact_sheet.jpg"
    critique = kit_dir / "style_critique.md"
    render_text_manifest = kit_dir / "render_text_manifest.json"
    editorial_review_path = kit_dir / "editorial_review.json"
    composition = dict(rendered_text.get("composition", {})) if isinstance(rendered_text.get("composition"), dict) else {}
    composition_mode = str(composition.get("mode", "unknown"))
    composition_reason = str(composition.get("reason", ""))
    facecam_detection = composition.get("facecam_detection", {}) if isinstance(composition.get("facecam_detection"), dict) else {}
    watermark_info = dict(rendered_text.get("campaign_watermark", {})) if isinstance(rendered_text.get("campaign_watermark"), dict) else {}
    watermark_required = db.campaign_watermark_required(campaign_slug)

    metadata = validate_video(review_video)
    write_json(ffprobe_path, metadata)
    extract_thumbnail(review_video, thumbnail)
    extract_contact_sheet(review_video, contact_sheet)
    write_json(
        render_text_manifest,
        {
            "profile": profile,
            "caption_only": bool(is_campaign_profile and not rendered_text.get("hook_card_visible")),
            "rendered_text": rendered_text,
            "internal_tokens_blocked": list(INTERNAL_RENDER_TEXT_TOKENS),
            "style_reference": "https://www.youtube.com/@IShouldClip/shorts",
            "reference_tiktok_hook": "https://www.tiktok.com/t/ZTBDvvEfD/",
            "notes": (
                "Campaign final renders burn a viewer-facing top summary hook plus subtitles. Internal labels remain blocked."
                if is_campaign_profile
                else "Only viewer-facing hook/source/caption copy may be burned into the video."
            ),
        },
    )
    editorial_review = db.editorial_review_for_rendered_kit(clip, kit_dir, campaign_slug, require_sidecar=False)
    write_json(editorial_review_path, editorial_review)

    write_text(
        caption,
        "\n".join(
            [
                "# Viewer Caption Package",
                "",
                *( [f"Hook card: {rendered_text.get('hook_card', '')}"] if rendered_text.get("hook_card") else [] ),
                *( [f"Source badge: {rendered_text.get('source_badge', '')}"] if rendered_text.get("source_badge") else [] ),
                *( ["Suggested post caption: Lacy on stream. #lacy"] if is_lacy else [] ),
                *( ["Burned-in text: top summary hook plus subtitles"] if is_campaign_profile else [] ),
                f"Caption standard: TikTok Sans Black, max {CAPTION_MAX_WORDS_PER_LINE} words per beat, target max {CAPTION_TARGET_MAX_LINE_CHARS} characters unless a single word is longer.",
                "",
                "Timed captions:",
                *[f"- {beat['start']:.2f}-{beat['end']:.2f}: {beat['text']}" for beat in beats],
            ]
        ),
    )
    write_text(
        transcript_path,
        "\n".join(
            [
                transcript_text,
                "",
                "Segments:",
                *[
                    f"- {segment.get('start', 0):.2f}-{segment.get('end', 0):.2f}: {segment.get('text', '')}"
                    for segment in transcript_segments
                ],
                "",
                "Word timings:",
                *[
                    f"- {word.get('start', 0):.2f}-{word.get('end', 0):.2f}: {word.get('word', '')}"
                    for word in word_timings[:80]
                ],
            ]
        )
        + "\n",
    )
    write_text(
        checklist,
        "\n".join(
            [
                "# Review Checklist",
                "- [x] Stored source URL exists for the clip candidate.",
                "- [x] Campaign source route is stored.",
                "- [x] Stored campaign rules exist for the matching campaign.",
                *(["- [x] Lacy brief requires arrested/missing-in-action theme; this clip is flagged for that requirement."] if lacy_fit else []),
                *(["- [x] Caption package includes Lacy name and #lacy."] if is_lacy else []),
                "- [x] Local media exists on disk.",
                *(
                    ["- [x] Required campaign watermark is installed and burned into the review frame."]
                    if watermark_required and watermark_info
                    else []
                ),
                "- [x] Stored word-timed transcript exists in SQLite.",
                "- [x] `review.mp4` validates as H.264/AAC 1080x1920.",
                *(
                    ["- [x] Streamer layout uses detected facecam top band plus centered screen/action crop."]
                    if composition_mode == "streamer_split_facecam_top"
                    else []
                ),
                *(
                    ["- [x] Streamer layout preserves the natural source frame; split facecam is not used by default."]
                    if composition_mode == "streamer_center_preserve_source"
                    else []
                ),
                *(
                    ["- [ ] Native streamer facecam composition is blocked because source media is already portrait/cropped."]
                    if composition_mode == "portrait_source_facecam_unrecoverable"
                    else []
                ),
                f"- [{'x' if editorial_review.get('status') == 'green' else ' '}] Editorial gate is green.",
                "- [x] `ffprobe.json`, `thumbnail.jpg`, `contact_sheet.jpg`, and `style_critique.md` exist.",
                "- [ ] Human review completed.",
                "- [ ] Ready-to-post approval granted.",
            ]
        )
        + "\n",
    )
    write_text(
        source_path,
        "\n".join(
            [
                "# Source",
                "",
                f"- Clip ID: `{clip['id']}`",
                f"- Source URL: {clip.get('source_url', '')}",
                f"- Source platform: {clip.get('source_platform', '')}",
                f"- Provenance: `{clip.get('provenance', '')}`",
                "- Source verification: `source_media_verified_local`",
                f"- Local media: `{clip.get('local_media_path', '')}`",
                f"- Campaign: `{project_name or campaign_slug or route.get('creator_handle', '')}`",
                f"- Campaign source route: `{route.get('id', '')}` ({route.get('availability_status', '')})",
                f"- Render composition: `{composition_mode}`",
                f"- Composition note: {composition_reason}",
                *(
                    [
                        f"- Campaign watermark asset: `{watermark_info.get('asset_path', '')}`",
                        f"- Campaign watermark placement: `{watermark_info.get('position', '')}` at x={watermark_info.get('x', '')}, y={watermark_info.get('y', '')}",
                    ]
                    if watermark_info
                    else []
                ),
                *(
                    [
                        f"- Facecam position: `{facecam_detection.get('position', '')}`",
                        f"- Facecam confidence: `{facecam_detection.get('confidence', '')}`",
                        f"- Facecam source rect: `{json.dumps(facecam_detection.get('source_rect', {}), sort_keys=True)}`",
                    ]
                    if facecam_detection
                    else []
                ),
                "",
                "## Stored Campaign Rules",
                *[f"- `{item.get('campaign_id', '')}`: {item.get('source_url', '')}" for item in rules],
                *(["", "## Lacy Brief Extract", lacy_brief_text] if is_lacy and lacy_brief_text else []),
                *(["", "## Campaign Fit", "- Lacy requirement: feature Lacy being arrested or missing in action.", f"- Matched terms: {', '.join(lacy_theme_hits) or db.LACY_CAMPAIGN_FIT_FLAG}"] if lacy_fit else []),
            ]
        )
        + "\n",
    )
    risk_lines = [
        "# Risk",
        "",
        "- This is not approval to publish.",
        "- Transcript was generated locally and should be spot-checked by a human editor.",
        "- Campaign fit is backed by stored rules and local source evidence; publishing still requires separate operator approval.",
        f"- Render composition: `{composition_mode}`. {composition_reason}",
    ]
    if composition_mode == "portrait_source_facecam_unrecoverable":
        risk_lines.append("- Source media is already portrait/cropped; native stream facecam cannot be recovered from this file. Re-fetch native landscape source before production approval.")
    if composition_mode == "streamer_center_screen_no_facecam_detected":
        risk_lines.append("- Landscape source was available, but facecam detection did not find a confident corner; human should inspect the source before approval.")
    if composition_mode == "streamer_center_preserve_source":
        risk_lines.append("- Facecam detection did not automatically force a top-band crop; natural source framing is preferred unless an editor explicitly enables split layout.")
    if editorial_review.get("status") != "green":
        risk_lines.append("- BLOCKER: Editorial gate is red: " + "; ".join(str(item) for item in editorial_review.get("blockers", [])[:4]))
    if watermark_required and watermark_info:
        risk_lines.append(f"- Required campaign watermark is burned in from `{watermark_info.get('asset_path', '')}`.")
    if watermark_required and not watermark_info:
        risk_lines.append("- BLOCKER: Required campaign watermark was not burned into this render.")
    if is_lacy and not lacy_fit:
        risk_lines.append("- BLOCKER: Lacy brief requires arrested/missing-in-action content, and this clip is not flagged as matching that theme.")
    if confidence < 0.65:
        risk_lines.append(f"- Transcript confidence is moderate (`{confidence:.2f}`), so caption timing should be treated as provisional.")
    if len(transcript_segments) <= 1:
        risk_lines.append("- Only one ASR segment was recovered from the clip, which makes caption timing weak by default.")
    if has_explicit_language(transcript_text):
        risk_lines.append("- Transcript contains explicit language and likely ASR inaccuracies, so copy and compliance should be reviewed manually.")
    write_text(risk_path, "\n".join(risk_lines) + "\n")

    if editorial_review.get("status") != "green":
        status = "red"
    elif profile in {db.FINAL_PROOF_PROFILE, db.CAMPAIGN_SHORT_PROFILE} and word_timings and transcript_segments:
        status = "green"
    else:
        status = "yellow"
    critique_lines = [
        "# Style Critique",
        "",
        f"Status: {status}",
        f"Profile: {profile}",
        f"Source: `{clip.get('source_url', '')}`",
        "",
        "## What Works",
        "- Uses the original source audio and preserved action framing.",
        "- Uses stored rules, route availability, and local provenance evidence instead of a substitute source.",
        "- Uses word-timed transcript data for visible caption beats.",
        "",
        "## Limits",
        "- Manual approval remains required before any downstream posting workflow.",
        "- Caption copy should still be checked against campaign rules and platform context.",
        *([f"- Editorial blocker: {blocker}" for blocker in editorial_review.get("blockers", [])[:5]] if editorial_review.get("status") != "green" else []),
        *(["- Lacy brief match is explicit: arrested/missing-in-action theme plus #lacy caption package."] if lacy_fit else []),
        *(["- The recovered transcript is a single explicit-language segment, so editorial judgment is still doing most of the work."] if len(transcript_segments) <= 1 and has_explicit_language(transcript_text) else []),
        "",
        "## Validation",
        f"- Transcript confidence: {confidence:.2f}",
        f"- Segment count: {len(transcript_segments)}",
        f"- Word timing count: {len(word_timings)}",
        f"- Editorial gate: {editorial_review.get('status', 'unknown')}",
        *(
            [f"- Required watermark burned in: {watermark_info.get('position', '')}."]
            if watermark_required and watermark_info
            else []
        ),
        "- Burned-in internal labels: none; rendered copy is a top summary hook plus subtitles." if is_campaign_profile else "- Burned-in internal labels: none; rendered copy is hook/source/caption only.",
    ]
    write_text(critique, "\n".join(critique_lines) + "\n")

    return {
        "caption": caption,
        "transcript": transcript_path,
        "checklist": checklist,
        "source": source_path,
        "risk": risk_path,
        "ffprobe": ffprobe_path,
        "thumbnail": thumbnail,
        "contact_sheet": contact_sheet,
        "critique": critique,
        "render_text_manifest": render_text_manifest,
        "editorial_review": editorial_review_path,
    }


def build_review_kit(clip_id: str = "", profile: str = "evidence_review_v1", campaign_slug: str = "", force: bool = False, caption_variant: str = "") -> Dict[str, Any]:
    db.init_db()
    campaign_slug = db.normalize_campaign_slug(campaign_slug)
    candidate = pick_candidate(clip_id, campaign_slug=campaign_slug)
    clip = candidate.clip
    route = candidate.route
    media_path = ensure_local_media(candidate)
    transcript = ensure_transcript(candidate, media_path)
    beats, caption_generation = best_caption_beats_for_transcript(transcript)
    if not beats:
        raise RuntimeError("Transcript exists but no usable caption beats were produced.")
    nomination_id = create_nomination(candidate, transcript, beats, profile)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    handle = str(route.get("creator_handle", "")).strip().lower()
    project_slug = db.campaign_slug_for_clip(clip) or campaign_slug
    if profile == db.CAMPAIGN_SHORT_PROFILE:
        slug = f"campaign-short-{project_slug}"
        handle = project_slug or handle or "campaign"
    else:
        slug = "source-render" if profile == db.FINAL_PROOF_PROFILE else "evidence"
    existing_kit = db.one(
        """
        SELECT render_kits.*
        FROM render_kits
        JOIN render_nominations ON render_nominations.id = render_kits.nomination_id
        WHERE render_nominations.clip_candidate_ids_json = ?
          AND render_nominations.nomination_type = 'single'
          AND render_nominations.target_style = ?
          AND render_nominations.campaign_slug = ?
        ORDER BY render_kits.created_at DESC
        LIMIT 1
        """,
        (json.dumps([str(clip["id"])]), profile, project_slug),
    )
    existing_path = str((existing_kit or {}).get("review_video_path", "")).strip()
    existing_status = db.production_feeder_kit_status(existing_kit) if existing_kit else {}
    existing_has_internal_path = "feeder-proof" in existing_path.lower() or "feeder proof" in existing_path.lower()
    if existing_kit and existing_path and not existing_has_internal_path and existing_status.get("classification") == "green" and not force:
        return {
            "status": "succeeded",
            "reused_existing": True,
            "clip_id": str(clip["id"]),
            "title": str(existing_kit.get("title", "")),
            "kit_id": str(existing_kit["id"]),
            "nomination_id": nomination_id,
            "source_url": str(clip.get("source_url", "")),
            "local_media_path": str(media_path),
            "review_video_path": existing_path,
            "kit_dir": str(Path(existing_path).parent),
            "profile": profile,
        }
    if existing_kit and existing_path and not existing_has_internal_path:
        kit_dir = Path(str(existing_kit["review_video_path"])).parent
    else:
        existing_kit = None
        kit_dir = KIT_ROOT / f"{stamp}-{slug}-{handle}-{clip['id']}"
    kit_dir.mkdir(parents=True, exist_ok=True)
    review_video, rendered_text = render_review_video(
        media_path,
        kit_dir,
        str(clip.get("title", "")),
        handle or "source",
        str(clip.get("source_platform", "")) or str(route.get("platform", "")) or "twitch",
        beats,
        transcript_text=str(transcript.get("full_text", "")),
        clip_id=str(clip.get("id", "")),
        profile=profile,
        caption_variant=caption_variant,
        campaign_slug=project_slug,
    )
    rendered_text["caption_generation"] = caption_generation
    artifacts = write_artifacts(candidate, transcript, kit_dir, review_video, beats, profile, rendered_text)
    if profile in {db.FINAL_PROOF_PROFILE, db.CAMPAIGN_SHORT_PROFILE}:
        if profile == db.CAMPAIGN_SHORT_PROFILE:
            kit_title = campaign_kit_title(clip, project_slug, transcript)
        else:
            kit_title = str(clip.get("title", "")).strip() or str(rendered_text.get("hook_card", "")).strip() or "Streamer clip"
    else:
        kit_title = f"{clip.get('title', '').strip() or 'Review Kit'} - Evidence Review"
    if existing_kit:
        kit_id = str(existing_kit["id"])
        db.execute(
            """
            UPDATE render_kits
            SET campaign_slug=?, title=?, review_video_path=?, caption_path=?, transcript_path=?, checklist_path=?, source_path=?, risk_path=?, is_demo=0
            WHERE id=?
            """,
            (
                project_slug,
                kit_title,
                str(review_video),
                str(artifacts["caption"]),
                str(artifacts["transcript"]),
                str(artifacts["checklist"]),
                str(artifacts["source"]),
                str(artifacts["risk"]),
                kit_id,
            ),
        )
    else:
        kit_id = db.create_render_kit(
            nomination_id,
            kit_title,
            review_video,
            artifacts["caption"],
            artifacts["transcript"],
            artifacts["checklist"],
            artifacts["source"],
            artifacts["risk"],
            is_demo=False,
            campaign_slug=project_slug,
        )
    db.log_audit("worker", "render_evidence_review_kit", "render_kit", kit_id, "created evidence-backed non-demo review kit", str(review_video))
    return {
        "status": "succeeded",
        "reused_existing": bool(existing_kit),
        "clip_id": str(clip["id"]),
        "title": kit_title,
        "kit_id": kit_id,
        "nomination_id": nomination_id,
        "source_url": str(clip.get("source_url", "")),
        "local_media_path": str(media_path),
        "review_video_path": str(review_video),
        "kit_dir": str(kit_dir),
        "profile": profile,
        "caption_variant": rendered_text.get("caption_style", {}).get("ab_variant", ""),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--clip-id", default="", help="Specific clip candidate id to backfill and render.")
    parser.add_argument("--campaign-slug", default="", choices=["", *db.active_campaign_project_slugs()], help="Active source-backed campaign project to build from.")
    parser.add_argument(
        "--profile",
        default="evidence_review_v1",
        choices=["evidence_review_v1", "selected_feeder_final_v1", db.CAMPAIGN_SHORT_PROFILE],
        help="Review profile to render. Evidence kits remain review artifacts until final campaign fit and human approval are proven elsewhere.",
    )
    parser.add_argument("--force", action="store_true", help="Rerender even when an existing green kit already satisfies the profile.")
    parser.add_argument("--caption-variant", default="", choices=["", "A", "B", "D", "E"], help="Production A/B caption treatment. C is intentionally excluded.")
    args = parser.parse_args()
    result = build_review_kit(args.clip_id, args.profile, args.campaign_slug, force=args.force, caption_variant=args.caption_variant)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
