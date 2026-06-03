#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db


OUT = ROOT / "artifacts" / "research-run" / "source-media-reconcile.json"


def ffprobe_ok(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,duration",
            "-show_entries",
            "format=duration,size",
            "-of",
            "json",
            str(path),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        return {"ok": False, "error": result.stderr.strip() or result.stdout.strip()}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": str(exc)}
    streams = payload.get("streams") or []
    duration = float((payload.get("format") or {}).get("duration") or 0)
    return {
        "ok": bool(streams) and duration > 0,
        "duration": duration,
        "width": int((streams[0] or {}).get("width") or 0) if streams else 0,
        "height": int((streams[0] or {}).get("height") or 0) if streams else 0,
        "size": int((payload.get("format") or {}).get("size") or 0),
    }


def risk_flags(clip: dict[str, Any]) -> list[str]:
    raw = clip.get("risk_flags_json") or "[]"
    try:
        values = json.loads(str(raw))
    except json.JSONDecodeError:
        values = []
    if not isinstance(values, list):
        values = []
    return [str(item) for item in values]


def main() -> int:
    db.init_db()
    media_roots = [
        db.source_media_root(),
        db.source_media_root() / "selected_feeders",
    ]
    candidates = {
        str(item["id"]): item
        for item in db.rows("SELECT * FROM clip_candidates WHERE risk_flags_json LIKE '%selected_feeder_%'")
    }
    updates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for media_root in media_roots:
        if not media_root.exists():
            continue
        for path in sorted(media_root.glob("clip_*.mp4")):
            clip_id = path.stem
            clip = candidates.get(clip_id)
            if not clip:
                skipped.append({"path": str(path), "reason": "no matching selected-feeder clip candidate"})
                continue
            probe = ffprobe_ok(path)
            if not probe["ok"]:
                skipped.append({"clip_id": clip_id, "path": str(path), "reason": "ffprobe failed", "probe": probe})
                continue

            flags = [flag for flag in risk_flags(clip) if flag != "metadata_only_no_download"]
            for flag in ["local_media_downloaded", "source_media_verified_local"]:
                if flag not in flags:
                    flags.append(flag)
            db.execute(
                """
                UPDATE clip_candidates
                SET local_media_path=?, risk_flags_json=?, discovered_at=?
                WHERE id=?
                """,
                (str(path), json.dumps(flags), db.utc_now(), clip_id),
            )
            db.log_audit(
                "worker",
                "reconcile_source_media",
                "clip_candidate",
                clip_id,
                "local media verified from disk",
                str(path),
            )
            updates.append({"clip_id": clip_id, "path": str(path), "probe": probe, "risk_flags": flags})

    payload = {
        "ok": True,
        "updated": updates,
        "updated_count": len(updates),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "source_counts": db.selected_feeder_source_media_counts(),
        "generated_at": db.utc_now(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
