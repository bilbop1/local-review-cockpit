from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional

from . import credentials
from . import database as db


SELECTED_FEEDERS = [
    {
        "campaign_slug": "yourrage",
        "platform": "twitch",
        "platform_handle": "yourragegaming",
        "risk_flag": "selected_feeder_yourrage",
        "mode": "production_feeder",
    },
    {
        "campaign_slug": "plaqueboymax",
        "platform": "twitch",
        "platform_handle": "plaqueboymax",
        "risk_flag": "selected_feeder_plaqueboymax",
        "mode": "production_feeder",
    },
    {
        "campaign_slug": "doublelift",
        "platform": "twitch",
        "platform_handle": "doublelift",
        "risk_flag": "selected_feeder_doublelift",
        "mode": "production_feeder_freshness_watch",
    },
    {
        "campaign_slug": "jasontheween",
        "platform": "twitch",
        "platform_handle": "jasontheween",
        "risk_flag": "selected_feeder_jasontheween",
        "mode": "production_feeder",
    },
    {
        "campaign_slug": "lacy",
        "platform": "twitch",
        "platform_handle": "lacy",
        "risk_flag": "selected_feeder_lacy",
        "mode": "demoted_brief_too_narrow",
    },
]
TWITCH_SWEEP_LOOKBACK_DAYS = 35
TWITCH_SWEEP_WINDOW_DAYS = 7
TWITCH_SWEEP_FIRST = 100
TWITCH_SWEEP_STORE_LIMIT = 25
TWITCH_FRESH_WINDOW_HOURS = (24, 48, 72, 96, 120)


def _parse_twitch_datetime(raw: Any) -> Optional[datetime]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clip_freshness_window_hours(clip: Mapping[str, Any], now: datetime, fallback_hours: int) -> int:
    created_at = _parse_twitch_datetime(clip.get("created_at") or clip.get("clip_created_at"))
    if not created_at:
        return fallback_hours
    age_seconds = max(0.0, (now.astimezone(timezone.utc) - created_at).total_seconds())
    age_hours = int((age_seconds + 3599) // 3600)
    for window in db.QUOTA_RECOVERY_FRESHNESS_LADDER_HOURS:
        if age_hours <= window:
            return int(window)
    return fallback_hours


def _stored_clip_window_hours(clip: Mapping[str, Any], selected_window: int) -> int:
    try:
        return int(clip.get("freshness_window_hours", 0) or selected_window or 0)
    except (TypeError, ValueError):
        return int(selected_window or 0)


def _json_excerpt(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=True)[:1800]
    except TypeError:
        return str(payload)[:1800]


def _clean_headers(headers: Mapping[str, str]) -> Dict[str, str]:
    return {
        "rate_limit": headers.get("Ratelimit-Remaining") or headers.get("ratelimit-remaining") or "",
        "twitch_remaining": headers.get("Ratelimit-Remaining") or headers.get("ratelimit-remaining") or "",
    }


def api_request(provider: str, method: str, url: str, *, params: Optional[Dict[str, Any]] = None, token_kind: str = "app", body: bytes = b"") -> Dict[str, Any]:
    if params:
        encoded = urllib.parse.urlencode(params, doseq=True)
        url = f"{url}?{encoded}"

    token_status = credentials.ensure_app_token(provider) if token_kind == "app" else {"status": "ready"}
    token = credentials.token_for(provider, token_kind)
    if not token:
        check_id = db.record_platform_check(
            provider,
            url,
            "blocked",
            request_summary=f"{method} {url}",
            error=f"{token_kind} token missing",
        )
        return {"status": "blocked", "check_id": check_id, "provider": provider, "detail": f"{token_kind} token missing"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": "ClippingOpsCockpit/0.1 local",
    }
    if provider == "twitch":
        client_id = credentials.client_id_for("twitch")
        if client_id:
            headers["Client-Id"] = client_id

    request = urllib.request.Request(url, data=body if body else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw else {}
            clean_headers = _clean_headers(response.headers)
            check_id = db.record_platform_check(
                provider,
                urllib.parse.urlparse(url).path,
                "succeeded",
                response.status,
                request_summary=f"{method} {url}",
                response_excerpt=_json_excerpt(payload),
                rate_limit_remaining=clean_headers.get("rate_limit", ""),
            )
            return {
                "status": "succeeded",
                "provider": provider,
                "http_status": response.status,
                "check_id": check_id,
                "token_status": token_status["status"],
                "data": payload,
                "rate_limit_remaining": clean_headers.get("rate_limit", ""),
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw[:1200]
        check_id = db.record_platform_check(
            provider,
            urllib.parse.urlparse(url).path,
            "failed",
            exc.code,
            request_summary=f"{method} {url}",
            response_excerpt=_json_excerpt(payload),
            error=_json_excerpt(payload),
        )
        return {
            "status": "failed",
            "provider": provider,
            "http_status": exc.code,
            "check_id": check_id,
            "detail": payload,
        }
    except Exception as exc:
        check_id = db.record_platform_check(
            provider,
            urllib.parse.urlparse(url).path,
            "failed",
            0,
            request_summary=f"{method} {url}",
            error=f"{type(exc).__name__}: {exc}",
        )
        return {
            "status": "failed",
            "provider": provider,
            "http_status": 0,
            "check_id": check_id,
            "detail": str(exc),
        }


def twitch_validate() -> Dict[str, Any]:
    token = credentials.token_for("twitch", "app")
    if not token:
        return {"status": "blocked", "provider": "twitch", "detail": "app token missing"}
    request = urllib.request.Request(
        "https://id.twitch.tv/oauth2/validate",
        headers={"Authorization": f"OAuth {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
            check_id = db.record_platform_check(
                "twitch",
                "/oauth2/validate",
                "succeeded",
                response.status,
                response_excerpt=_json_excerpt({k: v for k, v in payload.items() if k != "client_id"}),
            )
            return {"status": "succeeded", "provider": "twitch", "http_status": response.status, "check_id": check_id, "data": payload}
    except Exception as exc:
        check_id = db.record_platform_check("twitch", "/oauth2/validate", "failed", error=str(exc))
        return {"status": "failed", "provider": "twitch", "check_id": check_id, "detail": str(exc)}


def twitch_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return api_request("twitch", "GET", f"{credentials.TWITCH_API_BASE}/{path.lstrip('/')}", params=params)


def twitch_smoke(login: str = "") -> Dict[str, Any]:
    result: Dict[str, Any] = {"provider": "twitch", "validate": twitch_validate()}
    if login:
        users = twitch_get("users", {"login": login})
        result["users"] = users
        data = users.get("data", {}).get("data", []) if users.get("status") == "succeeded" else []
        if data:
            user = data[0]
            broadcaster_id = str(user.get("id", ""))
            result["streams"] = twitch_get("streams", {"user_id": broadcaster_id})
            result["clips"] = twitch_get("clips", {"broadcaster_id": broadcaster_id, "first": 5})
            db.upsert_source_route(
                {
                    "platform": "twitch",
                    "creator_handle": login,
                    "source_url": f"https://www.twitch.tv/{login}",
                    "route_type": "official_api",
                    "auth_state": "app_token",
                    "availability_status": "reachable",
                    "latest_check_id": users.get("check_id", ""),
                    "notes": "Twitch user lookup succeeded through Helix app-token route.",
                }
            )
    return result


def twitch_clip_supply_windows(broadcaster_id: str, *, lookback_days: int = TWITCH_SWEEP_LOOKBACK_DAYS) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    deduped: Dict[str, Dict[str, Any]] = {}
    windows: list[Dict[str, Any]] = []
    for offset in range(0, max(1, lookback_days), TWITCH_SWEEP_WINDOW_DAYS):
        ended = now - timedelta(days=offset)
        started = ended - timedelta(days=TWITCH_SWEEP_WINDOW_DAYS)
        params = {
            "broadcaster_id": broadcaster_id,
            "first": TWITCH_SWEEP_FIRST,
            "started_at": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ended_at": ended.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        result = twitch_get("clips", params)
        clip_rows = result.get("data", {}).get("data", []) if result.get("status") == "succeeded" else []
        windows.append(
            {
                "started_at": params["started_at"],
                "ended_at": params["ended_at"],
                "status": result.get("status"),
                "count": len(clip_rows),
                "check_id": result.get("check_id", ""),
            }
        )
        for clip in clip_rows:
            key = str(clip.get("url") or clip.get("id") or "")
            if not key:
                continue
            enriched = dict(clip)
            enriched["freshness_window_hours"] = _clip_freshness_window_hours(enriched, now, lookback_days * 24)
            existing = deduped.get(key)
            if not existing or int(enriched.get("view_count", 0) or 0) > int(existing.get("view_count", 0) or 0):
                deduped[key] = enriched
    sorted_clips = sorted(
        deduped.values(),
        key=lambda item: (
            int(item.get("freshness_window_hours", lookback_days * 24) or lookback_days * 24),
            -int(item.get("view_count", 0) or 0),
            abs(float(item.get("duration", 0) or 0) - 30.0),
        ),
    )
    succeeded = any(window.get("status") == "succeeded" for window in windows)
    return {
        "status": "succeeded" if succeeded else "blocked",
        "data": {"data": sorted_clips},
        "windows": windows,
        "clip_count": len(sorted_clips),
        "lookback_days": lookback_days,
        "mode": "emergency_35_day_fallback",
    }


def twitch_fresh_clip_supply_ladder(
    broadcaster_id: str,
    *,
    min_candidates: int = 1,
    now: Optional[datetime] = None,
    freshness_ladder_hours: Iterable[int] | None = None,
) -> Dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    deduped: Dict[str, Dict[str, Any]] = {}
    windows: list[Dict[str, Any]] = []
    fallback_reasons: list[str] = []
    selected_window = 0
    ladder = tuple(int(item) for item in (freshness_ladder_hours or TWITCH_FRESH_WINDOW_HOURS))
    for hours in ladder:
        started = current - timedelta(hours=hours)
        params = {
            "broadcaster_id": broadcaster_id,
            "first": TWITCH_SWEEP_FIRST,
            "started_at": started.isoformat(timespec="seconds").replace("+00:00", "Z"),
            "ended_at": current.isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        result = twitch_get("clips", params)
        clip_rows = result.get("data", {}).get("data", []) if result.get("status") == "succeeded" else []
        for clip in clip_rows:
            key = str(clip.get("url") or clip.get("id") or "")
            if not key:
                continue
            existing = deduped.get(key)
            if not existing or int(clip.get("view_count", 0) or 0) > int(existing.get("view_count", 0) or 0):
                enriched = dict(clip)
                enriched["freshness_window_hours"] = hours
                deduped[key] = enriched
        windows.append(
            {
                "window_hours": hours,
                "started_at": params["started_at"],
                "ended_at": params["ended_at"],
                "status": result.get("status"),
                "count": len(clip_rows),
                "deduped_count": len(deduped),
                "check_id": result.get("check_id", ""),
            }
        )
        if len(deduped) >= max(1, min_candidates):
            selected_window = hours
            break
        fallback_reasons.append(f"{hours}h returned {len(clip_rows)} clip(s), below minimum {max(1, min_candidates)}")
    sorted_clips = sorted(
        deduped.values(),
        key=lambda item: (
            int(item.get("view_count", 0) or 0),
            str(item.get("created_at", "")),
            -abs(float(item.get("duration", 0) or 0) - 30.0),
        ),
        reverse=True,
    )
    succeeded = bool(sorted_clips)
    return {
        "status": "succeeded" if succeeded else "blocked",
        "data": {"data": sorted_clips},
        "windows": windows,
        "clip_count": len(sorted_clips),
        "selected_window_hours": selected_window or (windows[-1]["window_hours"] if windows else 0),
        "freshness_ladder_hours": list(ladder),
        "fallback_reasons": fallback_reasons,
        "mode": "freshness_ladder",
    }


def _store_twitch_clip_candidates(
    login: str,
    users_result: Dict[str, Any],
    clips_result: Dict[str, Any],
    risk_flag: str = "",
    campaign_slug: str = "",
) -> Dict[str, Any]:
    users = users_result.get("data", {}).get("data", []) if users_result.get("status") == "succeeded" else []
    clips = clips_result.get("data", {}).get("data", []) if clips_result.get("status") == "succeeded" else []
    creator_id = str(users[0].get("id", "")) if users else ""
    stored: list[str] = []
    selected_window = int(clips_result.get("selected_window_hours", 0) or 0)
    sorted_clips = sorted(
        clips,
        key=lambda item: (
            _stored_clip_window_hours(item, selected_window) or 999999,
            -int(item.get("view_count", 0) or 0),
            abs(float(item.get("duration", 0) or 0) - 30.0),
        ),
    )
    for index, clip in enumerate(sorted_clips[:TWITCH_SWEEP_STORE_LIMIT], start=1):
        clip_url = str(clip.get("url") or clip.get("embed_url") or "")
        if not clip_url:
            continue
        flags = [risk_flag or f"selected_feeder_{login.lower()}", "metadata_only_no_download"]
        clip_window = _stored_clip_window_hours(clip, selected_window)
        if index <= 10 or (clip_window and clip_window <= 120):
            flags.append("editorial_indexed_top_fresh")
            if clip_window:
                flags.append(f"fresh_window_{clip_window}h")
        if clip_window == 24:
            flags.append("top_24h_candidate")
        stored.append(
            db.upsert_clip_candidate(
                {
                    "campaign_slug": db.normalize_campaign_slug(campaign_slug),
                    "source_platform": "twitch",
                    "source_url": clip_url,
                    "creator_id": creator_id,
                    "title": str(clip.get("title") or f"{login} Twitch clip"),
                    "duration": float(clip.get("duration", 0) or 0),
                    "view_count": int(clip.get("view_count", 0) or 0),
                    "clip_created_at": str(clip.get("created_at") or ""),
                    "media_url": str(clip.get("thumbnail_url") or ""),
                    "provenance": "official_api_metadata",
                    "risk_flags": flags,
                }
            )
        )
    return {"login": login, "stored_clip_candidates": stored, "clip_count": len(clips)}


def selected_feeder_sweep() -> Dict[str, Any]:
    results: list[Dict[str, Any]] = []
    job_id = db.create_job(
        "selected-feeder-sweep",
        "ingestion",
        "running",
        "public-api-metadata",
        40,
        logs="Sweeping selected feeders through public-safe platform API routes.",
    )
    for feeder in SELECTED_FEEDERS:
        login = feeder["platform_handle"]
        users = twitch_get("users", {"login": login})
        row: Dict[str, Any] = {
            "campaign_slug": feeder["campaign_slug"],
            "platform": feeder["platform"],
            "platform_handle": login,
            "risk_flag": feeder["risk_flag"],
            "mode": feeder["mode"],
            "users": users.get("status"),
        }
        data = users.get("data", {}).get("data", []) if users.get("status") == "succeeded" else []
        if data:
            broadcaster_id = str(data[0].get("id", ""))
            streams = twitch_get("streams", {"user_id": broadcaster_id})
            clips = twitch_fresh_clip_supply_ladder(broadcaster_id, min_candidates=1)
            row["streams"] = streams.get("status")
            row["clips"] = clips.get("status")
            row["selected_window_hours"] = clips.get("selected_window_hours", 0)
            row["freshness_ladder_hours"] = clips.get("freshness_ladder_hours", list(TWITCH_FRESH_WINDOW_HOURS))
            row["clip_count"] = clips.get("clip_count", 0)
            row["windows"] = clips.get("windows", [])
            row["stored"] = _store_twitch_clip_candidates(
                login,
                users,
                clips,
                str(feeder["risk_flag"]),
                str(feeder["campaign_slug"]),
            )
            row["status"] = "succeeded" if row["stored"].get("stored_clip_candidates") else "yellow_no_public_clips"
            db.upsert_source_route(
                {
                    "platform": "twitch",
                    "creator_handle": login,
                    "source_url": f"https://www.twitch.tv/{login}",
                    "route_type": "official_api",
                    "auth_state": "app_token",
                    "availability_status": "reachable",
                    "latest_check_id": users.get("check_id", ""),
                    "risk_flags": [str(feeder["risk_flag"])],
                    "notes": (
                        "Streamer-first campaign sweep through Twitch Helix freshness ladder "
                        f"24h->48h->72h->4d->5d; selected window {clips.get('selected_window_hours', 0)}h. "
                        "Clip candidates are metadata-only until a source download route is validated."
                    ),
                }
            )
        else:
            row["blocker"] = users.get("detail", "No Twitch user returned")
            row["status"] = "blocked"
        results.append(row)
    stored_count = sum(int(row.get("stored", {}).get("clip_count", 0) or 0) for row in results)
    succeeded = sum(1 for row in results if row.get("status") == "succeeded")
    status = "succeeded" if succeeded == len(SELECTED_FEEDERS) else ("partial" if succeeded else "blocked")
    db.execute(
        "UPDATE job_runs SET status=?, stage=?, progress=100, logs=?, finished_at=? WHERE id=?",
        (
            status,
            "metadata-stored" if succeeded else "no-candidates",
            json.dumps({"feeders": results, "registry": SELECTED_FEEDERS})[:1800],
            db.utc_now(),
            job_id,
        ),
    )
    db.log_audit("worker", "selected_feeder_sweep", "clip_candidates", "selected-feeders", status, "twitch helix")
    return {
        "status": status,
        "feeders": results,
        "stored_clip_count": stored_count,
        "selected_feeder_registry": SELECTED_FEEDERS,
        "kick_mode": "monitor_only",
    }


def kick_get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return api_request("kick", "GET", f"{credentials.KICK_API_BASE}/{path.lstrip('/')}", params=params)


def kick_introspect() -> Dict[str, Any]:
    return api_request("kick", "POST", f"{credentials.KICK_AUTH_BASE}/oauth/token/introspect", body=b"")


def kick_smoke(slug: str = "") -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "provider": "kick",
        "mode": "monitor_only",
        "production_ingestion_ready": False,
        "blocker": "Kick clip/source media ingestion is not production proof until local media download and selected-feeder provenance are validated.",
        "token": kick_introspect(),
        "livestream_stats": kick_get("livestreams/stats"),
    }
    if slug:
        channels = kick_get("channels", {"slug": slug})
        result["channels"] = channels
        data = channels.get("data", {}).get("data", []) if channels.get("status") == "succeeded" else []
        if data:
            channel = data[0]
            broadcaster_id = channel.get("broadcaster_user_id") or channel.get("user_id") or channel.get("id")
            params = {"broadcaster_user_id": broadcaster_id} if broadcaster_id else {"limit": 5}
            result["livestreams"] = kick_get("livestreams", params)
            db.upsert_source_route(
                {
                    "platform": "kick",
                    "creator_handle": slug,
                    "source_url": f"https://kick.com/{slug}",
                    "route_type": "official_api",
                    "auth_state": "app_token",
                    "availability_status": "reachable",
                    "latest_check_id": channels.get("check_id", ""),
                    "notes": "Kick channel lookup succeeded through public v1 app-token route.",
                }
            )
    return result


def latest_checks() -> Dict[str, Any]:
    return {
        "checks": db.rows("SELECT * FROM platform_api_checks ORDER BY created_at DESC LIMIT 50"),
        "routes": db.rows("SELECT * FROM source_routes ORDER BY updated_at DESC LIMIT 100"),
        "selected_feeder_registry": SELECTED_FEEDERS,
        "kick_mode": "monitor_only",
    }
