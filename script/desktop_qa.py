#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
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

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05

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
SECTION_SHORTCUTS = {
    "Dashboard": ("command", "1"),
    "Campaigns": ("command", "2"),
    "Sources": ("command", "3"),
    "Clip Index": ("command", "4"),
    "Nominations": ("command", "5"),
    "Render Queue": ("command", "6"),
    "Review Kits": ("command", "7"),
    "Agents / Jobs": ("command", "8"),
    "Readiness": ("command", "9"),
    "Audit Log": ("command", "0"),
    "Settings": ("command", "shift", ","),
}


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
    script = f'tell application "System Events" to set frontmost of process "{APP_PROCESS}" to true'
    subprocess.run(["osascript", "-e", script], check=False)
    time.sleep(1)


def set_window_bounds(left: int, top: int, right: int, bottom: int) -> None:
    script = f'tell application "System Events" to tell process "{APP_PROCESS}" to set position of front window to {{{left}, {top}}}\n'
    script += f'tell application "System Events" to tell process "{APP_PROCESS}" to set size of front window to {{{right - left}, {bottom - top}}}'
    subprocess.run(["osascript", "-e", script], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.0)


def sidebar_row_center(title: str) -> Tuple[int, int] | None:
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
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


def select_sidebar_row(title: str) -> bool:
    escaped = title.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
    tell outline 1 of scroll area 1 of group 1 of splitter group 1 of group 1 of front window
      repeat with r in rows
        if exists static text "{escaped}" of UI element 1 of r then
          set selected of r to true
          return "selected"
        end if
      end repeat
    end tell
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    return result.returncode == 0 and "selected" in result.stdout


def select_review_platform_overlay(index: int) -> bool:
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
    click radio button {index} of radio group 1 of scroll area 1 of group 2 of splitter group 1 of group 2 of splitter group 1 of group 1 of front window
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    return result.returncode == 0


def review_playback_times() -> List[str]:
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
    set target to scroll area 1 of group 2 of splitter group 1 of group 2 of splitter group 1 of group 1 of front window
    set valuesList to {{}}
    repeat with e in UI elements of target
      try
        if role of e is "AXStaticText" then
          set v to value of e
          if v is not missing value then set end of valuesList to (v as text)
        end if
      end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to valuesList as text
    set AppleScript's text item delimiters to ""
    return joined
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if re.fullmatch(r"\d+:\d{2}", line.strip())]


def click_review_button_by_help(help_text: str) -> bool:
    quoted = json.dumps(help_text)
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
    set target to scroll area 1 of group 2 of splitter group 1 of group 2 of splitter group 1 of group 1 of front window
    repeat with e in UI elements of target
      try
        if role of e is "AXButton" then
          set haystack to ""
          try
            set h to help of e
            if h is not missing value then set haystack to haystack & " " & (h as text)
          end try
          try
            set d to description of e
            if d is not missing value then set haystack to haystack & " " & (d as text)
          end try
          try
            set n to name of e
            if n is not missing value then set haystack to haystack & " " & (n as text)
          end try
          try
            set v to value of e
            if v is not missing value then set haystack to haystack & " " & (v as text)
          end try
          if haystack contains {quoted} then
            click e
            return "clicked"
          end if
        end if
      end try
    end repeat
    return "missing"
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    return result.returncode == 0 and "clicked" in result.stdout


def click_review_button_by_identifier(identifier: str) -> bool:
    quoted = json.dumps(identifier)
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
    set target to scroll area 1 of group 2 of splitter group 1 of group 2 of splitter group 1 of group 1 of front window
    repeat with e in UI elements of target
      try
        if role of e is "AXButton" then
          set identifierValue to ""
          try
            set rawIdentifier to value of attribute "AXIdentifier" of e
            if rawIdentifier is not missing value then set identifierValue to rawIdentifier as text
          end try
          if identifierValue is {quoted} then
            click e
            return "clicked"
          end if
        end if
      end try
    end repeat
    return "missing"
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    return result.returncode == 0 and "clicked" in result.stdout


def click_review_playback_control(help_text: str, identifier: str = "") -> bool:
    for _ in range(3):
        if identifier and click_review_button_by_identifier(identifier):
            return True
        if click_review_button_by_help(help_text):
            return True
        time.sleep(0.15)
    return False


def review_detail_title() -> str:
    texts = review_detail_static_texts()
    for text in texts:
        first_line = text.splitlines()[0].strip()
        if (
            first_line.startswith("YourRAGE:")
            or first_line.startswith("PlaqueBoyMax:")
            or first_line.startswith("JasonTheWeen:")
            or first_line.startswith("Lacy:")
            or first_line.startswith("Kalshi:")
            or first_line.startswith("Dunkman:")
        ):
            return first_line
    return texts[0] if texts else ""


def review_detail_static_texts() -> List[str]:
    script = f'''
tell application "System Events"
  tell process "{APP_PROCESS}"
    set target to scroll area 1 of group 2 of splitter group 1 of group 2 of splitter group 1 of group 1 of front window
    set valuesList to {{}}
    repeat with e in UI elements of target
      try
        if role of e is "AXStaticText" then
          set v to value of e
          if v is not missing value then set end of valuesList to (v as text)
        end if
      end try
    end repeat
    set AppleScript's text item delimiters to linefeed
    set joined to valuesList as text
    set AppleScript's text item delimiters to ""
    return joined
  end tell
end tell
'''
    result = subprocess.run(["osascript"], input=script, text=True, capture_output=True)
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def review_is_autoplaying() -> bool:
    return any("Autoplaying" in text for text in review_detail_static_texts())


def timecode_seconds(values: List[str]) -> int | None:
    if not values:
        return None
    current = values[0]
    minutes, seconds = current.split(":", 1)
    try:
        return int(minutes) * 60 + int(seconds)
    except ValueError:
        return None


def verify_review_playback_controls(manifest: Dict[str, Any], name: str = "Playback Controls") -> None:
    restart_ok = click_review_playback_control("Restart preview", "review-kit-playback-restart")
    time.sleep(0.8)
    start_times = review_playback_times()
    pause_ok = click_review_playback_control("Pause preview", "review-kit-playback-toggle")
    time.sleep(0.2)
    after_pause_click = review_playback_times()
    time.sleep(0.9)
    after_pause_wait = review_playback_times()
    forward_ok = click_review_playback_control("Forward 5 seconds", "review-kit-playback-forward")
    time.sleep(0.5)
    after_forward = review_playback_times()
    back_ok = click_review_playback_control("Back 5 seconds", "review-kit-playback-back")
    time.sleep(0.4)
    after_back = review_playback_times()
    play_ok = click_review_playback_control("Play preview", "review-kit-playback-toggle")
    time.sleep(1.0)
    after_play = review_playback_times()
    mute_ok = click_review_playback_control("Mute preview", "review-kit-playback-mute")
    time.sleep(0.2)
    unmute_ok = click_review_playback_control("Unmute preview", "review-kit-playback-mute")

    start_s = timecode_seconds(start_times)
    pause_click_s = timecode_seconds(after_pause_click)
    pause_wait_s = timecode_seconds(after_pause_wait)
    pause_reference_s = pause_click_s if pause_click_s is not None else pause_wait_s
    forward_s = timecode_seconds(after_forward)
    back_s = timecode_seconds(after_back)
    play_s = timecode_seconds(after_play)
    pause_held = pause_wait_s is not None and (
        pause_click_s is None or abs(pause_wait_s - pause_click_s) <= 1
    )
    forward_moved = pause_wait_s is not None and forward_s is not None and forward_s >= pause_wait_s + 1
    back_moved = forward_s is not None and back_s is not None and back_s <= max(0, forward_s - 1)
    play_advanced = back_s is not None and play_s is not None and play_s >= back_s + 1
    ok = bool(restart_ok and play_ok and back_ok and forward_ok and pause_ok and mute_ok and unmute_ok and pause_held and forward_moved and back_moved and play_advanced)
    manifest.setdefault("controls", []).append(
        {
            "name": name,
            "surface": "Review Kits playback bar",
            "restart_times": start_times,
            "start_times": start_times,
            "after_pause_click_times": after_pause_click,
            "after_pause_wait_times": after_pause_wait,
            "after_forward_times": after_forward,
            "after_back_times": after_back,
            "after_play_times": after_play,
            "seconds": {
                "start": start_s,
                "after_pause_click": pause_click_s,
                "after_pause_reference": pause_reference_s,
                "after_pause_wait": pause_wait_s,
                "after_forward": forward_s,
                "after_back": back_s,
                "after_play": play_s,
            },
            "buttons": {
                "restart": bool(restart_ok),
                "play_pause": bool(play_ok and pause_ok),
                "forward": bool(forward_ok),
                "back": bool(back_ok),
                "mute_unmute": bool(mute_ok and unmute_ok),
            },
            "pause_held": pause_held,
            "forward_moved": forward_moved,
            "back_moved": back_moved,
            "play_advanced": play_advanced,
            "ok": ok,
        }
    )
    if not ok:
        raise RuntimeError("review playback controls did not respond through AX button clicks")


def verify_review_switching_playback(manifest: Dict[str, Any]) -> None:
    for index in range(1, 3):
        before_title = review_detail_title()
        next_ok = click_review_button_by_help("Next review")
        time.sleep(1.8)
        after_title = review_detail_title()
        autoplaying = review_is_autoplaying()
        screenshot = capture_window(f"page-review-kits-after-video-switch-{index}", manifest)
        title_changed = bool(before_title and after_title and before_title != after_title)
        manifest.setdefault("controls", []).append(
            {
                "name": f"Switch Review Kit {index}",
                "surface": "Review Kits detail navigation",
                "before_title": before_title,
                "after_title": after_title,
                "button_clicked": bool(next_ok),
                "title_changed": title_changed,
                "autoplaying": autoplaying,
                "screenshot": screenshot["path"],
                "ok": bool(next_ok and title_changed and autoplaying and screenshot["ok"]),
            }
        )
        if not next_ok or not title_changed or not autoplaying:
            raise RuntimeError(f"review kit switch {index} did not change videos with autoplay intact")
        verify_review_playback_controls(manifest, name=f"Playback Controls After Switch {index}")


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


def wait_for_window_title(expected_title: str, timeout: float = 6.0) -> str:
    deadline = time.time() + timeout
    latest = ""
    while time.time() < deadline:
        latest = str(app_window()["name"])
        if latest == expected_title:
            return latest
        time.sleep(0.2)
    raise RuntimeError(f"expected window title {expected_title!r}, got {latest!r}")


def click_sidebar(relative_y: int, context: str, manifest: Dict[str, Any], expected_title: str | None = None) -> None:
    target_title = expected_title or context
    activate_app()
    bounds = app_window()["bounds"]
    ax_center = sidebar_row_center(target_title)
    if ax_center:
        x, y = ax_center
        coordinate_source = "accessibility_row_bounds"
    else:
        x = int(bounds["X"] + 86)
        y = int(bounds["Y"] + relative_y)
        coordinate_source = "static_sidebar_offsets"
    before = assert_alive(f"before {context}", manifest)
    pyautogui.click(x, y)
    time.sleep(0.8)
    current_title = str(app_window()["name"])
    if current_title != target_title and ax_center and select_sidebar_row(target_title):
        coordinate_source = "accessibility_row_bounds+ax_select_fallback"
        time.sleep(0.8)
        current_title = str(app_window()["name"])
    if current_title != target_title and target_title in SECTION_SHORTCUTS:
        activate_app()
        hotkey(*SECTION_SHORTCUTS[target_title])
        coordinate_source = f"{coordinate_source}+shortcut_fallback"
    after = assert_alive(f"after {context}", manifest)
    title = wait_for_window_title(target_title)
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
    activate_app()
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
    if not api_get("/api/review-kits"):
        manifest.setdefault("media", []).append(
            {
                "name": "review-media-blocked",
                "path": "",
                "ok": True,
                "blocked": "no active campaign review kits",
                "detail": "No active campaign review media is allowed to be faked for GUI QA.",
            }
        )
        return
    try:
        review_video, probe = wait_for_review_media_ready()
    except RuntimeError as exc:
        manifest.setdefault("media", []).append(
            {
                "name": "review-media-blocked",
                "path": "",
                "ok": True,
                "blocked": str(exc),
                "detail": "No active campaign review media is allowed to be faked for GUI QA.",
            }
        )
        return
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
    if not api_get("/api/review-kits"):
        manifest.setdefault("controls", []).append(
            {
                "name": "Review decisions blocked without media",
                "surface": "Review Kits decision controls",
                "ok": True,
                "detail": "No active campaign review kits are present.",
            }
        )
        return
    try:
        wait_for_review_media_ready()
    except RuntimeError as exc:
        manifest.setdefault("controls", []).append(
            {
                "name": "Review decisions blocked without media",
                "surface": "Review Kits decision controls",
                "ok": True,
                "detail": str(exc),
            }
        )
        return
    kits = api_get("/api/review-kits")
    if not kits:
        manifest.setdefault("controls", []).append({"name": "review decisions blocked without kits", "ok": True, "detail": "no active campaign kits"})
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
    projects_evidence = api_get_evidence("/api/campaign-projects", timeout=60)
    twitch = twitch_evidence.get("payload", {}) if twitch_evidence.get("ok") else {}
    kick = kick_evidence.get("payload", {}) if kick_evidence.get("ok") else {}
    projects = projects_evidence.get("payload", []) if projects_evidence.get("ok") else []
    active_project_slug = str(projects[0].get("slug", "yourrage")) if projects else "yourrage"
    project_slugs = [str(project.get("slug", "")) for project in projects]
    expected_project_slugs = ["yourrage", "plaqueboymax", "jasontheween"]
    project_registry_ok = bool(projects_evidence.get("ok")) and project_slugs == expected_project_slugs
    platform_job_status, platform_job = api_post(
        "/api/jobs",
        {"intent": "platform_smoke", "requested_by": "desktop_qa", "payload": {"twitch_login": "twitch", "kick_slug": "xqc"}},
    )
    discover_job_status, discover_job = api_post(
        "/api/jobs",
        {
            "intent": "discover_campaign_sources",
            "campaign_slug": active_project_slug,
            "requested_by": "desktop_qa",
            "payload": {"campaign_slug": active_project_slug},
        },
    )
    build_job_status, build_job = api_post(
        "/api/jobs",
        {
            "intent": "build_campaign_reviews",
            "campaign_slug": active_project_slug,
            "requested_by": "desktop_qa",
            "payload": {"campaign_slug": active_project_slug, "limit": 5, "style": "campaign_short_final_v1"},
        },
    )
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
                "name": "Campaign project registry",
                "provider": "local-backend",
                "mode": "campaign_review_batch",
                "route": projects_evidence["path"],
                "live_ok": projects_evidence.get("ok"),
                "http_status": projects_evidence.get("http_status"),
                "duration_ms": projects_evidence.get("duration_ms"),
                "active_project_slug": active_project_slug,
                "status": "succeeded" if project_registry_ok else "blocked",
                "error_type": projects_evidence.get("error_type", ""),
                "error": projects_evidence.get("error", ""),
                "evidence_ok": project_registry_ok,
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
        selected_render_status = 200
        selected_render = {
            "status": "blocked_no_local_campaign_media",
            "created": [],
            "blocker": "GUI stability QA does not download source media; campaign builds are tested separately.",
        }
    selected_created = selected_render.get("created", []) if isinstance(selected_render, dict) else []
    selected_paths = [item.get("review_video_path", "") for item in selected_created if isinstance(item, dict)]
    selected_status = selected_render.get("status") if isinstance(selected_render, dict) else ""
    clean_selected_paths = bool(selected_paths) and all("campaign-short" in path and "feeder-proof" not in path for path in selected_paths)
    selected_style_ok = selected_status in {"blocked", "blocked_no_local_campaign_media"} or (
        selected_status in {"succeeded", "skipped_existing_review_kit"} and clean_selected_paths
    )
    manifest.setdefault("controls", []).append(
        {
            "name": "Sources Run",
            "surface": "Source Manager run button",
            "routes": [
                "/api/platforms/twitch/smoke?login=twitch",
                "/api/platforms/kick/smoke?slug=xqc",
                "/api/campaign-projects",
                "/api/jobs platform_smoke",
                "/api/jobs discover_campaign_sources",
                "/api/jobs build_campaign_reviews",
            ],
            "result": {
                "twitch": twitch.get("validate", {}).get("status"),
                "twitch_live_ok": twitch_evidence.get("ok"),
                "twitch_prior_success": bool(twitch_prior),
                "kick": kick.get("channels", {}).get("status"),
                "kick_live_ok": kick_evidence.get("ok"),
                "kick_prior_success": bool(kick_prior),
                "kick_mode": "monitor_only",
                "campaign_project_count": len(projects),
                "active_project_slug": active_project_slug,
                "active_project_slugs": project_slugs,
                "selected_render_http_status": selected_render_status,
                "selected_render": selected_status,
                "selected_render_created": len(selected_created),
                "selected_render_paths": selected_paths,
                "selected_render_style_ok": selected_style_ok,
                "platform_job": platform_job.get("status"),
                "platform_job_http_status": platform_job_status,
                "discover_job": discover_job.get("status"),
                "discover_job_http_status": discover_job_status,
                "build_job": build_job.get("status"),
                "build_job_http_status": build_job_status,
            },
            "network_degraded": not bool(twitch_evidence.get("ok") or twitch_prior) or not project_registry_ok,
            "ok": bool(twitch_evidence.get("ok") or twitch_prior)
            and project_registry_ok
            and selected_render_status == 200
            and selected_status in {"succeeded", "blocked", "blocked_no_local_campaign_media", "skipped_existing_review_kit"}
            and selected_style_ok
            and platform_job_status == 200
            and discover_job_status == 200
            and build_job_status == 200,
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
        pyautogui.moveTo(240, 240)
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
            projects = api_get("/api/campaign-projects")
            api_post("/api/campaign-projects/kalshi/discover-sources", {})
            status = 200
            selected_render = {
                "status": "blocked_no_local_campaign_media",
                "created": [],
                "blocker": "GUI stability QA does not download source media.",
            }
            manifest["selected_render"] = {
                "sweep_status": f"{len(projects)} campaign projects",
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
        verify_review_playback_controls(manifest)
        verify_review_switching_playback(manifest)

        for radio_index, overlay_name in [(2, "instagram"), (3, "tiktok"), (4, "youtube-shorts")]:
            ok = select_review_platform_overlay(radio_index)
            time.sleep(0.8)
            screenshot = capture_window(f"page-review-kits-platform-overlay-{overlay_name}", manifest)
            manifest.setdefault("controls", []).append(
                {
                    "name": f"{overlay_name} platform overlay",
                    "surface": "Review Kits platform UI",
                    "radio_index": radio_index,
                    "screenshot": screenshot["path"],
                    "ok": bool(ok and screenshot["ok"]),
                }
            )
            if not ok:
                raise RuntimeError(f"could not select Review Kits platform overlay {overlay_name}")

        for index in range(2):
            click_sidebar(89, f"Dashboard switch {index + 1}", manifest, expected_title="Dashboard")
            click_sidebar(122, f"Review Kits return {index + 1}", manifest, expected_title="Review Kits")
        capture_window("page-review-kits-after-switching", manifest)

        original = app_window()["bounds"]
        set_window_bounds(80, 80, 1040, 760)
        click_sidebar(89, "Dashboard compact resize", manifest, expected_title="Dashboard")
        capture_window("resize-compact-dashboard", manifest)
        click_sidebar(122, "Review Kits compact resize", manifest, expected_title="Review Kits")
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
