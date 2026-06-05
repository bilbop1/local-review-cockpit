#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from script.build_evidence_review_kit import headline_card, top_hook_card_font


REFERENCE_PHRASE = "Max got tired of Jason and Silky green screening his stream"
DEFAULT_REFERENCE_FRAME = ROOT / "artifacts" / "review-kit-audit" / "top-typography-audit" / "reference-frame-1080.jpg"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "review-kit-audit" / "top-typography-audit" / "reference-audit"
TOP_CARD_REGION = (60, 292, 1020, 536)


def bbox(points: Iterable[Tuple[int, int]]) -> list[int] | None:
    items = list(points)
    if not items:
        return None
    xs = [point[0] for point in items]
    ys = [point[1] for point in items]
    return [min(xs), min(ys), max(xs) + 1, max(ys) + 1]


def measure_reference(image: Image.Image) -> Dict[str, Any]:
    crop = image.crop(TOP_CARD_REGION).convert("RGB")
    pixels = crop.load()
    white_points = []
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b = pixels[x, y]
            if r >= 246 and g >= 246 and b >= 246:
                white_points.append((x + TOP_CARD_REGION[0], y + TOP_CARD_REGION[1]))
    card = bbox(white_points)
    if not card:
        raise RuntimeError("reference top card could not be measured")
    return measure_text_in_region(image.convert("RGBA"), card, alpha_required=False, white_threshold=True)


def measure_overlay(image: Image.Image) -> Dict[str, Any]:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    alpha_pixels = alpha.load()
    points = []
    for y in range(rgba.height):
        for x in range(rgba.width):
            if alpha_pixels[x, y] >= 80:
                points.append((x, y))
    card = bbox(points)
    if not card:
        raise RuntimeError("production top card overlay has no visible pixels")
    return measure_text_in_region(rgba, card, alpha_required=True, white_threshold=False)


def measure_text_in_region(image: Image.Image, card: list[int], *, alpha_required: bool, white_threshold: bool) -> Dict[str, Any]:
    pixels = image.load()
    left, top, right, bottom = card
    text_points = []
    for y in range(top + 4, bottom - 4):
        for x in range(left + 4, right - 4):
            r, g, b, a = pixels[x, y]
            if alpha_required and a < 140:
                continue
            if white_threshold:
                if r > 242 and g > 242 and b > 242:
                    continue
            elif r > 245 and g > 245 and b > 245:
                continue
            if r < 112 and g < 112 and b < 112 and max(r, g, b) - min(r, g, b) < 64:
                text_points.append((x, y))
    text = bbox(text_points)
    if not text:
        raise RuntimeError("top card text could not be measured")
    card_width = right - left
    card_height = bottom - top
    text_width = text[2] - text[0]
    text_height = text[3] - text[1]
    text_area = len(text_points)
    return {
        "card_bbox": card,
        "card_width": card_width,
        "card_height": card_height,
        "card_center_x": (left + right) / 2,
        "text_bbox": text,
        "text_width": text_width,
        "text_height": text_height,
        "text_area": text_area,
        "text_density": text_area / max(1, text_width * text_height),
        "left_pad": text[0] - left,
        "right_pad": right - text[2],
        "top_pad": text[1] - top,
        "bottom_pad": bottom - text[3],
    }


def compare(reference: Dict[str, Any], production: Dict[str, Any]) -> Dict[str, Any]:
    checks = []

    def add(name: str, actual: float, expected: float, tolerance: float) -> None:
        delta = actual - expected
        checks.append(
            {
                "name": name,
                "actual": actual,
                "expected": expected,
                "delta": delta,
                "tolerance": tolerance,
                "ok": abs(delta) <= tolerance,
            }
        )

    add("card_center_x", production["card_center_x"], reference["card_center_x"], 16)
    add("card_top", production["card_bbox"][1], reference["card_bbox"][1], 8)
    add("card_width", production["card_width"], reference["card_width"], 16)
    add("card_height", production["card_height"], reference["card_height"], 18)
    add("text_left", production["text_bbox"][0], reference["text_bbox"][0], 12)
    add("text_top", production["text_bbox"][1], reference["text_bbox"][1], 8)
    add("text_width", production["text_width"], reference["text_width"], 24)
    add("text_height", production["text_height"], reference["text_height"], 8)
    add("top_pad", production["top_pad"], reference["top_pad"], 10)
    add("bottom_pad", production["bottom_pad"], reference["bottom_pad"], 5)
    add("right_pad", production["right_pad"], reference["right_pad"], 14)
    add("text_density", production["text_density"], reference["text_density"], 0.04)
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def write_sheet(reference: Image.Image, production_frame: Image.Image, path: Path) -> None:
    crop_box = (70, 300, 1010, 530)
    scale = 3
    label_h = 48
    rows = [
        ("REFERENCE", reference.crop(crop_box).resize(((crop_box[2] - crop_box[0]) * scale, (crop_box[3] - crop_box[1]) * scale), Image.Resampling.NEAREST)),
        ("PRODUCTION", production_frame.crop(crop_box).resize(((crop_box[2] - crop_box[0]) * scale, (crop_box[3] - crop_box[1]) * scale), Image.Resampling.NEAREST)),
    ]
    sheet = Image.new("RGB", (rows[0][1].width, (rows[0][1].height + label_h) * len(rows)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, image in rows:
        sheet.paste(image.convert("RGB"), (0, y))
        label_top = y + image.height
        draw.rectangle((0, label_top, sheet.width, label_top + label_h), fill=(0, 0, 0))
        draw.text((12, label_top + 14), label, fill=(255, 255, 255), font=ImageFont.load_default())
        y = label_top + label_h
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, quality=95)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit production top hook card against the stored TikTok reference frame.")
    parser.add_argument("--reference-frame", type=Path, default=DEFAULT_REFERENCE_FRAME)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    if not args.reference_frame.exists():
        raise SystemExit(f"reference frame missing: {args.reference_frame}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    reference = Image.open(args.reference_frame).convert("RGBA")
    overlay_path = args.out_dir / "production-title-card.png"
    rendered_hook = headline_card(overlay_path, REFERENCE_PHRASE, "max")
    overlay = Image.open(overlay_path).convert("RGBA")
    production_frame = Image.alpha_composite(reference, overlay)

    reference_metrics = measure_reference(reference)
    production_metrics = measure_overlay(overlay)
    comparison = compare(reference_metrics, production_metrics)
    payload = {
        "ok": comparison["ok"],
        "reference_phrase": REFERENCE_PHRASE,
        "rendered_hook": rendered_hook,
        "font": list(top_hook_card_font(34).getname()),
        "source_space_font_size": 34,
        "reference": reference_metrics,
        "production": production_metrics,
        "comparison": comparison,
        "sheet": str(args.out_dir / "reference-vs-production-top-card-3x.jpg"),
        "overlay": str(overlay_path),
    }
    write_sheet(reference, production_frame, args.out_dir / "reference-vs-production-top-card-3x.jpg")
    output_path = args.out_dir / "top-card-reference-audit.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(output_path)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
