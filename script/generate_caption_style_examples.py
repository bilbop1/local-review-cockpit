#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.caption_style import CAPTION_FONT_SIZE, CAPTION_VERTICAL_CENTER_Y, caption_font, caption_lines, caption_style_manifest


OUT_DIR = ROOT / "artifacts" / "caption-style-examples" / "caption-variants-v4"
FRAME_PATH = OUT_DIR / "source-frame.jpg"


def run(command: List[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=60)


def source_frame() -> Image.Image:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    kits = db.visible_render_kits()
    if not kits:
        active_slugs = tuple(db.active_campaign_project_slugs())
        placeholders = ",".join("?" for _ in active_slugs) or "''"
        kits = db.rows(
            f"SELECT review_video_path FROM render_kits WHERE campaign_slug IN ({placeholders}) ORDER BY created_at DESC",
            active_slugs,
        )
    for kit in kits:
        video = Path(str(kit.get("review_video_path", "")))
        thumbnail = video.parent / "thumbnail.jpg"
        if thumbnail.exists():
            return Image.open(thumbnail).convert("RGB").resize((1080, 1920))
        if video.exists():
            result = run(["ffmpeg", "-y", "-ss", "1.15", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(FRAME_PATH)])
            if result.returncode == 0 and FRAME_PATH.exists():
                return Image.open(FRAME_PATH).convert("RGB").resize((1080, 1920))
    image = Image.new("RGB", (1080, 1920), (28, 31, 38))
    draw = ImageDraw.Draw(image)
    for y in range(1920):
        color = (22 + y // 90, 27 + y // 120, 36 + y // 100)
        draw.line((0, y, 1080, y), fill=color)
    return image


def text_box(draw: ImageDraw.ImageDraw, text: str, size: int = CAPTION_FONT_SIZE) -> Tuple[List[str], object, int, int]:
    font = caption_font(size)
    lines = caption_lines(draw, text, font, 930, max_lines=1)
    height = sum(_bbox_size(draw, line, font, stroke_width=7)[1] for line in lines) + max(0, len(lines) - 1) * 14
    return lines, font, 540, CAPTION_VERTICAL_CENTER_Y - height // 2


def _bbox_size(draw: ImageDraw.ImageDraw, text: str, font, stroke_width: int = 0) -> Tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_text_at_visual_top(draw: ImageDraw.ImageDraw, text: str, visual_left: int, visual_top: int, font, fill, stroke=None, stroke_width: int = 0) -> None:
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    x = visual_left - bbox[0]
    y = visual_top - bbox[1]
    kwargs = {"font": font, "fill": fill}
    if stroke is not None and stroke_width:
        kwargs.update({"stroke_width": stroke_width, "stroke_fill": stroke})
    draw.text((x, y), text, **kwargs)


def draw_centered_stroke(draw: ImageDraw.ImageDraw, lines: List[str], font, top: int, fill, stroke, stroke_width: int = 6) -> None:
    y = top
    for line in lines:
        width, height = _bbox_size(draw, line, font, stroke_width=stroke_width)
        x = (1080 - width) // 2
        _draw_text_at_visual_top(draw, line, x, y, font, fill, stroke, stroke_width)
        y += height + 10


def draw_capsule(draw: ImageDraw.ImageDraw, lines: List[str], font, top: int, fill, bg, stroke=None) -> None:
    y = top
    for line in lines:
        width, height = _bbox_size(draw, line, font, stroke_width=0)
        pad_x = 28
        pad_y = 18
        left = (1080 - width) // 2 - pad_x
        draw.rounded_rectangle((left, y - pad_y, left + width + pad_x * 2, y + height + pad_y), radius=14, fill=bg)
        if stroke:
            draw.rounded_rectangle((left, y - pad_y, left + width + pad_x * 2, y + height + pad_y), radius=14, outline=stroke, width=3)
        _draw_text_at_visual_top(draw, line, (1080 - width) // 2, y, font, fill)
        y += height + 30


def draw_yellow_keyword(draw: ImageDraw.ImageDraw, text: str, font, top: int) -> None:
    words = text.split()
    if len(words) != 2:
        draw_centered_stroke(draw, [text], font, top, (255, 224, 0, 255), (0, 0, 0, 245), 6)
        return
    gap = 16
    stroke_width = 6
    first_w, first_h = _bbox_size(draw, words[0], font, stroke_width)
    second_w, second_h = _bbox_size(draw, words[1], font, stroke_width)
    total_w = first_w + gap + second_w
    left = (1080 - total_w) // 2
    y = top
    _draw_text_at_visual_top(draw, words[0], left, y, font, (255, 255, 255, 255), (0, 0, 0, 245), stroke_width)
    _draw_text_at_visual_top(draw, words[1], left + first_w + gap, y, font, (255, 224, 0, 255), (0, 0, 0, 245), stroke_width)


def make_variant(base: Image.Image, key: str, name: str, text: str, mode: str) -> Dict[str, str]:
    image = base.copy().convert("RGBA")
    veil = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(veil, "RGBA")
    lines, font, _, top = text_box(draw, text)

    if mode == "classic":
        draw_centered_stroke(draw, lines, font, top, (255, 255, 255, 255), (0, 0, 0, 245), 6)
    elif mode == "yellow-keyword":
        draw_yellow_keyword(draw, text, font, top)
    elif mode == "black-capsule":
        draw_capsule(draw, lines, font, top, (255, 255, 255, 255), (0, 0, 0, 192))
    elif mode == "white-card":
        draw_capsule(draw, lines, font, top, (12, 12, 12, 255), (255, 255, 255, 245), stroke=(0, 0, 0, 44))
    elif mode == "neon-shadow":
        draw_centered_stroke(draw, lines, font, top + 4, (0, 210, 255, 120), (255, 0, 112, 100), 4)
        draw_centered_stroke(draw, lines, font, top, (255, 255, 255, 255), (0, 0, 0, 245), 5)
        width, height = _bbox_size(draw, lines[0], font, 5)
        x = (1080 - width) // 2
        draw.rounded_rectangle((x, top + height + 11, x + width, top + height + 18), radius=4, fill=(0, 210, 255, 220))

    image.alpha_composite(veil)
    path = OUT_DIR / f"caption-style-{key}.png"
    image.convert("RGB").save(path, quality=94)
    return {"key": key, "name": name, "mode": mode, "path": str(path)}


def main() -> int:
    base = source_frame()
    examples = [
        ("A", "Native Classic", "THIS PART", "classic"),
        ("B", "Yellow Punch", "WATCH THIS", "yellow-keyword"),
        ("C", "Black Capsule", "THAT HIT", "black-capsule"),
        ("D", "White Card", "MARKET MOVED", "white-card"),
        ("E", "Neon Shadow", "WAIT HERE", "neon-shadow"),
    ]
    payload = {
        "generated_at": db.utc_now(),
        "caption_style": caption_style_manifest(),
        "examples": [make_variant(base, key, name, text, mode) for key, name, text, mode in examples],
    }
    manifest = OUT_DIR / "caption-style-examples.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
