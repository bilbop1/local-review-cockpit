#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from clipping_ops_backend import database as db  # noqa: E402
from clipping_ops_backend import platforms  # noqa: E402
from clipping_ops_backend import publishing  # noqa: E402
from clipping_ops_backend import server  # noqa: E402


BASE_URL = "http://127.0.0.1:8765"
WORKER_NAME = "hermes-dispatcher"


def api_post(path: str, payload: Dict[str, Any] | None = None, timeout: float = 30.0) -> Dict[str, Any]:
    body = json.dumps(payload or {}).encode("utf-8")
    request = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def claim_next(profile: str) -> Dict[str, Any]:
    return api_post("/api/jobs/claim-next", {"worker": WORKER_NAME, "hermes_profile": profile}, timeout=15)


def heartbeat(job: Dict[str, Any], stage: str, progress: int, logs: str = "") -> None:
    api_post(
        f"/api/jobs/{job['id']}/heartbeat",
        {"claim_token": job["claim_token"], "stage": stage, "progress": progress, "logs": logs},
        timeout=15,
    )


def complete(job: Dict[str, Any], result: Dict[str, Any], logs: str = "", output_path: str = "") -> Dict[str, Any]:
    return api_post(
        f"/api/jobs/{job['id']}/complete",
        {"claim_token": job["claim_token"], "result": result, "logs": logs, "output_path": output_path},
        timeout=30,
    )


def block(job: Dict[str, Any], error: str, result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return api_post(
        f"/api/jobs/{job['id']}/block",
        {"claim_token": job["claim_token"], "error": error, "result": result or {}, "stage": "blocked-by-hermes"},
        timeout=30,
    )


def fail(job: Dict[str, Any], error: str, result: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return api_post(
        f"/api/jobs/{job['id']}/fail",
        {"claim_token": job["claim_token"], "error": error, "result": result or {}},
        timeout=30,
    )


def payload_for(job: Dict[str, Any]) -> Dict[str, Any]:
    payload = job.get("payload")
    if isinstance(payload, dict):
        return payload
    raw = job.get("payload_json", "{}")
    try:
        parsed = json.loads(str(raw))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def review_risk_sweep() -> Dict[str, Any]:
    kits = db.visible_render_kits()
    statuses = []
    for kit in kits:
        status = db.production_feeder_kit_status(kit)
        statuses.append(
            {
                "kit_id": kit.get("id", ""),
                "title": kit.get("title", ""),
                "campaign_slug": kit.get("campaign_slug", ""),
                "classification": status.get("classification", "red"),
                "blockers": status.get("blockers", [])[:5],
            }
        )
    return {"status": "succeeded", "kit_count": len(kits), "kits": statuses}


def execute_job(job: Dict[str, Any]) -> Dict[str, Any]:
    intent = str(job.get("intent", ""))
    payload = payload_for(job)
    slug = db.normalize_campaign_slug(job.get("campaign_slug") or payload.get("campaign_slug", ""))

    if intent == "refresh_campaigns":
        return server.run_campaign_gate()
    if intent == "refresh_campaign_project":
        return server.refresh_campaign_project(slug)
    if intent == "discover_campaign_sources":
        return server.discover_campaign_sources(slug)
    if intent == "build_campaign_reviews":
        limit = int(payload.get("limit", db.CAMPAIGN_PROJECT_TARGET) or db.CAMPAIGN_PROJECT_TARGET)
        style = str(payload.get("style", db.CAMPAIGN_SHORT_PROFILE))
        return server.build_campaign_reviews(slug, limit=limit, style=style)
    if intent == "platform_smoke":
        results: List[Dict[str, Any]] = []
        twitch_login = str(payload.get("twitch_login", "")).strip()
        kick_slug = str(payload.get("kick_slug", "")).strip()
        if twitch_login:
            results.append({"provider": "twitch", "result": platforms.twitch_smoke(twitch_login)})
        if kick_slug:
            results.append({"provider": "kick", "result": platforms.kick_smoke(kick_slug)})
        if not results:
            return {"status": "blocked", "blocker": "No Twitch login or Kick slug provided.", "results": []}
        blocked = [item for item in results if item["result"].get("status") not in {"succeeded", "partial"}]
        return {"status": "blocked" if blocked else "succeeded", "results": results}
    if intent == "selected_feeder_sweep":
        return platforms.selected_feeder_sweep()
    if intent == "review_risk_sweep":
        return review_risk_sweep()
    if intent in {"prepare_publish_package", "publish_dry_run", "publish_live", "publish_status_sweep"}:
        return publishing.execute_hermes_publish_intent(intent, payload)
    return {"status": "blocked", "blocker": f"Unsupported Hermes job intent: {intent}"}


def run_once(profile: str) -> Dict[str, Any]:
    claimed = claim_next(profile)
    if claimed.get("status") == "empty":
        return {"status": "empty", "worker": WORKER_NAME}
    job = claimed
    heartbeat(job, "running-deterministic-worker", 15, f"{WORKER_NAME} executing {job.get('intent', '')}")
    try:
        result = execute_job(job)
    except Exception as exc:
        detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        return fail(job, detail, {"traceback": traceback.format_exc()[-4000:]})

    status = str(result.get("status", "")).lower()
    blocker = str(result.get("blocker") or "; ".join(str(item) for item in result.get("blockers", [])[:3]))
    if status in {"succeeded", "qualified", "skipped_existing_review_kit", "partial"}:
        return complete(job, result, logs=f"{job.get('intent', '')} completed through Hermes dispatcher.", output_path=str(db.render_root()))
    if status in {"blocked", "not_found"}:
        return block(job, blocker or f"{job.get('intent', '')} blocked.", result)
    return fail(job, blocker or f"{job.get('intent', '')} returned unexpected status {status}", result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Claim and execute queued Clipping Ops Hermes jobs.")
    parser.add_argument("--profile", default=db.hermes_profile())
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    results = []
    for _ in range(max(1, args.limit)):
        try:
            result = run_once(args.profile)
        except (urllib.error.URLError, TimeoutError) as exc:
            result = {"status": "backend_unavailable", "error": str(exc), "worker": WORKER_NAME}
        results.append(result)
        if result.get("status") in {"empty", "backend_unavailable"}:
            break

    payload = {"status": "succeeded" if all(item.get("status") != "backend_unavailable" for item in results) else "failed", "results": results}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        for item in results:
            print(f"{item.get('status', 'unknown')}: {item.get('id', item.get('worker', ''))}")
    raise SystemExit(0 if payload["status"] == "succeeded" else 1)


if __name__ == "__main__":
    main()
