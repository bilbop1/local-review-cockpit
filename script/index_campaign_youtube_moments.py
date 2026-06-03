#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from clipping_ops_backend import database as db
from clipping_ops_backend.server import _campaign_brief_artifact, _extract_urls, _upload_date_to_iso, _youtube_id, discover_campaign_sources, refresh_campaign_project


YT_DLP = ROOT / "backend" / ".venv" / "bin" / "yt-dlp"
SUBTITLE_ROOT = ROOT / "artifacts" / "research-run" / "youtube-subtitles"
AVAILABILITY_PATH = ROOT / "artifacts" / "research-run" / "kalshi-youtube-source-availability-2026-05-28.json"
DEFAULT_DURATION = 34.0

SCORING_TERMS = {
    "prediction market": 12,
    "prediction markets": 12,
    "event contract": 11,
    "event contracts": 11,
    "kalshi": 9,
    "sportsbook": 9,
    "sportsbooks": 9,
    "billionaire": 8,
    "stock market": 8,
    "cftc": 8,
    "lawsuit": 7,
    "sue": 7,
    "regulator": 7,
    "regulation": 7,
    "exchange": 7,
    "money": 6,
    "future": 6,
    "markets": 5,
    "bet": 5,
    "bets": 5,
    "people lose": 5,
    "probability": 5,
    "asset": 4,
    "assets": 4,
}

WEAK_STARTS = {
    "and",
    "but",
    "so",
    "because",
    "like",
    "me",
    "or",
    "was",
    "the",
    "then",
    "that",
    "this",
}


def run(command: List[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, timeout=timeout)


def load_availability() -> Dict[str, Dict[str, Any]]:
    if not AVAILABILITY_PATH.exists():
        return {}
    payload = json.loads(AVAILABILITY_PATH.read_text(encoding="utf-8"))
    return {str(item.get("id", "")): item for item in payload.get("results", [])}


def ensure_subtitles(video_url: str, video_id: str) -> Path:
    SUBTITLE_ROOT.mkdir(parents=True, exist_ok=True)
    expected = SUBTITLE_ROOT / f"{video_id}.en.vtt"
    if expected.exists() and expected.stat().st_size > 500:
        return expected
    if not YT_DLP.exists():
        raise RuntimeError(f"yt-dlp is missing at {YT_DLP}")
    command = [
        str(YT_DLP),
        "--skip-download",
        "--write-auto-subs",
        "--write-subs",
        "--sub-lang",
        "en",
        "--sub-format",
        "vtt",
        "-o",
        str(SUBTITLE_ROOT / "%(id)s.%(ext)s"),
        video_url,
    ]
    result = run(command, timeout=150)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "subtitle download failed")
    if expected.exists():
        return expected
    matches = sorted(SUBTITLE_ROOT.glob(f"{video_id}*.vtt"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        raise RuntimeError("subtitle download did not create a VTT file")
    matches[0].replace(expected)
    return expected


def seconds(value: str) -> float:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 3:
        hours, minutes, rest = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(rest)
    if len(parts) == 2:
        minutes, rest = parts
        return int(minutes) * 60 + float(rest)
    return float(value)


def clean_caption(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def parse_vtt(path: Path) -> List[Dict[str, Any]]:
    cues: List[Dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        match = re.match(r"^([0-9:.]+)\s+-->\s+([0-9:.]+)", line)
        if not match:
            index += 1
            continue
        start = seconds(match.group(1))
        end = seconds(match.group(2))
        index += 1
        text_lines: List[str] = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(lines[index].strip())
            index += 1
        text = clean_caption(" ".join(text_lines))
        if text:
            cues.append({"start": start, "end": end, "text": text})
        index += 1
    return cues


def sentence_aligned(cues: List[Dict[str, Any]], index: int) -> bool:
    if index <= 0:
        return True
    previous = str(cues[index - 1].get("text", "")).strip()
    current = str(cues[index].get("text", "")).strip()
    first = re.sub(r"[^A-Za-z0-9']", "", current.split()[0]).lower() if current.split() else ""
    visible_start = current.lstrip(" >\"'“”")
    starts_like_sentence = bool(visible_start[:1].isupper() or visible_start.startswith(("I ", "I'", "I'm")))
    return previous.endswith((".", "?", "!")) and first not in WEAK_STARTS and starts_like_sentence


def score_window(text: str, *, aligned: bool, view_count: int, upload_iso: str, first_sentence: str) -> float:
    lowered = text.lower()
    first_lowered = first_sentence.lower()
    score = 0.0
    for term, weight in SCORING_TERMS.items():
        if term in lowered:
            score += weight
    if aligned:
        score += 8
    else:
        score -= 8
    first_words = re.findall(r"[A-Za-z0-9]{2,}", first_sentence)
    if len(first_words) < 5:
        score -= 18
    if first_lowered.startswith((">>", "mhm", "right", "yeah", "you have to", "it was", "and ", "but ", "so ")):
        score -= 15
    if len(re.findall(r"[A-Za-z0-9]{2,}", text)) < 35:
        score -= 8
    if any(phrase in lowered for phrase in ("thanks for watching", "subscribe", "welcome back", "before we get started")):
        score -= 20
    score += min(6.0, max(0, view_count) / 10000.0)
    if upload_iso.startswith("2026"):
        score += 4
    return score


def select_moments(video_url: str, meta: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
    video_id = str(meta.get("id") or _youtube_id(video_url))
    vtt_path = ensure_subtitles(video_url, video_id)
    cues = parse_vtt(vtt_path)
    moments: List[Dict[str, Any]] = []
    for index, cue in enumerate(cues):
        start = float(cue["start"])
        end = start + DEFAULT_DURATION
        window = [item for item in cues[index:] if float(item["start"]) < end]
        if not window:
            continue
        text = " ".join(str(item["text"]) for item in window)
        aligned = sentence_aligned(cues, index)
        if not aligned:
            continue
        upload_iso = _upload_date_to_iso(meta.get("upload_date"))
        first_sentence = re.split(r"(?<=[.!?])\s+", clean_caption(text))[0].strip()
        score = score_window(
            text,
            aligned=aligned,
            view_count=int(meta.get("view_count", 0) or 0),
            upload_iso=upload_iso,
            first_sentence=first_sentence,
        )
        if score <= 0:
            continue
        moments.append(
            {
                "video_id": video_id,
                "source_url": f"https://www.youtube.com/watch?v={video_id}&t={int(start)}s",
                "title": str(meta.get("title", "") or f"Kalshi approved source {video_id}"),
                "hook": first_sentence[:120],
                "start": round(start, 2),
                "end": round(end, 2),
                "score": round(score, 2),
                "view_count": int(meta.get("view_count", 0) or 0),
                "clip_created_at": upload_iso,
                "subtitle_path": str(vtt_path),
                "aligned": aligned,
            }
        )
    moments.sort(key=lambda item: (item["score"], item["view_count"]), reverse=True)
    selected: List[Dict[str, Any]] = []
    for moment in moments:
        if len(selected) >= limit:
            break
        if any(abs(float(moment["start"]) - float(existing["start"])) < 50 and moment["video_id"] == existing["video_id"] for existing in selected):
            continue
        selected.append(moment)
    return selected


def write_vtt_transcript(clip_id: str, cues: List[Dict[str, Any]], start: float, end: float, subtitle_path: str) -> None:
    selected = [cue for cue in cues if float(cue["end"]) > start and float(cue["start"]) < end]
    segments: List[Dict[str, Any]] = []
    word_timings: List[Dict[str, Any]] = []
    text_parts: List[str] = []
    seen_cues: set[str] = set()
    for cue in selected:
        source_start = float(cue["start"])
        source_end = float(cue["end"])
        overlap_start = max(start, source_start)
        overlap_end = min(end, source_end)
        overlap = overlap_end - overlap_start
        source_duration = max(0.01, source_end - source_start)
        if overlap < 0.45:
            continue
        if source_start < start and overlap / source_duration < 0.45:
            continue
        cue_start = max(0.0, overlap_start - start)
        cue_end = min(end - start, max(cue_start + 0.45, overlap_end - start))
        text = clean_caption(str(cue["text"]))
        if not text:
            continue
        normalized_text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
        cue_key = f"{round(cue_start, 1)}:{normalized_text}"
        if cue_key in seen_cues:
            continue
        seen_cues.add(cue_key)
        words = [word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’%.-]*", text) if word.strip()]
        cue_word_timings: List[Dict[str, Any]] = []
        step = (cue_end - cue_start) / max(1, len(words))
        for index, word in enumerate(words):
            item = {
                "word": word,
                "start": round(cue_start + step * index, 2),
                "end": round(min(cue_end, cue_start + step * (index + 1)), 2),
                "probability": 0.82,
            }
            cue_word_timings.append(item)
            word_timings.append(item)
        segments.append({"start": round(cue_start, 2), "end": round(cue_end, 2), "text": text, "words": cue_word_timings})
        text_parts.append(text)
    full_text = " ".join(text_parts).strip()
    if not full_text or not word_timings:
        return
    db.execute(
        "DELETE FROM transcripts WHERE clip_candidate_id = ? AND provider = 'youtube_vtt_campaign_subtitles'",
        (clip_id,),
    )
    db.execute(
        """
        INSERT INTO transcripts
          (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
        VALUES (?, ?, 'youtube_vtt_campaign_subtitles', 'en', 0.82, ?, ?, ?, 'succeeded', ?)
        """,
        (
            db.new_id("transcript"),
            clip_id,
            full_text,
            json.dumps(segments),
            json.dumps(word_timings),
            db.utc_now(),
        ),
    )
    db.log_audit("worker", "write_vtt_transcript", "clip_candidate", clip_id, "succeeded", subtitle_path)


def index_kalshi(limit: int) -> Dict[str, Any]:
    refresh_campaign_project("kalshi")
    discover_campaign_sources("kalshi")
    doc = _campaign_brief_artifact("kalshi")
    urls = [url for url in _extract_urls(doc.read_text(encoding="utf-8", errors="replace")) if "youtube.com" in url or "youtu.be" in url]
    availability = load_availability()
    created: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for url in urls:
        video_id = _youtube_id(url)
        if not video_id:
            blockers.append(f"{url}: missing YouTube id")
            continue
        meta = availability.get(video_id, {"id": video_id, "title": f"Kalshi approved source {video_id}"})
        try:
            subtitle_path = ensure_subtitles(f"https://www.youtube.com/watch?v={video_id}", video_id)
            cues = parse_vtt(subtitle_path)
            for moment in select_moments(f"https://www.youtube.com/watch?v={video_id}", meta, max(1, min(3, limit))):
                clip_id = db.upsert_clip_candidate(
                    {
                        "id": f"clip_kalshi_moment_{video_id}_{int(float(moment['start']))}",
                        "campaign_slug": "kalshi",
                        "source_platform": "youtube",
                        "source_url": moment["source_url"],
                        "creator_id": str(meta.get("channel", "kalshi-approved-source")),
                        "title": f"{moment['title']} - {moment['hook']}",
                        "duration": DEFAULT_DURATION,
                        "view_count": int(moment.get("view_count", 0) or 0),
                        "clip_created_at": moment.get("clip_created_at", ""),
                        "clip_start_seconds": float(moment["start"]),
                        "clip_end_seconds": float(moment["end"]),
                        "provenance": "campaign_brief_youtube_subtitles",
                        "risk_flags": [
                            "campaign_project_kalshi",
                            "campaign_rules_stored",
                            "campaign_subtitle_selected",
                            "campaign_selected_good_moment",
                            "metadata_only_no_download",
                        ],
                    }
                )
                write_vtt_transcript(clip_id, cues, float(moment["start"]), float(moment["end"]), str(subtitle_path))
                db.execute(
                    "DELETE FROM viral_scores WHERE clip_candidate_id = ? AND model_version = 'campaign-youtube-subtitle-v1'",
                    (clip_id,),
                )
                db.execute(
                    """
                    INSERT INTO viral_scores
                      (id, clip_candidate_id, model_version, total_score, hook_score, punchline_score, fit_score, recency_score, saturation_risk, score_reason, confidence, created_at)
                    VALUES (?, ?, 'campaign-youtube-subtitle-v1', ?, ?, ?, ?, ?, 'low', ?, 0.82, ?)
                    """,
                    (
                        db.new_id("score"),
                        clip_id,
                        int(round(float(moment["score"]))),
                        min(10, max(1, int(round(float(moment["score"]) / 10)))),
                        6,
                        9,
                        8 if str(moment.get("clip_created_at", "")).startswith("2026") else 5,
                        f"Subtitle-selected Kalshi moment: {moment['hook']}",
                        db.utc_now(),
                    ),
                )
                moment["clip_id"] = clip_id
                created.append(moment)
        except Exception as exc:
            blockers.append(f"{video_id}: {exc}")
    created.sort(key=lambda item: (item["score"], item["view_count"]), reverse=True)
    created = created[:limit]
    db.create_job(
        "kalshi-youtube-moment-index",
        "research",
        "succeeded" if created else "blocked",
        "subtitle-moment-index",
        100 if created else 20,
        logs=f"Indexed {len(created)} sentence-aligned Kalshi source moment(s).",
        error="; ".join(blockers)[:1200],
    )
    db.log_audit("worker", "index_campaign_youtube_moments", "campaign_project", "kalshi", "succeeded" if created else "blocked", "; ".join(blockers[:2]))
    return {"campaign": "kalshi", "status": "succeeded" if created else "blocked", "created": created, "blockers": blockers[:8]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign", default="kalshi", choices=["kalshi"])
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    db.init_db()
    result = index_kalshi(max(1, args.limit))
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
