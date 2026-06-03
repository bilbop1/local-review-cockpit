from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .caption_style import caption_beat_violations, caption_text_quality_violations


APP_NAME = "ClippingOpsCockpit"
FRESH_EVIDENCE_HOURS = 24
CAMPAIGN_RECENT_CLIP_DAYS = 35
SELECTED_FEEDER_FLAGS = (
    "selected_feeder_yourrage",
    "selected_feeder_yourragegaming",
    "selected_feeder_plaqueboymax",
    "selected_feeder_jasontheween",
    "selected_feeder_doublelift",
    "selected_feeder_lacy",
    "selected_feeder_sketch",
    "selected_feeder_ohnepixel",
)
FINAL_PROOF_PROFILE = "selected_feeder_final_v1"
CAMPAIGN_SHORT_PROFILE = "campaign_short_final_v1"
CAMPAIGN_PROJECT_TARGET = 5
WATERMARK_REQUIRED_CAMPAIGNS = {"plaqueboymax", "jasontheween"}
LOCAL_MEDIA_READY_FLAGS = {"local_media_downloaded", "source_media_verified_local", "source_download_verified"}
DEFAULT_HERMES_PROFILE = "default"
HERMES_JOB_ACTIVE_STATUSES = ("queued", "claimed", "running")
HERMES_JOB_TERMINAL_STATUSES = ("succeeded", "blocked", "failed", "cancelled")
HERMES_JOB_INTENTS = {
    "refresh_campaigns": {"name": "Refresh Campaigns", "kind": "research", "stage": "queued-for-hermes"},
    "refresh_campaign_project": {"name": "Refresh Campaign Brief", "kind": "research", "stage": "queued-for-hermes"},
    "discover_campaign_sources": {"name": "Discover Campaign Sources", "kind": "research", "stage": "queued-for-hermes"},
    "build_campaign_reviews": {"name": "Build Campaign Reviews", "kind": "render", "stage": "queued-for-hermes"},
    "platform_smoke": {"name": "Run Platform Check", "kind": "platform", "stage": "queued-for-hermes"},
    "selected_feeder_sweep": {"name": "Check Creators", "kind": "platform", "stage": "queued-for-hermes"},
    "review_risk_sweep": {"name": "Review Risk Sweep", "kind": "review", "stage": "queued-for-hermes"},
}
CAMPAIGN_PROJECTS: Dict[str, Dict[str, str]] = {
    "yourrage": {
        "name": "YourRAGE",
        "campaign_url": "https://clipping.net/dashboard/campaigns/yourrage-x-clipping",
        "source_strategy": "Streamer-first Twitch clip/VOD sweep; requirements were captured as None, so prioritize recent high-retention stream moments.",
        "requirements_url": "",
        "requirements_text": "Requirements: None. Supported platforms captured from Clipping.net: YouTube, Instagram, TikTok. Source route: Twitch handle yourragegaming.",
        "platform": "twitch",
        "platform_handle": "yourragegaming",
        "active": "true",
    },
    "plaqueboymax": {
        "name": "PlaqueBoyMax",
        "campaign_url": "https://clipping.net/dashboard/campaigns/plaqueboymax-x-clipping",
        "source_strategy": "Active streamer-first Twitch sweep; use PlaqueBoyMax/PBM moments only and keep required watermark/source proof in the kit sidecars.",
        "requirements_url": "https://docs.google.com/document/d/14vQvB96kRqwWgwgph553vH3ibKgdqTPRrx-CKkreGkg/edit?usp=sharing",
        "watermark_url": "https://drive.google.com/drive/folders/1wRUOI5TLlrYBXO0I2sQI6wQZyepYG9O4?usp=sharing",
        "watermark_required": "true",
        "platform": "twitch",
        "platform_handle": "plaqueboymax",
        "active": "true",
        "activation_note": "Promoted after user confirmed the campaign is visible on the current Clipping.net front page.",
    },
    "doublelift": {
        "name": "Doublelift",
        "campaign_url": "https://clipping.net/dashboard/campaigns/doublelift-x-clipping",
        "source_strategy": "Streamer-first Twitch sweep for Big Brain Plays and Funny Moments; low minimum views, but budget/freshness must be reconfirmed before heavy rendering.",
        "requirements_url": "https://docs.google.com/document/d/1XNZxiDR__hpneFlLFMoqGp1p35j1gKR2HoT2FvlaltQ/edit?usp=sharing",
        "platform": "twitch",
        "platform_handle": "doublelift",
        "active": "false",
        "excluded_reason": "Watchlist until fresh Clipping.net status is confirmed; stored evidence implies the campaign expired and budget was 99% filled.",
    },
    "kalshi": {
        "name": "Kalshi",
        "campaign_url": "https://clipping.net/dashboard/campaigns/kalshi-x-clipping",
        "source_strategy": "Archived renderer proof lane: approved YouTube source videos from the Kalshi podcasts bounty, but weak daily clip/view impetus.",
        "requirements_url": "https://docs.google.com/document/d/15T4ZLKLj2QEYlYOGVOXvu7xKfHaAFpU3ANbLWB5BHfg/edit?usp=sharing",
        "active": "false",
        "excluded_reason": "Archived from the active review batch because it is source-clean but not streamer-native daily viral supply.",
    },
    "dunkman": {
        "name": "Dunkman",
        "campaign_url": "https://clipping.net/dashboard/campaigns/dunkman-x-clipping",
        "source_strategy": "Archived renderer proof lane: provided Box/Drive media-bank assets, but weak organic viewer motivation versus streamer clips.",
        "requirements_url": "https://docs.google.com/document/d/10I9Z4UriGH3hc7i2e0ryM8Pt8z4arGweV5NS5xP6_kY/edit?usp=sharing",
        "active": "false",
        "excluded_reason": "Archived from the active review batch because the content is not clip-native streamer supply.",
    },
    "haste": {
        "name": "Haste",
        "campaign_url": "https://clipping.net/dashboard/campaigns/haste-x-clipping",
        "source_strategy": "Excluded: the campaign exposes no source pack or approved source media, so rendering would become content generation.",
        "requirements_url": "",
        "active": "false",
        "excluded_reason": "No linked media pack/source brief/reference media; content generation is out of scope.",
    },
    "lacy": {
        "name": "Lacy",
        "campaign_url": "https://clipping.net/dashboard/campaigns/lacy-x-clipping",
        "source_strategy": "Demoted streamer lane: Twitch supply exists, but the brief narrowly requires arrested or missing-in-action moments.",
        "requirements_url": "https://docs.google.com/document/d/1gHf_Ae3WY_qHKwIUppazedxYEkidYHKT4jDG3YSLPrw/edit?usp=sharing",
        "platform": "twitch",
        "platform_handle": "lacy",
        "active": "false",
        "excluded_reason": "Demoted because normal daily Lacy clips do not satisfy the narrow arrested/missing-in-action brief.",
    },
    "jasontheween": {
        "name": "JasonTheWeen",
        "campaign_url": "https://clipping.net/dashboard/campaigns/jasontheween-x-clipping",
        "source_strategy": "Active streamer-first Twitch sweep with strong content velocity; respect watermark/strict source requirements from the stored brief.",
        "requirements_url": "https://docs.google.com/document/d/1-PiU5LkksY0oskl98vpIqAcAMV9IOjsM2jHFPADPj04/edit?usp=drivesdk",
        "watermark_url": "https://drive.google.com/file/d/1zPUm7GX4Se3ux63psvGR4FWGDcSg5RDr/view?usp=drive_link",
        "watermark_required": "true",
        "platform": "twitch",
        "platform_handle": "jasontheween",
        "active": "true",
        "activation_note": "Promoted after user confirmed the campaign is visible on the current Clipping.net front page.",
    },
    "full-squad-gaming": {
        "name": "Full Squad Gaming",
        "campaign_url": "https://clipping.net/dashboard/campaigns/full-squad-gaming-x-clipping",
        "source_strategy": "Long-run gaming backup with low minimum views, but no single verified streamer/VOD source route yet.",
        "requirements_url": "",
        "requirements_text": "Requirements: None. Captured as a long-run gaming campaign with YouTube/Instagram/TikTok/X support.",
        "active": "false",
        "excluded_reason": "Backup only until a daily source route is proven; the Twitch channel did not expose clip supply.",
    },
}
IGNORED_STUDY_PROFILES = {
    "demo-safe",
    "ishouldclip-inspired-a",
    "ishouldclip-inspired-b",
    "selected-feeder-a",
    "evidence_review_v1",
    "tiktok_demo_bold_caption",
}
REQUIRED_KIT_FILES = (
    "review.mp4",
    "caption.txt",
    "transcript.txt",
    "checklist.md",
    "source.md",
    "risk.md",
    "ffprobe.json",
    "thumbnail.jpg",
    "contact_sheet.jpg",
    "style_critique.md",
    "render_text_manifest.json",
    "editorial_review.json",
)
IRRELEVANT_REVIEW_TOKENS = (
    "local-demo",
    "demo_only",
    "not_campaign_verified",
    "hermes-instagram",
    "mo_ferocious",
    "frigidgoodauberginetoospicy",
    "clip_5104c87b569d",
    "clip-5104c87b569d",
    "selected feeder review - wild",
    "selected feeder review",
    "feeder proof",
    "feeder-proof",
    "evidence review",
    "selected-feeder-a",
    "wild - evidence review",
    "demo review kit",
    "tiktok_demo_bold_caption",
    "rendered_demo",
)
PRODUCTION_PROOF_BLOCKER_TOKENS = (
    "placeholder transcript",
    "selected-feeder-placeholder",
    "selected feeder review",
    "selected feeder final proof",
    "feeder proof",
    "demo review",
    "demo-only",
    "local demo",
    "demo media",
    "evidence review",
    "style study",
    "review-safe layout",
    "human-review gate",
    "human review gate",
    "not_campaign_verified",
)
RENDERED_TEXT_BLOCKER_TOKENS = (
    "selected feeder",
    "feeder proof",
    "evidence review",
    "review kit",
    "human review",
    "manual review",
    "local demo",
    "demo only",
    "proof",
)
WEAK_RENDERED_HOOKS = {
    "dd",
    "lmao",
    "lmfao",
    "sus",
    "cpr",
    "o7 l bmw",
}
EDITORIAL_MIN_VIEWS_BY_CAMPAIGN = {
    "yourrage": 1_500,
    "plaqueboymax": 1_500,
    "jasontheween": 2_000,
}
EDITORIAL_DEFAULT_MIN_VIEWS = 1_500
EDITORIAL_MAX_DURATION_SECONDS = 52.0
EDITORIAL_WEAK_TITLE_TOKENS = {
    "",
    "-",
    ".",
    "a",
    "gff",
    "i clipepd",
    "clip",
    "dd",
    "lmao",
    "lmfao",
    "lol",
    "w",
    "z",
}
EDITORIAL_FORBIDDEN_COMPOSITIONS = {
    "streamer_split_facecam_top",
}
LACY_CAMPAIGN_FIT_FLAG = "campaign_fit_lacy_arrested_or_mia"
LACY_ARREST_OR_MIA_TERMS = (
    "arrest",
    "arrested",
    "cops",
    "cop ",
    "police",
    "pulled over",
    "searched",
    "search the car",
    "search his car",
    "handcuff",
    "handcuffs",
    "detained",
    "warrant",
    "missing in action",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def app_support_dir() -> Path:
    configured = os.environ.get("CLIPPING_OPS_HOME")
    if configured:
        root = Path(configured).expanduser()
    else:
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    (root / "render_kits").mkdir(parents=True, exist_ok=True)
    (root / "demo_render_kits").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "watermarks").mkdir(parents=True, exist_ok=True)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    return root


def database_path() -> Path:
    return app_support_dir() / "clipping_ops.sqlite3"


def render_root() -> Path:
    root = app_support_dir() / "render_kits"
    root.mkdir(parents=True, exist_ok=True)
    return root


def demo_render_root() -> Path:
    root = app_support_dir() / "demo_render_kits"
    root.mkdir(parents=True, exist_ok=True)
    return root


def source_media_root() -> Path:
    root = app_support_dir() / "source_media"
    root.mkdir(parents=True, exist_ok=True)
    return root


def campaign_watermark_root() -> Path:
    root = app_support_dir() / "assets" / "watermarks"
    root.mkdir(parents=True, exist_ok=True)
    return root


def campaign_watermark_candidate_paths(slug: Any) -> List[Path]:
    normalized = normalize_campaign_slug(slug)
    if not normalized:
        return []
    root = campaign_watermark_root()
    return [root / f"{normalized}{ext}" for ext in (".png", ".jpg", ".jpeg", ".webp")]


def campaign_watermark_asset_path(slug: Any) -> str:
    for path in campaign_watermark_candidate_paths(slug):
        if path.exists() and path.is_file():
            return str(path)
    return ""


def campaign_watermark_required(slug: Any) -> bool:
    normalized = normalize_campaign_slug(slug)
    if not normalized:
        return False
    project = CAMPAIGN_PROJECTS[normalized]
    return normalized in WATERMARK_REQUIRED_CAMPAIGNS or project.get("watermark_required", "false") == "true"


def campaign_watermark_ready(slug: Any) -> bool:
    if not campaign_watermark_required(slug):
        return True
    return bool(campaign_watermark_asset_path(slug))


def campaign_watermark_blocker(slug: Any) -> str:
    normalized = normalize_campaign_slug(slug)
    if not normalized or not campaign_watermark_required(normalized) or campaign_watermark_ready(normalized):
        return ""
    project = CAMPAIGN_PROJECTS[normalized]
    candidates = ", ".join(path.name for path in campaign_watermark_candidate_paths(normalized))
    return (
        f"{project['name']} requires its campaign watermark before review kits can be rendered. "
        f"Install one of: {candidates}. Brief asset URL: {project.get('watermark_url', '')}"
    )


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    for key, value in list(item.items()):
        if key.endswith("_json") and isinstance(value, str):
            try:
                item[key[:-5]] = json.loads(value)
            except json.JSONDecodeError:
                item[key[:-5]] = value
    return item


def _risk_flags(item: Dict[str, Any]) -> List[str]:
    raw = item.get("risk_flags")
    if isinstance(raw, list):
        return [str(flag) for flag in raw]
    raw_json = str(item.get("risk_flags_json", "[]"))
    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError:
        return []
    return [str(flag) for flag in parsed] if isinstance(parsed, list) else []


def _json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _checklist_box_checked(text: str, label: str) -> bool:
    return f"[x] {label}".lower() in text.lower()


def contains_irrelevant_review_token(*values: Any) -> bool:
    text = " ".join(str(value or "") for value in values).lower()
    return any(token in text for token in IRRELEVANT_REVIEW_TOKENS)


def is_relevant_streamer_clip(item: Dict[str, Any]) -> bool:
    platform = str(item.get("source_platform", "")).lower()
    provenance = str(item.get("provenance", "")).lower()
    flags = _risk_flags(item)
    has_selected_flag = any(flag in flags for flag in SELECTED_FEEDER_FLAGS)
    if platform not in {"twitch", "kick"} or not has_selected_flag:
        return False
    if provenance == "local-demo":
        return False
    return not contains_irrelevant_review_token(
        item.get("id"),
        item.get("title"),
        item.get("source_url"),
        item.get("local_media_path"),
        provenance,
        " ".join(flags),
    )


def normalize_campaign_slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text if text in CAMPAIGN_PROJECTS else ""


def is_active_campaign_project(slug: Any) -> bool:
    normalized = normalize_campaign_slug(slug)
    return bool(normalized) and CAMPAIGN_PROJECTS[normalized].get("active", "true") == "true"


def active_campaign_project_slugs() -> List[str]:
    return [slug for slug, project in CAMPAIGN_PROJECTS.items() if project.get("active", "true") == "true"]


def excluded_campaign_projects() -> List[Dict[str, str]]:
    return [
        {
            "slug": slug,
            "name": project["name"],
            "campaign_url": project["campaign_url"],
            "reason": project.get("excluded_reason", "Campaign is excluded from active review batch."),
        }
        for slug, project in CAMPAIGN_PROJECTS.items()
        if project.get("active", "true") != "true"
    ]


def campaign_slug_for_clip(item: Dict[str, Any]) -> str:
    direct = normalize_campaign_slug(item.get("campaign_slug"))
    if direct:
        return direct
    for flag in _risk_flags(item):
        text = str(flag).lower()
        if text.startswith("campaign_project_"):
            slug = normalize_campaign_slug(text.removeprefix("campaign_project_"))
            if slug:
                return slug
    source_url = str(item.get("source_url", "")).lower()
    for slug in CAMPAIGN_PROJECTS:
        if slug in source_url:
            return slug
    return ""


def is_campaign_project_clip(item: Dict[str, Any]) -> bool:
    slug = campaign_slug_for_clip(item)
    if not slug:
        return False
    if not is_active_campaign_project(slug):
        return False
    flags = _risk_flags(item)
    if any(flag.startswith("selected_feeder_") for flag in flags):
        if not clip_within_recent_campaign_window(item, CAMPAIGN_RECENT_CLIP_DAYS):
            return False
    if str(item.get("provenance", "")).strip().lower() == "local-demo":
        return False
    return not contains_irrelevant_review_token(
        item.get("id"),
        item.get("title"),
        item.get("source_url"),
        item.get("local_media_path"),
        item.get("provenance"),
        " ".join(_risk_flags(item)),
    )


def clip_within_recent_campaign_window(item: Dict[str, Any], days: int = CAMPAIGN_RECENT_CLIP_DAYS) -> bool:
    raw = str(item.get("clip_created_at", "") or "").strip()
    if not raw:
        return False
    try:
        created = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
    return 0 <= age_seconds <= max(1, days) * 86400


def rows(sql: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
    with connect() as conn:
        return [row_to_dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]


def one(sql: str, params: Iterable[Any] = ()) -> Optional[Dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
        return row_to_dict(row) if row else None


def execute(sql: str, params: Iterable[Any] = ()) -> None:
    with connect() as conn:
        conn.execute(sql, tuple(params))


def log_audit(actor: str, action: str, target_type: str, target_id: str, result: str, source_context: str = "") -> None:
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO audit_events
              (id, actor, action, target_type, target_id, result, timestamp, source_context)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (new_id("audit"), actor, action, target_type, target_id, result, utc_now(), source_context),
        )


SCHEMA = """
CREATE TABLE IF NOT EXISTS campaign_gate_runs (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  visible_campaign_count INTEGER NOT NULL DEFAULT 0,
  selected_feeder_count INTEGER NOT NULL DEFAULT 0,
  blocker TEXT NOT NULL DEFAULT '',
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS campaign_records (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  status TEXT NOT NULL,
  visibility TEXT NOT NULL,
  platforms TEXT NOT NULL DEFAULT '',
  min_views TEXT NOT NULL DEFAULT '',
  payout_type TEXT NOT NULL DEFAULT '',
  budget_state TEXT NOT NULL DEFAULT '',
  qualification_status TEXT NOT NULL DEFAULT 'blocked',
  selected_feeder INTEGER NOT NULL DEFAULT 0,
  risk_flags_json TEXT NOT NULL DEFAULT '[]',
  requirements_url TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_evidence (
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL DEFAULT '',
  evidence_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  source_url TEXT NOT NULL DEFAULT '',
  screenshot_path TEXT NOT NULL DEFAULT '',
  extracted_text TEXT NOT NULL DEFAULT '',
  captured_by TEXT NOT NULL DEFAULT 'operator',
  confidence REAL NOT NULL DEFAULT 0,
  notes TEXT NOT NULL DEFAULT '',
  captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creator_targets (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL,
  active_status TEXT NOT NULL,
  sweep_schedule TEXT NOT NULL DEFAULT '',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_routes (
  id TEXT PRIMARY KEY,
  platform TEXT NOT NULL,
  creator_handle TEXT NOT NULL,
  source_url TEXT NOT NULL DEFAULT '',
  route_type TEXT NOT NULL,
  auth_state TEXT NOT NULL DEFAULT '',
  availability_status TEXT NOT NULL DEFAULT 'unchecked',
  latest_check_id TEXT NOT NULL DEFAULT '',
  risk_flags_json TEXT NOT NULL DEFAULT '[]',
  notes TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_candidates (
  id TEXT PRIMARY KEY,
  campaign_slug TEXT NOT NULL DEFAULT '',
  source_platform TEXT NOT NULL,
  source_url TEXT NOT NULL,
  creator_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  duration REAL NOT NULL DEFAULT 0,
  view_count INTEGER NOT NULL DEFAULT 0,
  clip_created_at TEXT NOT NULL DEFAULT '',
  clip_start_seconds REAL NOT NULL DEFAULT 0,
  clip_end_seconds REAL NOT NULL DEFAULT 0,
  media_url TEXT NOT NULL DEFAULT '',
  local_media_path TEXT NOT NULL DEFAULT '',
  provenance TEXT NOT NULL,
  risk_flags_json TEXT NOT NULL DEFAULT '[]',
  discovered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS platform_api_checks (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  endpoint TEXT NOT NULL,
  status TEXT NOT NULL,
  http_status INTEGER NOT NULL DEFAULT 0,
  request_summary TEXT NOT NULL DEFAULT '',
  response_excerpt TEXT NOT NULL DEFAULT '',
  rate_limit_remaining TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY,
  clip_candidate_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  language TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0,
  full_text TEXT NOT NULL,
  segments_json TEXT NOT NULL DEFAULT '[]',
  word_timings_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS viral_scores (
  id TEXT PRIMARY KEY,
  clip_candidate_id TEXT NOT NULL,
  model_version TEXT NOT NULL,
  total_score INTEGER NOT NULL,
  hook_score INTEGER NOT NULL,
  punchline_score INTEGER NOT NULL,
  fit_score INTEGER NOT NULL,
  recency_score INTEGER NOT NULL,
  saturation_risk TEXT NOT NULL,
  score_reason TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS clip_clusters (
  id TEXT PRIMARY KEY,
  creator_id TEXT NOT NULL DEFAULT '',
  stream_session_id TEXT NOT NULL DEFAULT '',
  related_clip_ids_json TEXT NOT NULL DEFAULT '[]',
  combine_reason TEXT NOT NULL,
  recommended_order_json TEXT NOT NULL DEFAULT '[]',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS render_nominations (
  id TEXT PRIMARY KEY,
  campaign_slug TEXT NOT NULL DEFAULT '',
  clip_candidate_ids_json TEXT NOT NULL,
  nomination_type TEXT NOT NULL,
  score_reason TEXT NOT NULL,
  edit_plan_json TEXT NOT NULL,
  target_style TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS render_kits (
  id TEXT PRIMARY KEY,
  nomination_id TEXT NOT NULL,
  campaign_slug TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  review_video_path TEXT NOT NULL,
  caption_path TEXT NOT NULL,
  transcript_path TEXT NOT NULL,
  checklist_path TEXT NOT NULL,
  source_path TEXT NOT NULL,
  risk_path TEXT NOT NULL,
  review_status TEXT NOT NULL,
  approved_by TEXT NOT NULL DEFAULT '',
  approved_at TEXT NOT NULL DEFAULT '',
  rejection_notes TEXT NOT NULL DEFAULT '',
  is_demo INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  intent TEXT NOT NULL DEFAULT '',
  campaign_slug TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL DEFAULT '{}',
  requested_by TEXT NOT NULL DEFAULT 'system',
  dedupe_key TEXT NOT NULL DEFAULT '',
  hermes_profile TEXT NOT NULL DEFAULT 'default',
  claimed_by TEXT NOT NULL DEFAULT '',
  claim_token TEXT NOT NULL DEFAULT '',
  heartbeat_at TEXT NOT NULL DEFAULT '',
  result_json TEXT NOT NULL DEFAULT '{}',
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  progress INTEGER NOT NULL DEFAULT 0,
  logs TEXT NOT NULL DEFAULT '',
  output_path TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  actor TEXT NOT NULL,
  action TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  result TEXT NOT NULL,
  timestamp TEXT NOT NULL,
  source_context TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        clip_columns = {row["name"] for row in conn.execute("PRAGMA table_info(clip_candidates)").fetchall()}
        if "clip_created_at" not in clip_columns:
            conn.execute("ALTER TABLE clip_candidates ADD COLUMN clip_created_at TEXT NOT NULL DEFAULT ''")
        if "campaign_slug" not in clip_columns:
            conn.execute("ALTER TABLE clip_candidates ADD COLUMN campaign_slug TEXT NOT NULL DEFAULT ''")
        if "clip_start_seconds" not in clip_columns:
            conn.execute("ALTER TABLE clip_candidates ADD COLUMN clip_start_seconds REAL NOT NULL DEFAULT 0")
        if "clip_end_seconds" not in clip_columns:
            conn.execute("ALTER TABLE clip_candidates ADD COLUMN clip_end_seconds REAL NOT NULL DEFAULT 0")
        nomination_columns = {row["name"] for row in conn.execute("PRAGMA table_info(render_nominations)").fetchall()}
        if "campaign_slug" not in nomination_columns:
            conn.execute("ALTER TABLE render_nominations ADD COLUMN campaign_slug TEXT NOT NULL DEFAULT ''")
        kit_columns = {row["name"] for row in conn.execute("PRAGMA table_info(render_kits)").fetchall()}
        if "campaign_slug" not in kit_columns:
            conn.execute("ALTER TABLE render_kits ADD COLUMN campaign_slug TEXT NOT NULL DEFAULT ''")
        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(job_runs)").fetchall()}
        job_defaults = {
            "intent": "TEXT NOT NULL DEFAULT ''",
            "campaign_slug": "TEXT NOT NULL DEFAULT ''",
            "payload_json": "TEXT NOT NULL DEFAULT '{}'",
            "requested_by": "TEXT NOT NULL DEFAULT 'system'",
            "dedupe_key": "TEXT NOT NULL DEFAULT ''",
            "hermes_profile": f"TEXT NOT NULL DEFAULT '{DEFAULT_HERMES_PROFILE}'",
            "claimed_by": "TEXT NOT NULL DEFAULT ''",
            "claim_token": "TEXT NOT NULL DEFAULT ''",
            "heartbeat_at": "TEXT NOT NULL DEFAULT ''",
            "result_json": "TEXT NOT NULL DEFAULT '{}'",
            "cancel_requested": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in job_defaults.items():
            if column not in job_columns:
                conn.execute(f"ALTER TABLE job_runs ADD COLUMN {column} {definition}")
        count = conn.execute("SELECT COUNT(*) AS count FROM campaign_gate_runs").fetchone()["count"]
        if count == 0:
            run_id = new_id("gate")
            now = utc_now()
            conn.execute(
                """
                INSERT INTO campaign_gate_runs
                  (id, status, started_at, finished_at, blocker, notes)
                VALUES (?, 'blocked', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    now,
                    now,
                    "Real campaign gate has not run in a signed-in Clipping.net browser session.",
                    "Demo rendering is allowed, but real campaign-specific render tests stay blocked until campaign rules and source routes are verified.",
                ),
            )
        audit_count = conn.execute("SELECT COUNT(*) AS count FROM audit_events").fetchone()["count"]
        if audit_count == 0:
            conn.execute(
                """
                INSERT INTO audit_events
                  (id, actor, action, target_type, target_id, result, timestamp, source_context)
                VALUES (?, 'system', 'initialize', 'database', 'local', 'created local source of truth', ?, 'startup')
                """,
                (new_id("audit"), utc_now()),
            )


def upsert_clip(path: Path, title: str, duration: float, provenance: str = "local-demo") -> str:
    existing = one("SELECT id FROM clip_candidates WHERE local_media_path = ?", (str(path),))
    if existing:
        return str(existing["id"])
    clip_id = new_id("clip")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO clip_candidates
              (id, campaign_slug, source_platform, source_url, title, duration, media_url, local_media_path, provenance, risk_flags_json, discovered_at)
            VALUES (?, '', 'local', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clip_id,
                path.as_uri(),
                title,
                duration,
                path.as_uri(),
                str(path),
                provenance,
                json.dumps(["demo_only", "not_campaign_verified"]),
                utc_now(),
            ),
        )
    return clip_id


def upsert_clip_candidate(payload: Dict[str, Any]) -> str:
    source_url = str(payload.get("source_url", "")).strip()
    title = str(payload.get("title", "")).strip() or source_url or "Untitled clip candidate"
    requested_id = str(payload.get("id", "")).strip()
    existing = one("SELECT * FROM clip_candidates WHERE id = ?", (requested_id,)) if requested_id else None
    if existing is None and source_url:
        existing = one("SELECT * FROM clip_candidates WHERE source_url = ?", (source_url,))
    clip_id = str(existing["id"]) if existing else (requested_id or new_id("clip"))
    incoming_risk_flags = payload.get("risk_flags", [])
    if not isinstance(incoming_risk_flags, list):
        incoming_risk_flags = [str(incoming_risk_flags)]
    risk_flags: List[str] = []
    if existing:
        risk_flags.extend(_risk_flags(existing))
    for flag in incoming_risk_flags:
        text = str(flag)
        if text not in risk_flags:
            risk_flags.append(text)
    existing_media_path = str(existing.get("local_media_path", "")).strip() if existing else ""
    incoming_media_path = str(payload.get("local_media_path", "")).strip()
    local_media_path = incoming_media_path or existing_media_path
    existing_clip_created_at = str(existing.get("clip_created_at", "")).strip() if existing else ""
    clip_created_at = str(payload.get("clip_created_at", "")).strip() or existing_clip_created_at
    campaign_slug = normalize_campaign_slug(payload.get("campaign_slug")) or (campaign_slug_for_clip(existing) if existing else "")
    if campaign_slug:
        project_flag = f"campaign_project_{campaign_slug}"
        if project_flag not in risk_flags:
            risk_flags.append(project_flag)
    existing_start = float(existing.get("clip_start_seconds", 0) or 0) if existing else 0.0
    existing_end = float(existing.get("clip_end_seconds", 0) or 0) if existing else 0.0
    clip_start = float(payload.get("clip_start_seconds", existing_start) or 0)
    clip_end = float(payload.get("clip_end_seconds", existing_end) or 0)
    if local_media_path and Path(local_media_path).exists():
        risk_flags = [flag for flag in risk_flags if flag != "metadata_only_no_download"]
        for flag in ["local_media_downloaded", "source_media_verified_local"]:
            if flag not in risk_flags:
                risk_flags.append(flag)
    else:
        risk_flags = [flag for flag in risk_flags if flag not in LOCAL_MEDIA_READY_FLAGS]
    params = (
        clip_id,
        campaign_slug,
        str(payload.get("source_platform", "")).strip().lower() or "unknown",
        source_url,
        str(payload.get("creator_id", "")),
        title,
        float(payload.get("duration", 0) or 0),
        int(payload.get("view_count", 0) or 0),
        clip_created_at,
        clip_start,
        clip_end,
        str(payload.get("media_url", "")),
        local_media_path,
        str(payload.get("provenance", "official_api_metadata")),
        json.dumps(risk_flags),
        utc_now(),
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO clip_candidates
              (id, campaign_slug, source_platform, source_url, creator_id, title, duration, view_count, clip_created_at, clip_start_seconds, clip_end_seconds, media_url, local_media_path, provenance, risk_flags_json, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              campaign_slug=excluded.campaign_slug,
              source_platform=excluded.source_platform,
              source_url=excluded.source_url,
              creator_id=excluded.creator_id,
              title=excluded.title,
              duration=excluded.duration,
              view_count=excluded.view_count,
              clip_created_at=excluded.clip_created_at,
              clip_start_seconds=excluded.clip_start_seconds,
              clip_end_seconds=excluded.clip_end_seconds,
              media_url=excluded.media_url,
              local_media_path=excluded.local_media_path,
              provenance=excluded.provenance,
              risk_flags_json=excluded.risk_flags_json,
              discovered_at=excluded.discovered_at
            """,
            params,
        )
    return clip_id


def update_clip_media(clip_id: str, local_media_path: Path, provenance: str, extra_risk_flags: List[str] | None = None) -> None:
    clip = one("SELECT risk_flags_json FROM clip_candidates WHERE id = ?", (clip_id,))
    risk_flags: List[str] = []
    if clip:
        try:
            parsed = json.loads(str(clip.get("risk_flags_json", "[]")))
            if isinstance(parsed, list):
                risk_flags = [str(item) for item in parsed]
        except json.JSONDecodeError:
            risk_flags = []
    risk_flags = [flag for flag in risk_flags if flag != "metadata_only_no_download"]
    for flag in extra_risk_flags or []:
        if str(flag) == "metadata_only_no_download":
            continue
        if flag not in risk_flags:
            risk_flags.append(flag)
    if local_media_path.exists():
        risk_flags = [flag for flag in risk_flags if flag != "metadata_only_no_download"]
        for flag in ("local_media_downloaded", "source_media_verified_local"):
            if flag not in risk_flags:
                risk_flags.append(flag)
    else:
        risk_flags = [flag for flag in risk_flags if flag not in LOCAL_MEDIA_READY_FLAGS]
    execute(
        """
        UPDATE clip_candidates
        SET local_media_path=?, media_url=?, provenance=?, risk_flags_json=?
        WHERE id=?
        """,
        (str(local_media_path), local_media_path.as_uri(), provenance, json.dumps(risk_flags), clip_id),
    )


def create_transcript(clip_id: str, text: str, provider: str = "demo-placeholder") -> str:
    existing = one("SELECT id FROM transcripts WHERE clip_candidate_id = ? ORDER BY created_at DESC LIMIT 1", (clip_id,))
    if existing:
        return str(existing["id"])
    transcript_id = new_id("transcript")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO transcripts
              (id, clip_candidate_id, provider, language, confidence, full_text, segments_json, status, created_at)
            VALUES (?, ?, ?, 'en', 0.4, ?, ?, 'demo', ?)
            """,
            (
                transcript_id,
                clip_id,
                provider,
                text,
                json.dumps([
                    {"start": 0.0, "end": 3.5, "text": "Demo local video selected for review-kit pipeline proof."},
                    {"start": 3.5, "end": 8.0, "text": "Real campaign kits require verified campaign rules and source provenance."},
                ]),
                utc_now(),
            ),
        )
    return transcript_id


def create_score(clip_id: str, reason: str) -> str:
    existing = one("SELECT id FROM viral_scores WHERE clip_candidate_id = ? ORDER BY created_at DESC LIMIT 1", (clip_id,))
    if existing:
        return str(existing["id"])
    score_id = new_id("score")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO viral_scores
              (id, clip_candidate_id, model_version, total_score, hook_score, punchline_score, fit_score, recency_score, saturation_risk, score_reason, confidence, created_at)
            VALUES (?, ?, 'local-v0-demo', 71, 7, 6, 8, 7, 'unknown_demo', ?, 0.55, ?)
            """,
            (score_id, clip_id, reason, utc_now()),
        )
    return score_id


def create_nomination(
    clip_id: str,
    title: str,
    reason: str,
    target_style: str = "tiktok_demo_bold_caption",
    status: str = "rendered_demo",
    campaign_slug: str = "",
) -> str:
    slug = normalize_campaign_slug(campaign_slug)
    if not slug:
        clip = one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,))
        slug = campaign_slug_for_clip(clip or {})
    existing = one(
        """
        SELECT id FROM render_nominations
        WHERE clip_candidate_ids_json = ?
          AND target_style = ?
          AND campaign_slug = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (json.dumps([clip_id]), target_style, slug),
    )
    nomination_id = new_id("nom")
    is_demo_nomination = target_style == "tiktok_demo_bold_caption" or status == "rendered_demo"
    is_campaign_nomination = target_style == CAMPAIGN_SHORT_PROFILE or bool(slug)
    edit_plan = {
        "opening_hook": "LOCAL DEMO KIT" if is_demo_nomination else "Clean campaign moment with source evidence",
        "clip_order": [clip_id],
        "caption_beats": [
            {"start": 0.0, "end": 2.6, "text": "LOCAL DEMO KIT" if is_demo_nomination else "WAIT FOR IT"},
            {"start": 2.6, "end": 6.0, "text": "REVIEW FIRST" if is_demo_nomination else "THEN IT TURNS"},
        ],
        "crop_focus": "preserve vertical source",
        "music_policy": "preserve source audio unless blocked",
        "risk_notes": (
            "Demo-only media. Not a campaign submission."
            if is_demo_nomination
            else "Campaign source with stored rules and provenance. Publishing approval remains separate."
        ),
        "why_this_can_hit": reason,
        "rejected_near_misses": "Off-target/demo clips are excluded from the visible cockpit surface.",
    }
    if is_campaign_nomination:
        edit_plan["campaign_slug"] = slug
    if existing:
        existing_id = str(existing["id"])
        execute(
            """
            UPDATE render_nominations
            SET campaign_slug=?, score_reason=?, edit_plan_json=?, target_style=?, status=?
            WHERE id=?
            """,
            (slug, reason, json.dumps(edit_plan), target_style, status, existing_id),
        )
        return existing_id
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO render_nominations
              (id, campaign_slug, clip_candidate_ids_json, nomination_type, score_reason, edit_plan_json, target_style, status, created_at)
            VALUES (?, ?, ?, 'single', ?, ?, ?, ?, ?)
            """,
            (nomination_id, slug, json.dumps([clip_id]), reason, json.dumps(edit_plan), target_style, status, utc_now()),
        )
    return nomination_id


def create_render_kit(
    nomination_id: str,
    title: str,
    review_video: Path,
    caption: Path,
    transcript: Path,
    checklist: Path,
    source: Path,
    risk: Path,
    is_demo: bool,
    campaign_slug: str = "",
) -> str:
    existing = one("SELECT id FROM render_kits WHERE review_video_path = ?", (str(review_video),))
    if existing:
        return str(existing["id"])
    kit_id = new_id("kit")
    slug = normalize_campaign_slug(campaign_slug)
    if not slug:
        nomination = one("SELECT * FROM render_nominations WHERE id = ?", (nomination_id,))
        slug = normalize_campaign_slug((nomination or {}).get("campaign_slug"))
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO render_kits
              (id, nomination_id, campaign_slug, title, review_video_path, caption_path, transcript_path, checklist_path, source_path, risk_path, review_status, is_demo, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review', ?, ?)
            """,
            (
                kit_id,
                nomination_id,
                slug,
                title,
                str(review_video),
                str(caption),
                str(transcript),
                str(checklist),
                str(source),
                str(risk),
                1 if is_demo else 0,
                utc_now(),
            ),
        )
    return kit_id


def hermes_profile() -> str:
    stored = one("SELECT value FROM system_settings WHERE key='hermes_profile'")
    profile = str((stored or {}).get("value", "")).strip()
    return profile or DEFAULT_HERMES_PROFILE


def set_hermes_profile(profile: str) -> str:
    cleaned = str(profile or "").strip() or DEFAULT_HERMES_PROFILE
    execute(
        """
        INSERT INTO system_settings (key, value, updated_at)
        VALUES ('hermes_profile', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (cleaned, utc_now()),
    )
    log_audit("operator", "set_hermes_profile", "system_settings", "hermes_profile", "stored", cleaned)
    return cleaned


def _stable_payload(payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not payload:
        return {}
    stable = dict(payload)
    stable.pop("force_revision", None)
    stable.pop("force_new", None)
    return stable


def _json_dumps_stable(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def job_dedupe_key(intent: str, campaign_slug: str = "", payload: Optional[Dict[str, Any]] = None) -> str:
    normalized = normalize_campaign_slug(campaign_slug)
    stable = _json_dumps_stable(_stable_payload(payload))
    digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]
    return f"{intent}:{normalized}:{digest}"


def _job_with_json(item: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(item)
    for source, target in (("payload_json", "payload"), ("result_json", "result")):
        try:
            enriched[target] = json.loads(str(enriched.get(source, "{}") or "{}"))
        except json.JSONDecodeError:
            enriched[target] = {}
    enriched["cancel_requested"] = bool(int(enriched.get("cancel_requested", 0) or 0))
    return enriched


def _job_name_for_intent(intent: str, campaign_slug: str = "") -> str:
    base = HERMES_JOB_INTENTS.get(intent, {}).get("name", intent.replace("_", " ").title())
    if campaign_slug:
        project = CAMPAIGN_PROJECTS.get(normalize_campaign_slug(campaign_slug))
        if project:
            return f"{project['name']}: {base}"
    return str(base)


def create_job(
    name: str,
    kind: str,
    status: str,
    stage: str,
    progress: int,
    logs: str = "",
    output_path: str = "",
    error: str = "",
    *,
    intent: str = "",
    campaign_slug: str = "",
    payload: Optional[Dict[str, Any]] = None,
    requested_by: str = "system",
    dedupe_key: str = "",
    hermes_profile_name: str = "",
    claimed_by: str = "",
    result: Optional[Dict[str, Any]] = None,
) -> str:
    job_id = new_id("job")
    finished = utc_now() if status in {"succeeded", "failed", "blocked"} else ""
    payload_json = _json_dumps_stable(payload or {})
    result_json = _json_dumps_stable(result or {})
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO job_runs
              (id, name, kind, intent, campaign_slug, payload_json, requested_by, dedupe_key, hermes_profile,
               claimed_by, result_json, status, stage, progress, logs, output_path, error, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                name,
                kind,
                intent,
                normalize_campaign_slug(campaign_slug),
                payload_json,
                requested_by,
                dedupe_key,
                hermes_profile_name or hermes_profile(),
                claimed_by,
                result_json,
                status,
                stage,
                progress,
                logs,
                output_path,
                error,
                utc_now(),
                finished,
            ),
        )
    return job_id


def create_job_intent(
    intent: str,
    payload: Optional[Dict[str, Any]] = None,
    *,
    campaign_slug: str = "",
    requested_by: str = "gui",
    hermes_profile_name: str = "",
    dedupe_key: str = "",
    force_new: bool = False,
) -> Dict[str, Any]:
    if intent not in HERMES_JOB_INTENTS:
        raise ValueError(f"unsupported Hermes job intent: {intent}")
    normalized_slug = normalize_campaign_slug(campaign_slug or (payload or {}).get("campaign_slug", ""))
    job_payload = dict(payload or {})
    if normalized_slug:
        job_payload["campaign_slug"] = normalized_slug
    key = dedupe_key or job_dedupe_key(intent, normalized_slug, job_payload)
    force = force_new or bool(job_payload.get("force_revision") or job_payload.get("force_new"))
    if not force:
        dedupe_statuses = "'queued', 'claimed', 'running', 'succeeded'" if intent == "build_campaign_reviews" else "'queued', 'claimed', 'running'"
        existing = one(
            f"""
            SELECT *
            FROM job_runs
            WHERE dedupe_key = ?
              AND intent = ?
              AND status IN ({dedupe_statuses})
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (key, intent),
        )
        if existing:
            found = _job_with_json(existing)
            found["deduped"] = True
            return found
    meta = HERMES_JOB_INTENTS[intent]
    job_id = create_job(
        _job_name_for_intent(intent, normalized_slug),
        str(meta["kind"]),
        "queued",
        str(meta["stage"]),
        0,
        logs="Queued for Hermes orchestration.",
        intent=intent,
        campaign_slug=normalized_slug,
        payload=job_payload,
        requested_by=requested_by,
        dedupe_key=key,
        hermes_profile_name=hermes_profile_name or hermes_profile(),
    )
    log_audit(requested_by, "queue_hermes_job", "job_run", job_id, intent, key)
    created = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    return _job_with_json(created or {})


def visible_jobs(limit: int = 100, status: str = "") -> List[Dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if status:
        where = "WHERE status = ?"
        params = (status,)
    return [_job_with_json(item) for item in rows(f"SELECT * FROM job_runs {where} ORDER BY started_at DESC LIMIT ?", (*params, limit))]


def queued_jobs(limit: int = 25) -> List[Dict[str, Any]]:
    return [
        _job_with_json(item)
        for item in rows(
            """
            SELECT *
            FROM job_runs
            WHERE status = 'queued'
              AND intent != ''
            ORDER BY started_at ASC
            LIMIT ?
            """,
            (limit,),
        )
    ]


def claim_job(job_id: str, worker: str, profile: str = "") -> Dict[str, Any]:
    item = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    if not item:
        raise ValueError("missing_job")
    if str(item.get("intent", "")) == "":
        raise ValueError("job_has_no_hermes_intent")
    if str(item.get("status", "")) not in {"queued", "claimed", "running"}:
        raise ValueError(f"job_not_claimable:{item.get('status', '')}")
    token = new_id("claim")
    now = utc_now()
    execute(
        """
        UPDATE job_runs
        SET status='claimed', stage='claimed-by-hermes', progress=MAX(progress, 5),
            claimed_by=?, claim_token=?, heartbeat_at=?, hermes_profile=?
        WHERE id=?
        """,
        (worker, token, now, profile or str(item.get("hermes_profile", "")) or hermes_profile(), job_id),
    )
    log_audit(worker, "claim_hermes_job", "job_run", job_id, "claimed", profile or hermes_profile())
    claimed = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    result = _job_with_json(claimed or {})
    result["claim_token"] = token
    return result


def _require_claim(job_id: str, token: str) -> Dict[str, Any]:
    item = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    if not item:
        raise ValueError("missing_job")
    if str(item.get("claim_token", "")) != token:
        raise ValueError("invalid_claim_token")
    return item


def heartbeat_job(job_id: str, token: str, stage: str = "", progress: Optional[int] = None, logs: str = "") -> Dict[str, Any]:
    item = _require_claim(job_id, token)
    next_stage = stage or str(item.get("stage", "")) or "running"
    next_progress = int(progress if progress is not None else item.get("progress", 0) or 0)
    next_logs = logs if logs else str(item.get("logs", ""))
    execute(
        """
        UPDATE job_runs
        SET status='running', stage=?, progress=?, logs=?, heartbeat_at=?
        WHERE id=?
        """,
        (next_stage, next_progress, next_logs, utc_now(), job_id),
    )
    updated = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    return _job_with_json(updated or {})


def complete_job(job_id: str, token: str, result: Optional[Dict[str, Any]] = None, logs: str = "", output_path: str = "") -> Dict[str, Any]:
    item = _require_claim(job_id, token)
    execute(
        """
        UPDATE job_runs
        SET status='succeeded', stage='completed-by-hermes', progress=100, logs=?, output_path=?,
            result_json=?, error='', heartbeat_at=?, finished_at=?
        WHERE id=?
        """,
        (
            logs or str(item.get("logs", "")),
            output_path or str(item.get("output_path", "")),
            _json_dumps_stable(result or {}),
            utc_now(),
            utc_now(),
            job_id,
        ),
    )
    log_audit(str(item.get("claimed_by", "hermes")), "complete_hermes_job", "job_run", job_id, "succeeded", str(result or {})[:500])
    updated = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    return _job_with_json(updated or {})


def block_job(job_id: str, token: str, error: str, result: Optional[Dict[str, Any]] = None, stage: str = "blocked") -> Dict[str, Any]:
    item = _require_claim(job_id, token)
    execute(
        """
        UPDATE job_runs
        SET status='blocked', stage=?, progress=100, error=?, result_json=?, heartbeat_at=?, finished_at=?
        WHERE id=?
        """,
        (stage, error[:1200], _json_dumps_stable(result or {}), utc_now(), utc_now(), job_id),
    )
    log_audit(str(item.get("claimed_by", "hermes")), "block_hermes_job", "job_run", job_id, "blocked", error[:500])
    updated = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    return _job_with_json(updated or {})


def fail_job(job_id: str, token: str, error: str, result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    item = _require_claim(job_id, token)
    execute(
        """
        UPDATE job_runs
        SET status='failed', stage='failed-by-hermes', progress=100, error=?, result_json=?, heartbeat_at=?, finished_at=?
        WHERE id=?
        """,
        (error[:1200], _json_dumps_stable(result or {}), utc_now(), utc_now(), job_id),
    )
    log_audit(str(item.get("claimed_by", "hermes")), "fail_hermes_job", "job_run", job_id, "failed", error[:500])
    updated = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    return _job_with_json(updated or {})


def cancel_job(job_id: str, actor: str = "operator") -> Dict[str, Any]:
    item = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    if not item:
        raise ValueError("missing_job")
    if str(item.get("status", "")) in HERMES_JOB_TERMINAL_STATUSES:
        return _job_with_json(item)
    execute(
        """
        UPDATE job_runs
        SET status='cancelled', cancel_requested=1, stage='cancelled', finished_at=?, error='cancelled by operator'
        WHERE id=?
        """,
        (utc_now(), job_id),
    )
    log_audit(actor, "cancel_hermes_job", "job_run", job_id, "cancelled", "")
    updated = one("SELECT * FROM job_runs WHERE id = ?", (job_id,))
    return _job_with_json(updated or {})


def hermes_native_execution_proof() -> Dict[str, Any]:
    succeeded = one(
        """
        SELECT *
        FROM job_runs
        WHERE intent != ''
          AND status = 'succeeded'
          AND claimed_by LIKE 'hermes%'
        ORDER BY finished_at DESC, started_at DESC
        LIMIT 1
        """
    )
    active_count = one("SELECT COUNT(*) AS count FROM job_runs WHERE intent != '' AND status IN ('queued','claimed','running')") or {"count": 0}
    if succeeded:
        return {
            "ok": True,
            "status": "green",
            "detail": f"{succeeded['intent']} succeeded via {succeeded['claimed_by']} at {succeeded['finished_at'] or succeeded['started_at']}",
            "job_id": str(succeeded["id"]),
            "active_jobs": int(active_count["count"]),
        }
    any_intent = one("SELECT COUNT(*) AS count FROM job_runs WHERE intent != ''") or {"count": 0}
    return {
        "ok": False,
        "status": "yellow" if int(any_intent["count"]) else "red",
        "detail": f"{active_count['count']} queued/running Hermes intent job(s); no succeeded Hermes-claimed job yet.",
        "job_id": "",
        "active_jobs": int(active_count["count"]),
    }


def visible_clip_candidates() -> List[Dict[str, Any]]:
    return [
        item
        for item in rows("SELECT * FROM clip_candidates ORDER BY view_count DESC, discovered_at DESC")
        if is_campaign_project_clip(item)
    ]


def campaign_slug_for_nomination(nomination: Optional[Dict[str, Any]]) -> str:
    if not nomination:
        return ""
    direct = normalize_campaign_slug(nomination.get("campaign_slug"))
    if direct:
        return direct
    for clip_id in _clip_ids_for_nomination(nomination):
        clip = one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,))
        slug = campaign_slug_for_clip(clip or {})
        if slug:
            return slug
    return ""


def campaign_slug_for_kit(kit: Dict[str, Any], nomination: Optional[Dict[str, Any]] = None) -> str:
    direct = normalize_campaign_slug(kit.get("campaign_slug"))
    if direct:
        return direct
    return campaign_slug_for_nomination(nomination or one("SELECT * FROM render_nominations WHERE id = ?", (str(kit.get("nomination_id", "")),)))


def visible_render_nominations() -> List[Dict[str, Any]]:
    visible_clip_ids = {str(item["id"]) for item in visible_clip_candidates()}
    visible: List[Dict[str, Any]] = []
    for item in rows("SELECT * FROM render_nominations ORDER BY created_at DESC"):
        if not campaign_slug_for_nomination(item):
            continue
        if contains_irrelevant_review_token(
            item.get("id"),
            item.get("score_reason"),
            item.get("target_style"),
            item.get("status"),
            item.get("clip_candidate_ids_json"),
        ):
            continue
        clip_ids = item.get("clip_candidate_ids")
        if not isinstance(clip_ids, list):
            try:
                clip_ids = json.loads(str(item.get("clip_candidate_ids_json", "[]")))
            except json.JSONDecodeError:
                clip_ids = []
        if any(str(clip_id) in visible_clip_ids for clip_id in clip_ids):
            visible.append(item)
    return visible


def visible_render_kits() -> List[Dict[str, Any]]:
    visible_nomination_ids = {str(item["id"]) for item in visible_render_nominations()}
    visible: List[Dict[str, Any]] = []
    for item in rows("SELECT * FROM render_kits"):
        nomination = one("SELECT * FROM render_nominations WHERE id = ?", (str(item.get("nomination_id", "")),))
        if not campaign_slug_for_kit(item, nomination):
            continue
        if int(item.get("is_demo", 0) or 0) == 1:
            continue
        if str(item.get("nomination_id", "")) not in visible_nomination_ids:
            continue
        if contains_irrelevant_review_token(
            item.get("title"),
            item.get("review_video_path"),
            item.get("caption_path"),
            item.get("transcript_path"),
            item.get("source_path"),
            item.get("risk_path"),
        ):
            continue
        if not Path(str(item.get("review_video_path", ""))).exists():
            continue
        proof_status = production_feeder_kit_status(item).get("classification")
        if proof_status not in {"green", "yellow"}:
            continue
        visible.append(enrich_render_kit_with_clip_metadata(item))
    return sorted(visible, key=render_kit_sort_key, reverse=True)


def render_kit_sort_key(kit: Dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(kit.get("rendered_at") or ""),
        str(kit.get("created_at") or ""),
        str(kit.get("clip_created_at") or kit.get("clip_discovered_at") or ""),
    )


def rendered_at_for_video(path_value: Any) -> str:
    try:
        path = Path(str(path_value))
        if not path.exists():
            return ""
        return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
    except (OSError, ValueError):
        return ""


def enrich_render_kit_with_clip_metadata(kit: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(kit)
    enriched["rendered_at"] = rendered_at_for_video(enriched.get("review_video_path", ""))
    nomination = one("SELECT * FROM render_nominations WHERE id = ?", (str(kit.get("nomination_id", "")),))
    campaign_slug = campaign_slug_for_kit(kit, nomination)
    if campaign_slug:
        project = CAMPAIGN_PROJECTS[campaign_slug]
        enriched["campaign_slug"] = campaign_slug
        enriched["campaign_name"] = project["name"]
        enriched["campaign_url"] = project["campaign_url"]
        enriched["approval_required_for_packaging"] = True
    else:
        enriched["campaign_slug"] = ""
        enriched["campaign_name"] = ""
        enriched["campaign_url"] = ""
        enriched["approval_required_for_packaging"] = False
    clip_ids = _clip_ids_for_nomination(nomination)
    clip = one("SELECT * FROM clip_candidates WHERE id = ?", (clip_ids[0],)) if clip_ids else None
    if clip:
        enriched["clip_id"] = str(clip.get("id", ""))
        clip_campaign_slug = campaign_slug_for_clip(clip)
        if clip_campaign_slug and not campaign_slug:
            project = CAMPAIGN_PROJECTS[clip_campaign_slug]
            enriched["campaign_slug"] = clip_campaign_slug
            enriched["campaign_name"] = project["name"]
            enriched["campaign_url"] = project["campaign_url"]
            enriched["approval_required_for_packaging"] = True
        enriched["clip_source_url"] = str(clip.get("source_url", ""))
        enriched["clip_source_platform"] = str(clip.get("source_platform", ""))
        enriched["clip_created_at"] = str(clip.get("clip_created_at", ""))
        enriched["clip_discovered_at"] = str(clip.get("discovered_at", ""))
        enriched["clip_view_count"] = int(clip.get("view_count", 0) or 0)
        enriched["clip_duration"] = float(clip.get("duration", 0) or 0)
        enriched["clip_start_seconds"] = float(clip.get("clip_start_seconds", 0) or 0)
        enriched["clip_end_seconds"] = float(clip.get("clip_end_seconds", 0) or 0)
    enriched["campaign_proof_status"] = production_feeder_kit_status(kit).get("classification", "red")
    return enriched


def visible_job_runs(limit: int = 50) -> List[Dict[str, Any]]:
    hidden_names = {"demo-render"}
    visible: List[Dict[str, Any]] = []
    for item in rows("SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?", (max(limit * 3, limit),)):
        name = str(item.get("name", ""))
        output_path = str(item.get("output_path", ""))
        error = str(item.get("error", ""))
        logs = str(item.get("logs", ""))
        if name in hidden_names or contains_irrelevant_review_token(name, output_path, error, logs):
            continue
        visible.append(_job_with_json(item))
        if len(visible) >= limit:
            break
    return visible


def visible_audit_events(limit: int = 100) -> List[Dict[str, Any]]:
    visible: List[Dict[str, Any]] = []
    for item in rows("SELECT * FROM audit_events ORDER BY timestamp DESC LIMIT ?", (max(limit * 3, limit),)):
        if str(item.get("action", "")) == "render_demo_kit":
            continue
        if contains_irrelevant_review_token(
            item.get("action"),
            item.get("target_id"),
            item.get("result"),
            item.get("source_context"),
        ):
            continue
        visible.append(item)
        if len(visible) >= limit:
            break
    return visible


def visible_counts() -> Dict[str, int]:
    visible_kits = visible_render_kits()
    visible_clips = visible_clip_candidates()
    visible_nominations = visible_render_nominations()
    visible_clip_ids = {str(item["id"]) for item in visible_clips}
    transcript_count = 0
    if visible_clip_ids:
        placeholders = ",".join("?" for _ in visible_clip_ids)
        transcript_count = int(one(f"SELECT COUNT(*) AS count FROM transcripts WHERE clip_candidate_id IN ({placeholders})", visible_clip_ids)["count"])
    return {
        "clips": len(visible_clips),
        "transcripts": transcript_count,
        "nominations": len(visible_nominations),
        "review_kits": len(visible_kits),
        "approvals_needed": sum(1 for item in visible_kits if item.get("review_status") == "needs_review"),
        "blocked_jobs": len([item for item in visible_job_runs(200) if item.get("status") in {"blocked", "failed"}]),
    }


def _latest_success_transcript(clip_id: str) -> Optional[Dict[str, Any]]:
    return one(
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


def _transcript_is_word_timed(transcript: Optional[Dict[str, Any]]) -> bool:
    if not transcript:
        return False
    provider = str(transcript.get("provider", "")).lower()
    full_text = str(transcript.get("full_text", "")).strip().lower()
    if not full_text or "placeholder" in provider or "placeholder transcript" in full_text:
        return False
    word_timings = transcript.get("word_timings")
    if not isinstance(word_timings, list):
        word_timings = _json_list(transcript.get("word_timings_json", "[]"))
    return bool(word_timings) and all(
        isinstance(item, dict)
        and str(item.get("word", "")).strip()
        and "start" in item
        and "end" in item
        for item in word_timings
    )


def _clip_ids_for_nomination(nomination: Optional[Dict[str, Any]]) -> List[str]:
    if not nomination:
        return []
    raw = nomination.get("clip_candidate_ids")
    if isinstance(raw, list):
        return [str(item) for item in raw]
    return [str(item) for item in _json_list(nomination.get("clip_candidate_ids_json", "[]"))]


def _campaign_rules_for_clip(clip: Dict[str, Any], source_text: str = "") -> List[Dict[str, Any]]:
    source_url = str(clip.get("source_url", "")).lower()
    flags = [flag.lower() for flag in _risk_flags(clip)]
    candidate_slugs: List[str] = []
    campaign_slug = campaign_slug_for_clip(clip)
    if campaign_slug:
        candidate_slugs.append(campaign_slug)
    for flag in flags:
        if flag.startswith("selected_feeder_"):
            candidate_slugs.append(flag.removeprefix("selected_feeder_"))
    source_haystack = f"{source_url}\n{source_text}".lower()
    alias_map = {
        "yourragegaming": "yourrage",
        "pbm": "plaqueboymax",
        "plaque": "plaqueboymax",
        "fullsquadgaming": "full-squad-gaming",
    }
    for slug, project in CAMPAIGN_PROJECTS.items():
        handle = str(project.get("platform_handle", "")).lower()
        if slug in source_haystack or (handle and handle in source_haystack):
            candidate_slugs.append(slug)
    for token, slug in alias_map.items():
        if token in source_haystack:
            candidate_slugs.append(slug)
    normalized = []
    for slug in candidate_slugs:
        alias = alias_map.get(slug, slug)
        if alias and alias not in normalized:
            normalized.append(alias)
    if not normalized:
        return []
    placeholders = ",".join("?" for _ in normalized)
    return rows(
        f"""
        SELECT *
        FROM campaign_evidence
        WHERE evidence_type = 'campaign_rules'
          AND lower(campaign_id) IN ({placeholders})
        ORDER BY captured_at DESC
        """,
        normalized,
    )


def _is_lacy_clip(clip: Dict[str, Any]) -> bool:
    flags = [flag.lower() for flag in _risk_flags(clip)]
    return "selected_feeder_lacy" in flags or "twitch.tv/lacy" in str(clip.get("source_url", "")).lower()


def _editorial_campaign_slug_for_clip(clip: Dict[str, Any], campaign_slug: str = "") -> str:
    return normalize_campaign_slug(campaign_slug) or campaign_slug_for_clip(clip)


def editorial_min_views_for_campaign(slug: str) -> int:
    return int(EDITORIAL_MIN_VIEWS_BY_CAMPAIGN.get(normalize_campaign_slug(slug), EDITORIAL_DEFAULT_MIN_VIEWS))


def _normalized_editorial_title(title: Any) -> str:
    return re.sub(r"\s+", " ", str(title or "").strip()).lower()


def editorial_candidate_gate(clip: Dict[str, Any], campaign_slug: str = "") -> Dict[str, Any]:
    """Clip-level editorial filter before any expensive render work.

    Mechanical proof is not enough. This gate rejects valid-but-boring/random
    Twitch pulls before they can dominate the review queue.
    """
    slug = _editorial_campaign_slug_for_clip(clip, campaign_slug)
    title = _normalized_editorial_title(clip.get("title", ""))
    views = int(clip.get("view_count", 0) or 0)
    duration = float(clip.get("duration", 0) or 0)
    min_views = editorial_min_views_for_campaign(slug)
    blockers: List[str] = []
    warnings: List[str] = []
    if views < min_views:
        blockers.append(f"clip has {views} views; editorial floor for {slug or 'campaign'} is {min_views}")
    if duration <= 0:
        blockers.append("clip duration is missing")
    elif duration > EDITORIAL_MAX_DURATION_SECONDS:
        blockers.append(f"clip is {duration:.1f}s; cut must be tighter than {EDITORIAL_MAX_DURATION_SECONDS:.0f}s unless manually revised")
    if title in EDITORIAL_WEAK_TITLE_TOKENS or len(title) < 4:
        blockers.append("clip title is too weak/generic to justify automatic review")
    if title.startswith("yourrage talks about") or title.endswith("speaking on the situation"):
        warnings.append("title reads like context/news coverage; human should confirm hook strength")
    if "metadata_only_no_download" in _risk_flags(clip):
        blockers.append("clip is metadata-only; local source media must be proven before review")
    return {
        "status": "green" if not blockers else "red",
        "blockers": blockers,
        "warnings": warnings,
        "clip_id": str(clip.get("id", "")),
        "campaign_slug": slug,
        "title": str(clip.get("title", "")),
        "view_count": views,
        "duration": duration,
        "thresholds": {
            "min_views": min_views,
            "max_duration_seconds": EDITORIAL_MAX_DURATION_SECONDS,
        },
    }


def _manifest_composition_mode(kit_dir: Path) -> str:
    manifest = read_json_artifact(kit_dir / "render_text_manifest.json")
    rendered = manifest.get("rendered_text", {}) if isinstance(manifest, dict) else {}
    composition = rendered.get("composition", {}) if isinstance(rendered, dict) else {}
    if not isinstance(composition, dict):
        return ""
    return str(composition.get("mode", ""))


def editorial_review_for_rendered_kit(
    clip: Dict[str, Any],
    kit_dir: Path,
    campaign_slug: str = "",
    *,
    require_sidecar: bool = True,
) -> Dict[str, Any]:
    gate = editorial_candidate_gate(clip, campaign_slug)
    blockers = [str(item) for item in gate.get("blockers", [])]
    warnings = [str(item) for item in gate.get("warnings", [])]
    composition_mode = _manifest_composition_mode(kit_dir)
    if composition_mode in EDITORIAL_FORBIDDEN_COMPOSITIONS:
        blockers.append("unnecessary facecam-top composition; keep streamer clips in a natural source frame unless explicitly justified")
    elif composition_mode == "portrait_source_facecam_unrecoverable":
        warnings.append("source media is portrait/cropped; native stream context may be unrecoverable")
    elif not composition_mode:
        blockers.append("render composition manifest is missing")

    sidecar_path = kit_dir / "editorial_review.json"
    sidecar_payload: Dict[str, Any] = {}
    if require_sidecar:
        sidecar_payload = read_json_artifact(sidecar_path)
        if not sidecar_payload:
            blockers.append("editorial_review.json missing")
        elif str(sidecar_payload.get("status", "")).lower() != "green":
            blockers.append("editorial review sidecar is not green")
    status = "green" if not blockers else "red"
    return {
        **gate,
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "composition_mode": composition_mode,
        "sidecar_path": str(sidecar_path),
        "sidecar_status": str(sidecar_payload.get("status", "")) if sidecar_payload else "",
        "reviewed_at": utc_now(),
    }


def _lacy_campaign_fit_status(
    clip: Dict[str, Any],
    *,
    source_text: str = "",
    caption_text: str = "",
    transcript_text: str = "",
    manifest_text: str = "",
    campaign_rule_text: str = "",
) -> Dict[str, Any]:
    """Return strict campaign-brief compliance evidence for the Lacy brief."""
    flags = [flag.lower() for flag in _risk_flags(clip)]
    haystack = "\n".join(
        [
            str(clip.get("title", "")),
            str(clip.get("source_url", "")),
            source_text,
            caption_text,
            transcript_text,
            manifest_text,
        ]
    ).lower()
    has_fit_flag = LACY_CAMPAIGN_FIT_FLAG in flags
    content_term_hits = [term for term in LACY_ARREST_OR_MIA_TERMS if term in haystack]
    caption_mentions_lacy = "lacy" in (caption_text + "\n" + manifest_text).lower()
    caption_has_hashtag = "#lacy" in caption_text.lower()
    brief_text = (source_text + "\n" + campaign_rule_text).lower()
    rules_name_requirement = "caption/text overlay must mention lacy" in brief_text
    rules_theme_requirement = "being arrested or being missing in action" in brief_text
    blockers: List[str] = []
    if not rules_theme_requirement:
        blockers.append("Lacy campaign brief text was not stored beside the kit")
    if not caption_mentions_lacy:
        blockers.append("Lacy caption/text overlay requirement not proven")
    if not caption_has_hashtag:
        blockers.append("Lacy #lacy caption requirement not proven")
    if not has_fit_flag and not content_term_hits:
        blockers.append("Lacy clip does not prove arrested/missing-in-action campaign theme")
    return {
        "ok": not blockers,
        "blockers": blockers,
        "content_term_hits": content_term_hits,
        "has_fit_flag": has_fit_flag,
        "rules_name_requirement": rules_name_requirement,
        "rules_theme_requirement": rules_theme_requirement,
    }


def _ffprobe_contract_ok(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    return (
        video.get("codec_name") == "h264"
        and int(video.get("width", 0) or 0) == 1080
        and int(video.get("height", 0) or 0) == 1920
        and audio.get("codec_name") == "aac"
    )


def _actual_review_video_ok(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                str(path),
            ],
            text=True,
            capture_output=True,
            timeout=12,
        )
    except Exception:
        return False
    if result.returncode != 0:
        return False
    try:
        payload = json.loads(result.stdout)
    except Exception:
        return False
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    audio = next((item for item in streams if item.get("codec_type") == "audio"), {})
    return (
        video.get("codec_name") == "h264"
        and int(video.get("width", 0) or 0) == 1080
        and int(video.get("height", 0) or 0) == 1920
        and audio.get("codec_name") == "aac"
    )


def _render_text_manifest_blockers(path: Path) -> List[str]:
    if not path.exists():
        return ["render_text_manifest.json missing"]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"render_text_manifest.json unreadable: {exc}"]
    rendered = payload.get("rendered_text", {})
    values: List[str] = []
    if isinstance(rendered, dict):
        for value in rendered.values():
            if isinstance(value, list):
                values.extend(str(item) for item in value)
            else:
                values.append(str(value))
    else:
        values.append(str(rendered))
    lowered = "\n".join(values).lower()
    blockers = [f"internal rendered text token present: {token}" for token in RENDERED_TEXT_BLOCKER_TOKENS if token in lowered]
    hook = str(rendered.get("hook_card", "") if isinstance(rendered, dict) else "").strip()
    normalized_hook = re.sub(r"\s+", " ", hook.lower()).strip()
    hook_words = re.findall(r"[a-z0-9]{2,}", normalized_hook)
    caption_beats = rendered.get("caption_beats", []) if isinstance(rendered, dict) else []
    if not isinstance(caption_beats, list):
        caption_beats = []
    caption_word_count = len(re.findall(r"[a-z0-9]{2,}", " ".join(str(item) for item in caption_beats).lower()))
    caption_violations = caption_beat_violations(caption_beats)
    if caption_violations:
        blockers.append("caption beat violates two-word short-line rule: " + "; ".join(caption_violations[:3]))
    caption_quality_violations = caption_text_quality_violations(caption_beats)
    if caption_quality_violations:
        blockers.append("caption text has broken ASR fragments: " + "; ".join(caption_quality_violations[:3]))
    caption_only = bool(payload.get("caption_only")) or (
        isinstance(rendered, dict)
        and str(rendered.get("layout", "")).strip().lower() == "caption_only"
        and rendered.get("hook_card_visible") is False
    )
    if caption_only:
        if len(caption_beats) < 3 or caption_word_count < 8:
            blockers.append("caption-only render has too few burned-in caption beats")
    elif normalized_hook in WEAK_RENDERED_HOOKS or len(hook_words) < 3:
        blockers.append("viewer hook card is too weak or shorthand for production proof")
    return blockers


def production_feeder_kit_status(kit: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical production render-proof classifier.

    The customer-facing app, QA audit, CEO report, and readiness endpoint all use
    this single function so demo/style-study kits can never accidentally satisfy
    production proof.
    """
    video_path = Path(str(kit.get("review_video_path", "")))
    kit_dir = video_path.parent
    nomination = one("SELECT * FROM render_nominations WHERE id = ?", (str(kit.get("nomination_id", "")),))
    target_style = str((nomination or {}).get("target_style", "")).strip()
    base_status = kit_dir_status(kit)
    profile = str(base_status.get("critique_profile") or target_style).strip()

    if int(kit.get("is_demo", 0) or 0) == 1 or profile in IGNORED_STUDY_PROFILES or target_style in IGNORED_STUDY_PROFILES:
        return {
            "classification": "ignored_study",
            "profile": profile or target_style,
            "target_style": target_style,
            "blockers": ["demo/reference/evidence-study kit is intentionally excluded from production proof"],
            "kit_dir": str(kit_dir),
            "clip_ids": _clip_ids_for_nomination(nomination),
        }

    campaign_slug = campaign_slug_for_kit(kit, nomination)
    is_campaign_profile = profile == CAMPAIGN_SHORT_PROFILE or target_style == CAMPAIGN_SHORT_PROFILE or bool(campaign_slug)
    blockers: List[str] = []
    if is_campaign_profile:
        if campaign_slug not in CAMPAIGN_PROJECTS:
            blockers.append("kit is not linked to an active campaign project")
        elif not is_active_campaign_project(campaign_slug):
            blockers.append(f"{CAMPAIGN_PROJECTS[campaign_slug]['name']} is excluded because no source media is linked")
        elif campaign_watermark_blocker(campaign_slug):
            blockers.append("required campaign watermark asset is missing")
        elif campaign_watermark_required(campaign_slug):
            manifest_payload = read_json_artifact(kit_dir / "render_text_manifest.json")
            rendered_manifest = manifest_payload.get("rendered_text", {}) if isinstance(manifest_payload, dict) else {}
            watermark_manifest = rendered_manifest.get("campaign_watermark", {}) if isinstance(rendered_manifest, dict) else {}
            if not (isinstance(watermark_manifest, dict) and rendered_manifest.get("watermark_visible") is True and watermark_manifest.get("asset_path")):
                blockers.append("required campaign watermark is not burned into rendered frame")
        if profile != CAMPAIGN_SHORT_PROFILE or target_style != CAMPAIGN_SHORT_PROFILE:
            blockers.append("campaign kit is not rendered with campaign_short_final_v1")
    elif profile != FINAL_PROOF_PROFILE or target_style != FINAL_PROOF_PROFILE:
        blockers.append("kit is not rendered with selected_feeder_final_v1")
    if not video_path.exists():
        blockers.append("review.mp4 missing")
    elif not _actual_review_video_ok(video_path):
        blockers.append("review.mp4 is not a readable H.264/AAC 1080x1920 file")
    if base_status.get("missing"):
        blockers.append(f"missing sidecars: {', '.join(base_status['missing'])}")
    if not _ffprobe_contract_ok(kit_dir / "ffprobe.json"):
        blockers.append("ffprobe sidecar does not prove H.264/AAC 1080x1920")
    blockers.extend(_render_text_manifest_blockers(kit_dir / "render_text_manifest.json"))
    if base_status.get("critique_status") != "green":
        blockers.append("style critique is not green")
    if str(kit.get("review_status", "")) == "rejected_revision_requested":
        blockers.append("kit is currently rejected for revision")

    combined_text = "\n".join(
        _text_file(kit_dir / name).lower()
        for name in ("caption.txt", "transcript.txt", "checklist.md", "source.md", "risk.md", "style_critique.md")
    )
    checklist_text = _text_file(kit_dir / "checklist.md")
    risk_text = _text_file(kit_dir / "risk.md").lower()
    visible_identity = "\n".join(
        [
            str(kit.get("title", "")),
            str(video_path),
            str(kit_dir),
            profile,
            target_style,
        ]
    ).lower()
    for token in PRODUCTION_PROOF_BLOCKER_TOKENS:
        if token in combined_text:
            blockers.append(f"blocked phrase present: {token}")
            break
    if "campaign fit still requires human judgment" in risk_text:
        blockers.append("campaign fit still requires human judgment")
    if "ready-to-post approval granted" in checklist_text.lower() and _checklist_box_checked(checklist_text, "Ready-to-post approval granted."):
        blockers.append("kit has publish approval language checked; production render proof must stay separate from posting approval")
    if any(token in visible_identity for token in ("feeder proof", "feeder-proof", "review kit", "evidence review")):
        blockers.append("visible artifact still carries proof/review naming")

    source_text = _text_file(kit_dir / "source.md")
    caption_text = _text_file(kit_dir / "caption.txt")
    transcript_text = _text_file(kit_dir / "transcript.txt")
    manifest_text = _text_file(kit_dir / "render_text_manifest.json")
    clip_ids = _clip_ids_for_nomination(nomination)
    if not clip_ids:
        blockers.append("nomination has no clip ids")
    checked_clips: List[Dict[str, Any]] = []
    hard_editorial_blocked = False
    for clip_id in clip_ids:
        clip = one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,))
        if not clip:
            blockers.append(f"{clip_id}: clip candidate missing")
            continue
        checked_clips.append(clip)
        editorial = editorial_review_for_rendered_kit(clip, kit_dir, campaign_slug, require_sidecar=True)
        if editorial.get("status") != "green":
            hard_editorial_blocked = True
            blockers.extend(f"{clip_id}: editorial gate: {blocker}" for blocker in editorial.get("blockers", [])[:6])
        clip_campaign_slug = campaign_slug_for_clip(clip)
        if is_campaign_profile:
            if clip_campaign_slug != campaign_slug:
                blockers.append(f"{clip_id}: clip is not linked to {campaign_slug or 'the campaign project'}")
        elif not is_relevant_streamer_clip(clip):
            blockers.append(f"{clip_id}: not a relevant selected-feeder Twitch/Kick clip")
        source_url = str(clip.get("source_url", "")).strip()
        if not source_url:
            blockers.append(f"{clip_id}: source URL missing")
        local_media = Path(str(clip.get("local_media_path", "")).strip()) if str(clip.get("local_media_path", "")).strip() else None
        if not local_media or not local_media.exists():
            blockers.append(f"{clip_id}: local source media missing")
        flags = _risk_flags(clip)
        if is_campaign_profile and clip_campaign_slug == "kalshi" and "campaign_selected_good_moment" not in flags:
            blockers.append(f"{clip_id}: Kalshi campaign clip was not promoted by subtitle-scored moment selection")
        if "source_media_verified_local" not in flags and "source_download_verified" not in flags:
            blockers.append(f"{clip_id}: local source media provenance flag missing")
        transcript = _latest_success_transcript(clip_id)
        if not _transcript_is_word_timed(transcript):
            blockers.append(f"{clip_id}: succeeded non-placeholder word-timed transcript missing")
        rules = _campaign_rules_for_clip(clip, source_text)
        if not rules:
            blockers.append(f"{clip_id}: stored campaign rules missing")
        if not is_campaign_profile and _is_lacy_clip(clip):
            campaign_rule_text = "\n".join(
                [str(item.get("title", "")) + "\n" + str(item.get("extracted_text", "")) + "\n" + str(item.get("notes", "")) for item in rules]
            )
            lacy_fit = _lacy_campaign_fit_status(
                clip,
                source_text=source_text,
                caption_text=caption_text,
                transcript_text=transcript_text,
                manifest_text=manifest_text,
                campaign_rule_text=campaign_rule_text,
            )
            if not lacy_fit["ok"]:
                blockers.extend(f"{clip_id}: {blocker}" for blocker in lacy_fit["blockers"])

    if not base_status.get("source_verified"):
        blockers.append("source.md does not prove local source media")

    classification = "green" if not blockers else ("red" if hard_editorial_blocked else ("yellow" if base_status.get("complete") and video_path.exists() else "red"))
    return {
        "classification": classification,
        "profile": profile,
        "target_style": target_style,
        "blockers": blockers,
        "kit_dir": str(kit_dir),
        "clip_ids": clip_ids,
        "checked_clip_count": len(checked_clips),
        "complete": bool(base_status.get("complete")),
        "critique_status": base_status.get("critique_status", "unknown"),
        "ffprobe_ok": _ffprobe_contract_ok(kit_dir / "ffprobe.json"),
        "editorial_gate": "red" if hard_editorial_blocked else "green",
    }


def selected_feeder_source_media_counts() -> Dict[str, int]:
    visible = visible_clip_candidates()
    verified = 0
    metadata_only = 0
    missing_media = 0
    transcript_ready = 0
    transcript_timed = 0
    transcript_clip_ids: Dict[str, Dict[str, Any]] = {}
    for item in rows("SELECT * FROM transcripts WHERE status = 'succeeded' ORDER BY created_at DESC"):
        clip_id = str(item["clip_candidate_id"])
        if clip_id not in transcript_clip_ids:
            transcript_clip_ids[clip_id] = item
    for clip in visible:
        flags = _risk_flags(clip)
        local_value = str(clip.get("local_media_path", "")).strip()
        local_path = Path(local_value) if local_value else None
        local_exists = bool(local_path and local_path.exists())
        is_metadata_only = "metadata_only_no_download" in flags and not local_exists
        if is_metadata_only:
            metadata_only += 1
        if local_exists:
            verified += 1
        elif not is_metadata_only:
            missing_media += 1
        transcript = transcript_clip_ids.get(str(clip["id"]))
        if transcript and "placeholder" not in str(transcript.get("provider", "")).lower():
            transcript_ready += 1
            if _transcript_is_word_timed(transcript):
                transcript_timed += 1
    return {
        "candidates": len(visible),
        "source_media_verified": verified,
        "metadata_only": metadata_only,
        "missing_media": missing_media,
        "transcript_ready": transcript_ready,
        "transcript_timed": transcript_timed,
    }


def campaign_rules_for_slug(slug: str) -> List[Dict[str, Any]]:
    normalized = normalize_campaign_slug(slug)
    if not normalized:
        return []
    return rows(
        """
        SELECT *
        FROM campaign_evidence
        WHERE evidence_type = 'campaign_rules'
          AND lower(campaign_id) = ?
        ORDER BY captured_at DESC
        """,
        (normalized,),
    )


def campaign_clips(slug: str) -> List[Dict[str, Any]]:
    normalized = normalize_campaign_slug(slug)
    if not normalized:
        return []
    candidates = rows(
        """
        SELECT clip_candidates.*
        FROM clip_candidates
        LEFT JOIN (
          SELECT clip_candidate_id, MAX(total_score) AS total_score
          FROM viral_scores
          GROUP BY clip_candidate_id
        ) latest_score ON latest_score.clip_candidate_id = clip_candidates.id
        WHERE campaign_slug = ?
           OR risk_flags_json LIKE ?
        ORDER BY
          CASE
            WHEN risk_flags_json LIKE '%campaign_selected_good_moment%' THEN 0
            WHEN risk_flags_json LIKE '%campaign_subtitle_selected%' THEN 1
            WHEN local_media_path IS NOT NULL AND local_media_path != '' THEN 2
            ELSE 3
          END,
          COALESCE(latest_score.total_score, 0) DESC,
          view_count DESC,
          discovered_at DESC
        """,
        (normalized, f"%campaign_project_{normalized}%"),
    )
    return [
        item
        for item in candidates
        if campaign_slug_for_clip(item) == normalized and is_campaign_project_clip(item)
    ]


def campaign_render_kits(slug: str) -> List[Dict[str, Any]]:
    normalized = normalize_campaign_slug(slug)
    if not normalized:
        return []
    collected: List[Dict[str, Any]] = []
    for kit in rows("SELECT * FROM render_kits ORDER BY created_at DESC"):
        nomination = one("SELECT * FROM render_nominations WHERE id = ?", (str(kit.get("nomination_id", "")),))
        if campaign_slug_for_kit(kit, nomination) == normalized:
            collected.append(enrich_render_kit_with_clip_metadata(kit))
    return sorted(collected, key=render_kit_sort_key, reverse=True)


def _clip_has_local_source_media(clip: Dict[str, Any]) -> bool:
    local_value = str(clip.get("local_media_path", "")).strip()
    if not local_value or not Path(local_value).exists():
        return False
    flags = _risk_flags(clip)
    return any(flag in flags for flag in LOCAL_MEDIA_READY_FLAGS)


def campaign_project_progress(slug: str) -> Dict[str, Any]:
    normalized = normalize_campaign_slug(slug)
    if not normalized:
        return {}
    project = CAMPAIGN_PROJECTS[normalized]
    if project.get("active", "true") != "true":
        reason = project.get("excluded_reason", "Campaign is excluded from active review batch.")
        return {
            "slug": normalized,
            "name": project["name"],
            "campaign_url": project["campaign_url"],
            "requirements_url": project.get("requirements_url", ""),
            "source_strategy": project["source_strategy"],
            "review_target_count": 0,
            "clip_count": 0,
            "source_ready_count": 0,
            "metadata_only_count": 0,
            "rendered_count": 0,
            "approved_count": 0,
            "needs_review_count": 0,
            "status": "excluded",
            "source_ready": False,
            "rules_stored": False,
            "watermark_required": campaign_watermark_required(normalized),
            "watermark_ready": campaign_watermark_ready(normalized),
            "watermark_url": project.get("watermark_url", ""),
            "watermark_asset_path": campaign_watermark_asset_path(normalized),
            "blocker": reason,
            "blockers": [reason],
            "next_action": "Excluded",
        }
    clips = campaign_clips(normalized)
    rules = campaign_rules_for_slug(normalized)
    kits = campaign_render_kits(normalized)
    proof_statuses = [production_feeder_kit_status(kit) for kit in kits]
    green_kits = [kit for kit, status in zip(kits, proof_statuses) if status.get("classification") == "green"]
    approved_green = [
        kit
        for kit, status in zip(kits, proof_statuses)
        if status.get("classification") == "green" and str(kit.get("review_status", "")) == "approved_manual_prep"
    ]
    local_source_ready = sum(1 for clip in clips if _clip_has_local_source_media(clip))
    metadata_only = sum(1 for clip in clips if "metadata_only_no_download" in _risk_flags(clip) or not _clip_has_local_source_media(clip))
    watermark_required = campaign_watermark_required(normalized)
    watermark_ready = campaign_watermark_ready(normalized)
    watermark_blocker = campaign_watermark_blocker(normalized)
    blockers: List[str] = []
    if not rules:
        blockers.append("Campaign brief/rules are not stored.")
    if local_source_ready == 0:
        blockers.append("No local source media is verified for this campaign.")
    if watermark_blocker:
        blockers.append(watermark_blocker)
    if len(green_kits) < CAMPAIGN_PROJECT_TARGET:
        blockers.append(f"{CAMPAIGN_PROJECT_TARGET - len(green_kits)} more validated review kit(s) needed.")
    if len(approved_green) < CAMPAIGN_PROJECT_TARGET:
        blockers.append(f"{CAMPAIGN_PROJECT_TARGET - len(approved_green)} review kit approval(s) needed.")
    status = "green" if not blockers else ("yellow" if green_kits or local_source_ready else "red")
    next_action = "Approved batch complete."
    if blockers:
        if not rules:
            next_action = "Refresh Campaigns"
        elif local_source_ready == 0:
            next_action = "Discover Sources"
        elif watermark_required and not watermark_ready:
            next_action = "Install Watermark Asset"
        elif len(green_kits) < CAMPAIGN_PROJECT_TARGET:
            next_action = "Build Reviews"
        else:
            next_action = "Approve Reviews"
    return {
        "slug": normalized,
        "name": project["name"],
        "campaign_url": project["campaign_url"],
        "requirements_url": project.get("requirements_url", ""),
        "source_strategy": project["source_strategy"],
        "review_target_count": CAMPAIGN_PROJECT_TARGET,
        "clip_count": len(clips),
        "source_ready_count": local_source_ready,
        "metadata_only_count": metadata_only,
        "rendered_count": len(green_kits),
        "approved_count": len(approved_green),
        "needs_review_count": sum(1 for kit in green_kits if str(kit.get("review_status", "")) == "needs_review"),
        "status": status,
        "source_ready": bool(local_source_ready),
        "rules_stored": bool(rules),
        "watermark_required": watermark_required,
        "watermark_ready": watermark_ready,
        "watermark_url": project.get("watermark_url", ""),
        "watermark_asset_path": campaign_watermark_asset_path(normalized),
        "blocker": blockers[0] if blockers else "",
        "blockers": blockers,
        "next_action": next_action,
    }


def campaign_project_records() -> List[Dict[str, Any]]:
    return [campaign_project_progress(slug) for slug in active_campaign_project_slugs()]


def three_campaign_review_batch_status() -> Dict[str, Any]:
    projects = campaign_project_records()
    active_slugs = active_campaign_project_slugs()
    excluded = excluded_campaign_projects()
    blockers: List[str] = []
    approval_blockers: List[str] = []
    for project in projects:
        project_blockers: List[str] = []
        project_approval_blockers: List[str] = []
        if project.get("approved_count", 0) < CAMPAIGN_PROJECT_TARGET:
            project_approval_blockers.append(f"{project.get('approved_count', 0)}/{CAMPAIGN_PROJECT_TARGET} approved")
        if project.get("rendered_count", 0) < CAMPAIGN_PROJECT_TARGET:
            project_blockers.append(f"{project.get('rendered_count', 0)}/{CAMPAIGN_PROJECT_TARGET} rendered")
        blocker = str(project.get("blocker", ""))
        if (
            project.get("status") != "green"
            and blocker
            and "approval" not in blocker
            and "validated review kit" not in blocker
        ):
            project_blockers.append(blocker)
        if project_blockers:
            blockers.append(f"{project.get('name')}: {', '.join(project_blockers)}")
        if project_approval_blockers:
            approval_blockers.append(f"{project.get('name')}: {', '.join(project_approval_blockers)}")
    ready = not blockers and len(projects) == len(active_slugs)
    approvals_ready = not approval_blockers and len(projects) == len(active_slugs)
    return {
        "status": "green" if ready else ("yellow" if any(project.get("rendered_count", 0) for project in projects) else "red"),
        "ready": ready,
        "approvals_ready": approvals_ready,
        "target_total": CAMPAIGN_PROJECT_TARGET * len(active_slugs),
        "approved_total": sum(int(project.get("approved_count", 0) or 0) for project in projects),
        "rendered_total": sum(int(project.get("rendered_count", 0) or 0) for project in projects),
        "projects": projects,
        "excluded_projects": excluded,
        "blockers": blockers,
        "approval_blockers": approval_blockers,
    }


def artifact_freshness(path: Path, max_age_hours: int = FRESH_EVIDENCE_HOURS) -> Dict[str, Any]:
    if not path.exists():
        return {"exists": False, "fresh": False, "path": str(path), "age_hours": None}
    age_seconds = max(0.0, datetime.now(timezone.utc).timestamp() - path.stat().st_mtime)
    return {
        "exists": True,
        "fresh": age_seconds <= max_age_hours * 3600,
        "path": str(path),
        "age_hours": round(age_seconds / 3600, 2),
    }


def read_json_artifact(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def codex_handoff_package_status(repo_root: Path) -> Dict[str, Any]:
    manifest_path = repo_root / "artifacts" / "handoff" / "codex-handoff.json"
    freshness = artifact_freshness(manifest_path)
    payload = read_json_artifact(manifest_path)
    ok = (
        bool(freshness["fresh"])
        and bool(payload.get("ok"))
        and bool(payload.get("source_build_handoff_ready"))
        and bool(payload.get("secrets_transferred") is False)
        and Path(str(payload.get("zip_path", ""))).exists()
    )
    detail = (
        f"mode={payload.get('mode', 'unknown')}; zip={payload.get('zip_path', '')}; "
        f"files={payload.get('file_count', 0)}; secrets_transferred={payload.get('secrets_transferred')}; "
        f"fresh={freshness['fresh']} age_hours={freshness['age_hours']}"
        if payload
        else "Codex source handoff manifest missing"
    )
    blocker = ""
    if not ok:
        blocker = "Run script/package_codex_handoff.sh to create a fresh no-secret source/build zip for buddy Codex sessions."
    return {
        "ok": ok,
        "detail": detail,
        "blocker": blocker,
        "manifest_path": str(manifest_path),
        "payload": payload,
    }


def hermes_cli_readiness() -> Dict[str, Any]:
    hermes_path = shutil.which("hermes") or str(Path.home() / ".local" / "bin" / "hermes")
    available = bool(hermes_path and Path(hermes_path).exists())
    if not available:
        return {"available": False, "auth_degraded": False, "cron_ok": False, "detail": "hermes missing"}
    try:
        cron = subprocess.run([hermes_path, "cron", "list"], text=True, capture_output=True, timeout=8)
        combined = f"{cron.stdout}\n{cron.stderr}".lower()
        auth_degraded = any(token in combined for token in ("401", "token invalidated", "invalid_grant", "unauthorized"))
        return {
            "available": True,
            "auth_degraded": auth_degraded,
            "cron_ok": cron.returncode == 0,
            "detail": "cron auth degraded" if auth_degraded else ("cron ok" if cron.returncode == 0 else "cron list failed"),
        }
    except Exception as exc:
        return {"available": True, "auth_degraded": False, "cron_ok": False, "detail": f"hermes cron check failed: {exc}"}


def kit_dir_status(kit: Dict[str, Any]) -> Dict[str, Any]:
    video_path = Path(str(kit.get("review_video_path", "")))
    kit_dir = video_path.parent
    missing = [name for name in REQUIRED_KIT_FILES if not (kit_dir / name).exists()]
    source_text = ""
    transcript_text = ""
    risk_text = ""
    critique_text = ""
    critique_status = "unknown"
    critique_profile = ""
    try:
        source_text = (kit_dir / "source.md").read_text(encoding="utf-8").lower()
    except Exception:
        pass
    try:
        transcript_text = (kit_dir / "transcript.txt").read_text(encoding="utf-8").lower()
    except Exception:
        pass
    try:
        risk_text = (kit_dir / "risk.md").read_text(encoding="utf-8").lower()
    except Exception:
        pass
    try:
        critique_text = (kit_dir / "style_critique.md").read_text(encoding="utf-8").lower()
        for line in critique_text.splitlines():
            if line.startswith("status:"):
                critique_status = line.split(":", 1)[1].strip().lower()
            elif line.startswith("profile:"):
                critique_profile = line.split(":", 1)[1].strip().lower()
    except Exception:
        pass
    transcript_placeholder = "placeholder transcript" in transcript_text or "placeholder transcript" in risk_text
    source_verified = (
        "yt-dlp fallback" in source_text
        or "source_download_verified" in source_text
        or "source_media_verified_local" in source_text
        or ("local media:" in source_text and "/source_media/" in source_text)
    )
    internal_label = any(token in (source_text + transcript_text + risk_text + critique_text) for token in ("local demo", "demo media", "demo-only"))
    review_safe_layout = "review-safe layout" in critique_text
    human_review_gate = "human-review gate" in critique_text or "human review gate" in critique_text
    return {
        "kit_dir": str(kit_dir),
        "missing": missing,
        "critique_status": critique_status,
        "critique_profile": critique_profile,
        "source_verified": source_verified,
        "transcript_placeholder": transcript_placeholder,
        "internal_label": internal_label,
        "review_safe_layout": review_safe_layout,
        "human_review_gate": human_review_gate,
        "complete": not missing,
    }


def kit_forces_yellow_until_proven(kit: Dict[str, Any], status: Dict[str, Any]) -> bool:
    title = str(kit.get("title", "")).lower()
    profile = str(status.get("critique_profile", "")).lower()
    forced_tokens = (
        "demo",
        "reference style",
        "reference",
        "evidence review",
        "feeder proof",
        "proof",
        "demo-safe",
        "ishouldclip-inspired",
        "evidence_review",
        "selected_feeder_final",
    )
    return bool(int(kit.get("is_demo", 0) or 0)) or status.get("internal_label", False) or any(
        token in title or token in profile for token in forced_tokens
    )


def status_from_bools(*checks: bool) -> str:
    return "green" if all(checks) else "red"


def feature(name: str, status: str, evidence: str, blocker: str = "", proof: str = "") -> Dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "evidence": evidence,
        "blocker": blocker,
        "proof": proof,
    }


def prune_irrelevant_review_surface(archive_files: bool = True) -> Dict[str, Any]:
    init_db()
    bad_clips = [
        str(item["id"])
        for item in rows("SELECT * FROM clip_candidates")
        if not is_campaign_project_clip(item)
    ]
    bad_nominations = [
        str(item["id"])
        for item in rows("SELECT * FROM render_nominations")
        if contains_irrelevant_review_token(
            item.get("id"),
            item.get("score_reason"),
            item.get("target_style"),
            item.get("status"),
            item.get("clip_candidate_ids_json"),
        )
        or any(clip_id in str(item.get("clip_candidate_ids_json", "")) for clip_id in bad_clips)
    ]
    bad_kits = [
        item
        for item in rows("SELECT * FROM render_kits")
        if int(item.get("is_demo", 0) or 0) == 1
        or str(item.get("nomination_id", "")) in bad_nominations
        or contains_irrelevant_review_token(
            item.get("title"),
            item.get("review_video_path"),
            item.get("caption_path"),
            item.get("transcript_path"),
            item.get("source_path"),
            item.get("risk_path"),
        )
        or any(
            "viewer hook card is too weak" in blocker
            or "Lacy clip does not prove arrested/missing-in-action" in blocker
            or "Lacy #lacy caption requirement not proven" in blocker
            or "editorial gate:" in blocker
            or "unnecessary facecam-top composition" in blocker
            or "clip has " in blocker and "editorial floor" in blocker
            for blocker in production_feeder_kit_status(item).get("blockers", [])
        )
    ]
    bad_jobs = [
        str(item["id"])
        for item in rows("SELECT * FROM job_runs")
        if str(item.get("name", "")) in {"demo-render", "selected-feeder-render", "review-kit-revision"}
        or contains_irrelevant_review_token(item.get("name"), item.get("logs"), item.get("output_path"), item.get("error"))
    ]

    archived_dirs: List[str] = []
    archive_root = app_support_dir() / "render_kits_irrelevant_archive" / datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    render_root_path = render_root().resolve()
    if archive_files:
        for clip in rows("SELECT * FROM clip_candidates"):
            if str(clip.get("id", "")) not in bad_clips:
                continue
            local_value = str(clip.get("local_media_path", "") or "").strip()
            if not local_value:
                continue
            media_path = Path(local_value)
            if not media_path.exists():
                continue
            try:
                media_root = source_media_root().resolve()
                resolved_media = media_path.resolve()
            except OSError:
                continue
            if media_root not in resolved_media.parents and resolved_media != media_root:
                continue
            destination = archive_root / "source_media" / media_path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = archive_root / "source_media" / f"{media_path.stem}-{uuid.uuid4().hex[:6]}{media_path.suffix}"
            shutil.move(str(media_path), str(destination))
            archived_dirs.append(str(destination))

        for kit in bad_kits:
            video_path = Path(str(kit.get("review_video_path", "")))
            kit_dir = video_path.parent
            try:
                resolved = kit_dir.resolve()
            except OSError:
                continue
            if not kit_dir.exists() or render_root_path not in resolved.parents:
                continue
            destination = archive_root / kit_dir.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = archive_root / f"{kit_dir.name}-{uuid.uuid4().hex[:6]}"
            shutil.move(str(kit_dir), str(destination))
            archived_dirs.append(str(destination))

        referenced_dirs = {
            str(Path(str(item.get("review_video_path", ""))).parent.resolve())
            for item in rows("SELECT review_video_path FROM render_kits")
            if str(item.get("review_video_path", "")).strip()
        }
        for kit_dir in render_root().iterdir():
            if not kit_dir.is_dir():
                continue
            try:
                resolved = str(kit_dir.resolve())
            except OSError:
                continue
            if resolved in referenced_dirs:
                continue
            destination = archive_root / kit_dir.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = archive_root / f"{kit_dir.name}-{uuid.uuid4().hex[:6]}"
            shutil.move(str(kit_dir), str(destination))
            archived_dirs.append(str(destination))

        for kit_dir in demo_render_root().iterdir():
            if not kit_dir.is_dir():
                continue
            missing = [name for name in REQUIRED_KIT_FILES if not (kit_dir / name).exists()]
            if not missing:
                continue
            destination = archive_root / f"demo-incomplete-{kit_dir.name}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                destination = archive_root / f"demo-incomplete-{kit_dir.name}-{uuid.uuid4().hex[:6]}"
            shutil.move(str(kit_dir), str(destination))
            archived_dirs.append(str(destination))

    def delete_ids(table: str, ids: List[str]) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", ids)

    if bad_clips:
        placeholders = ",".join("?" for _ in bad_clips)
        execute(f"DELETE FROM transcripts WHERE clip_candidate_id IN ({placeholders})", bad_clips)
        execute(f"DELETE FROM viral_scores WHERE clip_candidate_id IN ({placeholders})", bad_clips)
    delete_ids("render_kits", [str(item["id"]) for item in bad_kits])
    delete_ids("render_nominations", bad_nominations)
    delete_ids("clip_candidates", bad_clips)
    delete_ids("job_runs", bad_jobs)
    log_audit(
        "operator",
        "prune_irrelevant_review_surface",
        "review_surface",
        "visible-gui",
        f"removed {len(bad_clips)} clips, {len(bad_nominations)} nominations, {len(bad_kits)} kits",
        "local cleanup",
    )
    return {
        "status": "succeeded",
        "removed": {
            "clip_candidates": len(bad_clips),
            "render_nominations": len(bad_nominations),
            "render_kits": len(bad_kits),
            "job_runs": len(bad_jobs),
            "archived_dirs": len(archived_dirs),
        },
        "archive_root": str(archive_root) if archived_dirs else "",
        "archived_dirs": archived_dirs,
        "visible_counts": visible_counts(),
    }


def record_platform_check(
    provider: str,
    endpoint: str,
    status: str,
    http_status: int = 0,
    request_summary: str = "",
    response_excerpt: str = "",
    rate_limit_remaining: str = "",
    error: str = "",
) -> str:
    check_id = new_id("api")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO platform_api_checks
              (id, provider, endpoint, status, http_status, request_summary, response_excerpt, rate_limit_remaining, error, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                check_id,
                provider,
                endpoint,
                status,
                int(http_status or 0),
                request_summary,
                response_excerpt[:1800],
                rate_limit_remaining,
                error[:1200],
                utc_now(),
            ),
        )
    return check_id


def create_campaign_evidence(payload: Dict[str, Any]) -> Dict[str, Any]:
    evidence_id = new_id("evidence")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO campaign_evidence
              (id, campaign_id, evidence_type, title, source_url, screenshot_path, extracted_text, captured_by, confidence, notes, captured_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                str(payload.get("campaign_id", "")),
                str(payload.get("evidence_type", "note")),
                str(payload.get("title", "")),
                str(payload.get("source_url", "")),
                str(payload.get("screenshot_path", "")),
                str(payload.get("extracted_text", "")),
                str(payload.get("captured_by", "operator")),
                float(payload.get("confidence", 0) or 0),
                str(payload.get("notes", "")),
                utc_now(),
            ),
        )
    log_audit("operator", "add_campaign_evidence", "campaign_evidence", evidence_id, "stored", str(payload.get("source_url", "")))
    item = one("SELECT * FROM campaign_evidence WHERE id = ?", (evidence_id,))
    return item or {}


def upsert_source_route(payload: Dict[str, Any]) -> Dict[str, Any]:
    platform = str(payload.get("platform", "")).strip().lower()
    creator_handle = str(payload.get("creator_handle", "")).strip()
    route_type = str(payload.get("route_type", "manual_import")).strip()
    existing = one(
        "SELECT id FROM source_routes WHERE platform = ? AND creator_handle = ? AND route_type = ?",
        (platform, creator_handle, route_type),
    )
    route_id = str(existing["id"]) if existing else new_id("route")
    risk_flags = payload.get("risk_flags", [])
    if not isinstance(risk_flags, list):
        risk_flags = [str(risk_flags)]
    params = (
        route_id,
        platform,
        creator_handle,
        str(payload.get("source_url", "")),
        route_type,
        str(payload.get("auth_state", "")),
        str(payload.get("availability_status", "unchecked")),
        str(payload.get("latest_check_id", "")),
        json.dumps(risk_flags),
        str(payload.get("notes", "")),
        utc_now(),
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO source_routes
              (id, platform, creator_handle, source_url, route_type, auth_state, availability_status, latest_check_id, risk_flags_json, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              source_url=excluded.source_url,
              auth_state=excluded.auth_state,
              availability_status=excluded.availability_status,
              latest_check_id=excluded.latest_check_id,
              risk_flags_json=excluded.risk_flags_json,
              notes=excluded.notes,
              updated_at=excluded.updated_at
            """,
            params,
        )
    log_audit("operator", "upsert_source_route", "source_route", route_id, str(payload.get("availability_status", "unchecked")), platform)
    item = one("SELECT * FROM source_routes WHERE id = ?", (route_id,))
    return item or {}


def readiness_report() -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    gate = latest_campaign_gate()
    non_demo_kits = visible_render_kits()

    twitch_ok = one("SELECT COUNT(*) AS count FROM platform_api_checks WHERE provider='twitch' AND status='succeeded'") or {"count": 0}
    kick_ok = one("SELECT COUNT(*) AS count FROM platform_api_checks WHERE provider='kick' AND status='succeeded'") or {"count": 0}
    evidence_count = one("SELECT COUNT(*) AS count FROM campaign_evidence") or {"count": 0}
    selected_routes = one(
        """
        SELECT COUNT(*) AS count FROM source_routes
        WHERE availability_status IN ('verified','reachable')
          AND route_type IN ('official_api','authenticated_route','manual_import')
          AND risk_flags_json LIKE '%selected_feeder_%'
        """
    ) or {"count": 0}
    source_counts = selected_feeder_source_media_counts()

    non_demo_green_count = 0
    non_demo_yellow_count = 0
    non_demo_red_count = 0
    ignored_study_count = 0
    latest_kit_blockers: List[str] = []
    for kit in non_demo_kits:
        status = production_feeder_kit_status(kit)
        classification = str(status.get("classification", "red"))
        blockers = [str(item) for item in status.get("blockers", [])]
        if classification == "green":
            non_demo_green_count += 1
        elif classification == "yellow":
            non_demo_yellow_count += 1
        elif classification == "ignored_study":
            ignored_study_count += 1
        else:
            non_demo_red_count += 1
        if blockers:
            latest_kit_blockers.extend(blockers[:3])

    gui_manifest_path = repo_root / "artifacts" / "desktop-qa" / "manifest.json"
    gui_fresh = artifact_freshness(gui_manifest_path)
    gui_manifest = read_json_artifact(gui_manifest_path)
    gui_ok = (
        bool(gui_fresh["fresh"])
        and bool(gui_manifest.get("ok"))
        and bool(gui_manifest.get("app_survived_all_page_clicks"))
        and not gui_manifest.get("new_crash_reports")
        and len(gui_manifest.get("page_clicks", [])) >= 16
        and len(gui_manifest.get("controls", [])) >= 8
        and len(gui_manifest.get("media", [])) >= 1
    )
    gui_detail = (
        f"{len(gui_manifest.get('page_clicks', []))} clicks; "
        f"{len(gui_manifest.get('screenshots', []))} screenshots; "
        f"{len(gui_manifest.get('controls', []))} controls; "
        f"{len(gui_manifest.get('new_crash_reports', []))} new crashes; "
        f"fresh={gui_fresh['fresh']} age_hours={gui_fresh['age_hours']}"
        if gui_manifest
        else "desktop QA manifest missing"
    )

    security_path = repo_root / "artifacts" / "security" / "security-scan.json"
    security_fresh = artifact_freshness(security_path)
    security_payload = read_json_artifact(security_path)
    security_ok = bool(security_fresh["fresh"]) and bool(security_payload.get("ok"))
    security_detail = (
        f"{security_payload.get('finding_count', 'unknown')} findings; fresh={security_fresh['fresh']} age_hours={security_fresh['age_hours']}; {security_path}"
        if security_payload
        else "security scan artifact missing"
    )

    burned_caption_path = repo_root / "artifacts" / "review-kit-audit" / "burned-caption-verification.json"
    burned_caption_fresh = artifact_freshness(burned_caption_path)
    burned_caption_payload = read_json_artifact(burned_caption_path)
    burned_caption_ok = (
        bool(burned_caption_fresh["fresh"])
        and bool(burned_caption_payload.get("ok"))
        and int(burned_caption_payload.get("kit_count", 0) or 0) >= max(1, non_demo_green_count)
    )
    burned_caption_detail = (
        f"ok={burned_caption_payload.get('ok')}; kits={burned_caption_payload.get('kit_count', 0)}; "
        f"fresh={burned_caption_fresh['fresh']} age_hours={burned_caption_fresh['age_hours']}; {burned_caption_path}"
        if burned_caption_payload
        else "burned-in subtitle verification artifact missing"
    )

    launchagent_path = repo_root / "artifacts" / "backend" / "backend-launchagent.json"
    launchagent_fresh = artifact_freshness(launchagent_path)
    launchagent_payload = read_json_artifact(launchagent_path)
    launchagent_ok = bool(launchagent_fresh["fresh"]) and bool(launchagent_payload.get("ok"))
    launchagent_detail = (
        f"state={launchagent_payload.get('state', 'unknown')}; "
        f"last_exit={launchagent_payload.get('last_exit', '')}; "
        f"api={launchagent_payload.get('api_version', '')}; "
        f"fresh={launchagent_fresh['fresh']}"
        if launchagent_payload
        else "backend LaunchAgent check artifact missing"
    )

    no_key_path = repo_root / "artifacts" / "no-key" / "no-key-installer.json"
    no_key_fresh = artifact_freshness(no_key_path)
    no_key_payload = read_json_artifact(no_key_path)
    no_key_ok = bool(no_key_fresh["fresh"]) and bool(no_key_payload.get("ok"))
    no_key_detail = (
        f"ok={no_key_payload.get('ok')}; no_key_mode={no_key_payload.get('no_key_mode')}; fresh={no_key_fresh['fresh']}; {no_key_path}"
        if no_key_payload
        else "no-key installer proof artifact missing"
    )

    handoff = codex_handoff_package_status(repo_root)

    release_path = repo_root / "artifacts" / "distribution" / "release-verify.json"
    release_fresh = artifact_freshness(release_path)
    release_payload = read_json_artifact(release_path)
    release_ok = bool(release_fresh["fresh"]) and bool(release_payload.get("customer_ship_ready"))
    release_detail = (
        f"bundle={release_payload.get('bundle_ok')}; signed={release_payload.get('signed_ok')}; "
        f"identity={release_payload.get('signing_identity', '')}; notarized={release_payload.get('notarized_ok')}; "
        f"fresh={release_fresh['fresh']}"
        if release_payload
        else "release verification artifact missing"
    )

    product_path = repo_root / "artifacts" / "product-proof" / "artifact-summary.json"
    product_fresh = artifact_freshness(product_path)
    product_payload = read_json_artifact(product_path)
    product_required = ("workbook", "architecture_mermaid", "readiness_doc", "runbook", "deck_markdown")
    product_ok = bool(product_fresh["fresh"]) and all(
        Path(str(product_payload.get(key, ""))).exists() for key in product_required
    )
    hermes_cli = hermes_cli_readiness()
    hermes_proof = hermes_native_execution_proof()
    hermes_ok = bool(hermes_cli["available"]) and not bool(hermes_cli["auth_degraded"]) and bool(hermes_proof["ok"])
    hermes_status = "green" if hermes_ok else ("yellow" if hermes_cli["available"] else "red")
    hermes_blocker = ""
    if not hermes_cli["available"]:
        hermes_blocker = "Hermes CLI is missing from the local system."
    elif hermes_cli["auth_degraded"]:
        hermes_blocker = "Hermes scheduled agent jobs show stale auth/401 failures; refresh Hermes auth or reinstall schedules before internal readiness is green."
    elif not hermes_proof["ok"]:
        hermes_blocker = "At least one Hermes-claimed job must succeed before internal readiness is green."

    db_ok = database_path().exists()
    platform_ok = int(twitch_ok["count"]) > 0 and int(kick_ok["count"]) > 0
    gate_ok = gate.get("status") == "qualified"
    production_render_ok = non_demo_green_count > 0
    review_batch = three_campaign_review_batch_status()
    active_source_targets_ok = all(
        int(project.get("source_ready_count", 0) or 0) >= int(project.get("review_target_count", CAMPAIGN_PROJECT_TARGET) or CAMPAIGN_PROJECT_TARGET)
        and bool(project.get("rules_stored"))
        for project in review_batch.get("projects", [])
    )
    source_media_ok = active_source_targets_ok and bool(review_batch.get("ready"))

    features = [
        feature(
            "Local backend source of truth",
            "green" if db_ok else "red",
            str(database_path()),
            "" if db_ok else "SQLite database missing",
            str(database_path()),
        ),
        feature(
            "Hermes-native orchestration",
            hermes_status,
            f"{hermes_cli['detail']}; {hermes_proof['detail']}",
            hermes_blocker,
            "/api/agents",
        ),
        feature(
            "Platform API production smoke",
            "green" if platform_ok else "red",
            f"Twitch succeeded checks: {twitch_ok['count']}; Kick succeeded checks: {kick_ok['count']}",
            "" if platform_ok else "Both Twitch and Kick need fresh succeeded live API evidence.",
            "/api/platforms",
        ),
        feature(
            "Campaign research gate",
            "green" if gate_ok else "red",
            (
                f"{gate.get('visible_campaign_count', evidence_count['count'])} visible campaigns; "
                f"{gate.get('selected_feeder_count', selected_routes['count'])} verified source routes; "
                f"{evidence_count['count']} stored evidence rows"
            ),
            gate.get("blocker", "Campaign gate is not qualified"),
            "/api/campaign-gate",
        ),
        feature(
            "Campaign review source media",
            "green" if source_media_ok else ("yellow" if source_counts["source_media_verified"] else "red"),
            (
                f"{source_counts['candidates']} candidates; {source_counts['source_media_verified']} local media verified; "
                f"{source_counts['metadata_only']} indexed metadata-only not promoted; {source_counts['transcript_timed']} timed transcripts"
            ),
            "" if source_media_ok else "Each active campaign needs enough source-backed, word-timed rendered kits; metadata-only indexed candidates do not count until promoted.",
            "/api/clips",
        ),
        feature(
            "Campaign review render proof",
            "green" if production_render_ok else ("yellow" if non_demo_yellow_count else "red"),
            (
                f"{len(non_demo_kits)} campaign review kit(s); "
                f"{non_demo_green_count} green final proof; {non_demo_yellow_count} yellow final proof; "
                f"{non_demo_red_count} red; {ignored_study_count} ignored style study"
            ),
            "" if production_render_ok else (latest_kit_blockers[0] if latest_kit_blockers else "No campaign_short_final_v1 kit with source media, word timings, campaign rules, and green critique."),
            "/api/review-kits",
        ),
        feature(
            "Campaign review batch",
            str(review_batch["status"]),
            (
                f"{review_batch['approved_total']}/{review_batch['target_total']} approved; "
                f"{review_batch['rendered_total']} validated rendered kit(s); "
                f"{len(review_batch.get('excluded_projects', []))} excluded no-source campaign(s)"
            ),
            "" if review_batch["ready"] else "; ".join(review_batch["blockers"][:3]),
            "/api/campaign-projects",
        ),
        feature(
            "Review approvals for final handoff",
            "green" if review_batch.get("approvals_ready") else "yellow",
            (
                f"{review_batch['approved_total']}/{review_batch['target_total']} approved; "
                f"{review_batch['rendered_total']} validated rendered kit(s)"
            ),
            "" if review_batch.get("approvals_ready") else "; ".join(review_batch.get("approval_blockers", [])[:3]),
            "/api/campaign-projects",
        ),
        feature(
            "Burned-in subtitle proof",
            "green" if burned_caption_ok else "red",
            burned_caption_detail,
            "" if burned_caption_ok else "Run script/verify_burned_in_captions.py after rendering; caption sidecars alone do not prove subtitles are visible in the video pixels.",
            str(burned_caption_path),
        ),
        feature(
            "GUI crash/control QA",
            "green" if gui_ok else "red",
            gui_detail,
            "" if gui_ok else "Run fresh desktop QA; it must include page clicks, controls, media frame proof, and zero new crashes.",
            str(gui_manifest_path),
        ),
        feature(
            "Security scan",
            "green" if security_ok else "red",
            security_detail,
            "" if security_ok else "Run a fresh security scan and clear every secret-like finding.",
            str(security_path),
        ),
        feature(
            "Backend LaunchAgent restart",
            "green" if launchagent_ok else "red",
            launchagent_detail,
            "" if launchagent_ok else "LaunchAgent must install, restart, and serve the expected API version without local fallback.",
            str(launchagent_path),
        ),
        feature(
            "Buddy no-key installer",
            "green" if no_key_ok else "red",
            no_key_detail,
            "" if no_key_ok else "Run no-key installer verification from isolated CLIPPING_OPS_HOME and prove missing credentials are blocked.",
            str(no_key_path),
        ),
        feature(
            "Codex source handoff package",
            "green" if handoff["ok"] else "red",
            str(handoff["detail"]),
            "" if handoff["ok"] else str(handoff["blocker"]),
            str(handoff["manifest_path"]),
        ),
        feature(
            "Prebuilt Mac app signing/notarization",
            "green" if release_ok else ("yellow" if release_payload.get("bundle_ok") else "red"),
            release_detail,
            "" if release_ok else "Only required for handing someone a prebuilt .app. Codex source handoff can be green without Developer ID notarization.",
            str(release_path),
        ),
        feature(
            "Product proof artifacts",
            "green" if product_ok else "red",
            f"artifact_summary={product_path}; fresh={product_fresh['fresh']} age_hours={product_fresh['age_hours']}",
            "" if product_ok else "Regenerate CEO report, QA matrix, deck notes, architecture, and artifact index from fresh data.",
            str(product_path),
        ),
        feature(
            "Human approval only",
            "green",
            "Autopublish/payout/account changes are hard-blocked in backend routes.",
            "",
            "/api/health",
        ),
    ]

    feature_map = {item["name"]: item["status"] for item in features}
    internal_required = [
        "Local backend source of truth",
        "Hermes-native orchestration",
        "Platform API production smoke",
        "Campaign research gate",
        "Campaign review source media",
        "Campaign review render proof",
        "Campaign review batch",
        "Burned-in subtitle proof",
        "GUI crash/control QA",
        "Security scan",
        "Human approval only",
    ]
    buddy_required = ["Buddy no-key installer", "Security scan", "Human approval only"]
    codex_handoff_required = [
        "Local backend source of truth",
        "Buddy no-key installer",
        "Codex source handoff package",
        "Security scan",
        "Human approval only",
    ]
    customer_required = [item["name"] for item in features]

    def milestone(required: List[str]) -> Dict[str, Any]:
        statuses = [feature_map.get(name, "red") for name in required]
        blockers = [name for name in required if feature_map.get(name) != "green"]
        status = "green" if not blockers else ("yellow" if all(value != "red" for value in statuses) else "red")
        return {"status": status, "ready": status == "green", "blockers": blockers}

    milestones = {
        "internal_local_ready": milestone(internal_required),
        "buddy_no_key_ready": milestone(buddy_required),
        "codex_handoff_ready": milestone(codex_handoff_required),
        "customer_ship_ready": milestone(customer_required),
    }
    overall = "green" if milestones["internal_local_ready"]["ready"] and milestones["codex_handoff_ready"]["ready"] else "red"
    return {
        "generated_at": utc_now(),
        "overall": overall,
        "fresh_evidence_hours": FRESH_EVIDENCE_HOURS,
        "milestones": milestones,
        "features": features,
    }


def latest_campaign_gate() -> Dict[str, Any]:
    gate = one("SELECT * FROM campaign_gate_runs ORDER BY started_at DESC LIMIT 1")
    if gate:
        return gate
    return {
        "id": "missing",
        "status": "blocked",
        "started_at": "",
        "finished_at": "",
        "visible_campaign_count": 0,
        "selected_feeder_count": 0,
        "blocker": "Campaign gate has not been initialized.",
        "notes": "",
    }
