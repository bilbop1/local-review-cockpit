from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


APP_NAME = "ClippingOpsCockpit"
FRESH_EVIDENCE_HOURS = 24
SELECTED_FEEDER_FLAGS = ("selected_feeder_lacy", "selected_feeder_yourrage", "selected_feeder_yourragegaming")
FINAL_PROOF_PROFILE = "selected_feeder_final_v1"
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
  source_platform TEXT NOT NULL,
  source_url TEXT NOT NULL,
  creator_id TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL,
  duration REAL NOT NULL DEFAULT 0,
  view_count INTEGER NOT NULL DEFAULT 0,
  clip_created_at TEXT NOT NULL DEFAULT '',
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
              (id, source_platform, source_url, title, duration, media_url, local_media_path, provenance, risk_flags_json, discovered_at)
            VALUES (?, 'local', ?, ?, ?, ?, ?, ?, ?, ?)
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
    existing = one("SELECT * FROM clip_candidates WHERE source_url = ?", (source_url,))
    clip_id = str(existing["id"]) if existing else new_id("clip")
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
    if local_media_path and Path(local_media_path).exists():
        risk_flags = [flag for flag in risk_flags if flag != "metadata_only_no_download"]
        for flag in ["local_media_downloaded", "source_media_verified_local"]:
            if flag not in risk_flags:
                risk_flags.append(flag)
    params = (
        clip_id,
        str(payload.get("source_platform", "")).strip().lower() or "unknown",
        source_url,
        str(payload.get("creator_id", "")),
        title,
        float(payload.get("duration", 0) or 0),
        int(payload.get("view_count", 0) or 0),
        clip_created_at,
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
              (id, source_platform, source_url, creator_id, title, duration, view_count, clip_created_at, media_url, local_media_path, provenance, risk_flags_json, discovered_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title,
              duration=excluded.duration,
              view_count=excluded.view_count,
              clip_created_at=excluded.clip_created_at,
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
    for flag in extra_risk_flags or []:
        if flag not in risk_flags:
            risk_flags.append(flag)
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
) -> str:
    existing = one(
        "SELECT id FROM render_nominations WHERE clip_candidate_ids_json = ? ORDER BY created_at DESC LIMIT 1",
        (json.dumps([clip_id]),),
    )
    nomination_id = new_id("nom")
    is_demo_nomination = target_style == "tiktok_demo_bold_caption" or status == "rendered_demo"
    edit_plan = {
        "opening_hook": "LOCAL DEMO KIT" if is_demo_nomination else "Clean streamer moment with source evidence",
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
            else "Selected-feeder source with stored campaign route and rules. Publishing approval remains separate."
        ),
        "why_this_can_hit": reason,
        "rejected_near_misses": "Off-target/demo clips are excluded from the visible cockpit surface.",
    }
    if existing:
        existing_id = str(existing["id"])
        execute(
            """
            UPDATE render_nominations
            SET score_reason=?, edit_plan_json=?, target_style=?, status=?
            WHERE id=?
            """,
            (reason, json.dumps(edit_plan), target_style, status, existing_id),
        )
        return existing_id
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO render_nominations
              (id, clip_candidate_ids_json, nomination_type, score_reason, edit_plan_json, target_style, status, created_at)
            VALUES (?, ?, 'single', ?, ?, ?, ?, ?)
            """,
            (nomination_id, json.dumps([clip_id]), reason, json.dumps(edit_plan), target_style, status, utc_now()),
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
) -> str:
    existing = one("SELECT id FROM render_kits WHERE review_video_path = ?", (str(review_video),))
    if existing:
        return str(existing["id"])
    kit_id = new_id("kit")
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO render_kits
              (id, nomination_id, title, review_video_path, caption_path, transcript_path, checklist_path, source_path, risk_path, review_status, is_demo, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'needs_review', ?, ?)
            """,
            (
                kit_id,
                nomination_id,
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


def create_job(name: str, kind: str, status: str, stage: str, progress: int, logs: str = "", output_path: str = "", error: str = "") -> str:
    job_id = new_id("job")
    finished = utc_now() if status in {"succeeded", "failed", "blocked"} else ""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO job_runs
              (id, name, kind, status, stage, progress, logs, output_path, error, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_id, name, kind, status, stage, progress, logs, output_path, error, utc_now(), finished),
        )
    return job_id


def visible_clip_candidates() -> List[Dict[str, Any]]:
    return [
        item
        for item in rows("SELECT * FROM clip_candidates ORDER BY view_count DESC, discovered_at DESC")
        if is_relevant_streamer_clip(item)
    ]


def visible_render_nominations() -> List[Dict[str, Any]]:
    visible_clip_ids = {str(item["id"]) for item in visible_clip_candidates()}
    visible: List[Dict[str, Any]] = []
    for item in rows("SELECT * FROM render_nominations ORDER BY created_at DESC"):
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
        if production_feeder_kit_status(item).get("classification") != "green":
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
    clip_ids = _clip_ids_for_nomination(nomination)
    clip = one("SELECT * FROM clip_candidates WHERE id = ?", (clip_ids[0],)) if clip_ids else None
    if clip:
        enriched["clip_id"] = str(clip.get("id", ""))
        enriched["clip_source_url"] = str(clip.get("source_url", ""))
        enriched["clip_source_platform"] = str(clip.get("source_platform", ""))
        enriched["clip_created_at"] = str(clip.get("clip_created_at", ""))
        enriched["clip_discovered_at"] = str(clip.get("discovered_at", ""))
        enriched["clip_view_count"] = int(clip.get("view_count", 0) or 0)
        enriched["clip_duration"] = float(clip.get("duration", 0) or 0)
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
        visible.append(item)
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
    for flag in flags:
        if flag.startswith("selected_feeder_"):
            candidate_slugs.append(flag.removeprefix("selected_feeder_"))
    for token in ("lacy", "yourrage", "yourragegaming"):
        if token in source_url or token in source_text.lower():
            candidate_slugs.append(token)
    normalized = []
    for slug in candidate_slugs:
        alias = "yourrage" if slug == "yourragegaming" else slug
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
    if normalized_hook in WEAK_RENDERED_HOOKS or len(hook_words) < 3:
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

    blockers: List[str] = []
    if profile != FINAL_PROOF_PROFILE or target_style != FINAL_PROOF_PROFILE:
        blockers.append("kit is not rendered with selected_feeder_final_v1")
    if not video_path.exists():
        blockers.append("review.mp4 missing")
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
    for clip_id in clip_ids:
        clip = one("SELECT * FROM clip_candidates WHERE id = ?", (clip_id,))
        if not clip:
            blockers.append(f"{clip_id}: clip candidate missing")
            continue
        checked_clips.append(clip)
        if not is_relevant_streamer_clip(clip):
            blockers.append(f"{clip_id}: not a relevant selected-feeder Twitch/Kick clip")
        source_url = str(clip.get("source_url", "")).strip()
        if not source_url:
            blockers.append(f"{clip_id}: source URL missing")
        local_media = Path(str(clip.get("local_media_path", "")).strip()) if str(clip.get("local_media_path", "")).strip() else None
        if not local_media or not local_media.exists():
            blockers.append(f"{clip_id}: local source media missing")
        flags = _risk_flags(clip)
        if "source_media_verified_local" not in flags and "source_download_verified" not in flags:
            blockers.append(f"{clip_id}: local source media provenance flag missing")
        transcript = _latest_success_transcript(clip_id)
        if not _transcript_is_word_timed(transcript):
            blockers.append(f"{clip_id}: succeeded non-placeholder word-timed transcript missing")
        rules = _campaign_rules_for_clip(clip, source_text)
        if not rules:
            blockers.append(f"{clip_id}: stored campaign rules missing for selected feeder")
        if _is_lacy_clip(clip):
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
        blockers.append("source.md does not prove selected-feeder source media")

    classification = "green" if not blockers else ("yellow" if base_status.get("complete") and video_path.exists() else "red")
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
        is_metadata_only = "metadata_only_no_download" in flags
        if is_metadata_only:
            metadata_only += 1
        if local_path and local_path.exists():
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
        if not is_relevant_streamer_clip(item)
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
        and len(gui_manifest.get("controls", [])) >= 10
        and len(gui_manifest.get("media", [])) >= 2
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

    db_ok = database_path().exists()
    platform_ok = int(twitch_ok["count"]) > 0 and int(kick_ok["count"]) > 0
    gate_ok = gate.get("status") == "qualified"
    source_media_ok = (
        source_counts["source_media_verified"] > 0
        and source_counts["missing_media"] == 0
        and source_counts["transcript_timed"] == source_counts["source_media_verified"]
    )
    production_render_ok = non_demo_green_count > 0

    features = [
        feature(
            "Local backend source of truth",
            "green" if db_ok else "red",
            str(database_path()),
            "" if db_ok else "SQLite database missing",
            str(database_path()),
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
                f"{gate.get('selected_feeder_count', selected_routes['count'])} selected feeder source routes; "
                f"{evidence_count['count']} stored evidence rows"
            ),
            gate.get("blocker", "Campaign gate is not qualified"),
            "/api/campaign-gate",
        ),
        feature(
            "Selected feeder source media",
            "green" if source_media_ok else ("yellow" if source_counts["source_media_verified"] else "red"),
            (
                f"{source_counts['candidates']} candidates; {source_counts['source_media_verified']} local media verified; "
                f"{source_counts['metadata_only']} indexed metadata-only not promoted; {source_counts['transcript_timed']} timed transcripts"
            ),
            "" if source_media_ok else "At least one promoted feeder clip needs validated local media and a word-timed transcript before production proof can be green.",
            "/api/clips",
        ),
        feature(
            "Production feeder render proof",
            "green" if production_render_ok else ("yellow" if non_demo_yellow_count else "red"),
            (
                f"{len(non_demo_kits)} selected-feeder review kit(s); "
                f"{non_demo_green_count} green final proof; {non_demo_yellow_count} yellow final proof; "
                f"{non_demo_red_count} red; {ignored_study_count} ignored style study"
            ),
            "" if production_render_ok else (latest_kit_blockers[0] if latest_kit_blockers else "No selected_feeder_final_v1 kit with source media, word timings, campaign rules, and green critique."),
            "/api/review-kits",
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
            "Signed/notarized release package",
            "green" if release_ok else ("yellow" if release_payload.get("bundle_ok") else "red"),
            release_detail,
            "" if release_ok else "Customer ship requires a signed, hardened, notarized release artifact; ad-hoc signing is not enough.",
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
        "Platform API production smoke",
        "Campaign research gate",
        "Selected feeder source media",
        "Production feeder render proof",
        "Burned-in subtitle proof",
        "GUI crash/control QA",
        "Security scan",
        "Human approval only",
    ]
    buddy_required = ["Buddy no-key installer", "Security scan", "Human approval only"]
    customer_required = [item["name"] for item in features]

    def milestone(required: List[str]) -> Dict[str, Any]:
        statuses = [feature_map.get(name, "red") for name in required]
        blockers = [name for name in required if feature_map.get(name) != "green"]
        status = "green" if not blockers else ("yellow" if all(value != "red" for value in statuses) else "red")
        return {"status": status, "ready": status == "green", "blockers": blockers}

    milestones = {
        "internal_local_ready": milestone(internal_required),
        "buddy_no_key_ready": milestone(buddy_required),
        "customer_ship_ready": milestone(customer_required),
    }
    overall = "green" if milestones["customer_ship_ready"]["ready"] else "red"
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
