from __future__ import annotations

import argparse
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, urlparse

from . import database as db
from . import credentials
from . import platforms
from . import publishing
from .renderer import create_demo_kits, create_selected_feeder_kits, validate_video


HOST = "127.0.0.1"
PORT = 8765
API_VERSION = "2026-06-14-approval-slots-04"
REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_DIST_DIR = REPO_ROOT / "web" / "dist"
DIAGNOSTIC_SECRET_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"Apikey\s+(?!<redacted>|configured|missing)[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(access_token|refresh_token|client_secret|discord_token)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.IGNORECASE),
    re.compile(r"(upload[_-]?post[_-]?api[_-]?key|uploadpost_api_key|api_key)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.IGNORECASE),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----", re.IGNORECASE),
]


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def command_path(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    repo_venv_bin = Path(__file__).resolve().parents[1] / ".venv" / "bin"
    for directory in [
        str(repo_venv_bin),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        str(Path.home() / ".local" / "bin"),
        str(Path.home() / ".cargo" / "bin"),
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]:
        candidate = Path(directory) / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return ""


def launchctl_running(label: str) -> bool:
    result = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
        text=True,
        capture_output=True,
        timeout=4,
    )
    return result.returncode == 0 and "state = running" in result.stdout


def discord_state() -> Dict[str, Any]:
    directory = Path.home() / ".hermes" / "channel_directory.json"
    channels: List[str] = []
    if directory.exists():
        try:
            data = json.loads(directory.read_text(encoding="utf-8"))

            def walk(value: Any) -> None:
                if isinstance(value, dict):
                    name = value.get("name") or value.get("channel_name")
                    kind = value.get("type") or value.get("kind")
                    if name and (kind == "channel" or "clip-ops" in str(name).lower()):
                        channels.append(str(name))
                    for child in value.values():
                        walk(child)
                elif isinstance(value, list):
                    for child in value:
                        walk(child)

            walk(data)
        except Exception:
            channels = []
    required = ["clip-ops-alerts", "clip-ops-daily-brief", "clip-ops-approvals"]
    existing_lower = {channel.lower() for channel in channels}
    missing = [channel for channel in required if channel not in existing_lower]
    return {
        "configured": directory.exists(),
        "gateway_running": launchctl_running("ai.hermes.gateway"),
        "category": "CLIPPING OPS",
        "required_channels": required,
        "missing_channels": missing,
        "channel_limit": 3,
        "notes": "Discord is a Hermes messaging surface only. Backend and SQLite remain the source of truth.",
    }


def _run_hermes(args: List[str], timeout: int = 8) -> Dict[str, Any]:
    hermes = command_path("hermes")
    if not hermes:
        return {"ok": False, "stdout": "", "stderr": "hermes missing", "returncode": 127}
    try:
        result = subprocess.run([hermes, *args], text=True, capture_output=True, timeout=timeout)
        return {
            "ok": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired as exc:
        return {"ok": False, "stdout": exc.stdout or "", "stderr": f"timeout: {exc}", "returncode": 124}


def _hermes_profile_from_status(text: str) -> str:
    for line in text.splitlines():
        if line.strip().lower().startswith("profile:"):
            return line.split(":", 1)[1].strip() or db.DEFAULT_HERMES_PROFILE
    return db.DEFAULT_HERMES_PROFILE


def _hermes_field_from_status(text: str, field: str) -> str:
    wanted = field.strip().lower()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(f"{wanted}:"):
            return stripped.split(":", 1)[1].strip()
    return ""


def _cron_lines(text: str) -> List[str]:
    lines: List[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("Name:"):
            if current:
                lines.append(current)
            current = line.replace("Name:", "", 1).strip()
        elif current and ("Last" in line or "Error" in line or "Status" in line):
            current = f"{current}; {line}"
    if current:
        lines.append(current)
    clipping = [line for line in lines if "clip-" in line.lower() or "clipping" in line.lower()]
    return (clipping or lines)[:12]


def hermes_runtime_state() -> Dict[str, Any]:
    available = bool(command_path("hermes"))
    selected_profile = db.hermes_profile()
    status_args = ["status"] if selected_profile == "default" else ["-p", selected_profile, "status"]
    status_result = _run_hermes(status_args, timeout=2) if available else {"ok": False, "stdout": "", "stderr": "missing"}
    cron_result = _run_hermes(["cron", "list"], timeout=2) if available else {"ok": False, "stdout": "", "stderr": "missing"}
    combined = f"{status_result.get('stdout', '')}\n{status_result.get('stderr', '')}\n{cron_result.get('stdout', '')}\n{cron_result.get('stderr', '')}"
    lower = combined.lower()
    degraded_auth = any(token in lower for token in ["401", "token invalidated", "invalid_grant", "unauthorized"])
    gateway = launchctl_running("ai.hermes.gateway")
    detected_profile = _hermes_profile_from_status(str(status_result.get("stdout", "")))
    provider = _hermes_field_from_status(str(status_result.get("stdout", "")), "Provider")
    model = _hermes_field_from_status(str(status_result.get("stdout", "")), "Model")
    cron_job_details = db.clipping_hermes_cron_jobs()
    cron_jobs = db.cron_job_summary_lines(cron_job_details) or _cron_lines(str(cron_result.get("stdout", "")))
    minimax = db.minimax_hermes_status(
        selected_profile=selected_profile,
        provider=provider,
        model=model,
        cron_jobs=cron_job_details,
        available=available and bool(status_result.get("ok", False)),
        auth_degraded=degraded_auth,
        api_key_configured=db.minimax_profile_key_configured(selected_profile),
    )
    if not available:
        state = "unavailable"
    elif degraded_auth:
        state = "degraded_auth"
    elif not bool(status_result.get("ok", False)):
        state = "profile_blocked"
    elif not gateway:
        state = "gateway_blocked"
    elif not cron_result.get("ok", False):
        state = "cron_degraded"
    else:
        state = "ready"
    proof = db.hermes_native_execution_proof()
    return {
        "available": available,
        "gateway_running": gateway,
        "status": state,
        "selected_profile": selected_profile,
        "detected_profile": detected_profile,
        "provider": provider,
        "model": model,
        "minimax": minimax,
        "profile_source": "backend system_settings",
        "auth_degraded": degraded_auth,
        "cron_ok": bool(cron_result.get("ok", False)),
        "cron_jobs": cron_jobs,
        "cron_job_details": cron_job_details,
        "latest_execution_proof": proof,
        "worker_mode": "Hermes agent prompts plus no-agent deterministic scripts",
        "normal_path": "GUI queues job intents; Hermes claims jobs; backend records results.",
        "fallback_path": "Advanced local fallback endpoints remain available but do not count as Hermes-native proof.",
    }


def health() -> Dict[str, Any]:
    db.init_db()
    auth_status = credentials.all_status()
    twitch_ok = auth_status["providers"]["twitch"]["ok"]
    kick_ok = auth_status["providers"]["kick"]["ok"]
    hermes_proof = db.hermes_native_execution_proof()
    hermes_fast_ok = bool(command_path("hermes")) and launchctl_running("ai.hermes.gateway")
    checks = {
        "database": {"ok": db.database_path().exists(), "detail": str(db.database_path())},
        "ffmpeg": {"ok": bool(command_path("ffmpeg")), "detail": command_path("ffmpeg") or "missing"},
        "ffprobe": {"ok": bool(command_path("ffprobe")), "detail": command_path("ffprobe") or "missing"},
        "yt_dlp": {"ok": bool(command_path("yt-dlp")), "detail": command_path("yt-dlp") or "missing; real source fallback blocked"},
        "hermes": {"ok": bool(command_path("hermes")), "detail": command_path("hermes") or "missing"},
        "hermes_gateway": {"ok": launchctl_running("ai.hermes.gateway"), "detail": "launchd label ai.hermes.gateway"},
        "faster_whisper": {"ok": module_available("faster_whisper"), "detail": "python module"},
        "mister_whisper": {
            "ok": (Path.home() / "Library" / "Application Support" / "MisterWhisper" / "models").exists(),
            "detail": str(Path.home() / "Library" / "Application Support" / "MisterWhisper"),
        },
        "desktop_control": {
            "ok": module_available("pyautogui") and module_available("PIL"),
            "detail": "pyautogui + Pillow",
        },
        "hermes_native_orchestration": {
            "ok": hermes_fast_ok and hermes_proof["ok"],
            "detail": f"fast health only; cron/auth detail lives at /api/agents; {hermes_proof['detail']}",
        },
        "twitch_credentials": {
            "ok": twitch_ok,
            "detail": f"Keychain {auth_status['service']}; {auth_status['providers']['twitch']['client_id']}; app token {auth_status['providers']['twitch']['app_token']}",
        },
        "kick_credentials": {
            "ok": kick_ok,
            "detail": f"Keychain {auth_status['service']}; {auth_status['providers']['kick']['client_id']}; app token {auth_status['providers']['kick']['app_token']}",
        },
    }
    blockers = [name for name, check in checks.items() if not check["ok"] and name in {"yt_dlp", "twitch_credentials", "kick_credentials"}]
    gate = db.latest_campaign_gate()
    local_demo_status = "degraded" if blockers else "ready"
    campaign_status = "ready" if gate.get("status") == "qualified" else "blocked"
    production_green = bool(db.three_campaign_review_batch_status().get("ready"))
    publish = publishing.publish_status()
    return {
        "api_version": API_VERSION,
        "status": local_demo_status,
        "local_demo_status": local_demo_status,
        "campaign_status": campaign_status,
        "production_green": production_green,
        "app_support": str(db.app_support_dir()),
        "render_root": str(db.render_root()),
        "production_render_root": str(db.render_root()),
        "demo_render_root": str(db.demo_render_root()),
        "checks": checks,
        "blockers": blockers,
        "discord": discord_state(),
        "auth": auth_status,
        "publish": publish,
        "safety": {
            "autopublish": "locked_until_approved_confirmed",
            "payout_submission": "blocked",
            "account_connection": "blocked",
            "account_rebrand": "blocked",
            "ready_to_post_requires_preview": True,
        },
    }


def summary() -> Dict[str, Any]:
    db.init_db()
    counts = db.visible_counts()
    return {
        "counts": counts,
        "campaign_gate": db.latest_campaign_gate(),
        "latest_jobs": db.visible_job_runs(5),
        "latest_audit": db.visible_audit_events(8),
    }


def workspace_profile() -> Dict[str, Any]:
    stored = db.one("SELECT value FROM system_settings WHERE key='workspace_profile'")
    if stored:
        try:
            return json.loads(str(stored["value"]))
        except json.JSONDecodeError:
            pass
    return {
        "name": "Local Operator",
        "customer_id": "local-default",
        "license_mode": "local-placeholder",
        "billing_enabled": False,
        "diagnostics_export_enabled": True,
        "notes": "Local-first appliance profile. Billing and account management are intentionally not implemented.",
    }


def distribution_state() -> Dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[2]
    verify_path = repo_root / "artifacts" / "handoff" / "codex-handoff.json"
    if not verify_path.exists():
        return {
            "status": "missing",
            "customer_ship_ready": False,
            "artifact": str(verify_path),
            "mode": "source_build_web",
            "blocker": "Run script/package_codex_handoff.sh after web/backend verification.",
        }
    try:
        payload = json.loads(verify_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "status": "unreadable",
            "customer_ship_ready": False,
            "artifact": str(verify_path),
            "mode": "source_build_web",
            "blocker": f"Source handoff artifact is unreadable: {exc}",
        }
    payload.setdefault("artifact", str(verify_path))
    payload["mode"] = "source_build_web"
    payload["customer_ship_ready"] = bool(payload.get("ok"))
    payload["status"] = "green" if payload.get("ok") else "red"
    payload.setdefault("blocker", "" if payload.get("ok") else "Source-build web handoff package is not ready.")
    return payload


def update_workspace_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    current = workspace_profile()
    allowed = {"name", "customer_id", "license_mode", "notes"}
    for key in allowed:
        if key in payload:
            current[key] = str(payload.get(key, ""))
    current["billing_enabled"] = False
    current["diagnostics_export_enabled"] = True
    db.execute(
        """
        INSERT INTO system_settings (key, value, updated_at)
        VALUES ('workspace_profile', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (json.dumps(current), db.utc_now()),
    )
    db.log_audit("operator", "update_workspace_profile", "system_settings", "workspace_profile", "stored", "api")
    return current


def export_diagnostics() -> Dict[str, Any]:
    db.init_db()
    diagnostics_dir = db.app_support_dir() / "diagnostics"
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    stamp = db.utc_now().replace(":", "").replace("+", "Z")
    archive = diagnostics_dir / f"clipping-ops-diagnostics-{stamp}.zip"
    repo_root = Path(__file__).resolve().parents[2]
    gui_manifest_path = repo_root / "artifacts" / "web-qa" / "manifest.json"
    payloads = {
        "health.json": health(),
        "summary.json": summary(),
        "readiness.json": db.readiness_report(),
        "platforms.json": platforms.latest_checks(),
        "campaign_evidence.json": db.rows("SELECT * FROM campaign_evidence ORDER BY captured_at DESC"),
        "source_routes.json": db.rows("SELECT * FROM source_routes ORDER BY updated_at DESC"),
        "review_kits.json": db.rows("SELECT * FROM render_kits ORDER BY created_at DESC"),
        "publish_status.json": publishing.publish_status(),
        "publish_jobs.json": publishing.visible_publish_jobs(100),
        "workspace_profile.json": workspace_profile(),
        "security_notice.json": {
            "secrets_included": False,
            "keychain_items_included": False,
            "browser_sessions_included": False,
            "discord_tokens_included": False,
            "uploadpost_api_key_included": False,
            "note": "Diagnostics export includes operational state and artifact paths only.",
        },
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, payload in payloads.items():
            zipped.writestr(name, json.dumps(payload, indent=2))
        if gui_manifest_path.exists():
            zipped.write(gui_manifest_path, "web-qa-manifest.json")
    redaction_ok = True
    redaction_findings: List[str] = []
    with zipfile.ZipFile(archive) as zipped:
        for name in zipped.namelist():
            raw = zipped.read(name)
            if len(raw) > 2_000_000:
                continue
            text = raw.decode("utf-8", errors="ignore")
            for pattern in DIAGNOSTIC_SECRET_PATTERNS:
                if pattern.search(text):
                    redaction_ok = False
                    redaction_findings.append(name)
                    break
    db.log_audit("operator", "export_diagnostics", "diagnostics", archive.name, "created", str(archive))
    return {
        "status": "succeeded" if redaction_ok else "blocked",
        "path": str(archive),
        "files": list(payloads.keys()),
        "redaction_validated": redaction_ok,
        "redaction_findings": redaction_findings[:20],
    }


def clean_reset(payload: Dict[str, Any]) -> Dict[str, Any]:
    confirm = str(payload.get("confirm", ""))
    if confirm != "RESET_LOCAL_DEMO_DATA":
        return {
            "status": "blocked",
            "detail": "Clean reset requires confirm='RESET_LOCAL_DEMO_DATA'. Keychain and browser sessions are never touched.",
        }
    tables = [
        "campaign_gate_runs",
        "campaign_records",
        "campaign_evidence",
        "creator_targets",
        "source_routes",
        "clip_candidates",
        "transcripts",
        "viral_scores",
        "clip_clusters",
        "render_nominations",
        "render_kits",
        "job_runs",
        "platform_api_checks",
    ]
    with db.connect() as conn:
        for table in tables:
            conn.execute(f"DELETE FROM {table}")
    if db.render_root().exists():
        shutil.rmtree(db.render_root())
    db.render_root().mkdir(parents=True, exist_ok=True)
    if db.demo_render_root().exists():
        shutil.rmtree(db.demo_render_root())
    db.demo_render_root().mkdir(parents=True, exist_ok=True)
    db.init_db()
    db.log_audit("operator", "clean_reset", "local_state", "demo_data", "completed", "api")
    return {"status": "succeeded", "detail": "Local local-state data reset. Keychain, browser sessions, and external accounts were not touched."}


def list_agents() -> Dict[str, Any]:
    hermes = hermes_runtime_state()
    profile_status = "ready" if hermes["status"] == "ready" else hermes["status"]
    return {
        "profiles": [
            {
                "name": "clip-ops",
                "role": "Orchestrator, schedule owner, daily brief, Discord coordination",
                "status": profile_status,
                "can_write": "jobs, summaries, schedule records, publish dry-runs, safe task routing",
                "cannot_do": "approve kits, confirm live posts, connect accounts, submit payouts, rebrand, clear gambling promo gates",
            },
            {
                "name": "clip-research",
                "role": "Campaign and clip discovery",
                "status": profile_status,
                "can_write": "campaign candidates, clip candidates, source notes, score evidence",
                "cannot_do": "final approvals, live-post confirmation, unsafe scraping without labels",
            },
            {
                "name": "clip-review",
                "role": "Risk/readiness/learning reviewer",
                "status": profile_status,
                "can_write": "risk flags, review comments, learning summaries, approval recommendations",
                "cannot_do": "legal determinations, live-post confirmation, final risky-action approval",
            },
        ],
        "schedules": [
            "Fresh clip scheduler tick every 15 minutes.",
            "One review kit per active campaign every 3 hours, capped at 24/day total.",
            "Daily brief once clips/jobs exist.",
            "Immediate alert for job failure, rule drift, missing credential, or blocked review kit.",
        ],
        "hermes_available": hermes["available"],
        "gateway_running": hermes["gateway_running"],
        "status": hermes["status"],
        "selected_profile": hermes["selected_profile"],
        "detected_profile": hermes["detected_profile"],
        "provider": hermes["provider"],
        "model": hermes["model"],
        "minimax": hermes["minimax"],
        "auth_degraded": hermes["auth_degraded"],
        "cron_ok": hermes["cron_ok"],
        "cron_jobs": hermes["cron_jobs"],
        "cron_job_details": hermes.get("cron_job_details", []),
        "latest_execution_proof": hermes["latest_execution_proof"],
        "normal_path": hermes["normal_path"],
        "fallback_path": hermes["fallback_path"],
    }


def _research_artifact_path(*parts: str) -> Path:
    return Path(__file__).resolve().parents[2] / "artifacts" / "research-run" / Path(*parts)


def _campaign_brief_artifact(slug: str) -> Path:
    return {
        "plaqueboymax": _research_artifact_path("requirements-docs", "plaqueboymax-14vQvB96.txt"),
        "doublelift": _research_artifact_path("requirements-docs", "doublelift-1XNZxiDR.txt"),
        "jasontheween": _research_artifact_path("requirements-docs", "jasontheween-1-PiU5Lk.txt"),
        "lacy": _research_artifact_path("requirements-docs", "lacy-1gHf_Ae3-current.txt"),
        "kalshi": _research_artifact_path("requirements-docs", "kalshi-podcasts-15T4ZLKL.txt"),
        "dunkman": _research_artifact_path("requirements-docs", "dunkman-10I9Z4Ur.txt"),
        "haste": _research_artifact_path("detail-haste.json"),
    }.get(slug, Path())


def _extract_urls(text: str) -> List[str]:
    return [url.rstrip(")., \n\r\t") for url in re.findall(r"https?://[^\s)]+", text)]


def _youtube_id(url: str) -> str:
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{8,})", url)
    return match.group(1) if match else ""


def _start_seconds_from_url(url: str, fallback: int = 0) -> float:
    match = re.search(r"[?&]t=(\d+)s?", url)
    return float(match.group(1)) if match else float(fallback)


def _upload_date_to_iso(upload_date: Any) -> str:
    text = str(upload_date or "")
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}T00:00:00+00:00"
    return ""


def refresh_campaign_project(slug: str) -> Dict[str, Any]:
    normalized = db.normalize_campaign_slug(slug)
    if not normalized:
        return {"status": "not_found", "slug": slug, "blocker": "Unknown campaign project."}
    if not db.is_active_campaign_project(normalized):
        project = db.CAMPAIGN_PROJECTS[normalized]
        blocker = project.get("excluded_reason", "Campaign is excluded from active review batch.")
        db.log_audit("operator", "refresh_campaign_project", "campaign_project", normalized, "excluded", blocker)
        return {
            "status": "excluded",
            "slug": normalized,
            "project": {
                "slug": normalized,
                "name": project["name"],
                "campaign_url": project["campaign_url"],
                "excluded_reason": blocker,
            },
            "blocker": blocker,
        }
    project = db.CAMPAIGN_PROJECTS[normalized]
    artifact = _campaign_brief_artifact(normalized)
    if artifact.is_file():
        extracted = artifact.read_text(encoding="utf-8", errors="replace")
        source_url = project.get("requirements_url", "") or project["campaign_url"]
        confidence = 0.92
        title = f"{project['name']} stored campaign brief"
        notes = f"Stored from local research artifact {artifact}."
    elif project.get("requirements_text"):
        extracted = str(project["requirements_text"])
        source_url = project["campaign_url"]
        confidence = 0.82
        title = f"{project['name']} captured campaign brief summary"
        notes = "Stored from signed-in Clipping.net detail capture because the campaign had no external requirements document."
    else:
        return {"status": "blocked", "slug": normalized, "blocker": f"Brief artifact missing: {artifact}"}
    evidence = db.create_campaign_evidence(
        {
            "campaign_id": normalized,
            "evidence_type": "campaign_rules",
            "title": title,
            "source_url": source_url,
            "extracted_text": extracted,
            "confidence": confidence,
            "notes": notes,
        }
    )
    db.log_audit("operator", "refresh_campaign_project", "campaign_project", normalized, "stored", source_url)
    return {"status": "succeeded", "project": db.campaign_project_progress(normalized), "evidence": evidence}


def discover_campaign_sources(
    slug: str,
    *,
    freshness_ladder_hours: List[int] | None = None,
    quota_recovery: bool = False,
) -> Dict[str, Any]:
    normalized = db.normalize_campaign_slug(slug)
    if not normalized:
        return {"status": "not_found", "slug": slug, "created": [], "blocker": "Unknown campaign project."}
    if not db.is_active_campaign_project(normalized):
        blocker = db.CAMPAIGN_PROJECTS[normalized].get("excluded_reason", "Campaign is excluded from active review batch.")
        db.log_audit("worker", "discover_campaign_sources", "campaign_project", normalized, "excluded", blocker)
        return {"status": "excluded", "slug": normalized, "created": [], "blockers": [blocker], "blocker": blocker}
    refresh_result = refresh_campaign_project(normalized)
    if refresh_result.get("status") not in {"succeeded", "blocked"}:
        return {**refresh_result, "created": []}

    created: List[Dict[str, Any]] = []
    blockers: List[str] = []
    project = db.CAMPAIGN_PROJECTS[normalized]
    if project.get("platform") == "twitch" and project.get("platform_handle"):
        handle = str(project["platform_handle"])
        users = platforms.twitch_get("users", {"login": handle})
        data = users.get("data", {}).get("data", []) if users.get("status") == "succeeded" else []
        if not data:
            blockers.append(f"Twitch handle {handle} did not return a user through Helix.")
            status = "blocked"
        else:
            broadcaster_id = str(data[0].get("id", ""))
            ladder = freshness_ladder_hours or list(db.FRESHNESS_LADDER_HOURS)
            if quota_recovery:
                clips = platforms.twitch_clip_supply_windows(broadcaster_id, lookback_days=35)
                clips["selected_window_hours"] = 24 * int(clips.get("lookback_days", 35) or 35)
                clips["freshness_ladder_hours"] = list(ladder)
            else:
                clips = platforms.twitch_fresh_clip_supply_ladder(broadcaster_id, min_candidates=1, freshness_ladder_hours=ladder)
            flag = f"selected_feeder_{normalized}"
            if normalized == "yourrage":
                flag = "selected_feeder_yourrage"
            stored = platforms._store_twitch_clip_candidates(handle, users, clips, flag, normalized)
            route = db.upsert_source_route(
                {
                    "platform": "twitch",
                    "creator_handle": handle,
                    "source_url": f"https://www.twitch.tv/{handle}",
                    "route_type": "official_api",
                    "auth_state": "app_token",
                    "availability_status": "reachable",
                    "latest_check_id": users.get("check_id", ""),
                    "risk_flags": [flag, f"campaign_project_{normalized}", "campaign_rules_stored"],
                    "notes": (
                        "Streamer-first campaign source discovery through Twitch Helix "
                        f"{'quota recovery 35-day sweep' if quota_recovery else 'freshness ladder'}; "
                        f"selected window {clips.get('selected_window_hours', 0)}h. "
                        "Local media download is still required before rendering."
                    ),
                }
            )
            for clip_id in stored.get("stored_clip_candidates", []):
                created.append({"clip_id": clip_id, "source_url": f"https://www.twitch.tv/{handle}", "route_id": route.get("id", ""), "download_required": True})
            status = "succeeded" if created else "blocked"
            if not created:
                blockers.append(f"No public Twitch clips were returned for {handle} in the configured freshness ladder.")
    elif normalized == "kalshi":
        doc_path = _campaign_brief_artifact("kalshi")
        availability_path = _research_artifact_path("kalshi-youtube-source-availability-2026-05-28.json")
        doc_text = doc_path.read_text(encoding="utf-8", errors="replace") if doc_path.exists() else ""
        urls = [url for url in _extract_urls(doc_text) if "youtube.com" in url or "youtu.be" in url]
        availability = {}
        if availability_path.exists():
            payload = json.loads(availability_path.read_text(encoding="utf-8"))
            for item in payload.get("results", []):
                availability[str(item.get("id", ""))] = item
        route = db.upsert_source_route(
            {
                "platform": "youtube",
                "creator_handle": "kalshi",
                "source_url": db.CAMPAIGN_PROJECTS["kalshi"]["campaign_url"],
                "route_type": "manual_import",
                "availability_status": "reachable",
                "risk_flags": ["campaign_project_kalshi", "campaign_rules_stored"],
                "notes": "Approved source URLs came from the Kalshi campaign brief.",
            }
        )
        for index, url in enumerate(urls):
            video_id = _youtube_id(url)
            meta = availability.get(video_id, {})
            start = _start_seconds_from_url(url, fallback=45 + index * 30)
            short_duration = 34
            clip_id = db.upsert_clip_candidate(
                {
                    "id": f"clip_kalshi_{video_id or index}_{int(start)}",
                    "campaign_slug": "kalshi",
                    "source_platform": "youtube",
                    "source_url": url,
                    "creator_id": str(meta.get("channel", "kalshi-approved-source")),
                    "title": str(meta.get("title", "") or f"Kalshi approved source {index + 1}"),
                    "duration": short_duration,
                    "view_count": int(meta.get("view_count", 0) or 0),
                    "clip_created_at": _upload_date_to_iso(meta.get("upload_date")),
                    "clip_start_seconds": start,
                    "clip_end_seconds": start + short_duration,
                    "provenance": "campaign_brief_youtube",
                    "risk_flags": ["campaign_project_kalshi", "campaign_rules_stored", "metadata_only_no_download"],
                }
            )
            created.append({"clip_id": clip_id, "source_url": url, "route_id": route.get("id", "")})
        status = "succeeded" if created else "blocked"
        if not created:
            blockers.append("No Kalshi YouTube URLs were found in the stored brief artifact.")
    elif normalized == "dunkman":
        doc_path = _campaign_brief_artifact("dunkman")
        doc_text = doc_path.read_text(encoding="utf-8", errors="replace") if doc_path.exists() else ""
        urls = _extract_urls(doc_text)
        for index, url in enumerate(urls):
            platform = "google_drive" if "drive.google.com" in url else ("box" if "box.com" in url else "web")
            route = db.upsert_source_route(
                {
                    "platform": platform,
                    "creator_handle": "dunkman",
                    "source_url": url,
                    "route_type": "manual_import",
                    "availability_status": "unchecked",
                    "risk_flags": ["campaign_project_dunkman", "campaign_rules_stored"],
                    "notes": "Media-bank link from the Dunkman campaign brief. Rendering is blocked until local download verification succeeds.",
                }
            )
            clip_id = db.upsert_clip_candidate(
                {
                    "id": f"clip_dunkman_source_{index + 1}",
                    "campaign_slug": "dunkman",
                    "source_platform": platform,
                    "source_url": url,
                    "creator_id": "dunkman-media-bank",
                    "title": f"Dunkman media-bank source {index + 1}",
                    "duration": 0,
                    "provenance": "campaign_media_bank",
                    "risk_flags": ["campaign_project_dunkman", "campaign_rules_stored", "metadata_only_no_download"],
                }
            )
            created.append({"clip_id": clip_id, "source_url": url, "route_id": route.get("id", ""), "download_required": True})
        status = "blocked" if created else "blocked"
        blockers.append("Dunkman media-bank links are indexed only; local file download verification is still required before rendering.")
    else:
        status = "blocked"
        blockers.append(f"{normalized} source discovery is not implemented.")
    db.create_job(
        f"{normalized}-source-discovery",
        "research",
        "succeeded" if status == "succeeded" else "blocked",
        "campaign-source-discovery",
        100 if status == "succeeded" else 35,
        logs=f"Created/indexed {len(created)} source record(s) for {normalized}.",
        error="; ".join(blockers)[:1200],
    )
    db.log_audit("worker", "discover_campaign_sources", "campaign_project", normalized, status, "; ".join(blockers))
    return {"status": status, "project": db.campaign_project_progress(normalized), "created": created, "blockers": blockers}


def build_campaign_reviews(
    slug: str,
    limit: int = 5,
    style: str = db.CAMPAIGN_SHORT_PROFILE,
    *,
    quota_recovery: bool = False,
    hook_candidates_by_clip: Dict[str, List[Dict[str, Any]]] | None = None,
) -> Dict[str, Any]:
    normalized = db.normalize_campaign_slug(slug)
    if not normalized:
        return {"status": "not_found", "created": [], "blocker": "Unknown campaign project."}
    if not db.is_active_campaign_project(normalized):
        blocker = db.CAMPAIGN_PROJECTS[normalized].get("excluded_reason", "Campaign is excluded from active review batch.")
        db.log_audit("worker", "build_campaign_reviews", "campaign_project", normalized, "excluded", blocker)
        return {"status": "excluded", "created": [], "blocker": blocker}
    if style != db.CAMPAIGN_SHORT_PROFILE:
        return {"status": "blocked", "created": [], "blocker": "Only campaign_short_final_v1 can build this review batch."}
    progress = db.campaign_project_progress(normalized)
    watermark_blocker = db.campaign_watermark_blocker(normalized)
    if watermark_blocker:
        db.log_audit("worker", "build_campaign_reviews", "campaign_project", normalized, "blocked", watermark_blocker)
        return {"status": "blocked", "created": [], "blocker": watermark_blocker, "project": progress}
    if not progress.get("source_ready"):
        blocker = f"{progress.get('name', normalized)} has indexed sources, but no verified local source media yet."
        return {"status": "blocked", "created": [], "blocker": blocker}
    script = Path(__file__).resolve().parents[2] / "script" / "build_evidence_review_kit.py"
    candidates = db.review_candidate_order(db.campaign_clips(normalized), normalized, quota_recovery=quota_recovery)
    if not candidates:
        return {"status": "blocked", "created": [], "blocker": f"No {progress.get('name', normalized)} source candidates are indexed."}
    created: List[Dict[str, Any]] = []
    blockers: List[str] = []
    reviewed_clip_ids = {
        str(clip_id)
        for kit in db.campaign_render_kits(normalized)
        for clip_id in db.production_feeder_kit_status(kit).get("clip_ids", [])
    }
    skipped_existing = 0
    for candidate in candidates:
        if len(created) >= max(1, min(limit, db.CAMPAIGN_PROJECT_TARGET)):
            break
        candidate_id = str(candidate["id"])
        if candidate_id in reviewed_clip_ids:
            skipped_existing += 1
            continue
        command = [sys.executable, str(script), "--campaign-slug", normalized, "--clip-id", candidate_id, "--profile", db.CAMPAIGN_SHORT_PROFILE]
        if quota_recovery:
            command.append("--quota-recovery")
        candidate_hooks = (hook_candidates_by_clip or {}).get(candidate_id, [])
        if candidate_hooks:
            command.extend(["--hook-candidates-json", json.dumps(candidate_hooks)])
        try:
            result = subprocess.run(command, text=True, capture_output=True, timeout=1800, cwd=str(Path(__file__).resolve().parents[2]))
        except subprocess.TimeoutExpired as exc:
            blockers.append(f"{candidate_id}: render timed out: {exc}")
            continue
        if result.returncode != 0:
            blockers.append(f"{candidate_id}: {(result.stderr or result.stdout)[-1400:]}")
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            blockers.append(f"{candidate_id}: campaign review builder returned non-JSON output")
            continue
        if payload.get("status") != "succeeded":
            blocker_code = str(payload.get("blocker_code", "builder_blocked")).strip()
            blocker = str(payload.get("blocker", "campaign review builder blocked this candidate")).strip()
            blockers.append(f"{candidate_id}: {blocker_code}: {blocker}")
            continue
        kit = db.one("SELECT * FROM render_kits WHERE id = ?", (str(payload.get("kit_id", "")),))
        if kit:
            proof = db.production_feeder_kit_status(kit)
            payload["classification"] = proof.get("classification", "red")
            proof_clip_ids = [str(item) for item in proof.get("clip_ids", [])]
            if any(clip_id in reviewed_clip_ids for clip_id in proof_clip_ids):
                skipped_existing += 1
                continue
            if payload["classification"] != "green":
                blockers.append(f"{candidate_id}: rendered kit failed production proof: {'; '.join(str(item) for item in proof.get('blockers', [])[:4])}")
                continue
            reviewed_clip_ids.update(proof_clip_ids)
        else:
            blockers.append(f"{candidate_id}: builder did not create a render kit row")
            continue
        created.append(payload)
    if skipped_existing and not created:
        blockers.append(f"Skipped {skipped_existing} clip(s) that already have review kits; use an explicit revision flow to replace old drafts.")
    status = "succeeded" if created else "blocked"
    db.create_job(
        f"{normalized}-campaign-review-build",
        "render",
        status,
        "campaign-review" if created else "blocked",
        100 if created else 20,
        logs=f"Created/refreshed {len(created)} {db.CAMPAIGN_SHORT_PROFILE} review kit(s).",
        output_path=str(db.render_root()),
        error="; ".join(blockers)[:1200],
    )
    db.log_audit("worker", "build_campaign_reviews", "campaign_project", normalized, status, str(db.render_root()))
    return {"status": status, "project": db.campaign_project_progress(normalized), "created": created, "blockers": blockers[:8], "style": db.CAMPAIGN_SHORT_PROFILE}


def scheduled_campaign_review_build(slug: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    normalized = db.normalize_campaign_slug(slug)
    if not normalized:
        return {"status": "not_found", "blocker": "Unknown campaign project.", "created": []}
    payload = payload or {}
    quota_recovery = bool(payload.get("quota_recovery_mode"))
    freshness_ladder_hours = [int(item) for item in payload.get("freshness_ladder_hours", []) if str(item).strip()] or list(db.FRESHNESS_LADDER_HOURS)
    discovery = discover_campaign_sources(normalized, freshness_ladder_hours=freshness_ladder_hours, quota_recovery=quota_recovery)
    if discovery.get("status") not in {"succeeded", "blocked"}:
        return {**discovery, "created": []}
    raw_hook_candidates = payload.get("hook_candidates_by_clip", {})
    hook_candidates_by_clip = raw_hook_candidates if isinstance(raw_hook_candidates, dict) else {}
    result = build_campaign_reviews(
        normalized,
        limit=1,
        style=db.CAMPAIGN_SHORT_PROFILE,
        quota_recovery=quota_recovery,
        hook_candidates_by_clip=hook_candidates_by_clip,
    )
    result["schedule_payload"] = payload
    result["freshness_ladder_hours"] = freshness_ladder_hours
    result["quota_recovery_mode"] = quota_recovery
    result["quota_recovery_policy"] = db.quota_recovery_policy(quota_recovery)
    result["learning_context"] = db.learning_context_for_campaign(normalized, limit=8)
    if result.get("status") == "succeeded":
        db.log_audit("hermes-dispatcher", "scheduled_campaign_review_build", "campaign_project", normalized, "succeeded", json.dumps(result)[:800])
    return result


def reject_review_kit(kit_id: str, notes: str, tags: List[str] | None = None) -> Dict[str, Any]:
    signal = db.record_review_learning_signal(kit_id, notes, reason_tags=tags or [])
    kit = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
    payload = dict(kit or {})
    payload["learning_signal"] = signal
    return payload


def run_campaign_gate() -> Dict[str, Any]:
    gate_id = db.new_id("gate")
    evidence_count = db.one("SELECT COUNT(*) AS count FROM campaign_evidence") or {"count": 0}
    card_count = db.one("SELECT COUNT(*) AS count FROM campaign_evidence WHERE evidence_type = 'campaign_card'") or {"count": 0}
    detail_count = db.one("SELECT COUNT(*) AS count FROM campaign_evidence WHERE evidence_type = 'campaign_detail'") or {"count": 0}
    rules_count = db.one("SELECT COUNT(*) AS count FROM campaign_evidence WHERE evidence_type = 'campaign_rules'") or {"count": 0}
    latest_card = db.one(
        "SELECT extracted_text FROM campaign_evidence WHERE evidence_type = 'campaign_card' ORDER BY captured_at DESC LIMIT 1"
    )
    visible_campaign_count = int(evidence_count["count"])
    if latest_card:
        try:
            payload = json.loads(str(latest_card.get("extracted_text", "{}")))
            visible_campaign_count = len(payload.get("cards", [])) or int(payload.get("count", visible_campaign_count))
        except (TypeError, ValueError, json.JSONDecodeError):
            visible_campaign_count = int(evidence_count["count"])
    feeders = db.one(
        """
        SELECT COUNT(*) AS count FROM source_routes
        WHERE availability_status IN ('verified','reachable')
          AND route_type IN ('official_api','authenticated_route','manual_import')
          AND (
            risk_flags_json LIKE '%selected_feeder_%'
            OR risk_flags_json LIKE '%campaign_project_%'
          )
        """
    ) or {"count": 0}
    blockers = []
    if int(card_count["count"]) == 0:
        blockers.append("missing signed-in Clipping.net campaign card evidence")
    if int(detail_count["count"]) == 0:
        blockers.append("missing signed-in Clipping.net campaign detail evidence")
    if int(rules_count["count"]) == 0:
        blockers.append("missing campaign rules/requirements evidence")
    if int(feeders["count"]) == 0:
        blockers.append("missing verified campaign source route from API/manual import")
    status = "qualified" if not blockers and int(feeders["count"]) > 0 else "blocked"
    notes = (
        "Campaign gate evaluated from stored evidence and source routes. Real campaign rendering remains blocked "
        "until this run is qualified and an operator promotes campaign source media."
    )
    blocker = "; ".join(blockers)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO campaign_gate_runs
              (id, status, started_at, finished_at, visible_campaign_count, selected_feeder_count, blocker, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gate_id,
                status,
                db.utc_now(),
                db.utc_now(),
                visible_campaign_count,
                int(feeders["count"]),
                blocker,
                notes,
            ),
        )
    job_status = "succeeded" if status == "qualified" else "blocked"
    stage = "qualified" if status == "qualified" else "awaiting-evidence"
    db.create_job("campaign-research-gate", "research", job_status, stage, 100 if status == "qualified" else 30, logs=notes, error=blocker)
    db.log_audit("user", "request_campaign_gate", "campaign_gate", gate_id, status, "api")
    return db.latest_campaign_gate()


def build_selected_feeder_final_proof(limit: int = 2) -> Dict[str, Any]:
    script = Path(__file__).resolve().parents[2] / "script" / "build_evidence_review_kit.py"
    target_count = max(1, limit)
    existing_green = db.visible_render_kits()
    if existing_green:
        return {
            "status": "skipped_existing_review_kit",
            "created": [
                {
                    "kit_id": str(item.get("id", "")),
                    "title": str(item.get("title", "")),
                    "review_video_path": str(item.get("review_video_path", "")),
                    "reused": "true",
                    "classification": "green",
                }
                for item in existing_green[:target_count]
            ],
            "blockers": [],
            "style": db.FINAL_PROOF_PROFILE,
        }
    candidates = db.visible_clip_candidates()
    if not candidates:
        return {"status": "blocked", "created": [], "blocker": "No visible selected-feeder clip candidates are available."}

    created: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for candidate in candidates:
        if len(created) >= target_count:
            break
        command = [sys.executable, str(script), "--clip-id", str(candidate["id"]), "--profile", db.FINAL_PROOF_PROFILE]
        result = subprocess.run(command, text=True, capture_output=True, timeout=1800, cwd=str(Path(__file__).resolve().parents[2]))
        if result.returncode != 0:
            blockers.append(f"{candidate['id']}: {(result.stderr or result.stdout)[-1400:]}")
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            blockers.append(f"{candidate['id']}: proof builder returned non-JSON output")
            continue
        payload["classification"] = "pending_readiness_refresh"
        kit = db.one("SELECT * FROM render_kits WHERE id = ?", (str(payload.get("kit_id", "")),))
        if kit:
            payload["classification"] = db.production_feeder_kit_status(kit).get("classification", "red")
        created.append(payload)

    status = "succeeded" if created else "blocked"
    db.create_job(
        "selected-feeder-final-proof",
        "render",
        status,
        "final-proof" if created else "blocked",
        100 if created else 20,
        logs=f"Created/refreshed {len(created)} selected_feeder_final_v1 proof kit(s).",
        output_path=str(db.render_root()),
        error="; ".join(blockers)[:1200],
    )
    db.log_audit("worker", "render_selected_feeder_final_proof", "render_kit", "selected-feeders", status, str(db.render_root()))
    return {"status": status, "created": created, "blockers": blockers[:8], "style": db.FINAL_PROOF_PROFILE}


def validate_kit_artifacts(kit: Dict[str, Any]) -> Tuple[bool, str]:
    required = [
        "review_video_path",
        "caption_path",
        "transcript_path",
        "checklist_path",
        "source_path",
        "risk_path",
    ]
    missing = [key for key in required if not kit.get(key) or not Path(str(kit[key])).exists()]
    if missing:
        return False, f"missing artifact(s): {', '.join(missing)}"
    try:
        metadata = validate_video(Path(str(kit["review_video_path"])))
    except Exception as exc:
        return False, f"ffprobe validation failed: {exc}"
    kit_dir = Path(str(kit["review_video_path"])).parent
    extra_artifacts = ["ffprobe.json", "thumbnail.jpg", "contact_sheet.jpg", "style_critique.md", "render_text_manifest.json"]
    missing_extra = [name for name in extra_artifacts if not (kit_dir / name).exists()]
    if missing_extra:
        return False, f"missing review QA artifact(s): {', '.join(missing_extra)}"
    streams = metadata.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
    if video.get("codec_name") != "h264":
        return False, f"review video is not H.264: {video.get('codec_name', 'missing')}"
    if int(video.get("width", 0)) != 1080 or int(video.get("height", 0)) != 1920:
        return False, f"review video is not 9:16 1080x1920: {video}"
    if audio and audio.get("codec_name") != "aac":
        return False, f"review audio is not AAC: {audio.get('codec_name', 'missing')}"
    if not audio:
        return False, "review video has no AAC audio stream"
    return True, "validated H.264/AAC 1080x1920 review kit"


class Handler(BaseHTTPRequestHandler):
    server_version = "ClippingOpsBackend/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        db.app_support_dir().joinpath("logs", "api.log").open("a", encoding="utf-8").write((fmt % args) + "\n")

    def read_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def send_json(self, payload: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            return

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.FOUND)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def send_binary_file(
        self,
        path: Path,
        *,
        content_type: str | None = None,
        cache_control: str = "no-store",
    ) -> None:
        if not path.exists() or not path.is_file():
            self.send_json({"error": "file_not_found", "path": path.name}, HTTPStatus.NOT_FOUND)
            return
        content_type = content_type or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        total = path.stat().st_size
        range_header = self.headers.get("Range", "")
        start = 0
        end = total - 1
        status = HTTPStatus.OK
        if range_header.startswith("bytes="):
            match = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if match:
                raw_start, raw_end = match.groups()
                if raw_start:
                    start = int(raw_start)
                if raw_end:
                    end = min(int(raw_end), total - 1)
                if start >= total or end < start:
                    self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    self.send_header("Content-Range", f"bytes */{total}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                status = HTTPStatus.PARTIAL_CONTENT
        length = end - start + 1
        try:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", cache_control)
            if status == HTTPStatus.PARTIAL_CONTENT:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.end_headers()
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError):
            return

    def send_web_app(self, request_path: str) -> None:
        index = WEB_DIST_DIR / "index.html"
        if not index.exists():
            self.send_json(
                {
                    "error": "web_app_not_built",
                    "detail": "Run npm --prefix web install and npm --prefix web run build, then reload /app.",
                },
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        relative = request_path.removeprefix("/app").lstrip("/") or "index.html"
        candidate = (WEB_DIST_DIR / relative).resolve()
        try:
            candidate.relative_to(WEB_DIST_DIR.resolve())
        except ValueError:
            self.send_json({"error": "invalid_app_asset"}, HTTPStatus.BAD_REQUEST)
            return
        target = candidate if candidate.exists() and candidate.is_file() else index
        cache_control = "public, max-age=31536000, immutable" if "/assets/" in request_path else "no-store"
        self.send_binary_file(target, cache_control=cache_control)

    def send_review_media(self, kit_id: str) -> None:
        kit = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
        if not kit:
            self.send_json({"error": "missing_kit"}, HTTPStatus.NOT_FOUND)
            return
        video_path = Path(str(kit.get("review_video_path", ""))).expanduser()
        if not video_path.exists():
            self.send_json({"error": "missing_video", "kit_id": kit_id}, HTTPStatus.NOT_FOUND)
            return
        resolved = video_path.resolve()
        allowed_roots = [
            db.render_root().resolve(),
            db.demo_render_root().resolve(),
            db.app_support_dir().resolve(),
            REPO_ROOT.resolve(),
        ]
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            self.send_json({"error": "media_path_not_allowed", "kit_id": kit_id}, HTTPStatus.FORBIDDEN)
            return
        self.send_binary_file(resolved, content_type="video/mp4", cache_control="no-store")

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/":
                self.redirect("/app")
            elif path == "/app" or path.startswith("/app/"):
                self.send_web_app(path)
            elif path.startswith("/media/review-kits/") and path.endswith("/review.mp4"):
                parts = [part for part in path.split("/") if part]
                kit_id = parts[2] if len(parts) == 4 else ""
                self.send_review_media(kit_id)
            elif path == "/api/version":
                self.send_json({"status": "ok", "api_version": API_VERSION})
            elif path == "/api/health":
                self.send_json(health())
            elif path == "/api/summary":
                self.send_json(summary())
            elif path == "/api/campaign-gate":
                self.send_json(db.latest_campaign_gate())
            elif path == "/api/campaign-projects":
                self.send_json(db.campaign_project_records())
            elif path == "/api/clips":
                self.send_json(db.visible_clip_candidates())
            elif path == "/api/transcripts":
                self.send_json(db.rows("SELECT * FROM transcripts ORDER BY created_at DESC"))
            elif path == "/api/nominations":
                self.send_json(db.visible_render_nominations())
            elif path == "/api/render-queue":
                self.send_json(db.visible_job_runs(50))
            elif path == "/api/jobs":
                query = parse_qs(urlparse(self.path).query)
                status = (query.get("status") or [""])[0]
                limit = int((query.get("limit") or ["100"])[0] or "100")
                compact = str((query.get("compact") or [""])[0]).lower() in {"1", "true", "yes"}
                self.send_json(db.visible_jobs(limit=max(1, min(limit, 250)), status=status, compact=compact))
            elif path == "/api/review-kits":
                self.send_json(db.visible_render_kits())
            elif path == "/api/review-schedule":
                self.send_json(db.review_schedule_status())
            elif path == "/api/review-learning":
                query = parse_qs(urlparse(self.path).query)
                slug = (query.get("campaign_slug") or [""])[0]
                self.send_json(db.review_learning_signals(slug))
            elif path == "/api/campaign-evidence":
                self.send_json(db.rows("SELECT * FROM campaign_evidence ORDER BY captured_at DESC"))
            elif path == "/api/source-routes":
                self.send_json(db.rows("SELECT * FROM source_routes ORDER BY updated_at DESC"))
            elif path == "/api/platforms":
                self.send_json(platforms.latest_checks())
            elif path == "/api/platforms/twitch/smoke":
                query = parse_qs(urlparse(self.path).query)
                login = (query.get("login") or [""])[0]
                self.send_json(platforms.twitch_smoke(login))
            elif path == "/api/platforms/kick/smoke":
                query = parse_qs(urlparse(self.path).query)
                slug = (query.get("slug") or [""])[0]
                self.send_json(platforms.kick_smoke(slug))
            elif path == "/api/sweeps/selected-feeders":
                self.send_json(platforms.selected_feeder_sweep())
            elif path == "/api/readiness":
                self.send_json(db.readiness_report())
            elif path == "/api/workspace-profile":
                self.send_json(workspace_profile())
            elif path == "/api/agents":
                self.send_json(list_agents())
            elif path == "/api/hermes":
                self.send_json(hermes_runtime_state())
            elif path == "/api/audit":
                self.send_json(db.visible_audit_events(100))
            elif path == "/api/discord":
                self.send_json(discord_state())
            elif path == "/api/distribution":
                self.send_json(distribution_state())
            elif path == "/api/auth/status":
                self.send_json(credentials.all_status())
            elif path == "/api/publish/status":
                self.send_json(publishing.publish_status())
            elif path == "/api/auth/twitch/authorize-url":
                self.send_json(credentials.authorization_url("twitch"))
            elif path == "/api/auth/kick/authorize-url":
                self.send_json(credentials.authorization_url("kick"))
            elif path == "/auth/twitch/callback":
                query = urlparse(self.path).query
                params = parse_qs(query)
                code = (params.get("code") or [""])[0]
                state = (params.get("state") or [""])[0]
                result = credentials.exchange_authorization_code("twitch", code, state)
                db.log_audit("system", "exchange_oauth_code", "auth", "twitch", result["status"], "localhost callback")
                self.send_json(result, HTTPStatus.OK if result["status"] == "succeeded" else HTTPStatus.CONFLICT)
            elif path == "/auth/kick/callback":
                query = urlparse(self.path).query
                params = parse_qs(query)
                code = (params.get("code") or [""])[0]
                state = (params.get("state") or [""])[0]
                result = credentials.exchange_authorization_code("kick", code, state)
                db.log_audit("system", "exchange_oauth_code", "auth", "kick", result["status"], "localhost callback")
                self.send_json(result, HTTPStatus.OK if result["status"] == "succeeded" else HTTPStatus.CONFLICT)
            else:
                self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": "server_error", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        try:
            path = urlparse(self.path).path
            if path == "/api/review-schedule/tick":
                body = self.read_body()
                result = db.review_schedule_tick(
                    require_campaign_ready=not bool(body.get("ignore_campaign_blockers", False)),
                    force_due=bool(body.get("force_due", False)),
                )
                self.send_json(result, HTTPStatus.OK)
            elif path.startswith("/api/review-schedule/") and (path.endswith("/pause") or path.endswith("/resume")):
                parts = [part for part in path.split("/") if part]
                if len(parts) != 4:
                    self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
                    return
                slug = db.normalize_campaign_slug(parts[2])
                if not slug:
                    self.send_json({"error": "unknown_campaign"}, HTTPStatus.NOT_FOUND)
                    return
                enabled = 0 if parts[3] == "pause" else 1
                db.execute("UPDATE review_schedule SET enabled=?, updated_at=? WHERE campaign_slug=?", (enabled, db.utc_now(), slug))
                db.log_audit("user", f"review_schedule_{parts[3]}", "review_schedule", slug, "stored", "api")
                self.send_json(db.review_schedule_status(), HTTPStatus.OK)
            elif path == "/api/review-learning/summarize":
                signals = db.review_learning_signals(limit=250)
                by_campaign: Dict[str, Dict[str, Any]] = {}
                for signal in signals:
                    slug = str(signal.get("campaign_slug", "unknown") or "unknown")
                    row = by_campaign.setdefault(slug, {"campaign_slug": slug, "count": 0, "tags": {}, "notes": []})
                    row["count"] += 1
                    row["notes"].append(str(signal.get("notes", ""))[:240])
                    for tag in signal.get("reason_tags", []):
                        row["tags"][tag] = row["tags"].get(tag, 0) + 1
                self.send_json({"status": "succeeded", "campaigns": list(by_campaign.values())}, HTTPStatus.OK)
            elif path == "/api/jobs":
                body = self.read_body()
                job = db.create_job_intent(
                    str(body.get("intent", "")),
                    body.get("payload") if isinstance(body.get("payload"), dict) else body,
                    campaign_slug=str(body.get("campaign_slug", "")),
                    requested_by=str(body.get("requested_by", "gui")),
                    hermes_profile_name=str(body.get("hermes_profile", "")),
                    dedupe_key=str(body.get("dedupe_key", "")),
                    force_new=bool(body.get("force_new", False)),
                )
                self.send_json(job, HTTPStatus.OK)
            elif path == "/api/jobs/claim-next":
                body = self.read_body()
                queued = db.queued_jobs(1)
                if not queued:
                    self.send_json({"status": "empty", "job": None})
                    return
                job = db.claim_job(
                    str(queued[0]["id"]),
                    worker=str(body.get("worker", "hermes-dispatcher")),
                    profile=str(body.get("hermes_profile", "")),
                )
                self.send_json(job)
            elif path.startswith("/api/jobs/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) != 4:
                    self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
                    return
                job_id = parts[2]
                action = parts[3]
                body = self.read_body()
                try:
                    if action == "claim":
                        result = db.claim_job(
                            job_id,
                            worker=str(body.get("worker", "hermes-dispatcher")),
                            profile=str(body.get("hermes_profile", "")),
                        )
                    elif action == "heartbeat":
                        result = db.heartbeat_job(
                            job_id,
                            str(body.get("claim_token", "")),
                            stage=str(body.get("stage", "")),
                            progress=int(body["progress"]) if "progress" in body else None,
                            logs=str(body.get("logs", "")),
                        )
                    elif action == "complete":
                        result = db.complete_job(
                            job_id,
                            str(body.get("claim_token", "")),
                            result=body.get("result") if isinstance(body.get("result"), dict) else {},
                            logs=str(body.get("logs", "")),
                            output_path=str(body.get("output_path", "")),
                        )
                    elif action == "block":
                        result = db.block_job(
                            job_id,
                            str(body.get("claim_token", "")),
                            str(body.get("error", body.get("blocker", "blocked"))),
                            result=body.get("result") if isinstance(body.get("result"), dict) else {},
                            stage=str(body.get("stage", "blocked")),
                        )
                    elif action == "fail":
                        result = db.fail_job(
                            job_id,
                            str(body.get("claim_token", "")),
                            str(body.get("error", "failed")),
                            result=body.get("result") if isinstance(body.get("result"), dict) else {},
                        )
                    elif action == "cancel":
                        result = db.cancel_job(job_id, actor=str(body.get("actor", "operator")))
                    else:
                        self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
                        return
                    self.send_json(result)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            elif path == "/api/hermes/profile":
                body = self.read_body()
                self.send_json({"status": "succeeded", "profile": db.set_hermes_profile(str(body.get("profile", "")))})
            elif path == "/api/publish/settings":
                try:
                    self.send_json(publishing.set_publish_settings(self.read_body()))
                except publishing.PublishError as exc:
                    self.send_json({"error": exc.code, "detail": exc.detail}, HTTPStatus.CONFLICT)
            elif path == "/api/publish/schedule/tick":
                self.send_json(publishing.publish_schedule_tick(requested_by="api"))
            elif path == "/api/publish/schedule/rebalance":
                self.send_json(publishing.reschedule_approved_backlog(requested_by="api"))
            elif path == "/api/publish/jobs":
                try:
                    self.send_json(publishing.create_publish_job(self.read_body()), HTTPStatus.OK)
                except publishing.PublishError as exc:
                    status = HTTPStatus.NOT_FOUND if exc.status == "missing" else HTTPStatus.CONFLICT
                    self.send_json({"error": exc.code, "detail": exc.detail}, status)
            elif path.startswith("/api/publish/jobs/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) != 5:
                    self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
                    return
                job_id = parts[3]
                action = parts[4]
                try:
                    if action == "confirm-live":
                        result = publishing.confirm_live_publish(job_id)
                    elif action == "cancel":
                        result = publishing.cancel_publish_job(job_id, actor="user")
                    else:
                        self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
                        return
                    self.send_json(result)
                except publishing.PublishError as exc:
                    status = HTTPStatus.NOT_FOUND if exc.status == "missing" else HTTPStatus.CONFLICT
                    self.send_json({"error": exc.code, "detail": exc.detail}, status)
            elif path == "/api/demo/render":
                body = self.read_body()
                limit = int(body.get("limit", 1) or 1)
                self.send_json(create_demo_kits(limit=max(1, min(limit, 3))))
            elif path == "/api/render/selected-feeders":
                body = self.read_body()
                limit = int(body.get("limit", 2) or 2)
                style = str(body.get("style", "selected-feeder-a"))
                if style == db.FINAL_PROOF_PROFILE:
                    self.send_json(build_selected_feeder_final_proof(limit=max(1, min(limit, 4))))
                else:
                    if not style.startswith("selected-feeder-"):
                        style = "selected-feeder-a"
                    payload = create_selected_feeder_kits(limit=max(1, min(limit, 4)), style_slug=style)
                    payload["style_study_only"] = True
                    payload["production_proof"] = False
                    self.send_json(payload)
            elif path == "/api/auth/twitch/app-token":
                result = credentials.refresh_app_token("twitch")
                db.log_audit("system", "refresh_app_token", "auth", "twitch", result["status"], "Keychain token storage")
                self.send_json(result, HTTPStatus.OK if result["status"] != "failed" else HTTPStatus.BAD_GATEWAY)
            elif path == "/api/auth/kick/app-token":
                result = credentials.refresh_app_token("kick")
                db.log_audit("system", "refresh_app_token", "auth", "kick", result["status"], "Keychain token storage")
                self.send_json(result, HTTPStatus.OK if result["status"] != "failed" else HTTPStatus.BAD_GATEWAY)
            elif path == "/api/campaign-gate/run":
                self.send_json(run_campaign_gate())
            elif path.startswith("/api/campaign-projects/"):
                parts = [part for part in path.split("/") if part]
                if len(parts) != 4:
                    self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
                    return
                slug = parts[2]
                action = parts[3]
                if action == "refresh-brief":
                    result = refresh_campaign_project(slug)
                    self.send_json(result, HTTPStatus.OK if result.get("status") == "succeeded" else HTTPStatus.CONFLICT)
                elif action == "discover-sources":
                    result = discover_campaign_sources(slug)
                    self.send_json(result, HTTPStatus.OK if result.get("status") in {"succeeded", "blocked"} else HTTPStatus.CONFLICT)
                elif action == "build-reviews":
                    body = self.read_body()
                    limit = int(body.get("limit", db.CAMPAIGN_PROJECT_TARGET) or db.CAMPAIGN_PROJECT_TARGET)
                    style = str(body.get("style", db.CAMPAIGN_SHORT_PROFILE))
                    result = build_campaign_reviews(slug, limit=max(1, min(limit, db.CAMPAIGN_PROJECT_TARGET)), style=style)
                    self.send_json(result, HTTPStatus.OK)
                else:
                    self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
            elif path == "/api/campaign-evidence":
                item = db.create_campaign_evidence(self.read_body())
                self.send_json(item)
            elif path == "/api/source-routes":
                item = db.upsert_source_route(self.read_body())
                self.send_json(item)
            elif path == "/api/workspace-profile":
                self.send_json(update_workspace_profile(self.read_body()))
            elif path == "/api/diagnostics/export":
                self.send_json(export_diagnostics())
            elif path == "/api/system/clean-reset":
                result = clean_reset(self.read_body())
                self.send_json(result, HTTPStatus.OK if result["status"] == "succeeded" else HTTPStatus.CONFLICT)
            elif path == "/api/system/prune-irrelevant-review-surface":
                result = db.prune_irrelevant_review_surface()
                self.send_json(result)
            elif path.startswith("/api/review-kits/") and path.endswith("/publish-prep"):
                kit_id = path.split("/")[3]
                body = self.read_body()
                try:
                    package = publishing.create_publish_package(
                        kit_id,
                        platforms=body.get("platforms") if isinstance(body.get("platforms"), list) else publishing.DEFAULT_PUBLISH_PLATFORMS,
                        title=str(body.get("title", "")),
                        caption=str(body.get("caption", "")),
                    )
                    self.send_json(package)
                except publishing.PublishError as exc:
                    status = HTTPStatus.NOT_FOUND if exc.status == "missing" else HTTPStatus.CONFLICT
                    self.send_json({"error": exc.code, "detail": exc.detail}, status)
            elif path.startswith("/api/review-kits/") and path.endswith("/approve"):
                kit_id = path.split("/")[3]
                kit = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
                if not kit:
                    self.send_json({"error": "missing_kit"}, HTTPStatus.NOT_FOUND)
                    return
                ok, detail = validate_kit_artifacts(kit)
                if not ok:
                    self.send_json({"error": "kit_not_ready", "detail": detail}, HTTPStatus.CONFLICT)
                    return
                is_demo = int(kit.get("is_demo", 0) or 0) == 1
                if not is_demo and db.latest_campaign_gate().get("status") != "qualified":
                    self.send_json({"error": "campaign_gate_blocked", "detail": "Non-demo kits require a qualified campaign gate before Ready To Post."}, HTTPStatus.CONFLICT)
                    return
                next_status = "demo_reviewed" if is_demo else "approved_manual_prep"
                db.execute(
                    "UPDATE render_kits SET review_status=?, approved_by='user', approved_at=? WHERE id=?",
                    (next_status, db.utc_now(), kit_id),
                )
                db.log_audit("user", "approve_review_kit", "render_kit", kit_id, f"{next_status}; {detail}", "api")
                auto_slot = None
                if not is_demo:
                    try:
                        auto_slot = publishing.schedule_approved_kit(kit_id, requested_by="approval-api")
                    except publishing.PublishError as exc:
                        db.log_audit("system", "auto_slot_publish_failed", "render_kit", kit_id, exc.code, exc.detail[:800])
                        self.send_json({"error": exc.code, "detail": exc.detail, "kit_id": kit_id}, HTTPStatus.CONFLICT)
                        return
                updated = db.one("SELECT * FROM render_kits WHERE id = ?", (kit_id,))
                response = db.enrich_render_kit_with_clip_metadata(updated, verify_video=False) if updated else {}
                response["publish_auto_slot"] = auto_slot
                self.send_json(response)
            elif path.startswith("/api/review-kits/") and path.endswith("/reject"):
                kit_id = path.split("/")[3]
                body = self.read_body()
                notes = str(body.get("notes", "")).strip()
                if not notes:
                    self.send_json({"error": "notes_required", "detail": "Killing a kit requires notes so Hermes can learn what to avoid."}, HTTPStatus.CONFLICT)
                    return
                tags = body.get("reason_tags") if isinstance(body.get("reason_tags"), list) else []
                self.send_json(reject_review_kit(kit_id, notes, tags=[str(tag) for tag in tags]))
            else:
                self.send_json({"error": "not_found", "path": path}, HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": "server_error", "detail": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--render-demo", action="store_true")
    args = parser.parse_args()

    db.init_db()
    if args.render_demo:
        print(json.dumps(create_demo_kits(), indent=2))
        return

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Clipping Ops backend listening at http://{args.host}:{args.port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
