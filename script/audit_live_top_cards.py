#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
VERIFY_REPORT = ROOT / "artifacts" / "review-kit-audit" / "burned-caption-verification.json"
REFERENCE_FRAME = ROOT / "artifacts" / "review-kit-audit" / "top-typography-audit" / "reference-frame-1080.jpg"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "review-kit-audit" / "top-typography-audit" / "current-live-top-card-audit"


def run_verifier() -> None:
    subprocess.run([sys.executable, str(ROOT / "script" / "verify_burned_in_captions.py")], check=True, cwd=str(ROOT))


def load_report(refresh: bool) -> Dict[str, Any]:
    if refresh or not VERIFY_REPORT.exists():
        run_verifier()
    return json.loads(VERIFY_REPORT.read_text(encoding="utf-8"))


def sheet_rows(report: Dict[str, Any]) -> List[tuple[str, Image.Image]]:
    if not REFERENCE_FRAME.exists():
        raise SystemExit(f"reference frame missing: {REFERENCE_FRAME}")
    crop = (0, 270, 1080, 540)
    rows: List[tuple[str, Image.Image]] = [
        ("REFERENCE FROM TIKTOK EXAMPLE", Image.open(REFERENCE_FRAME).convert("RGB").crop(crop))
    ]
    for item in report.get("results", []):
        top_hook = item.get("top_hook_check") or {}
        frame_path = Path(str(top_hook.get("frame") or ""))
        if not frame_path.exists():
            continue
        hook = str(top_hook.get("hook") or "")
        title = str(item.get("title") or "")
        kit_id = str(item.get("kit_id") or "")
        label = f"{kit_id} | {hook or title}"
        rows.append((label, Image.open(frame_path).convert("RGB").crop(crop)))
    return rows


def write_sheet(rows: List[tuple[str, Image.Image]], path: Path) -> None:
    scale_width = 540
    label_height = 34
    font = ImageFont.load_default()
    scaled: List[tuple[str, Image.Image]] = []
    for label, image in rows:
        height = round(image.height * scale_width / image.width)
        scaled.append((label, image.resize((scale_width, height), Image.Resampling.LANCZOS)))
    sheet = Image.new("RGB", (scale_width, sum(image.height + label_height for _, image in scaled)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    y = 0
    for label, image in scaled:
        sheet.paste(image, (0, y))
        y += image.height
        draw.rectangle((0, y, sheet.width, y + label_height), fill=(0, 0, 0))
        draw.text((6, y + 9), label[:120], fill=(255, 255, 255), font=font)
        y += label_height
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, quality=94)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a decoded-frame top-card sheet for active review kits.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--refresh", action="store_true", help="Run burned-caption verification before building the sheet.")
    args = parser.parse_args()

    report = load_report(args.refresh)
    rows = sheet_rows(report)
    sheet_path = args.out_dir / "current-live-top-cards-vs-reference.jpg"
    write_sheet(rows, sheet_path)
    payload = {
        "ok": bool(report.get("ok")) and len(rows) > 1,
        "kit_count": report.get("kit_count"),
        "rows": len(rows),
        "source_report": str(VERIFY_REPORT),
        "sheet": str(sheet_path),
    }
    metrics_path = args.out_dir / "metrics.json"
    metrics_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(sheet_path)
    print(json.dumps(payload, indent=2))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
