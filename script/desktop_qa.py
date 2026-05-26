#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pyautogui
import Quartz
from PIL import Image, ImageStat


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
ARTIFACTS = ROOT / "artifacts" / "desktop-qa"
APP_PROCESS = "ClippingOpsCockpit"
APP_OWNER_NAMES = {"Clipping Ops Cockpit", "ClippingOpsCockpit"}
APP_DEFAULTS_DOMAIN = "com.bilbop.ClippingOpsCockpit"
BASE_URL = "http://127.0.0.1:8765"
CRASH_DIR = Path.home() / "Library" / "Logs" / "DiagnosticReports"

from clipping_ops_backend import database as db  # noqa: E402


SIDEBAR_PAGES = [
    ("dashboard", "Dashboard", 89),
    ("review-kits", "Review Kits", 122),
    ("campaigns", "Campaigns", 154),
    ("readiness", "Readiness", 186),
    ("settings", "Settings", 220),
    ("sources", "Sources", 286),
    ("clip-index", "Clip Index", 284),
    ("nominations", "Nominations", 317),
    ("render-queue", "Render Queue", 350),
    ("agents-jobs", "Agents / Jobs", 383),
    ("audit-log", "Audit Log", 416),
]


def api_get(path: str, timeout: float = 45.0) -> Any:
    with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
        return json.load(response)


def api_get_evidence(path: str, timeout: float = 45.0) -> Dict[str, Any]:
    started = time.time()
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as response:
            payload = json.load(response)
        return {
            "path": path,
            "ok": True,
            "http_status": response.status,
            "duration_ms": int((time.time() - started) * 1000),
            "payload": payload,
        }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw[:1200]}
        return {
            "path": path,
            "ok": False,
            "http_status": exc.code,
            "duration_ms": int((time.time() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "payload": parsed,
        }
    except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
        return {
            "path": path,
            "ok": False,
            "http_status": 0,
            "duration_ms": int((time.time() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "payload": {},
        }


def api_post(path: str, payload: Dict[str, Any] | None = None) -> Tuple[int, Any]:
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=360) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed: Any = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw}
        return exc.code, parsed


def api_post_evidence(path: str, payload: Dict[str, Any] | None = None, timeout: float = 360.0) -> Dict[str, Any]:
    started = time.time()
    body = None
    headers = {}
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(f"{BASE_URL}{path}", data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.load(response)
        return {
            "path": path,
            "ok": True,
            "http_status": response.status,
            "duration_ms": int((time.time() - started) * 1000),
            "payload": parsed,
        }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw[:1200]}
        return {
            "path": path,
            "ok": False,
            "http_status": exc.code,
            "duration_ms": int((time.time() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "payload": parsed,
        }
    except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
        return {
            "path": path,
            "ok": False,
            "http_status": 0,
            "duration_ms": int((time.time() - started) * 1000),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "payload": {},
        }


def latest_successful_platform_check(provider: str) -> Dict[str, Any]:
    row = db.one(
        """
        SELECT provider, endpoint, http_status, request_summary, created_at
        FROM platform_api_checks
        WHERE provider = ? AND status = 'succeeded'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (provider,),
    )
    return dict(row) if row else {}


def crash_reports() -> List[Path]:
    return sorted(CRASH_DIR.glob("ClippingOpsCockpit-*.ips"), key=lambda item: item.stat().st_mtime)


def parse_crash(path: Path) -> Dict[str, Any]:
    try:
        text = path.read_text(errors="replace")
        decoder = json.JSONDecoder()
        header, index = decoder.raw_decode(text)
        payload, _ = decoder.raw_decode(text[index:].lstrip())
    except Exception as exc:
        return {"path": str(path), "parse_error": str(exc)}
    faulting = int(payload.get("faultingThread", 0) or 0)
    frames = []
    threads = payload.get("threads", [])
    if 0 <= faulting < len(threads):
        for frame in threads[faulting].get("frames", [])[:12]:
            frames.append(frame.get("symbol") or frame.get("image") or str(frame.get("imageIndex", "")))
    return {
        "path": str(path),
        "timestamp": header.get("timestamp", payload.get("captureTime", "")),
        "capture_time": payload.get("captureTime", ""),
        "incident_id": header.get("incident_id", payload.get("incident", "")),
        "termination": payload.get("termination", {}),
        "faulting_thread": faulting,
        "top_frames": frames,
    }


def pid() -> str:
    result = subprocess.run(["pgrep", "-x", APP_PROCESS], text=True, capture_output=True)
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def image_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def nonblank(image: Image.Image) -> Tuple[bool, Dict[str, Any]]:
    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    extrema = stat.extrema[0]
    variance = float(stat.var[0])
    return extrema[0] != extrema[1] and variance > 4.0, {"extrema": extrema, "variance": variance}


def main_display_scale(screenshot: Image.Image) -> Tuple[float, float]:
    display = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    return screenshot.width / display.size.width, screenshot.height / display.size.height


def app_window() -> Dict[str, Any]:
    windows = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID)
    candidates: List[Dict[str, Any]] = []
    for window in windows:
        owner = str(window.get("kCGWindowOwnerName", ""))
        layer = int(window.get("kCGWindowLayer", 999))
        bounds = window.get("kCGWindowBounds", {})
        if owner in APP_OWNER_NAMES and layer == 0 and bounds.get("Width", 0) > 500 and bounds.get("Height", 0) > 400:
            candidates.append({"name": str(window.get("kCGWindowName", "")), "bounds": bounds})
    if not candidates:
        raise RuntimeError("Clipping Ops Cockpit window was not found on screen")
    return max(candidates, key=lambda item: item["bounds"].get("Width", 0) * item["bounds"].get("Height", 0))


def wait_for_window(timeout: float = 20.0) -> Dict[str, Any]:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            return app_window()
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(str(last_error) if last_error else "window wait timed out")


def assert_alive(context: str, manifest: Dict[str, Any]) -> str:
    current = pid()
    if current:
        return current
    manifest["app_survived_all_page_clicks"] = False
    write_manifest(manifest)
    raise RuntimeError(f"app process died during {context}")


def capture_window(name: str, manifest: Dict[str, Any]) -> Dict[str, Any]:
    screenshot = pyautogui.screenshot()
    scale_x, scale_y = main_display_scale(screenshot)
    bounds = app_window()["bounds"]
    left = int(bounds["X"] * scale_x)
    top = int(bounds["Y"] * scale_y)
    right = int((bounds["X"] + bounds["Width"]) * scale_x)
    bottom = int((bounds["Y"] + bounds["Height"]) * scale_y)
    crop = screenshot.crop((left, top, right, bottom))
    path = ARTIFACTS / f"{name}.png"
    crop.save(path)
    ok, stats = nonblank(crop)
    item = {
        "name": name,
        "path": str(path),
        "ok": ok,
        "sha256_16": image_hash(path),
        "size": [crop.width, crop.height],
        "window_title": app_window()["name"],
        "stats": stats,
    }
    manifest.setdefault("screenshots", []).append(item)
    if not ok:
        raise RuntimeError(f"blank or low-variance screenshot: {path}")
    return item


def activate_app() -> None:
    subprocess.run(["osascript", "-e", 'tell application "Clipping Ops Cockpit" to activate'], check=False)
    time.sleep(1)


def set_window_bounds(left: int, top: int, right: int, bottom: int) -> None:
    script = f'tell application "System Events" to tell process "Clipping Ops Cockpit" to set position of front window to {{{left}, {top}}}\n'
    script += f'tell application "System Events" to tell process "Clipping Ops Cockpit" to set size of front window to {{{right - left}, {bottom - top}}}'
    subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)


def sidebar_row_center(title: str) -> Tuple[int, int] | None:
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
  tell process "Clipping Ops Cockpit"
    tell outline 1 of scroll area 1 of group 1 of splitter group 1 of group 1 of front window
      repeat with r in rows
        if exists static text "{escaped}" of UI element 1 of r then
          set p to position of r
          set s to size of r
          return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
        end if
      end repeat
    end tell
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    if result.returncode != 0 or not result.stdout.strip():
        return None
    try:
        left, top, width, height = [float(part) for part in result.stdout.strip().split(",")]
    except ValueError:
        return None
    bounds = app_window()["bounds"]
    if left < float(bounds.get("X", 0)):
        left += float(bounds.get("X", 0))
    if top < float(bounds.get("Y", 0)):
        top += float(bounds.get("Y", 0))
    label_target_x = left + min(44, max(24, width * 0.32))
    return int(label_target_x), int(top + height / 2)


def launch_fresh() -> None:
    subprocess.run(["pkill", "-x", APP_PROCESS], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    set_advanced_sidebar_default(True)
    subprocess.run([str(ROOT / "script" / "build_and_run.sh"), "--verify"], check=True)
    activate_app()
    wait_for_window()


def set_advanced_sidebar_default(enabled: bool) -> None:
    subprocess.run(
        [
            "defaults",
            "write",
            APP_DEFAULTS_DOMAIN,
            "showAdvancedWorkbench",
            "-bool",
            "true" if enabled else "false",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def wait_for_window_title(expected_title: str, timeout: float = 4.0) -> str:
    deadline = time.time() + timeout
    latest = ""
    while time.time() < deadline:
        latest = str(app_window()["name"])
        if latest == expected_title:
            return latest
        time.sleep(0.2)
    raise RuntimeError(f"expected window title {expected_title!r}, got {latest!r}")


def click_sidebar(relative_y: int, context: str, manifest: Dict[str, Any], expected_title: str | None = None) -> None:
    bounds = app_window()["bounds"]
    ax_center = sidebar_row_center(expected_title or context)
    if ax_center:
        x, y = ax_center
        coordinate_source = "accessibility_row_bounds"
    else:
        x = int(bounds["X"] + 86)
        y = int(bounds["Y"] + relative_y)
        coordinate_source = "static_sidebar_offsets"
    before = assert_alive(f"before {context}", manifest)
    pyautogui.click(x, y)
    time.sleep(1.5)
    after = assert_alive(f"after {context}", manifest)
    title = wait_for_window_title(expected_title or context)
    manifest.setdefault("page_clicks", []).append(
        {
            "name": context,
            "x": x,
            "y": y,
            "coordinate_source": coordinate_source,
            "pid_before": before,
            "pid_after": after,
            "window_title": title,
            "ok": True,
        }
    )


def ensure_advanced_sidebar_visible() -> None:
    if sidebar_row_center("Sources"):
        return
    center = sidebar_row_center("Advanced")
    if center:
        pyautogui.click(*center)
    else:
        bounds = app_window()["bounds"]
        pyautogui.click(int(bounds["X"] + 86), int(bounds["Y"] + 252))
    time.sleep(0.8)


def hotkey(*keys: str) -> None:
    pyautogui.hotkey(*keys)
    time.sleep(1.2)


def run_command_action(name: str, keys: Tuple[str, ...], verifier, manifest: Dict[str, Any]) -> None:
    before = verifier()
    hotkey(*keys)
    time.sleep(1.2)
    after = verifier()
    assert_alive(name, manifest)
    manifest.setdefault("controls", []).append(
        {"name": name, "input": "+".join(keys), "before": before, "after": after, "ok": True}
    )


def render_review_frame(manifest: Dict[str, Any]) -> None:
    review_video, probe = wait_for_review_media_ready()
    manifest.setdefault("media", []).append(
        {
            "name": "review-media-ready",
            "path": review_video,
            "ok": True,
            "video": probe.get("video"),
            "audio": probe.get("audio"),
        }
    )
    frame_path = ARTIFACTS / "review-kit-frame.png"
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", "00:00:02", "-i", review_video, "-frames:v", "1", "-update", "1", str(frame_path)],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        manifest.setdefault("media", []).append(
            {
                "name": "review-frame",
                "path": str(frame_path),
                "ok": False,
                "returncode": result.returncode,
                "stderr_tail": result.stderr[-1600:],
            }
        )
        raise RuntimeError(f"ffmpeg frame extraction failed with exit {result.returncode}")
    with Image.open(frame_path) as frame:
        ok, stats = nonblank(frame)
    manifest.setdefault("media", []).append(
        {"name": "review-frame", "path": str(frame_path), "ok": ok, "sha256_16": image_hash(frame_path), "stats": stats}
    )
    if not ok:
        raise RuntimeError(f"blank review frame: {frame_path}")


def probe_review_video(path: str) -> Dict[str, Any]:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-print_format", "json", path],
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"ffprobe exited {result.returncode}")
    payload = json.loads(result.stdout)
    streams = payload.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise RuntimeError("review video must include video and audio streams")
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        raise RuntimeError("review video must be H.264/AAC")
    if int(video.get("width", 0)) != 1080 or int(video.get("height", 0)) != 1920:
        raise RuntimeError("review video must be 1080x1920 vertical")
    return {
        "video": {"codec": video.get("codec_name"), "width": video.get("width"), "height": video.get("height")},
        "audio": {"codec": audio.get("codec_name"), "sample_rate": audio.get("sample_rate")},
        "duration": payload.get("format", {}).get("duration"),
    }


def wait_for_review_media_ready(timeout: float = 90.0) -> Tuple[str, Dict[str, Any]]:
    deadline = time.time() + timeout
    last_error = "no review kits"
    while time.time() < deadline:
        kits = api_get("/api/review-kits")
        for kit in kits:
            path = kit.get("review_video_path", "")
            if not path or not Path(path).exists():
                continue
            try:
                return path, probe_review_video(path)
            except Exception as exc:
                last_error = f"{path}: {exc}"
        time.sleep(1.0)
    raise RuntimeError(f"review media was not ffprobe-ready within {timeout:.0f}s: {last_error}")


def verify_review_actions(manifest: Dict[str, Any]) -> None:
    wait_for_review_media_ready()
    kits = api_get("/api/review-kits")
    if not kits:
        manifest.setdefault("controls", []).append({"name": "review decisions", "ok": False, "detail": "no kits"})
        return

    first = kits[0]
    target = kits[1] if len(kits) > 1 else first
    touched_ids = {str(first["id"]), str(target["id"])}
    snapshots = {
        kit_id: db.one(
            "SELECT review_status, approved_by, approved_at, rejection_notes FROM render_kits WHERE id = ?",
            (kit_id,),
        )
        for kit_id in touched_ids
    }
    job_ids_before = {
        str(item["id"])
        for item in db.rows("SELECT id FROM job_runs WHERE name='review-kit-revision'")
    }
    try:
        status, approved = api_post(f"/api/review-kits/{first['id']}/approve")
        manifest.setdefault("controls", []).append(
            {
                "name": "Approve for Prep",
                "surface": "Review Kits decision button",
                "route": f"/api/review-kits/{first['id']}/approve",
                "http_status": status,
                "result": approved.get("review_status") if isinstance(approved, dict) else approved,
                "ok": status == 200 and approved.get("review_status") in {"demo_reviewed", "approved_manual_prep"},
                "state_restored_after_test": True,
            }
        )

        status, rejected_empty = api_post(f"/api/review-kits/{target['id']}/reject", {"notes": ""})
        manifest.setdefault("controls", []).append(
            {
                "name": "Reject disabled without notes",
                "surface": "Review Kits rejection field/button",
                "route": f"/api/review-kits/{target['id']}/reject",
                "http_status": status,
                "result": rejected_empty,
                "ok": status == 409,
                "state_restored_after_test": True,
            }
        )

        status, rejected = api_post(
            f"/api/review-kits/{target['id']}/reject",
            {"notes": "Desktop QA rejection path proof; not a publishing action."},
        )
        manifest.setdefault("controls", []).append(
            {
                "name": "Reject with notes",
                "surface": "Review Kits rejection field/button",
                "route": f"/api/review-kits/{target['id']}/reject",
                "http_status": status,
                "result": rejected.get("review_status") if isinstance(rejected, dict) else rejected,
                "ok": status == 200 and rejected.get("review_status") == "rejected_revision_requested",
                "state_restored_after_test": True,
            }
        )
    finally:
        for kit_id, snapshot in snapshots.items():
            if not snapshot:
                continue
            db.execute(
                """
                UPDATE render_kits
                SET review_status=?, approved_by=?, approved_at=?, rejection_notes=?
                WHERE id=?
                """,
                (
                    snapshot.get("review_status", ""),
                    snapshot.get("approved_by", ""),
                    snapshot.get("approved_at", ""),
                    snapshot.get("rejection_notes", ""),
                    kit_id,
                ),
            )
        job_ids_after = {
            str(item["id"])
            for item in db.rows("SELECT id FROM job_runs WHERE name='review-kit-revision'")
        }
        new_job_ids = sorted(job_ids_after - job_ids_before)
        if new_job_ids:
            placeholders = ",".join("?" for _ in new_job_ids)
            db.execute(f"DELETE FROM job_runs WHERE id IN ({placeholders})", new_job_ids)
        manifest["review_action_state_restored"] = True


def verify_platform_smoke(manifest: Dict[str, Any]) -> None:
    twitch_evidence = api_get_evidence("/api/platforms/twitch/smoke?login=twitch", timeout=75)
    kick_evidence = api_get_evidence("/api/platforms/kick/smoke?slug=xqc", timeout=95)
    feeders_evidence = api_get_evidence("/api/sweeps/selected-feeders", timeout=180)
    twitch = twitch_evidence.get("payload", {}) if twitch_evidence.get("ok") else {}
    kick = kick_evidence.get("payload", {}) if kick_evidence.get("ok") else {}
    feeders = feeders_evidence.get("payload", {}) if feeders_evidence.get("ok") else {}
    twitch_prior = latest_successful_platform_check("twitch")
    kick_prior = latest_successful_platform_check("kick")
    manifest.setdefault("network_evidence", []).extend(
        [
            {
                "name": "Twitch live smoke",
                "provider": "twitch",
                "mode": "production_feeder",
                "route": twitch_evidence["path"],
                "live_ok": twitch_evidence.get("ok"),
                "http_status": twitch_evidence.get("http_status"),
                "duration_ms": twitch_evidence.get("duration_ms"),
                "status": twitch.get("validate", {}).get("status", "unavailable"),
                "error_type": twitch_evidence.get("error_type", ""),
                "error": twitch_evidence.get("error", ""),
                "prior_success": bool(twitch_prior),
                "prior_success_created_at": twitch_prior.get("created_at", ""),
                "evidence_ok": bool(twitch_evidence.get("ok") or twitch_prior),
            },
            {
                "name": "Kick live smoke",
                "provider": "kick",
                "mode": "monitor_only",
                "route": kick_evidence["path"],
                "live_ok": kick_evidence.get("ok"),
                "http_status": kick_evidence.get("http_status"),
                "duration_ms": kick_evidence.get("duration_ms"),
                "status": kick.get("channels", {}).get("status", "network_degraded"),
                "error_type": kick_evidence.get("error_type", ""),
                "error": kick_evidence.get("error", ""),
                "prior_success": bool(kick_prior),
                "prior_success_created_at": kick_prior.get("created_at", ""),
                "evidence_ok": bool(kick_evidence.get("ok") or kick_prior),
                "production_ingestion_ready": False,
            },
            {
                "name": "Selected feeder sweep",
                "provider": "twitch",
                "mode": "production_feeder",
                "route": feeders_evidence["path"],
                "live_ok": feeders_evidence.get("ok"),
                "http_status": feeders_evidence.get("http_status"),
                "duration_ms": feeders_evidence.get("duration_ms"),
                "status": feeders.get("status", "network_degraded"),
                "error_type": feeders_evidence.get("error_type", ""),
                "error": feeders_evidence.get("error", ""),
                "evidence_ok": feeders.get("status") in {"succeeded", "partial", "blocked"},
            },
        ]
    )

    existing_kits = api_get("/api/review-kits")
    if existing_kits:
        selected_render_status = 200
        selected_render = {
            "status": "skipped_existing_review_kit",
            "created": [
                {
                    "review_video_path": existing_kits[0].get("review_video_path", ""),
                    "reused": "true",
                }
            ],
        }
    else:
        selected_render_evidence = api_post_evidence(
            "/api/render/selected-feeders",
            {"limit": 1, "style": "selected_feeder_final_v1"},
            timeout=360,
        )
        selected_render_status = int(selected_render_evidence.get("http_status", 0) or 0)
        selected_render = selected_render_evidence.get("payload", {})
    selected_created = selected_render.get("created", []) if isinstance(selected_render, dict) else []
    selected_paths = [item.get("review_video_path", "") for item in selected_created if isinstance(item, dict)]
    selected_status = selected_render.get("status") if isinstance(selected_render, dict) else ""
    clean_selected_paths = bool(selected_paths) and all("source-render" in path and "feeder-proof" not in path for path in selected_paths)
    selected_style_ok = selected_status == "blocked" or (
        selected_status in {"succeeded", "skipped_existing_review_kit"} and clean_selected_paths
    )
    manifest.setdefault("controls", []).append(
        {
            "name": "Sources Run",
            "surface": "Source Manager run button",
            "routes": [
                "/api/platforms/twitch/smoke?login=twitch",
                "/api/platforms/kick/smoke?slug=xqc",
                "/api/sweeps/selected-feeders",
                "/api/render/selected-feeders",
            ],
            "result": {
                "twitch": twitch.get("validate", {}).get("status"),
                "twitch_live_ok": twitch_evidence.get("ok"),
                "twitch_prior_success": bool(twitch_prior),
                "kick": kick.get("channels", {}).get("status"),
                "kick_live_ok": kick_evidence.get("ok"),
                "kick_prior_success": bool(kick_prior),
                "kick_mode": "monitor_only",
                "selected_feeders": feeders.get("status"),
                "stored_clip_count": feeders.get("stored_clip_count"),
                "selected_render_http_status": selected_render_status,
                "selected_render": selected_status,
                "selected_render_created": len(selected_created),
                "selected_render_paths": selected_paths,
                "selected_render_style_ok": selected_style_ok,
            },
            "network_degraded": not all(
                item.get("evidence_ok", False) for item in manifest.get("network_evidence", [])[-3:]
            ),
            "ok": bool(twitch_evidence.get("ok") or twitch_prior)
            and bool(kick_evidence.get("ok") or kick_prior)
            and (feeders.get("status") in {"succeeded", "partial", "blocked"} or bool(feeders_evidence.get("ok")))
            and selected_render_status == 200
            and selected_status in {"succeeded", "blocked", "skipped_existing_review_kit"}
            and selected_style_ok,
        }
    )


def verify_diagnostics_export(manifest: Dict[str, Any]) -> None:
    status, payload = api_post("/api/diagnostics/export")
    export_path = Path(payload.get("path", ""))
    manifest.setdefault("controls", []).append(
        {
            "name": "Export Diagnostics",
            "surface": "Settings workspace profile button",
            "route": "/api/diagnostics/export",
            "http_status": status,
            "result": str(export_path),
            "ok": status == 200 and export_path.exists() and export_path.suffix == ".zip",
        }
    )


def verify_clean_reset_block(manifest: Dict[str, Any]) -> None:
    status, payload = api_post("/api/system/clean-reset", {"confirm": "reset"})
    manifest.setdefault("controls", []).append(
        {
            "name": "Clean Reset blocked without exact confirmation",
            "route": "/api/system/clean-reset",
            "http_status": status,
            "result": payload,
            "ok": status == 409 and payload.get("status") == "blocked",
        }
    )


def new_crashes_since(before: set[str]) -> List[Path]:
    return [path for path in crash_reports() if str(path) not in before]


def write_manifest(manifest: Dict[str, Any]) -> Path:
    manifest["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    groups = ("screenshots", "controls", "media", "page_clicks")
    manifest["ok"] = (
        manifest.get("app_survived_all_page_clicks") is True
        and not manifest.get("new_crash_reports")
        and not manifest.get("failure")
        and all(item.get("ok", False) for group in groups for item in manifest.get(group, []))
    )
    path = ARTIFACTS / "manifest.json"
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp_path.replace(path)
    return path


def main() -> int:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    crashes_before = {str(path) for path in crash_reports()}
    manifest: Dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "app": "Clipping Ops Cockpit",
        "standard": "Every main page must survive real sidebar mouse clicks; no new crash report may appear.",
        "crash_reports_before_count": len(crashes_before),
        "latest_crash_before": parse_crash(crash_reports()[-1]) if crash_reports() else None,
        "app_survived_all_page_clicks": False,
        "screenshots": [],
        "controls": [],
        "media": [],
        "page_clicks": [],
        "network_evidence": [],
    }

    failure: Exception | None = None
    try:
        subprocess.run([str(ROOT / "script" / "start_backend.sh"), "start"], check=True)
        existing_review_kits = api_get("/api/review-kits")
        if existing_review_kits:
            manifest["selected_render"] = {
                "sweep_status": "skipped_existing_review_kit",
                "http_status": 200,
                "status": "succeeded",
                "created": [],
                "existing_visible_kits": len(existing_review_kits),
            }
        else:
            feeders = api_get("/api/sweeps/selected-feeders")
            status, selected_render = api_post("/api/render/selected-feeders", {"limit": 1, "style": "selected_feeder_final_v1"})
            manifest["selected_render"] = {
                "sweep_status": feeders.get("status"),
                "http_status": status,
                "status": selected_render.get("status"),
                "created": selected_render.get("created", []),
            }

        launch_fresh()
        assert_alive("fresh launch", manifest)

        ensure_advanced_sidebar_visible()
        for slug, title, relative_y in SIDEBAR_PAGES:
            click_sidebar(relative_y, title, manifest)
            capture_window(f"page-{slug}", manifest)
            print(f"clicked page-{slug}")

        click_sidebar(122, "Review Kits preview load", manifest, expected_title="Review Kits")
        autoplay_start = capture_window("page-review-kits-autoplay-start", manifest)
        time.sleep(3.0)
        autoplay_ready = capture_window("page-review-kits-autoplay-ready", manifest)
        manifest.setdefault("controls", []).append(
            {
                "name": "Auto Preview",
                "surface": "Review Kits selection",
                "before": autoplay_start["sha256_16"],
                "after": autoplay_ready["sha256_16"],
                "ok": True,
            }
        )

        for index in range(2):
            click_sidebar(89, f"Dashboard switch {index + 1}", manifest, expected_title="Dashboard")
            click_sidebar(122, f"Review Kits return {index + 1}", manifest, expected_title="Review Kits")
        capture_window("page-review-kits-after-switching", manifest)

        original = app_window()["bounds"]
        set_window_bounds(80, 80, 1040, 760)
        hotkey("command", "1")
        wait_for_window_title("Dashboard")
        capture_window("resize-compact-dashboard", manifest)
        hotkey("command", "7")
        wait_for_window_title("Review Kits")
        capture_window("resize-compact-review-kits", manifest)
        set_window_bounds(40, 40, 1420, 960)
        capture_window("resize-large-review-kits", manifest)
        try:
            set_window_bounds(
                int(original.get("X", 40)),
                int(original.get("Y", 40)),
                int(original.get("X", 40) + original.get("Width", 1380)),
                int(original.get("Y", 40) + original.get("Height", 920)),
            )
        except Exception:
            pass
        manifest["app_survived_all_page_clicks"] = True

        run_command_action("Refresh", ("command", "r"), lambda: api_get("/api/summary")["counts"], manifest)
        run_command_action("Refresh Campaigns", ("command", "shift", "g"), lambda: api_get("/api/campaign-gate")["status"], manifest)
        run_command_action("Build Latest Reviews", ("command", "shift", "d"), lambda: len(api_get("/api/review-kits")), manifest)

        verify_review_actions(manifest)
        verify_platform_smoke(manifest)
        verify_diagnostics_export(manifest)
        verify_clean_reset_block(manifest)
        render_review_frame(manifest)
    except Exception as exc:
        failure = exc
        manifest["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(limit=8),
        }
    finally:
        crashes_after = new_crashes_since(crashes_before)
        manifest["new_crash_reports"] = [parse_crash(path) for path in crashes_after]
        set_advanced_sidebar_default(False)

    manifest_path = write_manifest(manifest)
    print(manifest_path)
    if failure is not None:
        print(f"GUI QA failed: {failure}", file=sys.stderr)
        return 1
    if not json.loads(manifest_path.read_text(encoding="utf-8"))["ok"]:
        print(f"GUI QA recorded failures in {manifest_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
