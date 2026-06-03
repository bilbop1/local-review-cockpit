from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from . import database as db
from .caption_style import CAPTION_FONT_SIZE, CAPTION_VERTICAL_CENTER_Y, caption_font, caption_lines


DEMO_SOURCES = [
    Path("/Users/bilbop/Downloads/hermes-instagram/mo_ferocious-DUmTuGCAaEk-discord.mp4"),
    Path("/Users/bilbop/Downloads/hermes-instagram/mo_ferocious-DUmTuGCAaEk.mp4"),
]


@dataclass(frozen=True)
class RenderStyle:
    slug: str
    title_suffix: str
    headline: str
    subhead: str
    caption_beats: tuple[tuple[float, float, str], ...]
    status: str
    critique: tuple[str, ...]


RENDER_STYLES = [
    RenderStyle(
        slug="demo-safe",
        title_suffix="Demo Safe",
        headline="LOCAL DEMO KIT",
        subhead="review only - no posting",
        caption_beats=((0.0, 2.4, "LOCAL DEMO"), (2.4, 5.2, "REVIEW FIRST")),
        status="yellow",
        critique=(
            "This is safe and legible, but it is not competitive Shorts packaging.",
            "The visible demo labeling is useful for proof, not for a production edit.",
        ),
    ),
    RenderStyle(
        slug="ishouldclip-inspired-a",
        title_suffix="Reference Style A",
        headline="WATCH THE TURN",
        subhead="style study - local demo",
        caption_beats=((0.0, 2.2, "WAIT FOR IT"), (2.2, 4.8, "THEN IT TURNS"), (4.8, 7.8, "REVIEW ONLY")),
        status="yellow",
        critique=(
            "Closer to the reference: compact headline card, central source crop, and side-fill background.",
            "Still yellow because the source is demo media and the captions are heuristic rather than transcript-timed.",
        ),
    ),
    RenderStyle(
        slug="ishouldclip-inspired-b",
        title_suffix="Reference Style B",
        headline="THIS PART NEEDS A CLIP",
        subhead="fast caption pass - local demo",
        caption_beats=((0.0, 1.6, "THIS PART"), (1.6, 3.1, "NEEDS A CLIP"), (3.1, 5.0, "CUT TIGHTER"), (5.0, 7.2, "HUMAN REVIEW")),
        status="yellow",
        critique=(
            "Most aggressive local variant: shorter caption beats and stronger hook language.",
            "Still not green until a real selected-feeder source, real transcript timing, and campaign fit are validated.",
        ),
    ),
    RenderStyle(
        slug="selected-feeder-a",
        title_suffix="Selected Feeder A",
        headline="WATCH THE TURN",
        subhead="selected feeder - manual review",
        caption_beats=((0.0, 1.6, "WAIT FOR IT"), (1.6, 3.8, "THEN IT TURNS"), (3.8, 6.0, "REVIEW ONLY")),
        status="yellow",
        critique=(
            "Real selected-feeder source is present with stored source URL and local media provenance.",
            "Still yellow until transcript timing, campaign-specific final fit, and human review are complete.",
        ),
    ),
]

DEMO_STYLE_SLUGS = {"demo-safe", "ishouldclip-inspired-a", "ishouldclip-inspired-b"}


REFERENCE_RUBRIC = [
    "Punchy headline in a white rounded card near the top safe zone.",
    "Central vertical source framing with blurred or extended side fill when the source is narrow.",
    "Bold high-contrast captions that change quickly and do not cover the face/action.",
    "Small source/brand watermark, never a giant internal operations banner.",
    "No publishing implication: demo/proof outputs must remain visibly blocked from posting.",
]


def _run(command: List[str], timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def ffprobe_duration(path: Path) -> float:
    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        timeout=30,
    )
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or "ffprobe failed")
    return float(probe.stdout.strip() or 0)


def validate_video(path: Path) -> Dict[str, object]:
    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
    )
    if probe.returncode != 0:
        raise RuntimeError(probe.stderr.strip() or "ffprobe validation failed")
    return json.loads(probe.stdout)


def media_root() -> Path:
    root = db.source_media_root() / "selected_feeders"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _font(size: int):
    return caption_font(size)


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, stroke_width: int = 0) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    stroke: int = 0,
    stroke_fill: tuple[int, int, int, int] = (0, 0, 0, 0),
) -> None:
    width, _ = _text_size(draw, text, font, stroke)
    draw.text(((1080 - width) // 2, y), text, font=font, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)


def _draw_headline_card(draw: ImageDraw.ImageDraw, text: str, y: int, font: ImageFont.ImageFont) -> None:
    lines = text.split("\n")
    line_sizes = [_text_size(draw, line, font) for line in lines]
    width = max(size[0] for size in line_sizes)
    line_height = max(size[1] for size in line_sizes) + 10
    card_width = min(900, width + 54)
    card_height = line_height * len(lines) + 26
    left = (1080 - card_width) // 2
    draw.rounded_rectangle((left, y, left + card_width, y + card_height), radius=18, fill=(255, 255, 255, 248))
    current_y = y + 13
    for line in lines:
        line_width, _ = _text_size(draw, line, font)
        draw.text((left + (card_width - line_width) // 2, current_y), line, font=font, fill=(16, 16, 16, 255))
        current_y += line_height


def make_overlay(path: Path, style: RenderStyle) -> None:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, 1080, 128), fill=(0, 0, 0, 74))
    _draw_headline_card(draw, style.headline, 150, _font(44 if len(style.headline) > 18 else 52))
    draw.text((452, 912), "ClippingOps", font=_font(20), fill=(255, 255, 255, 190), stroke_width=2, stroke_fill=(0, 0, 0, 160))

    if style.slug == "demo-safe":
        draw.rounded_rectangle((62, 1628, 1018, 1752), radius=18, fill=(0, 0, 0, 120))
        _draw_centered(draw, "DEMO ONLY - HUMAN REVIEW", 1660, _font(46), (255, 255, 255, 255), 3, (0, 0, 0, 210))
    else:
        draw.rounded_rectangle((120, 1642, 960, 1734), radius=18, fill=(0, 0, 0, 128))
        _draw_centered(draw, style.subhead.upper(), 1668, _font(34), (255, 255, 255, 245), 2, (0, 0, 0, 210))
    image.save(path)


def make_caption_overlay(path: Path, text: str, y: int, font_size: int) -> None:
    image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image, "RGBA")
    font = _font(font_size)
    lines = caption_lines(draw, text, font, 930, max_lines=2) or [text]
    total_height = sum(_text_size(draw, line, font, stroke_width=6)[1] for line in lines) + max(0, len(lines) - 1) * 10
    top = y - total_height // 2
    for line in lines:
        width, height = _text_size(draw, line, font, stroke_width=6)
        x = max(24, (1080 - width) // 2)
        draw.text((x, top), line, font=font, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(0, 0, 0, 245))
        top += height + 10
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _caption_filter(input_label: str, style: RenderStyle, first_input_index: int) -> tuple[str, str, List[Path]]:
    current = input_label
    filters: List[str] = []
    caption_paths: List[Path] = []
    for index, (start, end, text) in enumerate(style.caption_beats, start=1):
        out = f"cap{index}"
        size = 76 if len(text) <= 12 else 64
        y = 292 if index % 2 else 374
        caption_paths.append(Path(f"caption_{index}.png"))
        input_index = first_input_index + index - 1
        filters.append(f"[{current}][{input_index}:v]overlay=0:0:format=auto:enable='between(t,{start:.2f},{end:.2f})'[{out}]")
        current = out
    return ";".join(filters), current, caption_paths


def render_demo_video(source: Path, output: Path, title: str, style: RenderStyle) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    overlay = output.parent / "overlay.png"
    make_overlay(overlay, style)
    caption_inputs: List[Path] = []
    for index, (_, _, text) in enumerate(style.caption_beats, start=1):
        path = output.parent / f"caption_{index}.png"
        make_caption_overlay(path, text, CAPTION_VERTICAL_CENTER_Y, CAPTION_FONT_SIZE if len(text) <= 12 else CAPTION_FONT_SIZE - 6)
        caption_inputs.append(path)
    if style.slug == "demo-safe":
        base = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[base];[base][1:v]overlay=0:0:format=auto[v0]"
    else:
        base = (
            "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
            "boxblur=24:2,eq=brightness=-0.18:saturation=0.86,setsar=1[bg];"
            "[0:v]scale=900:1600:force_original_aspect_ratio=decrease,setsar=1[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];[base][1:v]overlay=0:0:format=auto[v0]"
        )
    captions, final_label, _ = _caption_filter("v0", style, 2)
    filtergraph = f"{base};{captions};[{final_label}]null[v]" if captions else f"{base};[v0]null[v]"
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(source),
        "-i",
        str(overlay),
    ]
    for caption_input in caption_inputs:
        command.extend(["-i", str(caption_input)])
    command.extend([
        "-filter_complex",
        filtergraph,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
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
        str(output),
    ])
    result = _run(command)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-4000:] or "ffmpeg render failed")
    metadata = validate_video(output)
    streams = metadata.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
    if int(video_stream.get("width", 0)) != 1080 or int(video_stream.get("height", 0)) != 1920:
        raise RuntimeError(f"render output has unexpected dimensions: {video_stream}")


def write_json(path: Path, payload: Dict[str, object]) -> None:
    write_text(path, json.dumps(payload, indent=2) + "\n")


def extract_thumbnail(video: Path, output: Path) -> None:
    result = _run(["ffmpeg", "-y", "-ss", "00:00:02", "-i", str(video), "-frames:v", "1", "-update", "1", str(output)], timeout=60)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:] or "thumbnail extraction failed")
    with Image.open(output) as frame:
        extrema = frame.convert("L").getextrema()
    if extrema[0] == extrema[1]:
        raise RuntimeError(f"thumbnail is blank: {output}")


def extract_contact_sheet(video: Path, output: Path) -> None:
    result = _run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(video),
            "-vf",
            "fps=1,scale=216:384,tile=5x1",
            "-frames:v",
            "1",
            str(output),
        ],
        timeout=90,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-1200:] or "contact sheet extraction failed")


def write_style_critique(path: Path, style: RenderStyle, source: Path, metadata: Dict[str, object]) -> None:
    rubric = "\n".join(f"- {item}" for item in REFERENCE_RUBRIC)
    critique = "\n".join(f"- {item}" for item in style.critique)
    write_text(
        path,
        "\n".join(
            [
                "# Style Critique",
                "",
                f"Status: {style.status}",
                f"Profile: {style.slug}",
                f"Source: `{source}`",
                "",
                "## Reference Rubric",
                rubric,
                "",
                "## Anti-Sycophant Notes",
                critique,
                "",
                "## Validation",
                f"- ffprobe streams: {len(metadata.get('streams', []))}",
                "- This file is a local review artifact. It is not an approval to post.",
                "",
            ]
        ),
    )


def _style_by_slug(slug: str) -> RenderStyle:
    return next((style for style in RENDER_STYLES if style.slug == slug), RENDER_STYLES[1])


def _demo_styles() -> List[RenderStyle]:
    return [style for style in RENDER_STYLES if style.slug in DEMO_STYLE_SLUGS]


def write_render_text_manifest(path: Path, style: RenderStyle, notes: str) -> None:
    write_json(
        path,
        {
            "profile": style.slug,
            "rendered_text": {
                "headline": style.headline,
                "subhead": style.subhead,
                "caption_beats": [text for _, _, text in style.caption_beats],
            },
            "internal_tokens_blocked": [],
            "style_reference": "https://www.youtube.com/@IShouldClip/shorts",
            "notes": notes,
        },
    )


def download_candidate_media(candidate: Dict[str, object]) -> Path:
    existing_value = str(candidate.get("local_media_path", "")).strip()
    existing = Path(existing_value) if existing_value else None
    if existing and existing.exists() and existing.is_file():
        return existing
    ytdlp = shutil.which("yt-dlp") or str(Path(__file__).resolve().parents[1] / ".venv" / "bin" / "yt-dlp")
    if not Path(ytdlp).exists():
        raise RuntimeError("yt-dlp is missing from the managed backend runtime")
    output_template = str(media_root() / f"{candidate['id']}.%(ext)s")
    command = [
        ytdlp,
        "--no-playlist",
        "--format",
        "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format",
        "mp4",
        "--output",
        output_template,
        str(candidate["source_url"]),
    ]
    result = _run(command, timeout=240)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[-2400:] or "yt-dlp selected-feeder download failed")
    downloaded = sorted(media_root().glob(f"{candidate['id']}.*"), key=lambda item: item.stat().st_mtime, reverse=True)
    if not downloaded:
        raise RuntimeError("yt-dlp reported success but no local media file was found")
    local_path = downloaded[0]
    db.update_clip_media(str(candidate["id"]), local_path, "yt_dlp_fallback", ["source_download_verified", "manual_review_required"])
    return local_path


def create_selected_feeder_kits(limit: int = 2, style_slug: str = "selected-feeder-a") -> Dict[str, object]:
    db.init_db()
    if db.latest_campaign_gate().get("status") != "qualified":
        blocker = "Campaign gate must be qualified before non-demo selected-feeder renders."
        db.create_job("selected-feeder-render", "render", "blocked", "campaign-gate", 0, error=blocker)
        return {"status": "blocked", "created": [], "blocker": blocker}
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        blocker = "ffmpeg and ffprobe are required before selected-feeder render kits can be created."
        db.create_job("selected-feeder-render", "render", "blocked", "preflight", 0, error=blocker)
        return {"status": "blocked", "created": [], "blocker": blocker}

    candidates = db.rows(
        """
        SELECT * FROM clip_candidates
        WHERE risk_flags_json LIKE '%selected_feeder_%'
        ORDER BY view_count DESC, discovered_at DESC
        LIMIT ?
        """,
        (max(limit * 4, 8),),
    )
    if not candidates:
        blocker = "No selected-feeder clip candidates are stored yet."
        db.create_job("selected-feeder-render", "render", "blocked", "source-discovery", 0, error=blocker)
        return {"status": "blocked", "created": [], "blocker": blocker}

    style = _style_by_slug(style_slug)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    created: List[Dict[str, str]] = []
    job_id = db.create_job("selected-feeder-render", "render", "running", "source-download", 30, logs="Rendering evidence-backed selected-feeder review kits.")
    blockers: List[str] = []
    for candidate in candidates:
        if len(created) >= limit:
            break
        if not db.is_relevant_streamer_clip(candidate):
            blockers.append(f"{candidate.get('id')}: skipped irrelevant/off-target review source")
            continue
        kit_dir: Optional[Path] = None
        try:
            existing_kits = db.rows(
                """
                SELECT render_kits.*
                FROM render_kits
                JOIN render_nominations ON render_kits.nomination_id = render_nominations.id
                WHERE render_kits.is_demo = 0
                  AND render_nominations.clip_candidate_ids_json = ?
                ORDER BY render_kits.created_at DESC
                LIMIT 20
                """,
                (json.dumps([str(candidate["id"])]),),
            )
            reused_existing = False
            for existing_kit in existing_kits:
                existing_video = Path(str(existing_kit.get("review_video_path", "")))
                if (
                    existing_video.exists()
                    and style.slug in str(existing_video.parent)
                    and not db.contains_irrelevant_review_token(existing_kit.get("title"), existing_video)
                ):
                    created.append(
                        {
                            "kit_id": str(existing_kit["id"]),
                            "title": str(existing_kit.get("title", "")),
                            "source_url": str(candidate.get("source_url", "")),
                            "review_video_path": str(existing_video),
                            "style_critique_path": str(existing_video.parent / "style_critique.md"),
                            "contact_sheet_path": str(existing_video.parent / "contact_sheet.jpg"),
                            "reused": "true",
                        }
                    )
                    reused_existing = True
                    break
            if reused_existing:
                continue
            local_source = download_candidate_media(candidate)
            duration = ffprobe_duration(local_source)
            title = f"Selected Feeder Review - {candidate.get('title') or candidate['id']}"
            transcript_text = (
                f"Selected-feeder review kit from {candidate.get('source_platform')} source metadata. "
                "Media was fetched through a labeled yt-dlp fallback route for local review only. "
                "This does not publish, submit, or imply campaign approval."
            )
            db.create_transcript(str(candidate["id"]), transcript_text, provider="selected-feeder-placeholder")
            db.create_score(str(candidate["id"]), "Selected feeder clip candidate with stored campaign gate, source URL, and local media availability.")
            nomination_id = db.create_nomination(
                str(candidate["id"]),
                title,
                "Selected feeder candidate rendered for manual review.",
                target_style=style.slug,
                status="rendered_non_demo",
            )

            safe_title = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(candidate["id"]))[:48]
            kit_dir = db.render_root() / f"{stamp}-selected-{safe_title}-{style.slug}"
            review_video = kit_dir / "review.mp4"
            caption = kit_dir / "caption.txt"
            transcript = kit_dir / "transcript.txt"
            checklist = kit_dir / "checklist.md"
            source_doc = kit_dir / "source.md"
            risk = kit_dir / "risk.md"
            ffprobe_doc = kit_dir / "ffprobe.json"
            thumbnail = kit_dir / "thumbnail.jpg"
            contact_sheet = kit_dir / "contact_sheet.jpg"
            critique = kit_dir / "style_critique.md"

            render_demo_video(local_source, review_video, title, style)
            metadata = validate_video(review_video)
            write_json(ffprobe_doc, metadata)
            extract_thumbnail(review_video, thumbnail)
            extract_contact_sheet(review_video, contact_sheet)
            write_style_critique(critique, style, local_source, metadata)
            write_text(
                caption,
                "\n".join(
                    [
                        str(candidate.get("title", title)),
                        f"Source: {candidate.get('source_url', '')}",
                        "Selected feeder review kit. Manual approval only. No autonomous publishing.",
                        "",
                    ]
                ),
            )
            write_text(transcript, transcript_text + "\n")
            write_text(
                checklist,
                "\n".join(
                    [
                        "# Review Checklist",
                        "- [x] Campaign gate is qualified.",
                        "- [x] Source URL and selected-feeder provenance are stored.",
                        "- [x] Local media exists and ffprobe validates review output.",
                        "- [x] Thumbnail/contact sheet/style critique exist.",
                        "- [ ] Human approved for manual publishing prep.",
                        "- [ ] Campaign-specific final rules reviewed immediately before posting.",
                    ]
                )
                + "\n",
            )
            write_text(
                source_doc,
                "\n".join(
                    [
                        "# Source",
                        "",
                        f"- Platform: {candidate.get('source_platform', '')}",
                        f"- URL: {candidate.get('source_url', '')}",
                        f"- View count from API metadata: {candidate.get('view_count', 0)}",
                        f"- Local media: `{local_source}`",
                        "- Provenance: official API metadata plus labeled yt-dlp fallback media fetch.",
                        "",
                    ]
                ),
            )
            write_text(
                risk,
                "# Risk\n\n- Not auto-published.\n- yt-dlp fallback must be rechecked against current campaign/source rules before posting.\n- Placeholder transcript; not word-timed.\n- Human approval and final campaign compliance review required.\n",
            )
            kit_id = db.create_render_kit(
                nomination_id,
                title,
                review_video,
                caption,
                transcript,
                checklist,
                source_doc,
                risk,
                is_demo=False,
            )
            db.log_audit("worker", "render_selected_feeder_kit", "render_kit", kit_id, "created selected-feeder review kit", str(review_video))
            created.append(
                {
                    "kit_id": kit_id,
                    "title": title,
                    "source_url": str(candidate.get("source_url", "")),
                    "review_video_path": str(review_video),
                    "style_critique_path": str(critique),
                    "contact_sheet_path": str(contact_sheet),
                }
            )
        except Exception as exc:
            if kit_dir is not None:
                shutil.rmtree(kit_dir, ignore_errors=True)
            blockers.append(f"{candidate.get('id')}: {exc}")

    status = "succeeded" if created else "blocked"
    db.execute(
        "UPDATE job_runs SET status=?, stage=?, progress=100, logs=?, error=?, output_path=?, finished_at=? WHERE id=?",
        (
            status,
            "review-handoff" if created else "source-fetch-blocked",
            f"Created {len(created)} selected-feeder kit(s).",
            "; ".join(blockers)[:1200],
            str(db.render_root()),
            db.utc_now(),
            job_id,
        ),
    )
    return {"status": status, "created": created, "blockers": blockers[:8]}


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def create_demo_kits(limit: int = 3) -> Dict[str, object]:
    db.init_db()
    missing = [str(path) for path in DEMO_SOURCES if not path.exists()]
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        blocker = "ffmpeg and ffprobe are required before demo render kits can be created."
        db.create_job("demo-render", "render", "blocked", "preflight", 0, error=blocker)
        return {"status": "blocked", "created": [], "blocker": blocker, "missing_sources": missing}

    created: List[Dict[str, str]] = []
    sources = [path for path in DEMO_SOURCES if path.exists()][:limit]
    if not sources:
        blocker = "No local demo videos found under /Users/bilbop/Downloads/hermes-instagram."
        db.create_job("demo-render", "render", "blocked", "source-discovery", 0, error=blocker)
        return {"status": "blocked", "created": [], "blocker": blocker, "missing_sources": missing}

    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_id = db.create_job("demo-render", "render", "running", "rendering", 50, logs="Rendering local demo review kits with reference-style variants.")
    for index, source in enumerate(sources, start=1):
        for style in _demo_styles():
            kit_dir: Optional[Path] = None
            try:
                duration = ffprobe_duration(source)
                title = f"Demo Review Kit {index} - {style.title_suffix}"
                kit_dir = db.demo_render_root() / f"{stamp}-demo-{index}-{style.slug}"
                review_video = kit_dir / "review.mp4"
                caption = kit_dir / "caption.txt"
                transcript = kit_dir / "transcript.txt"
                checklist = kit_dir / "checklist.md"
                source_doc = kit_dir / "source.md"
                risk = kit_dir / "risk.md"
                ffprobe_doc = kit_dir / "ffprobe.json"
                thumbnail = kit_dir / "thumbnail.jpg"
                contact_sheet = kit_dir / "contact_sheet.jpg"
                critique = kit_dir / "style_critique.md"
                render_text_manifest = kit_dir / "render_text_manifest.json"

                render_demo_video(source, review_video, title, style)
                metadata = validate_video(review_video)
                write_json(ffprobe_doc, metadata)
                extract_thumbnail(review_video, thumbnail)
                extract_contact_sheet(review_video, contact_sheet)
                write_style_critique(critique, style, source, metadata)
                write_render_text_manifest(
                    render_text_manifest,
                    style,
                    "Demo study manifest. Keep demo/reference variants yellow until real selected-feeder media, transcript timing, and campaign fit are proven.",
                )

                clip_id = db.upsert_clip(source, title, duration)
                transcript_text = (
                    "Demo review kit generated from local media. "
                    "This proves the review-first render path only. "
                    "It is not a Clipping.net campaign submission and must not be posted as campaign output. "
                    f"Render style profile: {style.slug}."
                )
                db.create_transcript(clip_id, transcript_text)
                reason = "Local vertical media is available, short, and suitable for proving the renderer and in-app preview path."
                db.create_score(clip_id, reason)
                nomination_id = db.create_nomination(clip_id, title, reason)

                write_text(
                    caption,
                    "\n".join(
                        [
                            "LOCAL DEMO KIT",
                            f"Style profile: {style.slug}",
                            f"Headline: {style.headline}",
                            "Review-first pipeline proof. Do not publish as campaign output.",
                            "",
                        ]
                    ),
                )
                write_text(transcript, transcript_text + "\n")
                write_text(
                    checklist,
                    "\n".join(
                        [
                            "# Review Checklist",
                            "- [x] Video file exists and ffprobe validates it.",
                            "- [x] Demo-only status is visible.",
                            "- [x] Thumbnail/contact sheet/style critique exist.",
                            "- [ ] Real campaign rules verified.",
                            "- [ ] Source rights/provenance verified.",
                            "- [ ] Human approved for Ready To Post.",
                        ]
                    )
                    + "\n",
                )
                write_text(
                    source_doc,
                    f"# Source\n\nLocal demo source: `{source}`\n\nThis is not a campaign source URL.\n",
                )
                write_text(
                    risk,
                    "# Risk\n\n- Demo-only local media.\n- Not campaign verified.\n- No autonomous publishing allowed.\n- Style is a reference study, not a channel impersonation.\n",
                )
                kit_id = db.create_render_kit(
                    nomination_id,
                    title,
                    review_video,
                    caption,
                    transcript,
                    checklist,
                    source_doc,
                    risk,
                    is_demo=True,
                )
                db.log_audit("worker", "render_demo_kit", "render_kit", kit_id, f"created {style.slug} demo review kit", str(review_video))
                created.append(
                    {
                        "kit_id": kit_id,
                        "title": title,
                        "style_profile": style.slug,
                        "style_status": style.status,
                        "review_video_path": str(review_video),
                        "style_critique_path": str(critique),
                        "contact_sheet_path": str(contact_sheet),
                    }
                )
            except Exception as exc:
                if kit_dir is not None:
                    shutil.rmtree(kit_dir, ignore_errors=True)
                db.create_job("demo-render", "render", "failed", "rendering", 80, error=str(exc))
                db.log_audit("worker", "render_demo_kit", "render_kit", "demo", f"failed: {exc}", str(source))
                return {"status": "failed", "created": created, "blocker": str(exc), "missing_sources": missing}

    db.execute(
        "UPDATE job_runs SET status='succeeded', stage='review-handoff', progress=100, output_path=?, finished_at=? WHERE id=?",
        (str(db.render_root()), db.utc_now(), job_id),
    )
    return {"status": "succeeded", "created": created, "missing_sources": missing}
