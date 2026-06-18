"""Deterministic top-card quality gate for campaign review kits."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


GENERIC_CHAT_PHRASES = (
    "had the whole chat watching",
    "whole chat watching",
    "chat was watching",
    "everyone was watching",
    "chat locked in",
    "over this moment",
    "stream went crazy",
    "chat went crazy",
)

ASR_GARBLE_PHRASES = (
    "your ridge",
    "little sisin",
    "sisin yonna",
)

INTERNAL_HOOK_TOKENS = (
    "selected feeder",
    "feeder proof",
    "evidence review",
    "review kit",
    "manual review",
    "human review",
    "local demo",
    "demo only",
)

FILLER_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "in",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}

STREAMER_WORDS = {
    "yourrage",
    "yourragegaming",
    "plaqueboymax",
    "max",
    "jasontheween",
    "jason",
    "lacy",
}

SUMMARY_VERBS = {
    "asked",
    "caught",
    "debated",
    "found",
    "got",
    "heard",
    "made",
    "opened",
    "realized",
    "regretted",
    "shut",
    "started",
    "turned",
    "watched",
}


class HookQualityError(RuntimeError):
    """Raised when no candidate hook is safe to render into a review kit."""

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        super().__init__(str(payload.get("blocker") or payload.get("blocker_code") or "blocked_hook_quality"))


def _compact_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip(" ,.;:-")


def _word_tokens(value: Any) -> List[str]:
    return re.findall(r"[a-z0-9]{2,}", str(value or "").lower())


def _token_key(value: Any) -> str:
    return " ".join(_word_tokens(value))


def _has_repeated_ngram(words: List[str], size: int) -> bool:
    if len(words) < size * 2:
        return False
    seen: set[tuple[str, ...]] = set()
    for index in range(0, len(words) - size + 1):
        ngram = tuple(words[index : index + size])
        if all(word in FILLER_WORDS for word in ngram):
            continue
        if ngram in seen:
            return True
        seen.add(ngram)
    return False


def _has_consecutive_repeated_content(words: List[str]) -> bool:
    previous = ""
    for word in words:
        if word in FILLER_WORDS or word in STREAMER_WORDS:
            previous = ""
            continue
        if previous == word:
            return True
        previous = word
    return False


def _uppercase_word_ratio(value: Any) -> float:
    raw_words = re.findall(r"[A-Za-z0-9']{3,}", str(value or ""))
    if not raw_words:
        return 0.0
    uppercase = [
        word
        for word in raw_words
        if any(char.isalpha() for char in word) and word.upper() == word and word.lower() != word
    ]
    return len(uppercase) / max(1, len(raw_words))


def _looks_like_raw_asr_fragment(text: str, words: List[str]) -> bool:
    if len(words) < 7:
        return False
    if _has_consecutive_repeated_content(words) or _has_repeated_ngram(words, 3):
        return True
    if _uppercase_word_ratio(text) >= 0.55:
        return True
    has_summary_verb = any(word in SUMMARY_VERBS for word in words)
    if has_summary_verb:
        return False
    question_starts = {"what", "why", "how", "who", "where", "when", "yeah", "nah", "bro"}
    return words[0] in question_starts and len(words) >= 9


def _candidate_text(candidate: Any) -> str:
    if isinstance(candidate, dict):
        return _compact_text(candidate.get("text") or candidate.get("hook") or candidate.get("hook_card"))
    return _compact_text(candidate)


def _candidate_source(candidate: Any, index: int) -> str:
    if isinstance(candidate, dict):
        return _compact_text(candidate.get("source") or candidate.get("provider") or f"candidate_{index}")
    return f"candidate_{index}"


def _learning_avoid_phrases(learning_context: Dict[str, Any] | None) -> List[str]:
    if not isinstance(learning_context, dict):
        return []
    phrases: List[str] = []
    notes = learning_context.get("recent_notes", [])
    if isinstance(notes, list):
        for note in notes:
            lowered = str(note or "").lower()
            for phrase in GENERIC_CHAT_PHRASES:
                if phrase in lowered and phrase not in phrases:
                    phrases.append(phrase)
    return phrases


def hook_quality_violations(
    hook: Any,
    *,
    clip_title: str = "",
    handle: str = "",
    campaign_slug: str = "",
    transcript_text: str = "",
    recent_hooks: Iterable[str] | None = None,
    learning_context: Dict[str, Any] | None = None,
) -> List[str]:
    text = _compact_text(hook)
    lowered = text.lower()
    words = _word_tokens(text)
    content_words = [word for word in words if word not in FILLER_WORDS and word not in STREAMER_WORDS]
    violations: List[str] = []

    if not text:
        violations.append("empty_hook")
        return violations
    if any(token in lowered for token in INTERNAL_HOOK_TOKENS):
        violations.append("internal_label_hook")
    if any(phrase in lowered for phrase in GENERIC_CHAT_PHRASES):
        violations.append("generic_chat_hook")
    if any(phrase in lowered for phrase in ASR_GARBLE_PHRASES):
        violations.append("asr_garble_hook")
    if re.search(r"\b(?:said|says|goes|yells|yelled|asks|asked)\s*:", lowered):
        violations.append("quote_dump_hook")
    if _token_key(clip_title) and _token_key(text) == _token_key(clip_title):
        violations.append("raw_title_echo")
    if _has_consecutive_repeated_content(words) or _has_repeated_ngram(words, 3):
        violations.append("repetitive_hook")
    if _looks_like_raw_asr_fragment(text, words):
        violations.append("raw_asr_fragment_hook")
    if len(words) < 5:
        violations.append("too_short_hook")
    if len(words) > 14:
        violations.append("too_long_hook")
    if len(content_words) < 3:
        violations.append("low_information_hook")
    if lowered.endswith(" on stream") and len(words) <= 6:
        violations.append("generic_on_stream_hook")

    recent_keys = {_token_key(item) for item in recent_hooks or [] if _token_key(item)}
    if _token_key(text) in recent_keys:
        violations.append("duplicate_recent_hook")

    avoid_phrases = _learning_avoid_phrases(learning_context)
    if any(phrase in lowered for phrase in avoid_phrases):
        violations.append("rejected_learning_phrase")

    return violations


def select_hook_candidate(
    candidates: Iterable[Any],
    *,
    clip_title: str = "",
    handle: str = "",
    campaign_slug: str = "",
    transcript_text: str = "",
    recent_hooks: Iterable[str] | None = None,
    learning_context: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    reviewed: List[Dict[str, Any]] = []
    selected: Dict[str, Any] | None = None

    for index, candidate in enumerate(candidates, start=1):
        text = _candidate_text(candidate)
        source = _candidate_source(candidate, index)
        violations = hook_quality_violations(
            text,
            clip_title=clip_title,
            handle=handle,
            campaign_slug=campaign_slug,
            transcript_text=transcript_text,
            recent_hooks=recent_hooks,
            learning_context=learning_context,
        )
        item = {
            "text": text,
            "source": source,
            "status": "blocked" if violations else "passed",
            "violations": violations,
        }
        reviewed.append(item)
        if selected is None and not violations:
            selected = item

    if selected:
        return {
            "status": "succeeded",
            "selected_hook": selected["text"],
            "selected_source": selected["source"],
            "campaign_slug": campaign_slug,
            "candidates": reviewed,
        }

    return {
        "status": "blocked",
        "blocker_code": "blocked_hook_quality",
        "blocker": "No hook candidate passed the top-card quality gate.",
        "campaign_slug": campaign_slug,
        "candidates": reviewed,
    }


def require_selected_hook(payload: Dict[str, Any]) -> str:
    if payload.get("status") != "succeeded":
        raise HookQualityError(payload)
    return str(payload.get("selected_hook", "")).strip()
