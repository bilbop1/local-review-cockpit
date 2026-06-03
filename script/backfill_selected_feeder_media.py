#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db


OUT = ROOT / "artifacts" / "research-run" / "selected-feeder-media-backfill.json"
YT_DLP = ROOT / "backend" / ".venv" / "bin" / "yt-dlp"


def run(command: list[str], timeout: int = 900) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        return subprocess.CompletedProcess(command, 124, stdout, (stderr or "") + f"\ntimeout after {timeout}s")


def ffprobe(path: Path) -> dict[str, Any]:
    result = run(
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
    try:
        raw = json.loads(str(clip.get("risk_flags_json") or "[]"))
    except json.JSONDecodeError:
        raw = []
    if not isinstance(raw, list):
        raw = []
    return [str(item) for item in raw]


def update_clip(clip: dict[str, Any], path: Path, probe: dict[str, Any], provenance_note: str) -> None:
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
        (str(path), json.dumps(flags), db.utc_now(), str(clip["id"])),
    )
    db.log_audit(
        "worker",
        "backfill_selected_feeder_media",
        "clip_candidate",
        str(clip["id"]),
        "source media verified",
        f"{provenance_note}; {probe.get('width')}x{probe.get('height')} {probe.get('duration')}s",
    )


def candidate_media_path(clip_id: str) -> Path:
    root = db.source_media_root() / "selected_feeders"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{clip_id}.mp4"


def existing_media_path(clip: dict[str, Any]) -> Path | None:
    clip_id = str(clip["id"])
    paths = []
    if str(clip.get("local_media_path", "")).strip():
        paths.append(Path(str(clip["local_media_path"])))
    paths.extend(
        [
            db.source_media_root() / f"{clip_id}.mp4",
            db.source_media_root() / "selected_feeders" / f"{clip_id}.mp4",
        ]
    )
    for path in paths:
        if path.exists():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--download-timeout", type=int, default=360)
    args = parser.parse_args()

    db.init_db()
    if not YT_DLP.exists():
        raise SystemExit(f"yt-dlp missing at {YT_DLP}")

    clips = sorted(
        db.visible_clip_candidates(),
        key=lambda item: (
            str(item.get("clip_created_at", "")),
            int(item.get("view_count", 0) or 0),
            str(item.get("discovered_at", "")),
        ),
        reverse=True,
    )[: max(1, args.limit)]
    downloaded: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for clip in clips:
        clip_id = str(clip["id"])
        existing = existing_media_path(clip)
        if existing:
            probe = ffprobe(existing)
            if probe["ok"]:
                update_clip(clip, existing, probe, "existing local media")
                skipped.append({"clip_id": clip_id, "reason": "already had local media", "path": str(existing), "probe": probe})
                continue

        source_url = str(clip.get("source_url", "")).strip()
        if not source_url:
            failed.append({"clip_id": clip_id, "error": "missing source_url"})
            continue
        output = candidate_media_path(clip_id)
        command = [
            str(YT_DLP),
            "--no-warnings",
            "--no-progress",
            "--force-overwrites",
            "--socket-timeout",
            "20",
            "--retries",
            "3",
            "--fragment-retries",
            "3",
            "--concurrent-fragments",
            "8",
            "-f",
            "worst[ext=mp4]/worst",
            "--merge-output-format",
            "mp4",
            "-o",
            str(output),
            source_url,
        ]
        result = run(command, timeout=max(60, args.download_timeout))
        if result.returncode != 0 or not output.exists():
            failed.append(
                {
                    "clip_id": clip_id,
                    "source_url": source_url,
                    "error": (result.stderr.strip() or result.stdout.strip() or "yt-dlp download failed")[-1800:],
                }
            )
            continue
        probe = ffprobe(output)
        if not probe["ok"]:
            failed.append({"clip_id": clip_id, "source_url": source_url, "path": str(output), "error": "ffprobe failed", "probe": probe})
            continue
        update_clip(clip, output, probe, "yt-dlp twitch clip download")
        downloaded.append({"clip_id": clip_id, "source_url": source_url, "path": str(output), "probe": probe})

    payload = {
        "ok": not failed,
        "downloaded": downloaded,
        "downloaded_count": len(downloaded),
        "skipped": skipped,
        "skipped_count": len(skipped),
        "failed": failed,
        "failed_count": len(failed),
        "source_counts": db.selected_feeder_source_media_counts(),
        "generated_at": db.utc_now(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
