from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

from PIL import ImageDraw, ImageFont


CAPTION_MAX_WORDS_PER_LINE = 2
CAPTION_TARGET_MAX_LINE_CHARS = 12
CAPTION_MAX_LINES = 1
CAPTION_FONT_NAME = "TikTok Sans 36pt Black"
CAPTION_FONT_SIZE = 62
CAPTION_SAFE_BAND_TOP_Y = 1128
CAPTION_SAFE_BAND_BOTTOM_Y = 1235
CAPTION_VERTICAL_CENTER_Y = 1184
CAPTION_MIN_CENTER_Y = CAPTION_SAFE_BAND_TOP_Y + 36
CAPTION_MAX_CENTER_Y = CAPTION_SAFE_BAND_BOTTOM_Y - 36
PRODUCTION_CAPTION_VARIANTS = ("A", "B", "D", "E")
DEFAULT_CAMPAIGN_CAPTION_VARIANT = "B"
CAPTION_MIN_WORD_DURATION = 0.06
CAPTION_MIN_VTT_WORD_DURATION = 0.12
CAPTION_SINGLE_WORD_WINDOW_SECONDS = 0.44
CAPTION_TWO_WORD_WINDOW_SECONDS = 0.58
CAPTION_AUDIO_SYNC_DELAY_SECONDS = 0.0
CAPTION_AUDIO_LEAD_RATIO = 0.58
CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS = 0.04
CAPTION_MAX_AUDIO_LEAD_SECONDS = 0.04
CAPTION_MAX_AUDIO_LAG_SECONDS = 0.08
CAPTION_MAX_WORD_GAP_SECONDS = 0.34
CAPTION_MAX_WORD_SPAN_SECONDS = 0.72

FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
CAPTION_TOKEN_RE = r"[A-Za-z0-9][A-Za-z0-9'’%$*-]*"


def caption_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        FONT_DIR / "TikTokSans36pt-Black.ttf",
        FONT_DIR / "TikTokSans36pt-ExtraBold.ttf",
        Path("/System/Library/Fonts/Supplemental/Impact.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Black.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
        Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        Path("/System/Library/Fonts/Helvetica.ttc"),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                return ImageFont.truetype(str(candidate), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def caption_style_manifest() -> Dict[str, Any]:
    return {
        "font_family": "TikTok Sans",
        "font_file": str((FONT_DIR / "TikTokSans36pt-Black.ttf").resolve()),
        "font_weight": "Black",
        "font_size": CAPTION_FONT_SIZE,
        "license": "SIL Open Font License 1.1",
        "source": "https://github.com/tiktok/TikTokSans/releases/tag/v4.000",
        "max_words_per_line": CAPTION_MAX_WORDS_PER_LINE,
        "target_max_line_chars": CAPTION_TARGET_MAX_LINE_CHARS,
        "max_lines_per_caption": CAPTION_MAX_LINES,
        "max_words_on_screen": CAPTION_MAX_WORDS_PER_LINE,
        "production_ab_variants": list(PRODUCTION_CAPTION_VARIANTS),
        "default_campaign_variant": DEFAULT_CAMPAIGN_CAPTION_VARIANT,
        "vertical_center_y": CAPTION_VERTICAL_CENTER_Y,
        "safe_band_top_y": CAPTION_SAFE_BAND_TOP_Y,
        "safe_band_bottom_y": CAPTION_SAFE_BAND_BOTTOM_Y,
        "audio_sync_delay_seconds": CAPTION_AUDIO_SYNC_DELAY_SECONDS,
        "audio_lead_ratio": CAPTION_AUDIO_LEAD_RATIO,
        "max_pre_audio_lead_seconds": CAPTION_MAX_PRE_AUDIO_LEAD_SECONDS,
        "max_audio_lead_seconds": CAPTION_MAX_AUDIO_LEAD_SECONDS,
        "max_audio_lag_seconds": CAPTION_MAX_AUDIO_LAG_SECONDS,
        "max_word_gap_seconds": CAPTION_MAX_WORD_GAP_SECONDS,
        "max_word_span_seconds": CAPTION_MAX_WORD_SPAN_SECONDS,
        "placement": "platform-safe lower third; above TikTok/Reels/Shorts caption and nav UI",
    }


def normalize_caption_variant(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if text in PRODUCTION_CAPTION_VARIANTS else "A"


def caption_variant_for_key(value: Any) -> str:
    text = str(value or "")
    if not text:
        return "A"
    index = sum(ord(char) for char in text) % len(PRODUCTION_CAPTION_VARIANTS)
    return PRODUCTION_CAPTION_VARIANTS[index]


def caption_center_y_for_source(width: float, height: float) -> int:
    return CAPTION_VERTICAL_CENTER_Y


def clean_caption_word(value: Any) -> str:
    word = re.sub(r"\s+", " ", str(value or "").strip())
    return word.strip()


def _display_len(words: Iterable[str]) -> int:
    return len(" ".join(words).strip())


def split_words_for_caption(words: Iterable[str]) -> List[List[str]]:
    groups: List[List[str]] = []
    current: List[str] = []
    for raw_word in words:
        word = clean_caption_word(raw_word)
        if not word:
            continue
        if current:
            candidate = [*current, word]
            if len(candidate) > CAPTION_MAX_WORDS_PER_LINE or _display_len(candidate) > CAPTION_TARGET_MAX_LINE_CHARS:
                groups.append(current)
                current = [word]
            else:
                current = candidate
        else:
            current = [word]
        if word.endswith((".", "?", "!", ":")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups


def timed_caption_groups(words: Iterable[Dict[str, Any]], max_groups: int = 80) -> List[List[Dict[str, Any]]]:
    groups: List[List[Dict[str, Any]]] = []
    current: List[Dict[str, Any]] = []
    for item in words:
        word = clean_caption_word(item.get("word", ""))
        if not word:
            continue
        next_item = {**item, "word": word}
        force_new_group = False
        if current:
            try:
                previous_end = float(current[-1].get("end", 0) or 0)
                next_start = float(next_item.get("start", 0) or 0)
                force_new_group = next_start - previous_end > CAPTION_MAX_WORD_GAP_SECONDS
            except (TypeError, ValueError):
                force_new_group = False
        if current and force_new_group:
            groups.append(current)
            current = [next_item]
        elif current:
            candidate_words = [str(piece["word"]) for piece in [*current, next_item]]
            if len(candidate_words) > CAPTION_MAX_WORDS_PER_LINE or _display_len(candidate_words) > CAPTION_TARGET_MAX_LINE_CHARS:
                groups.append(current)
                current = [next_item]
            else:
                current.append(next_item)
        else:
            current = [next_item]
        if word.endswith((".", "?", "!", ":")):
            groups.append(current)
            current = []
        if len(groups) >= max_groups:
            return groups[:max_groups]
    if current and len(groups) < max_groups:
        groups.append(current)
    return groups[:max_groups]


SPLIT_WORD_REPAIRS = {
    ("sil", "ky"): "Silky",
    ("ship", "pers"): "shippers",
    ("sh", "ippers"): "shippers",
    ("ped", "ophile"): "pedophile",
    ("col", "oring"): "coloring",
    ("en", "vision"): "envision",
    ("shin", "iness"): "shininess",
    ("ig", "gas"): "iggas",
    ("lo", "ci"): "loci",
}


def _normalized_word_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def caption_word_duration_cap(word: Any) -> float:
    normalized = _normalized_word_key(word)
    if not normalized:
        return 0.18
    return min(0.52, max(0.18, 0.10 + len(normalized) * 0.035))


def repair_timed_words_for_caption(words: Iterable[Dict[str, Any]], provider: Any = "") -> List[Dict[str, Any]]:
    """Repair ASR token fragments while preserving the original timing anchors."""
    provider_text = str(provider or "").lower()
    min_duration = CAPTION_MIN_VTT_WORD_DURATION if ("vtt" in provider_text or "subtitle" in provider_text) else CAPTION_MIN_WORD_DURATION
    parsed: List[Dict[str, Any]] = []
    raw_items = list(words)
    for index, item in enumerate(raw_items):
        word = clean_caption_word(item.get("word", ""))
        if not word:
            continue
        try:
            start = float(item.get("start", 0) or 0)
            end = float(item.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        if start < 0:
            continue
        if end <= start or end - start < min_duration:
            next_start = None
            for later in raw_items[index + 1 :]:
                try:
                    candidate = float(later.get("start", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if candidate > start:
                    next_start = candidate
                    break
            if next_start is not None:
                end = min(start + min_duration, max(start + 0.025, next_start - 0.01))
            else:
                end = start + min_duration
        if end - start > CAPTION_MAX_WORD_SPAN_SECONDS:
            start = max(0.0, end - caption_word_duration_cap(word))
        parsed.append({"word": word, "start": start, "end": end, "_index": index})

    parsed.sort(key=lambda value: (float(value["start"]), float(value["end"]), int(value["_index"])))
    repaired: List[Dict[str, Any]] = []
    index = 0
    while index < len(parsed):
        item = parsed[index]
        word = str(item["word"])
        normalized = _normalized_word_key(word)
        if not normalized and re.fullmatch(r"[,.!?;:]+", word) and repaired:
            previous = repaired[-1]
            previous["word"] = str(previous["word"]).rstrip(".,!?;:") + word
            previous["end"] = max(float(previous["end"]), float(item["end"]))
            index += 1
            continue
        if not normalized and not re.fullmatch(r"['’][a-zA-Z]+", word):
            index += 1
            continue
        if re.fullmatch(r"['’][a-zA-Z]+", word) and repaired:
            previous = repaired[-1]
            previous["word"] = str(previous["word"]) + word.replace("’", "'")
            previous["end"] = max(float(previous["end"]), float(item["end"]))
            index += 1
            continue
        if index + 1 < len(parsed):
            next_item = parsed[index + 1]
            pair = (normalized, _normalized_word_key(next_item["word"]))
            if pair in SPLIT_WORD_REPAIRS:
                repaired.append(
                    {
                        "word": SPLIT_WORD_REPAIRS[pair],
                        "start": float(item["start"]),
                        "end": max(float(item["end"]), float(next_item["end"])),
                    }
                )
                index += 2
                continue
            if pair[1] in {"ing", "ness", "ers", "er", "ed", "s"} and len(pair[0]) >= 4:
                repaired.append(
                    {
                        "word": str(item["word"]) + str(next_item["word"]).lower(),
                        "start": float(item["start"]),
                        "end": max(float(item["end"]), float(next_item["end"])),
                    }
                )
                index += 2
                continue
        if normalized:
            repaired.append({"word": word, "start": float(item["start"]), "end": float(item["end"])})
        index += 1
    return repaired


def clean_timed_words_for_caption(words: Iterable[Dict[str, Any]], provider: Any = "") -> List[Dict[str, Any]]:
    """Drop impossible transcript timings before they become burned-in captions."""
    provider_text = str(provider or "").lower()
    min_duration = CAPTION_MIN_VTT_WORD_DURATION if ("vtt" in provider_text or "subtitle" in provider_text) else CAPTION_MIN_WORD_DURATION
    parsed: List[Dict[str, Any]] = []
    for index, item in enumerate(repair_timed_words_for_caption(words, provider)):
        word = clean_caption_word(item.get("word", ""))
        if not word:
            continue
        try:
            start = float(item.get("start", 0) or 0)
            end = float(item.get("end", 0) or 0)
        except (TypeError, ValueError):
            continue
        if start < 0 or end <= start:
            continue
        normalized = re.sub(r"[^a-z0-9]+", "", word.lower())
        minimum_allowed = 0.025 if len(normalized) <= 2 else min_duration
        if end - start < minimum_allowed:
            continue
        parsed.append({"word": word, "start": start, "end": end, "_index": index})

    parsed.sort(key=lambda value: (float(value["start"]), float(value["end"]), int(value["_index"])))
    cleaned: List[Dict[str, Any]] = []
    recent_by_word: Dict[str, float] = {}
    for item in parsed:
        word = str(item["word"])
        normalized = re.sub(r"[^a-z0-9]+", "", word.lower())
        if not normalized:
            continue
        start = float(item["start"])
        end = float(item["end"])

        if normalized in recent_by_word and start - recent_by_word[normalized] < 0.08:
            continue
        if cleaned:
            previous = cleaned[-1]
            previous_end = float(previous["end"])
            if start < previous_end - 0.04:
                start = previous_end + 0.02
                if end - start < min_duration:
                    continue

        cleaned_item = {"word": word, "start": round(start, 3), "end": round(end, 3)}
        if "probability" in item:
            cleaned_item["probability"] = item["probability"]
        cleaned.append(cleaned_item)
        recent_by_word[normalized] = start
    return cleaned


def caption_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    style_font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = CAPTION_MAX_LINES,
) -> List[str]:
    words = [word.upper() for word in re.findall(CAPTION_TOKEN_RE, text)]
    if not words:
        return []
    lines: List[str] = []
    for group in split_words_for_caption(words):
        line = " ".join(group).strip()
        while line and draw.textbbox((0, 0), line, font=style_font, stroke_width=7)[2] > max_width and len(line) > 8:
            line = line[:-1].rstrip()
        if line:
            lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def caption_display_text(text: Any) -> str:
    words = re.findall(CAPTION_TOKEN_RE, str(text or ""))
    return " ".join(word.upper().replace("’", "'") for word in words).strip()


def caption_display_window_seconds(text: Any) -> float:
    words = re.findall(CAPTION_TOKEN_RE, str(text or ""))
    if len(words) <= 1:
        return CAPTION_SINGLE_WORD_WINDOW_SECONDS
    return CAPTION_TWO_WORD_WINDOW_SECONDS


def caption_start_for_group(raw_start: float, raw_end: float, text: Any) -> float:
    """Start captions on the aligned first spoken word."""
    return max(0.0, float(raw_start))


def apply_caption_audio_sync_delay(start: float, end: float) -> tuple[float, float]:
    """Apply the calibrated render sync offset."""
    shifted_start = max(0.0, float(start) + CAPTION_AUDIO_SYNC_DELAY_SECONDS)
    shifted_end = max(shifted_start + 0.12, float(end) + CAPTION_AUDIO_SYNC_DELAY_SECONDS)
    return shifted_start, shifted_end


def caption_text_violations(text: str) -> List[str]:
    violations: List[str] = []
    for index, line in enumerate(str(text).splitlines() or [str(text)], start=1):
        words = re.findall(CAPTION_TOKEN_RE, line)
        if len(words) > CAPTION_MAX_WORDS_PER_LINE:
            violations.append(f"line {index} has {len(words)} words")
        if len(words) > 1 and len(" ".join(words)) > CAPTION_TARGET_MAX_LINE_CHARS:
            violations.append(f"line {index} exceeds {CAPTION_TARGET_MAX_LINE_CHARS} characters")
    return violations


def caption_beat_violations(beats: Iterable[Any]) -> List[str]:
    violations: List[str] = []
    for index, beat in enumerate(beats, start=1):
        text = str(beat)
        words = re.findall(CAPTION_TOKEN_RE, text)
        if len(words) > CAPTION_MAX_WORDS_PER_LINE:
            violations.append(f"caption beat {index} has {len(words)} words")
        if len(words) > 1 and len(" ".join(words)) > CAPTION_TARGET_MAX_LINE_CHARS:
            violations.append(f"caption beat {index} exceeds {CAPTION_TARGET_MAX_LINE_CHARS} characters")
    return violations


BROKEN_CAPTION_PHRASES = (
    "AIN 'T",
    "DON 'T",
    "DIDN 'T",
    "DOESN 'T",
    "WASN 'T",
    "WEREN 'T",
    "CAN 'T",
    "IT 'S",
    "LET 'S",
    "I 'M",
    "I 'LL",
    "DON DIDN",
    "STILL ISN",
    "'T IMPRESS",
    "ING YOU",
    "SH IPPERS",
    "PED OPHILE",
    "COL ORING",
    "EN VISION",
    "SHIN INESS",
    "IGG AS",
)


def caption_text_quality_violations(beats: Iterable[Any]) -> List[str]:
    violations: List[str] = []
    for index, beat in enumerate(beats, start=1):
        text = re.sub(r"\s+", " ", str(beat).strip().upper())
        if not text:
            continue
        if re.search(r"(^|\s)['’][A-Z]+", text):
            violations.append(f"caption beat {index} starts with detached apostrophe fragment: {text}")
            continue
        if re.search(r"[A-Z0-9]+\s+['’][A-Z]+", text):
            violations.append(f"caption beat {index} has detached apostrophe fragment: {text}")
            continue
        matched = next((phrase for phrase in BROKEN_CAPTION_PHRASES if phrase == text), "")
        if matched:
            violations.append(f"caption beat {index} has broken ASR fragment `{matched}`: {text}")
            continue
        if re.search(r"\b[A-Z]{2,}\s+(ING|IPPERS|OPHILE|ORING|INESS|VISION)\b", text):
            violations.append(f"caption beat {index} appears to split one word: {text}")
    return violations
