from __future__ import annotations

import json
import mimetypes
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import credentials
from . import database as db
from .renderer import validate_video


UPLOADPOST_PROVIDER = "uploadpost"
UPLOADPOST_BASE_URL = "https://api.upload-post.com/api"
SUPPORTED_PLATFORMS = ("tiktok", "instagram", "youtube")
PUBLISH_MODES = ("dry_run", "live")
AUTO_PUBLISH_SLOT_HOURS = (0, 3, 6, 9, 12, 15, 18, 21)
AUTO_PUBLISH_SLOT_MINUTE = 14
SCHEDULED_PUBLISH_TERMINAL_STATUSES = {"cancelled", "failed"}


class PublishError(ValueError):
    def __init__(self, code: str, detail: str, status: str = "blocked") -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


def _json_loads(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except json.JSONDecodeError:
        return fallback


def _setting(key: str, default: str = "") -> str:
    item = db.one("SELECT value FROM system_settings WHERE key = ?", (key,))
    if item:
        return str(item.get("value", ""))
    return default


def _set_setting(key: str, value: str) -> None:
    db.execute(
        """
        INSERT INTO system_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (key, value, db.utc_now()),
    )


def _bool_setting(key: str, env_name: str = "", default: bool = False) -> bool:
    if env_name and os.environ.get(env_name, "").strip().lower() in {"1", "true", "yes", "y"}:
        return True
    raw = _setting(key, "true" if default else "false").strip().lower()
    return raw in {"1", "true", "yes", "y"}


def uploadpost_api_key() -> str:
    if credentials.no_key_mode():
        return ""
    return (
        os.environ.get("UPLOAD_POST_API_KEY", "").strip()
        or os.environ.get("UPLOADPOST_API_KEY", "").strip()
        or credentials.read_secret("uploadpost.api_key")
    )


def uploadpost_user() -> str:
    return (
        os.environ.get("UPLOAD_POST_USER", "").strip()
        or _setting("publish.uploadpost.user", "local-operator").strip()
        or "local-operator"
    )


def uploadpost_mode() -> str:
    mode = _setting("publish.uploadpost.mode", "dry_run").strip().lower()
    return mode if mode in PUBLISH_MODES else "dry_run"


def uploadpost_warmup_complete() -> bool:
    return _bool_setting("publish.uploadpost.warmup_complete", "CLIPPING_OPS_UPLOADPOST_WARMUP_COMPLETE")


def set_publish_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    if "warmup_complete" in payload:
        _set_setting("publish.uploadpost.warmup_complete", "true" if bool(payload.get("warmup_complete")) else "false")
    if "mode" in payload:
        mode = str(payload.get("mode", "dry_run")).strip().lower()
        if mode not in PUBLISH_MODES:
            raise PublishError("invalid_mode", "Publish mode must be dry_run or live.")
        _set_setting("publish.uploadpost.mode", mode)
    if "user" in payload:
        user = str(payload.get("user", "")).strip() or "local-operator"
        _set_setting("publish.uploadpost.user", user)
    db.log_audit("operator", "update_publish_settings", "publish_settings", UPLOADPOST_PROVIDER, "stored", "api")
    return publish_status()


def publish_status() -> Dict[str, Any]:
    db.init_db()
    key_present = bool(uploadpost_api_key())
    warmup = uploadpost_warmup_complete()
    mode = uploadpost_mode()
    blockers: List[str] = []
    if not key_present:
        blockers.append("Upload-Post API key missing.")
    if not warmup:
        blockers.append("Account warm-up is not marked complete.")
    if mode != "live":
        blockers.append("Provider mode is dry-run.")
    return {
        "status": "green" if key_present and warmup and mode == "live" else "yellow",
        "supported_platforms": list(SUPPORTED_PLATFORMS),
        "default_platforms": list(SUPPORTED_PLATFORMS),
        "auto_schedule": {
            "auto_slot_on_approve": True,
            "mode": "dry_run",
            "slots_per_day": len(AUTO_PUBLISH_SLOT_HOURS),
            "slot_minute": AUTO_PUBLISH_SLOT_MINUTE,
            "slot_hours": list(AUTO_PUBLISH_SLOT_HOURS),
            "cadence_hours": 3,
            "timezone": datetime.now().astimezone().tzname(),
        },
        "provider": {
            "name": UPLOADPOST_PROVIDER,
            "mode": mode,
            "base_url": UPLOADPOST_BASE_URL,
            "api_key": "configured" if key_present else "missing",
            "warmup_complete": warmup,
            "user": uploadpost_user(),
            "live_ready": key_present and warmup and mode == "live",
            "blockers": blockers,
        },
        "latest_jobs": visible_publish_jobs(20),
        "notes": [
            "Approval auto-slots a scheduled dry-run publish job into the next future :14 slot.",
            "Dry-run validates approved review kits without uploading.",
            "Live posting requires approved kit, Upload-Post key, completed warm-up, live mode, and final confirmation.",
        ],
    }


def normalize_platforms(platforms: Iterable[Any]) -> List[str]:
    normalized: List[str] = []
    for value in platforms:
        platform = str(value).strip().lower()
        if not platform:
            continue
        if platform not in SUPPORTED_PLATFORMS:
            raise PublishError("invalid_platform", f"Unsupported publish platform: {platform}")
        if platform not in normalized:
            normalized.append(platform)
    if not normalized:
        raise PublishError("missing_platform", "At least one publish platform is required.")
    return normalized


def _read_text(path_value: Any) -> str:
    try:
        path = Path(str(path_value))
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _caption_metadata(kit: Dict[str, Any]) -> Dict[str, Any]:
    caption_text = _read_text(kit.get("caption_path", ""))
    title = str(kit.get("title", "Untitled clip")).strip() or "Untitled clip"
    suggested = ""
    hook = ""
    for line in caption_text.splitlines():
        clean = line.strip()
        if clean.lower().startswith("hook card:"):
            hook = clean.split(":", 1)[1].strip()
        elif clean.lower().startswith("suggested post caption:"):
            suggested = clean.split(":", 1)[1].strip()
    if hook:
        title = hook
    caption = suggested or hook or title
    hashtags = re.findall(r"#[A-Za-z0-9_]+", caption_text)
    return {
        "title": title[:180],
        "caption": caption.strip(),
        "hashtags": sorted(set(hashtags), key=hashtags.index),
        "raw_caption_text": caption_text,
    }


def _publish_kit_blockers(kit: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if not kit:
        return ["Review kit is missing."]
    if int(kit.get("is_demo", 0) or 0) == 1:
        blockers.append("Demo kits cannot be published.")
    if str(kit.get("review_status", "")) != "approved_manual_prep":
        blockers.append("Review kit must be approved for prep before publishing.")
    video_path = Path(str(kit.get("review_video_path", "")))
    if not video_path.exists():
        blockers.append("Rendered review video is missing.")
    else:
        try:
            metadata = validate_video(video_path)
            streams = metadata.get("streams", [])
            video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
            if video.get("codec_name") != "h264" or int(video.get("width", 0)) != 1080 or int(video.get("height", 0)) != 1920:
                blockers.append("Rendered video must be H.264 1080x1920.")
            if audio.get("codec_name") != "aac":
                blockers.append("Rendered video must include AAC audio.")
        except Exception as exc:
            blockers.append(f"ffprobe validation failed: {exc}")
    metadata = _caption_metadata(kit)
    if not metadata["caption"]:
        blockers.append("Publish caption is missing.")
    for sidecar in ("caption_path", "source_path", "risk_path"):
        if not Path(str(kit.get(sidecar, ""))).exists():
            blockers.append(f"Required sidecar missing: {sidecar}.")
    return blockers


def _package_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["platforms"] = _json_loads(item.get("platforms_json"), [])
    item["hashtags"] = _json_loads(item.get("hashtags_json"), [])
    item["checklist"] = _json_loads(item.get("checklist_json"), [])
    item.pop("platforms_json", None)
    item.pop("hashtags_json", None)
    item.pop("checklist_json", None)
    return item


def _job_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(row)
    item["platforms"] = _json_loads(item.get("platforms_json"), [])
    item["provider_response"] = _json_loads(item.get("provider_response_json"), {})
    item["post_urls"] = _json_loads(item.get("post_urls_json"), {})
    item["final_confirmed"] = bool(int(item.get("final_confirmed", 0) or 0))
    item.pop("platforms_json", None)
    item.pop("provider_response_json", None)
    item.pop("post_urls_json", None)
    return item


def _local_now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        return datetime.now().astimezone().replace(microsecond=0)
    current = now.replace(microsecond=0)
    if current.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        return current.replace(tzinfo=local_tz)
    return current.astimezone()


def _parse_time(value: Any, *, fallback_tz: Optional[timezone] = None) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=fallback_tz or datetime.now().astimezone().tzinfo)
    return parsed


def _slot_after(moment: datetime) -> datetime:
    current = _local_now(moment)
    base = current.replace(second=0, microsecond=0)
    for day_offset in range(0, 370):
        day = base.date() + timedelta(days=day_offset)
        for hour in AUTO_PUBLISH_SLOT_HOURS:
            candidate = datetime.combine(day, datetime.min.time(), tzinfo=base.tzinfo).replace(
                hour=hour,
                minute=AUTO_PUBLISH_SLOT_MINUTE,
            )
            if candidate > current:
                return candidate
    raise PublishError("slot_allocator_failed", "Could not find a future publish slot.")


def _future_slots(count: int, now: Optional[datetime] = None) -> List[datetime]:
    slots: List[datetime] = []
    cursor = _local_now(now)
    for _ in range(count):
        cursor = _slot_after(cursor)
        slots.append(cursor)
    return slots


def _pending_publish_jobs_for_rebalance(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    current = _local_now(now)
    records: List[Dict[str, Any]] = []
    for row in db.rows(
        """
        SELECT p.*, r.campaign_slug
        FROM publish_jobs p
        JOIN render_kits r ON r.id = p.kit_id
        WHERE p.mode='dry_run'
          AND p.status='scheduled'
          AND p.scheduled_at != ''
        ORDER BY p.scheduled_at ASC, p.created_at ASC
        """
    ):
        scheduled_at = _parse_time(row.get("scheduled_at"), fallback_tz=current.tzinfo)
        if scheduled_at and scheduled_at > current:
            item = dict(row)
            item["_scheduled_dt"] = scheduled_at
            records.append(item)
    return records


def _balanced_publish_order(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_slug: Dict[str, List[Dict[str, Any]]] = {}
    slug_order: Dict[str, int] = {}
    for index, record in enumerate(records):
        slug = str(record.get("campaign_slug") or record.get("kit_id") or "")
        by_slug.setdefault(slug, []).append(record)
        slug_order.setdefault(slug, index)

    ordered: List[Dict[str, Any]] = []
    previous_slug = ""
    while by_slug:
        candidates = [slug for slug in by_slug if slug != previous_slug] or list(by_slug)
        selected = max(candidates, key=lambda slug: (len(by_slug[slug]), -slug_order[slug]))
        ordered.append(by_slug[selected].pop(0))
        previous_slug = selected
        if not by_slug[selected]:
            by_slug.pop(selected, None)
    return ordered


def rebalance_publish_schedule(now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    records = _pending_publish_jobs_for_rebalance(now=now)
    if not records:
        return []
    slots = _future_slots(len(records), now=now)
    ordered = _balanced_publish_order(records)
    now_text = db.utc_now()
    for record, slot in zip(ordered, slots):
        slot_text = slot.isoformat(timespec="seconds")
        if str(record.get("scheduled_at", "")) != slot_text:
            db.execute("UPDATE publish_jobs SET scheduled_at=?, updated_at=? WHERE id=?", (slot_text, now_text, record["id"]))
    return [get_publish_job(str(record["id"])) for record in ordered]


def _existing_publish_job_for_kit(kit_id: str) -> Dict[str, Any] | None:
    row = db.one(
        """
        SELECT *
        FROM publish_jobs
        WHERE kit_id = ?
          AND status NOT IN ('cancelled', 'failed')
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (kit_id,),
    )
    return _job_from_row(row) if row else None


def create_publish_package(
    kit_id: str,
    *,
    platforms: Iterable[Any] = SUPPORTED_PLATFORMS,
    title: str = "",
    caption: str = "",
) -> Dict[str, Any]:
    db.init_db()
    kit = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
    if not kit:
        raise PublishError("missing_kit", "Review kit not found.", status="missing")
    normalized_platforms = normalize_platforms(platforms)
    blockers = _publish_kit_blockers(kit)
    if blockers:
        raise PublishError("publish_prep_blocked", "; ".join(blockers))
    metadata = _caption_metadata(kit)
    final_title = title.strip() or metadata["title"]
    final_caption = caption.strip() or metadata["caption"]
    hashtags = re.findall(r"#[A-Za-z0-9_]+", final_caption) or metadata["hashtags"]
    package_id = str((db.one("SELECT id FROM publish_packages WHERE kit_id = ?", (kit_id,)) or {}).get("id") or db.new_id("pubpkg"))
    now = db.utc_now()
    existing = db.one("SELECT id FROM publish_packages WHERE kit_id = ?", (kit_id,))
    created_at = str((existing or {}).get("created_at") or now)
    checklist = [
        "approved_review_kit",
        "valid_1080x1920_h264_aac",
        "caption_present",
        "sidecars_present",
        "no_live_post_without_confirmation",
    ]
    db.execute(
        """
        INSERT INTO publish_packages
          (id, kit_id, provider, platforms_json, title, caption, hashtags_json, video_path, status, checklist_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, ?)
        ON CONFLICT(kit_id) DO UPDATE SET
          provider=excluded.provider,
          platforms_json=excluded.platforms_json,
          title=excluded.title,
          caption=excluded.caption,
          hashtags_json=excluded.hashtags_json,
          video_path=excluded.video_path,
          status='ready',
          checklist_json=excluded.checklist_json,
          updated_at=excluded.updated_at
        """,
        (
            package_id,
            kit_id,
            UPLOADPOST_PROVIDER,
            json.dumps(normalized_platforms),
            final_title,
            final_caption,
            json.dumps(hashtags),
            str(kit.get("review_video_path", "")),
            json.dumps(checklist),
            created_at,
            now,
        ),
    )
    db.log_audit("user", "prepare_publish_package", "render_kit", kit_id, "ready", UPLOADPOST_PROVIDER)
    return get_publish_package(package_id)


def get_publish_package(package_id: str) -> Dict[str, Any]:
    row = db.one("SELECT * FROM publish_packages WHERE id = ?", (package_id,))
    if not row:
        raise PublishError("missing_package", "Publish package not found.", status="missing")
    return _package_from_row(row)


def _package_for_job(package_id: str) -> Dict[str, Any]:
    package = get_publish_package(package_id)
    kit = db.one("SELECT * FROM render_kits WHERE id = ?", (package["kit_id"],))
    if not kit:
        raise PublishError("missing_kit", "Review kit for publish package is missing.")
    blockers = _publish_kit_blockers(kit)
    if blockers:
        raise PublishError("publish_package_invalid", "; ".join(blockers))
    return package


def create_publish_job(payload: Dict[str, Any]) -> Dict[str, Any]:
    db.init_db()
    mode = str(payload.get("mode", "dry_run")).strip().lower()
    if mode not in PUBLISH_MODES:
        raise PublishError("invalid_mode", "Publish mode must be dry_run or live.")
    provider = str(payload.get("provider", UPLOADPOST_PROVIDER)).strip().lower() or UPLOADPOST_PROVIDER
    if provider != UPLOADPOST_PROVIDER:
        raise PublishError("invalid_provider", "Upload-Post is the only configured publish provider.")
    package_id = str(payload.get("package_id", "")).strip()
    if not package_id:
        kit_id = str(payload.get("kit_id", "")).strip()
        package = create_publish_package(
            kit_id,
            platforms=payload.get("platforms") if isinstance(payload.get("platforms"), list) else SUPPORTED_PLATFORMS,
            title=str(payload.get("title", "")),
            caption=str(payload.get("caption", "")),
        )
    else:
        package = _package_for_job(package_id)
    platforms = normalize_platforms(payload.get("platforms") if isinstance(payload.get("platforms"), list) else package["platforms"])
    title = str(payload.get("title", "")).strip() or str(package["title"])
    caption = str(payload.get("caption", "")).strip() or str(package["caption"])
    scheduled_at = str(payload.get("scheduled_at", "")).strip()
    defer_until_due = bool(payload.get("defer_hermes_until_due")) and mode == "dry_run" and bool(scheduled_at)
    job_id = db.new_id("pubjob")
    now = db.utc_now()
    status = "scheduled" if defer_until_due else ("queued" if mode == "dry_run" else "awaiting_confirmation")
    stage = "waiting-for-slot" if defer_until_due else ("queued-for-hermes" if mode == "dry_run" else "awaiting-final-confirmation")
    db.execute(
        """
        INSERT INTO publish_jobs
          (id, package_id, kit_id, provider, mode, platforms_json, title, caption, scheduled_at, status, stage, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_id,
            package["id"],
            package["kit_id"],
            provider,
            mode,
            json.dumps(platforms),
            title,
            caption,
            scheduled_at,
            status,
            stage,
            now,
            now,
        ),
    )
    hermes_intent = "publish_dry_run" if mode == "dry_run" and not defer_until_due else ""
    if hermes_intent:
        hermes_job = db.create_job_intent(
            hermes_intent,
            {"publish_job_id": job_id, "package_id": package["id"], "mode": mode},
            requested_by=str(payload.get("requested_by", "gui")),
            force_new=True,
        )
        db.execute("UPDATE publish_jobs SET hermes_job_id=?, updated_at=? WHERE id=?", (hermes_job["id"], db.utc_now(), job_id))
    db.log_audit("user", "queue_publish_job", "publish_job", job_id, status, f"{provider}:{mode}")
    return get_publish_job(job_id)


def schedule_approved_kit(
    kit_id: str,
    *,
    now: Optional[datetime] = None,
    requested_by: str = "approval-auto-slot",
    platforms: Iterable[Any] = SUPPORTED_PLATFORMS,
) -> Dict[str, Any]:
    db.init_db()
    existing_job = _existing_publish_job_for_kit(kit_id)
    package = create_publish_package(kit_id, platforms=platforms)
    if existing_job:
        return {
            "status": existing_job.get("status", "scheduled"),
            "publish_package": package,
            "publish_job": existing_job,
            "deduped": True,
        }

    first_slot = _future_slots(1, now=now)[0].isoformat(timespec="seconds")
    job = create_publish_job(
        {
            "package_id": package["id"],
            "mode": "dry_run",
            "platforms": list(platforms),
            "scheduled_at": first_slot,
            "requested_by": requested_by,
            "defer_hermes_until_due": True,
        }
    )
    rebalanced = rebalance_publish_schedule(now=now)
    updated = next((item for item in rebalanced if item["id"] == job["id"]), get_publish_job(job["id"]))
    db.log_audit(requested_by, "auto_slot_publish_job", "render_kit", kit_id, updated["scheduled_at"], "approval")
    return {
        "status": "scheduled",
        "publish_package": package,
        "publish_job": updated,
        "deduped": False,
    }


def schedule_approved_backlog(
    *,
    now: Optional[datetime] = None,
    requested_by: str = "publish-scheduler",
    limit: int = 48,
) -> Dict[str, Any]:
    db.init_db()
    scheduled_kit_ids: List[str] = []
    blocked: List[Dict[str, Any]] = []
    candidates = db.rows(
        """
        SELECT *
        FROM render_kits r
        WHERE r.review_status='approved_manual_prep'
          AND r.is_demo=0
          AND NOT EXISTS (
            SELECT 1
            FROM publish_jobs p
            WHERE p.kit_id = r.id
              AND p.status NOT IN ('cancelled', 'failed')
          )
        ORDER BY r.approved_at ASC, r.created_at ASC
        LIMIT ?
        """,
        (max(1, min(limit, 250)),),
    )
    for kit in candidates:
        kit_id = str(kit.get("id", ""))
        try:
            schedule_approved_kit(kit_id, now=now, requested_by=requested_by)
            scheduled_kit_ids.append(kit_id)
        except PublishError as exc:
            blocked.append({"kit_id": kit_id, "error": exc.detail, "code": exc.code})
            db.log_audit(requested_by, "auto_slot_backlog_failed", "render_kit", kit_id, exc.code, exc.detail[:800])
    if scheduled_kit_ids:
        rebalance_publish_schedule(now=now)
    scheduled = [
        job
        for kit_id in scheduled_kit_ids
        for job in [_existing_publish_job_for_kit(kit_id)]
        if job
    ]
    return {"scheduled": scheduled, "blocked": blocked}


def get_publish_job(job_id: str) -> Dict[str, Any]:
    row = db.one("SELECT * FROM publish_jobs WHERE id = ?", (job_id,))
    if not row:
        raise PublishError("missing_publish_job", "Publish job not found.", status="missing")
    return _job_from_row(row)


def visible_publish_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    return [
        _job_from_row(row)
        for row in db.rows("SELECT * FROM publish_jobs ORDER BY created_at DESC LIMIT ?", (max(1, min(limit, 250)),))
    ]


def cancel_publish_job(job_id: str, actor: str = "operator") -> Dict[str, Any]:
    job = get_publish_job(job_id)
    if job["status"] in {"posted", "failed", "cancelled", "dry_run_succeeded"}:
        return job
    db.execute(
        """
        UPDATE publish_jobs
        SET status='cancelled', stage='cancelled', error='cancelled by operator', updated_at=?
        WHERE id=?
        """,
        (db.utc_now(), job_id),
    )
    db.log_audit(actor, "cancel_publish_job", "publish_job", job_id, "cancelled", "")
    return get_publish_job(job_id)


def publish_schedule_tick(now: Optional[datetime] = None, requested_by: str = "publish-scheduler") -> Dict[str, Any]:
    db.init_db()
    current = _local_now(now)
    backlog = schedule_approved_backlog(now=current, requested_by=requested_by)
    queued: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    due_rows: List[Dict[str, Any]] = []
    next_scheduled_at = ""
    for row in db.rows(
        """
        SELECT *
        FROM publish_jobs
        WHERE mode='dry_run'
          AND status='scheduled'
          AND scheduled_at != ''
        ORDER BY scheduled_at ASC
        """
    ):
        scheduled_at = _parse_time(row.get("scheduled_at"), fallback_tz=current.tzinfo)
        if not scheduled_at:
            continue
        if scheduled_at <= current:
            due_rows.append(row)
        elif not next_scheduled_at:
            next_scheduled_at = scheduled_at.isoformat(timespec="seconds")

    for row in due_rows:
        job_id = str(row["id"])
        try:
            package = _package_for_job(str(row["package_id"]))
        except PublishError as exc:
            db.execute(
                """
                UPDATE publish_jobs
                SET status='blocked', stage='blocked', error=?, updated_at=?
                WHERE id=?
                """,
                (exc.detail[:1200], db.utc_now(), job_id),
            )
            blocked.append({"publish_job_id": job_id, "error": exc.detail})
            continue
        hermes_job = db.create_job_intent(
            "publish_dry_run",
            {
                "publish_job_id": job_id,
                "package_id": package["id"],
                "mode": "dry_run",
                "scheduled_at": str(row.get("scheduled_at", "")),
            },
            requested_by=requested_by,
            force_new=True,
        )
        db.execute(
            """
            UPDATE publish_jobs
            SET status='queued', stage='queued-for-hermes', hermes_job_id=?, updated_at=?
            WHERE id=?
            """,
            (hermes_job["id"], db.utc_now(), job_id),
        )
        queued.append(hermes_job)

    all_blocked = [*backlog["blocked"], *blocked]
    status = "queued" if queued else ("scheduled" if backlog["scheduled"] else ("blocked" if all_blocked else "idle"))
    db.log_audit(
        requested_by,
        "publish_schedule_tick",
        "publish_jobs",
        current.isoformat(timespec="seconds"),
        status,
        json.dumps({"scheduled_backlog": len(backlog["scheduled"]), "queued": len(queued), "blocked": len(all_blocked)})[:800],
    )
    return {
        "status": status,
        "now": current.isoformat(timespec="seconds"),
        "scheduled_backlog": backlog["scheduled"],
        "queued": queued,
        "blocked": all_blocked,
        "next_scheduled_at": next_scheduled_at,
    }


def confirm_live_publish(job_id: str) -> Dict[str, Any]:
    job = get_publish_job(job_id)
    if job["mode"] != "live":
        raise PublishError("not_live_job", "Only live publish jobs need final confirmation.")
    if job["status"] == "cancelled":
        raise PublishError("cancelled_job", "Cancelled publish jobs cannot be confirmed.")
    _package_for_job(job["package_id"])
    status = publish_status()
    blockers = status["provider"]["blockers"]
    if blockers:
        raise PublishError("live_provider_blocked", "; ".join(blockers))
    hermes_job = db.create_job_intent(
        "publish_live",
        {"publish_job_id": job_id, "package_id": job["package_id"], "mode": "live"},
        requested_by="gui",
        force_new=True,
    )
    db.execute(
        """
        UPDATE publish_jobs
        SET final_confirmed=1, status='queued', stage='confirmed-for-hermes', hermes_job_id=?, updated_at=?
        WHERE id=?
        """,
        (hermes_job["id"], db.utc_now(), job_id),
    )
    db.log_audit("user", "confirm_live_publish", "publish_job", job_id, "queued", hermes_job["id"])
    return get_publish_job(job_id)


def _job_blockers(job: Dict[str, Any], package: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if job["status"] == "cancelled":
        blockers.append("Publish job was cancelled.")
    if job["mode"] == "dry_run" and job["status"] == "scheduled":
        scheduled_at = _parse_time(job.get("scheduled_at"))
        if scheduled_at and scheduled_at > _local_now():
            blockers.append(f"Publish job is scheduled for {scheduled_at.isoformat(timespec='seconds')}.")
    normalize_platforms(job["platforms"])
    if not str(job.get("caption", "")).strip():
        blockers.append("Publish caption is missing.")
    _package_for_job(package["id"])
    if job["mode"] == "live":
        provider = publish_status()["provider"]
        blockers.extend(provider["blockers"])
        if not job["final_confirmed"]:
            blockers.append("Final live-post confirmation is missing.")
    return blockers


def safe_uploadpost_request_summary(job: Dict[str, Any], package: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "method": "POST",
        "url": f"{UPLOADPOST_BASE_URL}/upload",
        "headers": {
            "Authorization": "Apikey <redacted>",
            "Idempotency-Key": job["id"],
        },
        "fields": {
            "user": uploadpost_user(),
            "platform[]": job["platforms"],
            "title": job["title"],
            "description": job["caption"],
            "video": package["video_path"],
        },
    }


def _multipart_body(fields: Dict[str, Any], file_field: str, file_path: Path) -> Tuple[bytes, str]:
    boundary = f"clippingops-{int(time.time() * 1000)}"
    chunks: List[bytes] = []
    for key, value in fields.items():
        values = value if isinstance(value, list) else [value]
        for item in values:
            chunks.append(f"--{boundary}\r\n".encode("utf-8"))
            chunks.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode("utf-8"))
            chunks.append(str(item).encode("utf-8"))
            chunks.append(b"\r\n")
    mime = mimetypes.guess_type(str(file_path))[0] or "video/mp4"
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode("utf-8")
    )
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _redacted_payload(value: Any) -> Any:
    text = json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
    text = re.sub(r"Apikey\s+[A-Za-z0-9._~+/=-]+", "Apikey <redacted>", text, flags=re.IGNORECASE)
    text = re.sub(r"(api[_-]?key|token|secret)[\"']?\s*[:=]\s*[\"'][^\"']+[\"']", r"\1: \"<redacted>\"", text, flags=re.IGNORECASE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:4000]


def _extract_post_urls(response: Dict[str, Any]) -> Dict[str, str]:
    urls: Dict[str, str] = {}
    results = response.get("results")
    if isinstance(results, dict):
        for platform, result in results.items():
            if isinstance(result, dict) and result.get("url"):
                urls[str(platform)] = str(result["url"])
    for key in ("url", "post_url"):
        if response.get(key):
            urls["default"] = str(response[key])
    return urls


def _send_uploadpost(job: Dict[str, Any], package: Dict[str, Any]) -> Dict[str, Any]:
    api_key = uploadpost_api_key()
    fields = {
        "user": uploadpost_user(),
        "platform[]": job["platforms"],
        "title": job["title"],
        "description": job["caption"],
    }
    body, content_type = _multipart_body(fields, "video", Path(str(package["video_path"])))
    request = urllib.request.Request(
        f"{UPLOADPOST_BASE_URL}/upload",
        data=body,
        headers={
            "Authorization": f"Apikey {api_key}",
            "Idempotency-Key": job["id"],
            "Content-Type": content_type,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        raw = response.read().decode("utf-8", errors="replace")
    try:
        payload: Dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        payload = {"raw": raw[:4000]}
    return payload


def execute_publish_job(job_id: str) -> Dict[str, Any]:
    job = get_publish_job(job_id)
    package = get_publish_package(job["package_id"])
    request_summary = safe_uploadpost_request_summary(job, package)
    try:
        blockers = _job_blockers(job, package)
    except PublishError as exc:
        blockers = [exc.detail]
    if blockers:
        error = "; ".join(blockers)
        db.execute(
            """
            UPDATE publish_jobs
            SET status='blocked', stage='blocked', error=?, provider_response_json=?, updated_at=?
            WHERE id=?
            """,
            (error[:1200], json.dumps({"request_summary": request_summary}), db.utc_now(), job_id),
        )
        db.log_audit("hermes-dispatcher", "block_publish_job", "publish_job", job_id, "blocked", error[:500])
        return {"status": "blocked", "blocker": error, "request_summary": request_summary}

    if job["mode"] == "dry_run":
        result = {
            "dry_run": True,
            "provider": UPLOADPOST_PROVIDER,
            "request_summary": request_summary,
            "key_present": bool(uploadpost_api_key()),
            "warmup_complete": uploadpost_warmup_complete(),
        }
        db.execute(
            """
            UPDATE publish_jobs
            SET status='dry_run_succeeded', stage='validated-no-upload', provider_response_json=?, error='', updated_at=?
            WHERE id=?
            """,
            (json.dumps(result), db.utc_now(), job_id),
        )
        db.log_audit("hermes-dispatcher", "publish_dry_run", "publish_job", job_id, "succeeded", UPLOADPOST_PROVIDER)
        return {"status": "succeeded", "result": result}

    try:
        response = _send_uploadpost(job, package)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        db.execute(
            """
            UPDATE publish_jobs
            SET status='failed', stage='provider-error', error=?, provider_response_json=?, updated_at=?
            WHERE id=?
            """,
            (
                f"Upload-Post HTTP {exc.code}: {detail}"[:1200],
                json.dumps({"http_status": exc.code, "detail": detail, "request_summary": request_summary}),
                db.utc_now(),
                job_id,
            ),
        )
        return {"status": "failed", "blocker": f"Upload-Post HTTP {exc.code}", "detail": detail}
    except Exception as exc:
        db.execute(
            """
            UPDATE publish_jobs
            SET status='failed', stage='provider-error', error=?, provider_response_json=?, updated_at=?
            WHERE id=?
            """,
            (
                f"Upload-Post request failed: {exc}"[:1200],
                json.dumps({"error": type(exc).__name__, "request_summary": request_summary}),
                db.utc_now(),
                job_id,
            ),
        )
        return {"status": "failed", "blocker": f"Upload-Post request failed: {exc}"}

    safe_response = _redacted_payload(response)
    urls = _extract_post_urls(response)
    provider_job_id = str(response.get("id") or response.get("job_id") or response.get("upload_id") or "")
    posted = bool(response.get("success", True))
    db.execute(
        """
        UPDATE publish_jobs
        SET status=?, stage=?, provider_job_id=?, provider_response_json=?, post_urls_json=?, error='', posted_at=?, updated_at=?
        WHERE id=?
        """,
        (
            "posted" if posted else "provider_returned_non_success",
            "posted" if posted else "provider-response",
            provider_job_id,
            json.dumps(safe_response),
            json.dumps(urls),
            db.utc_now() if posted else "",
            db.utc_now(),
            job_id,
        ),
    )
    db.log_audit("hermes-dispatcher", "publish_live", "publish_job", job_id, "posted" if posted else "provider_response", provider_job_id)
    return {"status": "succeeded" if posted else "blocked", "provider_response": safe_response, "post_urls": urls}


def execute_hermes_publish_intent(intent: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if intent == "prepare_publish_package":
        kit_id = str(payload.get("kit_id", "")).strip()
        package = create_publish_package(
            kit_id,
            platforms=payload.get("platforms") if isinstance(payload.get("platforms"), list) else SUPPORTED_PLATFORMS,
            title=str(payload.get("title", "")),
            caption=str(payload.get("caption", "")),
        )
        return {"status": "succeeded", "package": package}
    if intent in {"publish_dry_run", "publish_live"}:
        publish_job_id = str(payload.get("publish_job_id", "")).strip()
        return execute_publish_job(publish_job_id)
    if intent == "publish_schedule_tick":
        return publish_schedule_tick(requested_by="hermes-dispatcher")
    if intent == "publish_status_sweep":
        return {"status": "succeeded", "publish": publish_status()}
    return {"status": "blocked", "blocker": f"Unsupported publish intent: {intent}"}
