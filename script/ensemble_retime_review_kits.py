#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from clipping_ops_backend import database as db
from clipping_ops_backend.caption_style import (
    caption_display_text,
    caption_display_window_seconds,
    clean_timed_words_for_caption,
    timed_caption_groups,
)

import build_evidence_review_kit as review_builder


OUT = ROOT / "artifacts" / "review-kit-audit" / "ensemble-retiming.json"
DEFAULT_MODELS = ("base.en", "small.en", "medium.en", "distil-medium.en")
ENSEMBLE_PROVIDER = "ensemble_timestamp_consensus_v1"


def norm(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def phrase_tokens(text: Any) -> List[str]:
    return [norm(token) for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’%$.-]*", str(text or "")) if norm(token)]


def latest_non_ensemble_transcript(clip_id: str) -> Dict[str, Any] | None:
    return db.one(
        """
        SELECT *
        FROM transcripts
        WHERE clip_candidate_id = ?
          AND status = 'succeeded'
          AND provider NOT LIKE 'ensemble_timestamp_consensus%'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (clip_id,),
    )


def transcript_words(transcript: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    if not transcript:
        return []
    raw = transcript.get("word_timings")
    if not isinstance(raw, list):
        try:
            raw = json.loads(str(transcript.get("word_timings_json", "[]")))
        except json.JSONDecodeError:
            raw = []
    return clean_timed_words_for_caption(raw, transcript.get("provider", ""))


def transcript_source_name(transcript: Dict[str, Any] | None) -> str:
    provider = re.sub(r"[^a-z0-9]+", "_", str((transcript or {}).get("provider", "")).lower()).strip("_")
    return provider or "existing_transcript"


def caption_targets_for_kit(kit: Dict[str, Any]) -> List[str]:
    manifest = Path(str(kit["review_video_path"])).parent / "render_text_manifest.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    rendered = payload.get("rendered_text", {})
    beats = rendered.get("caption_beats", []) if isinstance(rendered, dict) else []
    return [caption_display_text(item) for item in beats if caption_display_text(item)]


def caption_variant_for_kit(kit: Dict[str, Any]) -> str:
    manifest = Path(str(kit["review_video_path"])).parent / "render_text_manifest.json"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        return str(payload.get("rendered_text", {}).get("caption_style", {}).get("ab_variant", "")).strip()
    except Exception:
        return ""


def targets_from_words(words: List[Dict[str, Any]], max_targets: int = 80) -> List[str]:
    targets: List[str] = []
    for group in timed_caption_groups(words, max_groups=max_targets):
        text = caption_display_text(" ".join(str(item.get("word", "")) for item in group))
        if text:
            targets.append(text)
    return targets


def target_groups_from_words(words: List[Dict[str, Any]], max_targets: int = 80) -> List[Dict[str, Any]]:
    targets: List[Dict[str, Any]] = []
    for group in timed_caption_groups(words, max_groups=max_targets):
        text = caption_display_text(" ".join(str(item.get("word", "")) for item in group))
        if not text:
            continue
        starts = [float(item.get("start", 0) or 0) for item in group]
        ends = [float(item.get("end", 0) or 0) for item in group]
        targets.append(
            {
                "target_index": len(targets) + 1,
                "text": text,
                "start": round(min(starts), 3),
                "end": round(max(ends), 3),
                "words": [str(item.get("word", "")).strip() for item in group],
            }
        )
    return targets


def canonical_anchor_vote(source_name: str, target: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "target_index": int(target["target_index"]),
        "text": str(target["text"]),
        "source": source_name,
        "matched": True,
        "match_mode": "canonical_group_anchor",
        "start": round(float(target["start"]), 3),
        "end": round(float(target["end"]), 3),
        "words": list(target.get("words", [])) if isinstance(target.get("words"), list) else [],
    }


def source_quality_score(name: str, words: List[Dict[str, Any]]) -> tuple[float, int]:
    long_spans = 0
    backwards = 0
    previous_start = -1.0
    for item in words:
        try:
            start = float(item.get("start", 0) or 0)
            end = float(item.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        if end - start > 0.82:
            long_spans += 1
        if previous_start >= 0 and start < previous_start - 0.02:
            backwards += 1
        previous_start = start
    penalty = long_spans * 2.5 + backwards * 4.0
    preference_bonus = 0.0
    if "distil_medium" in name:
        preference_bonus = 4.0
    elif "medium" in name:
        preference_bonus = 3.5
    elif "small" in name:
        preference_bonus = 2.0
    elif "base" in name:
        preference_bonus = 1.0
    return (len(words) + preference_bonus - penalty, len(words))


def minimum_consensus_survivors(target_count: int) -> int:
    return min(target_count, max(8, int(target_count * 0.35)))


def preferred_canonical_source(source_word_sets: Dict[str, List[Dict[str, Any]]], min_votes: int = 3) -> str:
    max_word_count = max((len(words) for words in source_word_sets.values()), default=0)

    def score(name: str) -> tuple[float, float, int, int, float, float, int]:
        words = source_word_sets[name]
        word_count = len(words)
        if max_word_count >= 20 and word_count < 12 and word_count < max_word_count * 0.25:
            quality, _word_count = source_quality_score(name, words)
            return (0.0, 0.0, 0, 0, 0.0, quality - max_word_count, word_count)
        target_groups = target_groups_from_words(words)
        if not target_groups:
            quality, _word_count = source_quality_score(name, words)
            return (0.0, 0.0, 0, 0, 0.0, quality, word_count)

        targets = [str(target["text"]) for target in target_groups]
        support_by_index: Dict[int, int] = {int(target["target_index"]): 1 for target in target_groups}
        for source_name, source_words in source_word_sets.items():
            if source_name == name:
                continue
            for vote in model_votes_for_targets(source_name, source_words, targets, canonical_targets=target_groups):
                if vote.get("matched"):
                    support_by_index[int(vote["target_index"])] = support_by_index.get(int(vote["target_index"]), 1) + 1

        survivors = sum(1 for count in support_by_index.values() if count >= min_votes)
        two_vote_segments = sum(1 for count in support_by_index.values() if count >= 2)
        target_count = len(target_groups)
        coverage = survivors / max(1, target_count)
        average_support = sum(support_by_index.values()) / max(1, target_count)
        passes_survivor_floor = 1.0 if survivors >= minimum_consensus_survivors(target_count) else 0.0
        quality, word_count = source_quality_score(name, words)
        return (passes_survivor_floor, coverage, survivors, two_vote_segments, average_support, quality, word_count)

    return max(source_word_sets, key=score)


def display_window_for_vote(text: str, vote: Dict[str, Any]) -> Dict[str, float]:
    start = float(vote["start"])
    end = float(vote["end"])
    max_window = caption_display_window_seconds(text) + 0.04
    duration = max(0.0, end - start)
    tokens = phrase_tokens(text)
    suspicious_long_span = duration > max_window + 0.24 or (len(tokens) <= 1 and duration > 0.58)
    display_start = max(0.0, end - max_window) if suspicious_long_span else start
    display_end = min(max(end + 0.08, display_start + 0.20), display_start + max_window)
    return {
        "display_start": round(display_start, 3),
        "display_end": round(display_end, 3),
        "raw_start": round(start, 3),
        "raw_end": round(end, 3),
        "suspicious_long_span": 1.0 if suspicious_long_span else 0.0,
    }


def find_phrase(words: List[Dict[str, Any]], tokens: List[str], start_index: int) -> tuple[int, List[Dict[str, Any]]] | None:
    if not tokens:
        return None
    normalized = [norm(item.get("word", "")) for item in words]
    width = len(tokens)
    for index in range(max(0, start_index), max(0, len(words) - width + 1)):
        if normalized[index : index + width] == tokens:
            return index, words[index : index + width]
    # Small fallback for tokenization differences: match combined text across one extra token.
    target = "".join(tokens)
    for index in range(max(0, start_index), len(words)):
        combined = ""
        matched: List[Dict[str, Any]] = []
        for item in words[index : min(len(words), index + width + 2)]:
            combined += norm(item.get("word", ""))
            matched.append(item)
            if combined == target:
                return index, matched
            if len(combined) > len(target) + 4:
                break
    return None


def token_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if len(left) >= 3 and len(right) >= 3 and (left in right or right in left):
        return 0.82
    return difflib.SequenceMatcher(a=left, b=right).ratio()


def aligned_votes_for_targets(source_name: str, words: List[Dict[str, Any]], targets: List[str]) -> Dict[int, Dict[str, Any]]:
    normalized_words = [norm(item.get("word", "")) for item in words]
    target_tokens: List[tuple[int, str]] = []
    for index, text in enumerate(targets, start=1):
        for token in phrase_tokens(text):
            target_tokens.append((index, token))

    matched_by_target: Dict[int, List[Dict[str, Any]]] = {}
    word_index = 0
    for target_index, token in target_tokens:
        best_index = -1
        best_score = 0.0
        search_limit = min(len(words), word_index + 28)
        for index in range(word_index, search_limit):
            candidate = normalized_words[index]
            score = token_similarity(token, candidate)
            if len(token) <= 2 and token != candidate:
                score = 0.0
            if score > best_score:
                best_score = score
                best_index = index
        if best_index >= 0 and best_score >= 0.68:
            matched_by_target.setdefault(target_index, []).append(words[best_index])
            word_index = best_index + 1

    votes: Dict[int, Dict[str, Any]] = {}
    for index, text in enumerate(targets, start=1):
        matched_words = matched_by_target.get(index, [])
        if not matched_words:
            continue
        start = min(float(item.get("start", 0) or 0) for item in matched_words)
        end = max(float(item.get("end", 0) or 0) for item in matched_words)
        votes[index] = {
            "target_index": index,
            "text": text,
            "source": source_name,
            "matched": True,
            "match_mode": "ordered_fuzzy_alignment",
            "start": round(start, 3),
            "end": round(end, 3),
            "words": [str(item.get("word", "")).strip() for item in matched_words],
        }
    return votes


def same_index_timing_votes_for_targets(
    source_name: str,
    words: List[Dict[str, Any]],
    targets: List[str],
    canonical_targets: List[Dict[str, Any]],
    max_anchor_distance: float = 1.0,
) -> Dict[int, Dict[str, Any]]:
    """Use ordinal-near groups as timing votes when short ASR text diverges."""
    if not canonical_targets:
        return {}
    source_groups = target_groups_from_words(words, max_targets=len(canonical_targets) + 4)
    votes: Dict[int, Dict[str, Any]] = {}
    for target in canonical_targets:
        try:
            target_index = int(target["target_index"])
            anchor_start = float(target["start"])
            anchor_end = float(target["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if target_index < 1 or target_index > len(source_groups):
            continue
        candidate = source_groups[target_index - 1]
        try:
            start = float(candidate["start"])
            end = float(candidate["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if end <= start:
            continue
        distance = max(abs(start - anchor_start), abs(end - anchor_end))
        if distance > max_anchor_distance:
            continue
        target_text = str(target.get("text") or targets[target_index - 1])
        candidate_text = str(candidate.get("text", ""))
        target_norm = norm(target_text)
        candidate_norm = norm(candidate_text)
        target_is_short = len(phrase_tokens(target_text)) <= 2
        text_similarity = token_similarity(target_norm, candidate_norm)
        if not target_is_short and text_similarity < 0.36:
            continue
        votes[target_index] = {
            "target_index": target_index,
            "text": target_text,
            "source": source_name,
            "matched": True,
            "match_mode": "same_index_temporal_anchor",
            "start": round(start, 3),
            "end": round(end, 3),
            "words": list(candidate.get("words", [])) if isinstance(candidate.get("words"), list) else [],
            "candidate_text": candidate_text,
            "anchor_distance_seconds": round(distance, 3),
        }
    return votes


def model_votes_for_targets(
    source_name: str,
    words: List[Dict[str, Any]],
    targets: List[str],
    canonical_targets: List[Dict[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    votes: List[Dict[str, Any]] = []
    fallback_votes = aligned_votes_for_targets(source_name, words, targets)
    ordinal_votes = same_index_timing_votes_for_targets(source_name, words, targets, canonical_targets or [])
    search_from = 0
    for index, text in enumerate(targets, start=1):
        tokens = phrase_tokens(text)
        match = find_phrase(words, tokens, search_from)
        if not match:
            votes.append(
                fallback_votes.get(
                    index,
                    ordinal_votes.get(
                        index,
                        {"target_index": index, "text": text, "source": source_name, "matched": False},
                    ),
                )
            )
            continue
        word_index, matched_words = match
        search_from = word_index + max(1, len(matched_words))
        start = min(float(item.get("start", 0) or 0) for item in matched_words)
        end = max(float(item.get("end", 0) or 0) for item in matched_words)
        votes.append(
            {
                "target_index": index,
                "text": text,
                "source": source_name,
                "matched": True,
                "match_mode": "exact_phrase",
                "start": round(start, 3),
                "end": round(end, 3),
                "words": [str(item.get("word", "")).strip() for item in matched_words],
            }
        )
    return votes


def transcribe_faster_whisper(model_name: str, media_path: Path) -> List[Dict[str, Any]]:
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(media_path),
        language="en",
        beam_size=5,
        vad_filter=False,
        word_timestamps=True,
        condition_on_previous_text=False,
    )
    words: List[Dict[str, Any]] = []
    for segment in segments:
        for word in getattr(segment, "words", []) or []:
            word_text = str(getattr(word, "word", "")).strip()
            if not word_text:
                continue
            words.append(
                {
                    "word": word_text,
                    "start": round(float(getattr(word, "start", segment.start) or 0), 3),
                    "end": round(float(getattr(word, "end", segment.end) or 0), 3),
                    "probability": round(float(getattr(word, "probability", 0) or 0), 4),
                }
            )
    return clean_timed_words_for_caption(words, f"faster_whisper:{model_name}")


def median(values: Iterable[float]) -> float:
    return float(statistics.median(list(values)))


def filter_votes_near_anchor(votes: List[Dict[str, Any]], anchor_source: str, max_distance: float = 1.0) -> List[Dict[str, Any]]:
    matched = [vote for vote in votes if vote.get("matched")]
    anchor = next((vote for vote in matched if str(vote.get("source", "")) == anchor_source), None)
    if not anchor:
        return matched
    anchor_start = float(anchor["start"])
    anchor_end = float(anchor["end"])
    return [
        vote
        for vote in matched
        if str(vote.get("source", "")) == anchor_source
        or (abs(float(vote["start"]) - anchor_start) <= max_distance and abs(float(vote["end"]) - anchor_end) <= max_distance)
    ]


def anchored_segment(text: str, anchor: Dict[str, Any], votes: List[Dict[str, Any]]) -> Dict[str, Any]:
    matched = [vote for vote in votes if vote.get("matched")]
    windows = [display_window_for_vote(text, vote) for vote in matched] or [display_window_for_vote(text, anchor)]
    start_values = [float(window["display_start"]) for window in windows]
    end_values = [float(window["display_end"]) for window in windows]
    raw_start_values = [float(vote["start"]) for vote in matched] or [float(anchor["start"])]
    raw_end_values = [float(vote["end"]) for vote in matched] or [float(anchor["end"])]
    spread = max(max(start_values) - min(start_values), max(end_values) - min(end_values)) if start_values and end_values else 0.0
    start = max(0.0, median(start_values))
    max_window = caption_display_window_seconds(text) + 0.04
    end = min(max(median(end_values), start + 0.20), start + max_window)
    return {
        "caption_beat": True,
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "source_start": round(median(raw_start_values), 3),
        "source_end": round(median(raw_end_values), 3),
        "model_votes": len(matched),
        "model_names": [str(vote["source"]) for vote in matched],
        "vote_spread_seconds": round(spread, 3),
        "timing_mode": "strong_model_anchor",
        "anchor_source": str(anchor.get("source", "")),
        "long_span_vote_count": int(sum(1 for window in windows if window.get("suspicious_long_span"))),
        "raw_votes": matched,
    }


def consensus_for_target(text: str, votes: List[Dict[str, Any]], min_votes: int, anchor_source: str = "") -> Dict[str, Any]:
    matched = [vote for vote in votes if vote.get("matched")]
    anchor = next((vote for vote in matched if str(vote.get("source", "")) == anchor_source), None)
    if len(matched) < min_votes:
        if anchor and len(matched) >= 2:
            windows = [display_window_for_vote(text, vote) for vote in matched]
            start_values = [float(window["display_start"]) for window in windows]
            end_values = [float(window["display_end"]) for window in windows]
            spread = max(max(start_values) - min(start_values), max(end_values) - min(end_values))
            if spread > 0.35:
                raise RuntimeError(f"{text}: two-vote anchor spread {spread:.2f}s is too wide")
            return anchored_segment(text, anchor, votes)
        raise RuntimeError(f"{text}: only {len(matched)} timing vote(s), need {min_votes}")
    windows = [display_window_for_vote(text, vote) for vote in matched]
    start_median = median(float(window["display_start"]) for window in windows)
    end_median = median(float(window["display_end"]) for window in windows)
    filtered = [
        vote
        for vote, window in zip(matched, windows)
        if abs(float(window["display_start"]) - start_median) <= 0.75 and abs(float(window["display_end"]) - end_median) <= 0.75
    ]
    if len(filtered) >= min_votes:
        matched = filtered
        windows = [display_window_for_vote(text, vote) for vote in matched]
        start_median = median(float(window["display_start"]) for window in windows)
        end_median = median(float(window["display_end"]) for window in windows)
    start_values = [float(window["display_start"]) for window in windows]
    end_values = [float(window["display_end"]) for window in windows]
    raw_start_values = [float(vote["start"]) for vote in matched]
    raw_end_values = [float(vote["end"]) for vote in matched]
    spread = max(max(start_values) - min(start_values), max(end_values) - min(end_values))
    if spread > 0.85:
        raise RuntimeError(f"{text}: timing vote spread {spread:.2f}s is too wide")
    # Use the aligned first-word timestamp as the display anchor; no render-time late bias.
    start = max(0.0, start_median)
    max_window = caption_display_window_seconds(text) + 0.04
    end = min(max(end_median + 0.08, start + 0.20), start + max_window)
    return {
        "caption_beat": True,
        "text": text,
        "start": round(start, 3),
        "end": round(end, 3),
        "source_start": round(median(raw_start_values), 3),
        "source_end": round(median(raw_end_values), 3),
        "model_votes": len(matched),
        "model_names": [str(vote["source"]) for vote in matched],
        "vote_spread_seconds": round(spread, 3),
        "timing_mode": "ensemble_consensus",
        "anchor_source": anchor_source,
        "long_span_vote_count": int(sum(1 for window in windows if window.get("suspicious_long_span"))),
        "raw_votes": matched,
    }


def apply_source_context_corrections(clip: Dict[str, Any] | None, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not clip:
        return segments
    title_tokens = {norm(token) for token in re.findall(r"[A-Za-z0-9'’.-]+", str(clip.get("title", "")))}
    corrected: List[Dict[str, Any]] = []
    for segment in segments:
        updated = dict(segment)
        text = str(updated.get("text", "")).strip()
        if "rae" in title_tokens:
            if text == "RIGHT WOULD":
                updated["text"] = "RAE WOULD"
                updated["context_correction"] = "source_title_name_hint:rae"
            elif text == "RAY":
                updated["text"] = "RAE"
                updated["context_correction"] = "source_title_name_hint:rae"
        if norm(text) in {"niggi", "nigga", "nigger"}:
            updated["text"] = "N-WORD"
            updated["context_correction"] = "platform_safe_explicit_language_display"
        corrected.append(updated)
    return corrected


def words_from_consensus_segments(segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    word_timings: List[Dict[str, Any]] = []
    for segment in segments:
        tokens = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’%$.-]*", str(segment["text"]))
        if not tokens:
            continue
        start = float(segment["start"])
        end = float(segment["end"])
        step = max((end - start) / max(1, len(tokens)), 0.08)
        for index, token in enumerate(tokens):
            word_timings.append(
                {
                    "word": token,
                    "start": round(start + step * index, 3),
                    "end": round(min(end, start + step * (index + 1)), 3),
                    "probability": 1.0,
                }
            )
    return word_timings


def store_consensus_transcript(clip_id: str, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
    transcript_id = db.new_id("transcript")
    clean_segments = [{key: value for key, value in segment.items() if key != "raw_votes"} for segment in segments]
    word_timings = words_from_consensus_segments(clean_segments)
    full_text = " ".join(str(segment["text"]) for segment in clean_segments)
    avg_votes = sum(int(segment.get("model_votes", 0) or 0) for segment in clean_segments) / max(1, len(clean_segments))
    db.execute(
        """
        INSERT INTO transcripts
          (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, word_timings_json, status, created_at)
        VALUES (?, ?, ?, 'en', ?, ?, ?, ?, 'succeeded', ?)
        """,
        (
            transcript_id,
            clip_id,
            ENSEMBLE_PROVIDER,
            min(1.0, avg_votes / 5.0),
            full_text,
            json.dumps(clean_segments),
            json.dumps(word_timings),
            db.utc_now(),
        ),
    )
    db.log_audit("worker", "ensemble_retime_review_kit", "clip_candidate", clip_id, f"stored {ENSEMBLE_PROVIDER}", transcript_id)
    return db.one("SELECT * FROM transcripts WHERE id = ?", (transcript_id,)) or {}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default=",".join(DEFAULT_MODELS))
    parser.add_argument("--min-votes", type=int, default=3)
    parser.add_argument("--clip-id", default="")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args()

    db.init_db()
    kits = db.visible_render_kits()
    if args.clip_id:
        kits = [kit for kit in kits if str(kit.get("clip_id", "")) == args.clip_id]
        if not kits:
            raise SystemExit(f"no visible review kit for clip id {args.clip_id}")
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for kit in kits:
        clip_id = str(kit["clip_id"])
        clip = db.one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,))
        media_path = Path(str((clip or {}).get("local_media_path", "")))
        targets = caption_targets_for_kit(kit)
        kit_result: Dict[str, Any] = {
            "clip_id": clip_id,
            "kit_id": str(kit["id"]),
            "title": str(kit["title"]),
            "previous_targets": targets,
            "targets": [],
            "target_source": "",
            "sources": [],
            "consensus": [],
            "dropped_targets": [],
        }
        if not media_path.exists():
            failures.append({"clip_id": clip_id, "error": f"media missing: {media_path}"})
            continue
        source_word_sets: Dict[str, List[Dict[str, Any]]] = {}

        existing_transcript = latest_non_ensemble_transcript(clip_id)
        existing_words = transcript_words(existing_transcript)
        if existing_words:
            existing_source_name = transcript_source_name(existing_transcript)
            source_word_sets[existing_source_name] = existing_words
            kit_result["sources"].append({"name": existing_source_name, "word_count": len(existing_words)})

        for model_name in models:
            source_name = f"faster_whisper_{model_name.replace('.', '_').replace('-', '_')}"
            try:
                words = transcribe_faster_whisper(model_name, media_path)
                source_word_sets[source_name] = words
                kit_result["sources"].append({"name": source_name, "word_count": len(words)})
            except Exception as exc:
                kit_result["sources"].append({"name": source_name, "error": str(exc)[:1200]})

        try:
            if not source_word_sets:
                raise RuntimeError("no ensemble transcription sources produced word timings")
            canonical_name = preferred_canonical_source(source_word_sets, min_votes=args.min_votes)
            target_groups = target_groups_from_words(source_word_sets[canonical_name])
            if not target_groups:
                raise RuntimeError("no canonical caption targets were produced")
            targets = [str(target["text"]) for target in target_groups]
            kit_result["target_source"] = canonical_name
            kit_result["targets"] = targets
            source_votes: Dict[int, List[Dict[str, Any]]] = {index: [] for index in range(1, len(targets) + 1)}
            for source_name, words in source_word_sets.items():
                if source_name == canonical_name:
                    for target in target_groups:
                        source_votes[int(target["target_index"])].append(canonical_anchor_vote(source_name, target))
                    continue
                for vote in model_votes_for_targets(source_name, words, targets, canonical_targets=target_groups):
                    source_votes[int(vote["target_index"])].append(vote)

            consensus_segments = []
            for index, text in enumerate(targets, start=1):
                try:
                    anchored_votes = filter_votes_near_anchor(source_votes[index], canonical_name)
                    consensus_segments.append(
                        consensus_for_target(
                            text,
                            anchored_votes,
                            min_votes=args.min_votes,
                            anchor_source=canonical_name,
                        )
                    )
                except RuntimeError as exc:
                    kit_result["dropped_targets"].append({"index": index, "text": text, "reason": str(exc)})
            minimum_survivors = minimum_consensus_survivors(len(targets))
            if len(consensus_segments) < minimum_survivors:
                raise RuntimeError(
                    f"too few consensus captions survived ({len(consensus_segments)}/{len(targets)}); refusing to rerender"
                )
            consensus_segments = apply_source_context_corrections(clip, consensus_segments)
            store_consensus_transcript(clip_id, consensus_segments)
            kit_result["consensus"] = consensus_segments
            if not args.no_render:
                kit_result["render"] = review_builder.build_review_kit(
                    clip_id=clip_id,
                    profile=db.CAMPAIGN_SHORT_PROFILE,
                    campaign_slug=str(kit.get("campaign_slug", "")),
                    force=True,
                    caption_variant=caption_variant_for_kit(kit),
                    quota_recovery=True,
                )
        except Exception as exc:
            failures.append({"clip_id": clip_id, "error": str(exc)[:1800], "sources": kit_result["sources"]})

        results.append(kit_result)
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps({"status": "running", "results": results, "failures": failures}, indent=2) + "\n", encoding="utf-8")

    payload = {
        "status": "succeeded" if not failures else "failed",
        "provider": ENSEMBLE_PROVIDER,
        "model_count_target": 1 + len(models),
        "faster_whisper_models": models,
        "kit_count": len(kits),
        "results": results,
        "failures": failures,
        "generated_at": db.utc_now(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
