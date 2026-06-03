#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db


MISTER_HOME = Path.home() / "Library" / "Application Support" / "MisterWhisper"
SERVER_BIN = MISTER_HOME / "whisper-build" / "bin" / "whisper-server"
MODEL_PATH = MISTER_HOME / "models" / "ggml-large-v3-turbo-q5_0.bin"
OUT = ROOT / "artifacts" / "research-run" / "selected-feeder-transcript-backfill.json"
SERVER_LOG = ROOT / ".run" / "mister-whisper-server.log"
TMP_DIR = ROOT / ".run" / "mister-tmp"


def api_alive(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def start_server(port: int) -> subprocess.Popen[str] | None:
    if api_alive(port):
        return None
    if not SERVER_BIN.exists() or not MODEL_PATH.exists():
        raise RuntimeError("MisterWhisper whisper-server or model is missing.")
    SERVER_LOG.parent.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    log = SERVER_LOG.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [
            str(SERVER_BIN),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--inference-path",
            "/inference",
            "--language",
            "en",
            "--threads",
            "8",
            "--processors",
            "1",
            "--model",
            str(MODEL_PATH),
            "--convert",
            "--tmp-dir",
            str(TMP_DIR),
        ],
        text=True,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(180):
        if api_alive(port):
            return process
        if process.poll() is not None:
            raise RuntimeError(f"MisterWhisper server exited early with {process.returncode}; see {SERVER_LOG}")
        time.sleep(0.5)
    raise RuntimeError(f"MisterWhisper server did not become ready on port {port}; see {SERVER_LOG}")


def stop_server(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def latest_transcript(clip_id: str) -> dict[str, Any] | None:
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


def has_timed_real_transcript(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    if str(row.get("provider", "")).endswith("placeholder"):
        return False
    segments = row.get("segments")
    word_timings = row.get("word_timings")
    return isinstance(word_timings, list) and bool(word_timings) and isinstance(segments, list) and bool(segments) and all(
        isinstance(item, dict) and "start" in item and "end" in item and str(item.get("text", "")).strip()
        for item in segments
    )


def transcribe(path: Path, port: int, timeout: int) -> dict[str, Any]:
    result = subprocess.run(
        [
            "curl",
            "-fsS",
            "-X",
            "POST",
            "-F",
            f"file=@{path}",
            "-F",
            "response_format=verbose_json",
            f"http://127.0.0.1:{port}/inference",
        ],
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "MisterWhisper request failed")
    payload = json.loads(result.stdout)
    if "error" in payload:
        raise RuntimeError(str(payload["error"]))
    return payload


def average_probability(segments: list[dict[str, Any]]) -> float:
    probabilities: list[float] = []
    for segment in segments:
        for word in segment.get("words") or []:
            try:
                probabilities.append(float(word.get("probability")))
            except Exception:
                pass
    if not probabilities:
        return 0.75 if segments else 0.0
    return round(sum(probabilities) / len(probabilities), 4)


def clean_segments(raw: Any) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get("text", "")).split())
        if not text:
            continue
        words = []
        for word in item.get("words") or []:
            if not isinstance(word, dict):
                continue
            words.append(
                {
                    "word": str(word.get("word", "")).strip(),
                    "start": round(float(word.get("start", 0) or 0), 2),
                    "end": round(float(word.get("end", 0) or 0), 2),
                    "probability": round(float(word.get("probability", 0) or 0), 4),
                }
            )
        segments.append(
            {
                "start": round(float(item.get("start", 0) or 0), 2),
                "end": round(float(item.get("end", 0) or 0), 2),
                "text": text,
                "words": words,
            }
        )
    return segments


def store_transcript(clip_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    segments = clean_segments(payload.get("segments"))
    text = " ".join(str(payload.get("text", "")).split())
    if not text:
        text = " ".join(segment["text"] for segment in segments).strip()
    if not text or not segments:
        raise RuntimeError("MisterWhisper returned no usable timed transcript.")
    transcript_id = db.new_id("transcript")
    word_timings = [word for segment in segments for word in segment.get("words", [])]
    confidence = average_probability(segments)
    db.execute(
        """
        INSERT INTO transcripts
          (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
        VALUES (?, ?, 'mister_whisper', 'en', ?, ?, ?, ?, 'succeeded', ?)
        """,
        (transcript_id, clip_id, confidence, text, json.dumps(segments), json.dumps(word_timings), db.utc_now()),
    )
    db.log_audit(
        "worker",
        "backfill_selected_feeder_transcript",
        "clip_candidate",
        clip_id,
        f"stored MisterWhisper transcript; segments={len(segments)} confidence={confidence}",
        "local whisper.cpp",
    )
    return db.one("SELECT * FROM transcripts WHERE id = ?", (transcript_id,)) or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--port", type=int, default=9595)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    db.init_db()
    server = None
    stored: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    try:
        server = start_server(args.port)
        clips = [
            item
            for item in sorted(
                db.visible_clip_candidates(),
                key=lambda row: (
                    str(row.get("clip_created_at", "")),
                    int(row.get("view_count", 0) or 0),
                    str(row.get("discovered_at", "")),
                ),
                reverse=True,
            )
            if str(item.get("local_media_path", "")).strip()
        ][: max(1, args.limit)]
        for clip in clips:
            clip_id = str(clip["id"])
            existing = latest_transcript(clip_id)
            if has_timed_real_transcript(existing):
                skipped.append({"clip_id": clip_id, "reason": "already has timed non-placeholder transcript"})
                continue
            media_path = Path(str(clip.get("local_media_path", "")))
            if not media_path.exists():
                failed.append({"clip_id": clip_id, "error": "local media path missing"})
                continue
            try:
                payload = transcribe(media_path, args.port, max(30, args.timeout))
                row = store_transcript(clip_id, payload)
                stored.append(
                    {
                        "clip_id": clip_id,
                        "transcript_id": row.get("id", ""),
                        "segments": len(row.get("segments", [])),
                        "confidence": row.get("confidence", 0),
                        "text_excerpt": str(row.get("full_text", ""))[:160],
                    }
                )
            except Exception as exc:
                failed.append({"clip_id": clip_id, "error": str(exc)[:1800]})
    finally:
        stop_server(server)

    payload = {
        "ok": not failed,
        "stored": stored,
        "stored_count": len(stored),
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
