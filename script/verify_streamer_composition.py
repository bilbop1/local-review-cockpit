#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db


SUMMARY_PATH = ROOT / "artifacts" / "review-kit-audit" / "streamer-composition-verification.json"
FRAME_DIR = ROOT / "artifacts" / "review-kit-audit" / "streamer-composition-frames"


def video_dimensions(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=45,
    )
    if result.returncode != 0:
        return (0, 0)
    try:
        width, height = result.stdout.strip().split(",", 1)
        return (int(width), int(height))
    except Exception:
        return (0, 0)


def extract_frame(video: Path, clip_id: str) -> str:
    FRAME_DIR.mkdir(parents=True, exist_ok=True)
    frame = FRAME_DIR / f"{clip_id}-composition.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", "00:00:02", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(frame)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=90,
    )
    return str(frame) if frame.exists() else ""


def manifest_composition(kit_dir: Path) -> Dict[str, Any]:
    manifest = kit_dir / "render_text_manifest.json"
    if not manifest.exists():
        return {}
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rendered = payload.get("rendered_text", {})
    composition = rendered.get("composition", {}) if isinstance(rendered, dict) else {}
    return composition if isinstance(composition, dict) else {}


def verify_kit(row: Dict[str, Any]) -> Dict[str, Any]:
    clip = db.one("SELECT * FROM clip_candidates WHERE id = ?", (str(row.get("clip_id", "")),)) or {}
    source = Path(str(clip.get("local_media_path", "")).strip())
    review_video = Path(str(row.get("review_video_path", "")))
    source_width, source_height = video_dimensions(source) if source.exists() else (0, 0)
    review_width, review_height = video_dimensions(review_video) if review_video.exists() else (0, 0)
    composition = manifest_composition(review_video.parent)
    mode = str(composition.get("mode", ""))
    platform = str(clip.get("source_platform", "")).lower()
    source_url = str(clip.get("source_url", "")).lower()
    is_streamer_twitch = platform == "twitch" or "twitch.tv/" in source_url
    violations = []
    warnings = []
    if review_width != 1080 or review_height != 1920:
        violations.append(f"review output is {review_width}x{review_height}, expected 1080x1920")
    if is_streamer_twitch:
        if not source.exists():
            violations.append("local Twitch source media is missing")
        if source_height > source_width and source_width <= 720:
            violations.append(f"Twitch source is still mobile/portrait ({source_width}x{source_height}); native landscape source is required")
        if source_width > source_height and mode not in {"streamer_center_preserve_source", "streamer_center_screen_no_facecam_detected"}:
            violations.append(f"landscape Twitch source used unsupported composition mode `{mode}`")
        if mode == "streamer_center_screen_no_facecam_detected":
            warnings.append("no confident facecam corner detected; human should inspect probe frames before approving")
        if mode == "streamer_center_preserve_source":
            warnings.append("facecam split was suppressed; human should confirm the natural frame is stronger than a split layout")
    return {
        "kit_id": row.get("id", ""),
        "clip_id": row.get("clip_id", ""),
        "title": row.get("title", ""),
        "source_media_path": str(source),
        "source_dimensions": {"width": source_width, "height": source_height},
        "review_video_path": str(review_video),
        "review_dimensions": {"width": review_width, "height": review_height},
        "composition": composition,
        "sample_frame": extract_frame(review_video, str(row.get("clip_id", ""))) if review_video.exists() else "",
        "warnings": warnings,
        "violations": violations,
        "ok": not violations,
    }


def main() -> None:
    db.init_db()
    results = [verify_kit(dict(row)) for row in db.visible_render_kits()]
    payload = {
        "ok": bool(results) and all(item["ok"] for item in results),
        "kit_count": len(results),
        "results": results,
        "generated_at": db.utc_now(),
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(SUMMARY_PATH)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
