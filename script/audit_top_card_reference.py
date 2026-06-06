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


def line_bboxes(points: Iterable[Tuple[int, int]], *, row_gap: int = 8) -> list[list[int]]:
    items = list(points)
    if not items:
        return []
    rows = sorted({point[1] for point in items})
    groups: list[tuple[int, int]] = []
    start = rows[0]
    previous = rows[0]
    for row in rows[1:]:
        if row - previous > row_gap:
            groups.append((start, previous))
            start = row
        previous = row
    groups.append((start, previous))
    boxes: list[list[int]] = []
    for top, bottom in groups:
        line_points = [point for point in items if top <= point[1] <= bottom]
        line_box = bbox(line_points)
        if line_box:
            boxes.append(line_box)
    return boxes


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
    pixels = rgba.load()
    white_points = []
    shadow_points = []
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, a = pixels[x, y]
            if a >= 80:
                shadow_points.append((x, y))
            if a >= 170 and r >= 245 and g >= 245 and b >= 245:
                white_points.append((x, y))
    card = bbox(white_points)
    if not card:
        raise RuntimeError("production top card overlay has no white card pixels")
    metrics = measure_text_in_region(rgba, card, alpha_required=True, white_threshold=False)
    shadow = bbox(shadow_points)
    if shadow:
        metrics["shadow_bbox"] = shadow
    return metrics


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
            is_dark_text = r < 112 and g < 112 and b < 112 and max(r, g, b) - min(r, g, b) < 64
            is_color_emoji = max(r, g, b) >= 120 and max(r, g, b) - min(r, g, b) >= 50
            if is_dark_text or is_color_emoji:
                text_points.append((x, y))
    text = bbox(text_points)
    if not text:
        raise RuntimeError("top card text could not be measured")
    card_width = right - left
    card_height = bottom - top
    text_width = text[2] - text[0]
    text_height = text[3] - text[1]
    text_area = len(text_points)
    lines = line_bboxes(text_points)
    line_metrics = [
        {
            "bbox": line,
            "center_x": (line[0] + line[2]) / 2,
            "center_delta": ((line[0] + line[2]) / 2) - ((left + right) / 2),
            "width": line[2] - line[0],
        }
        for line in lines
    ]
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
        "line_count": len(line_metrics),
        "line_metrics": line_metrics,
        "max_abs_line_center_delta": max((abs(item["center_delta"]) for item in line_metrics), default=0),
    }


def measure_text_color_split(image: Image.Image, card: list[int]) -> Dict[str, Any]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    left, top, right, bottom = card
    dark_points = []
    color_points = []
    for y in range(top + 4, bottom - 4):
        for x in range(left + 4, right - 4):
            r, g, b, a = pixels[x, y]
            if a < 80:
                continue
            if r > 245 and g > 245 and b > 245:
                continue
            is_dark_text = r < 112 and g < 112 and b < 112 and max(r, g, b) - min(r, g, b) < 64
            is_color_emoji = max(r, g, b) >= 120 and max(r, g, b) - min(r, g, b) >= 50
            if is_dark_text:
                dark_points.append((x, y))
            if is_color_emoji:
                color_points.append((x, y))
    color = bbox(color_points)
    dark = bbox(dark_points)
    payload: Dict[str, Any] = {
        "dark_bbox": dark,
        "dark_area": len(dark_points),
        "emoji_color_bbox": color,
        "emoji_color_area": len(color_points),
    }
    if color:
        payload["emoji_color_width"] = color[2] - color[0]
        payload["emoji_color_height"] = color[3] - color[1]
        payload["emoji_color_center_x"] = (color[0] + color[2]) / 2
    return payload


def measure_ink_profile(image: Image.Image, card: list[int]) -> Dict[str, Any]:
    rgba = image.convert("RGBA")
    pixels = rgba.load()
    left, top, right, bottom = card
    dark_luma = []
    emoji_count = 0
    for y in range(top + 4, bottom - 4):
        for x in range(left + 4, right - 4):
            r, g, b, a = pixels[x, y]
            if a < 80 or (r > 245 and g > 245 and b > 245):
                continue
            is_color_emoji = max(r, g, b) >= 120 and max(r, g, b) - min(r, g, b) >= 50
            if is_color_emoji:
                emoji_count += 1
                continue
            is_dark_text = r < 112 and g < 112 and b < 112 and max(r, g, b) - min(r, g, b) < 64
            if is_dark_text:
                dark_luma.append((r + g + b) / 3)
    if not dark_luma:
        raise RuntimeError("top card ink profile could not be measured")
    values = sorted(dark_luma)
    black_pixels = sum(1 for value in dark_luma if value < 20)
    edge_pixels = len(dark_luma) - black_pixels
    return {
        "dark_text_pixels": len(dark_luma),
        "emoji_pixels": emoji_count,
        "mean_luma": sum(dark_luma) / len(dark_luma),
        "median_luma": values[len(values) // 2],
        "p90_luma": values[max(0, int(len(values) * 0.9) - 1)],
        "black_pixel_ratio": black_pixels / max(1, len(dark_luma)),
        "edge_pixel_ratio": edge_pixels / max(1, len(dark_luma)),
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

    add("card_center_x", production["card_center_x"], reference["card_center_x"], 3)
    add("card_top", production["card_bbox"][1], reference["card_bbox"][1], 0)
    add("card_width", production["card_width"], reference["card_width"], 3)
    add("card_height", production["card_height"], reference["card_height"], 1)
    add("text_left", production["text_bbox"][0], reference["text_bbox"][0], 2)
    add("text_top", production["text_bbox"][1], reference["text_bbox"][1], 1)
    add("text_width", production["text_width"], reference["text_width"], 3)
    add("text_height", production["text_height"], reference["text_height"], 2)
    add("top_pad", production["top_pad"], reference["top_pad"], 1)
    add("bottom_pad", production["bottom_pad"], reference["bottom_pad"], 1)
    add("right_pad", production["right_pad"], reference["right_pad"], 3)
    add("text_density", production["text_density"], reference["text_density"], 0.006)
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def compare_emoji(reference: Dict[str, Any], production: Dict[str, Any]) -> Dict[str, Any]:
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

    ref_box = reference.get("emoji_color_bbox")
    prod_box = production.get("emoji_color_bbox")
    if not ref_box or not prod_box:
        return {"ok": False, "checks": [{"name": "emoji_color_bbox", "ok": False, "reason": "missing emoji color bbox"}]}
    add("emoji_color_left", prod_box[0], ref_box[0], 5)
    add("emoji_color_top", prod_box[1], ref_box[1], 2)
    add("emoji_color_bottom", prod_box[3], ref_box[3], 3)
    add("emoji_color_center_x", production["emoji_color_center_x"], reference["emoji_color_center_x"], 4)
    add("emoji_color_width", production["emoji_color_width"], reference["emoji_color_width"], 8)
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def compare_ink_profile(reference: Dict[str, Any], production: Dict[str, Any]) -> Dict[str, Any]:
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

    add("mean_luma", production["mean_luma"], reference["mean_luma"], 3.5)
    add("black_pixel_ratio", production["black_pixel_ratio"], reference["black_pixel_ratio"], 0.04)
    add("edge_pixel_ratio", production["edge_pixel_ratio"], reference["edge_pixel_ratio"], 0.04)
    add("p90_luma", production["p90_luma"], reference["p90_luma"], 11)
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def compare_line_centering(production: Dict[str, Any], *, tolerance: float = 12.0) -> Dict[str, Any]:
    checks = []
    lines = production.get("line_metrics", [])
    if not lines:
        return {"ok": False, "checks": [{"name": "line_metrics", "ok": False, "reason": "no detected text lines"}]}
    for index, line in enumerate(lines, start=1):
        delta = float(line.get("center_delta", 999))
        checks.append(
            {
                "name": f"line_{index}_center_delta",
                "actual": delta,
                "expected": 0,
                "delta": delta,
                "tolerance": tolerance,
                "ok": abs(delta) <= tolerance,
            }
        )
    return {"ok": all(check["ok"] for check in checks), "checks": checks}


def _textish_pixel(r: int, g: int, b: int, a: int = 255) -> bool:
    if a < 80:
        return False
    if r > 245 and g > 245 and b > 245:
        return False
    is_dark_text = r < 112 and g < 112 and b < 112 and max(r, g, b) - min(r, g, b) < 64
    is_color_emoji = max(r, g, b) >= 120 and max(r, g, b) - min(r, g, b) >= 50
    return is_dark_text or is_color_emoji


def _dilated(points: set[tuple[int, int]], radius: int = 1) -> set[tuple[int, int]]:
    output: set[tuple[int, int]] = set()
    for x, y in points:
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                output.add((x + dx, y + dy))
    return output


def masked_card_similarity(reference: Image.Image, production: Image.Image, card: list[int]) -> Dict[str, Any]:
    ref = reference.convert("RGBA")
    prod = production.convert("RGBA")
    ref_pixels = ref.load()
    prod_pixels = prod.load()
    left, top, right, bottom = card
    ref_text: set[tuple[int, int]] = set()
    prod_text: set[tuple[int, int]] = set()
    text_union: set[tuple[int, int]] = set()
    background_diff = 0.0
    background_count = 0
    for y in range(top + 4, bottom - 4):
        for x in range(left + 4, right - 4):
            rr, rg, rb, ra = ref_pixels[x, y]
            pr, pg, pb, pa = prod_pixels[x, y]
            ref_is_text = _textish_pixel(rr, rg, rb, ra)
            prod_is_text = _textish_pixel(pr, pg, pb, pa)
            if ref_is_text:
                ref_text.add((x, y))
            if prod_is_text:
                prod_text.add((x, y))
            if ref_is_text or prod_is_text:
                text_union.add((x, y))
            else:
                background_diff += (abs(rr - pr) + abs(rg - pg) + abs(rb - pb)) / 3
                background_count += 1
    text_diff = 0.0
    for x, y in text_union:
        rr, rg, rb, _ = ref_pixels[x, y]
        pr, pg, pb, _ = prod_pixels[x, y]
        text_diff += (abs(rr - pr) + abs(rg - pg) + abs(rb - pb)) / 3
    exact_overlap = len(ref_text & prod_text)
    prod_dilated = _dilated(prod_text, radius=1)
    ref_dilated = _dilated(ref_text, radius=1)
    ref_near_prod = sum(1 for point in ref_text if point in prod_dilated)
    prod_near_ref = sum(1 for point in prod_text if point in ref_dilated)
    return {
        "ref_text_pixels": len(ref_text),
        "production_text_pixels": len(prod_text),
        "text_pixel_delta": len(prod_text) - len(ref_text),
        "text_union_pixels": len(text_union),
        "exact_text_overlap_ratio": exact_overlap / max(1, len(ref_text | prod_text)),
        "ref_near_production_ratio": ref_near_prod / max(1, len(ref_text)),
        "production_near_reference_ratio": prod_near_ref / max(1, len(prod_text)),
        "masked_text_mad": text_diff / max(1, len(text_union)),
        "card_background_mad": background_diff / max(1, background_count),
    }


def compare_visual_similarity(similarity: Dict[str, Any]) -> Dict[str, Any]:
    checks = []

    def add(name: str, actual: float, expected: float, tolerance: float, *, minimum: bool = False, maximum: bool = False) -> None:
        if minimum:
            ok = actual >= expected
            delta = actual - expected
        elif maximum:
            ok = actual <= expected
            delta = actual - expected
        else:
            delta = actual - expected
            ok = abs(delta) <= tolerance
        checks.append(
            {
                "name": name,
                "actual": actual,
                "expected": expected,
                "delta": delta,
                "tolerance": tolerance,
                "ok": ok,
            }
        )

    add("text_pixel_delta", similarity["text_pixel_delta"], 0, 260)
    add("ref_near_production_ratio", similarity["ref_near_production_ratio"], 0.772, 0, minimum=True)
    add("production_near_reference_ratio", similarity["production_near_reference_ratio"], 0.780, 0, minimum=True)
    add("masked_text_mad", similarity["masked_text_mad"], 121, 0, maximum=True)
    add("card_background_mad", similarity["card_background_mad"], 7.5, 0, maximum=True)
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
    reference_color = measure_text_color_split(reference, reference_metrics["card_bbox"])
    production_color = measure_text_color_split(production_frame, production_metrics["card_bbox"])
    emoji_comparison = compare_emoji(reference_color, production_color)
    reference_ink = measure_ink_profile(reference, reference_metrics["card_bbox"])
    production_ink = measure_ink_profile(production_frame, production_metrics["card_bbox"])
    ink_comparison = compare_ink_profile(reference_ink, production_ink)
    line_centering = compare_line_centering(production_metrics)
    visual_similarity = masked_card_similarity(reference, production_frame, reference_metrics["card_bbox"])
    visual_comparison = compare_visual_similarity(visual_similarity)
    payload = {
        "ok": comparison["ok"] and emoji_comparison["ok"] and ink_comparison["ok"] and line_centering["ok"] and visual_comparison["ok"],
        "reference_phrase": REFERENCE_PHRASE,
        "rendered_hook": rendered_hook,
        "font": list(top_hook_card_font(34).getname()),
        "source_space_font_size": 34,
        "reference": reference_metrics,
        "production": production_metrics,
        "reference_color": reference_color,
        "production_color": production_color,
        "reference_ink": reference_ink,
        "production_ink": production_ink,
        "comparison": comparison,
        "emoji_comparison": emoji_comparison,
        "ink_comparison": ink_comparison,
        "line_centering": line_centering,
        "visual_similarity": visual_similarity,
        "visual_comparison": visual_comparison,
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
