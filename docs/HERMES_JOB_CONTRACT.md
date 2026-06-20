# Hermes Job Contract

The backend job ledger is the normal interface between GUI intent, Hermes orchestration, and deterministic scripts.

## Source Of Truth

- SQLite/backend owns job state.
- GUI buttons create jobs with `POST /api/jobs`.
- Hermes or the no-agent dispatcher claims jobs.
- Workers write completion, blocked, or failed state back through job lifecycle APIs.
- Direct worker endpoints are advanced fallback only and do not prove Hermes-native readiness.

## Allowed Intents

| Intent | Purpose | Minimum Payload |
| --- | --- | --- |
| `refresh_campaigns` | Refresh global campaign gate/evidence | `{}` |
| `refresh_campaign_project` | Refresh one campaign brief | `{"campaign_slug":"yourrage"}` |
| `discover_campaign_sources` | Verify/download campaign source candidates | `{"campaign_slug":"yourrage"}` |
| `build_campaign_reviews` | Build campaign review kits | `{"campaign_slug":"yourrage","limit":5,"style":"campaign_short_final_v1"}` |
| `scheduled_campaign_review_build` | Build one due fresh review kit from the 24h->5d ladder | `{"campaign_slug":"yourrage","limit":1,"style":"campaign_short_final_v1","selection_mode":"fresh_best_candidate"}` |
| `retime_review_kit_captions` | Retime/rerender one review kit through ensemble word alignment | `{"clip_id":"clip_x","min_votes":3}` or `{"kit_id":"kit_x","min_votes":3}` |
| `platform_smoke` | Run Twitch/Kick smoke checks | `{"twitch_login":"yourragegaming"}` or `{"kick_slug":"name"}` |
| `selected_feeder_sweep` | Check configured streamer feeders | `{}` |
| `review_risk_sweep` | Audit review kits and blockers | `{}` |
| `review_learning_summary` | Summarize killed kits into next-cycle guidance | `{}` |
| `prepare_publish_package` | Prepare an approved kit for posting | `{"kit_id":"kit_x"}` |
| `publish_dry_run` | Validate publish payload without posting | `{"publish_job_id":"pubjob_x"}` |
| `publish_live` | Live Upload-Post job after final confirmation | `{"publish_job_id":"pubjob_x"}` |

Upload-Post jobs never select a provider profile from job payload. The backend always sends the single configured local Upload-Post user/profile from Settings, so each operator's clone is pinned to their own profile.
| `publish_schedule_tick` | Promote due scheduled dry-runs into Hermes publish jobs | `{}` |
| `publish_status_sweep` | Refresh/report publish status | `{}` |

Unsupported intents must be blocked, not guessed.

## Create Job

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"intent":"discover_campaign_sources","campaign_slug":"yourrage","requested_by":"incoming-agent","payload":{"campaign_slug":"yourrage"}}'
```

Expected: `status` is `queued` or an existing active job is returned with `deduped: true`.

## Worker Lifecycle

Claim next queued job:

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs/claim-next \
  -H 'Content-Type: application/json' \
  -d '{"worker":"hermes-dispatcher","hermes_profile":"clipping-ops-minimax"}'
```

Heartbeat:

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs/JOB_ID/heartbeat \
  -H 'Content-Type: application/json' \
  -d '{"claim_token":"CLAIM_TOKEN","stage":"running","progress":40,"logs":"working"}'
```

Complete:

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs/JOB_ID/complete \
  -H 'Content-Type: application/json' \
  -d '{"claim_token":"CLAIM_TOKEN","result":{"status":"succeeded"},"logs":"done"}'
```

Block safely:

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs/JOB_ID/block \
  -H 'Content-Type: application/json' \
  -d '{"claim_token":"CLAIM_TOKEN","error":"source media missing","result":{"status":"blocked"}}'
```

Fail only for errors:

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs/JOB_ID/fail \
  -H 'Content-Type: application/json' \
  -d '{"claim_token":"CLAIM_TOKEN","error":"exception summary","result":{"status":"failed"}}'
```

Blocked means the system behaved correctly but needs credentials/source/operator action. Failed means code or runtime broke.

## Example Jobs

Refresh campaigns:

```json
{"intent":"refresh_campaigns","requested_by":"gui","payload":{}}
```

Discover YourRAGE sources:

```json
{"intent":"discover_campaign_sources","campaign_slug":"yourrage","requested_by":"gui","payload":{"campaign_slug":"yourrage"}}
```

Build campaign reviews:

```json
{"intent":"build_campaign_reviews","campaign_slug":"jasontheween","requested_by":"gui","payload":{"campaign_slug":"jasontheween","limit":5,"style":"campaign_short_final_v1"}}
```

Hermes build intents must run caption alignment before reporting success. The dispatcher calls `script/ensemble_retime_review_kits.py` for each created clip; if alignment blocks, the Hermes job blocks instead of handing the operator a mistimed review video.

Hermes build intents must also respect the deterministic top-card quality gate before render. Campaign-short builders write `blocked_hook_quality` when every proposed hook is generic, duplicated, a raw-title echo, a raw ASR fragment, a repeated transcript loop, a quote dump, too short/long, or contains internal language. Treat that as a normal retry/selection blocker: pick a better clip or propose better hook copy, then queue a fresh build. Do not force a bad hook into Review Kits.

Hermes/MiniMax may pass hook proposals through the job payload as `hook_candidates_by_clip`, keyed by clip ID. Each candidate is a JSON object with at least `text` and `source`; the builder evaluates candidates in order and appends the deterministic local fallback after them. Good hook candidates should be viewer-facing summaries shaped like protagonist + situation + tension/payoff. Do not submit captions that start with `Streamer said:`, copy the clip title, or paste the first words of the transcript.

```json
{
  "intent": "build_campaign_reviews",
  "campaign_slug": "yourrage",
  "payload": {
    "campaign_slug": "yourrage",
    "limit": 1,
    "style": "campaign_short_final_v1",
    "hook_candidates_by_clip": {
      "clip_example": [
        {"text": "YourRAGE opened a link and instantly regretted it", "source": "hermes"}
      ]
    }
  }
}
```

Repair existing unreviewed top cards only:

```bash
PYTHONPATH=backend backend/.venv/bin/python script/repair_review_top_cards.py --apply --quota-recovery
```

Use `--only-failing` for a narrower pass. The repair command only targets non-demo `needs_review` campaign kits; already-approved and rejected kits are not rerendered.

Scheduled fresh review build:

```json
{"intent":"scheduled_campaign_review_build","campaign_slug":"yourrage","requested_by":"review-scheduler","payload":{"campaign_slug":"yourrage","limit":1,"style":"campaign_short_final_v1","selection_mode":"fresh_best_candidate","freshness_ladder_hours":[24,48,72,96,120]}}
```

Retime one existing review kit:

```json
{"intent":"retime_review_kit_captions","campaign_slug":"yourrage","requested_by":"clip-review","payload":{"clip_id":"clip_example","min_votes":3}}
```

Review/risk sweep:

```json
{"intent":"review_risk_sweep","requested_by":"clip-review","payload":{}}
```

Publish dry-run:

```json
{"intent":"publish_dry_run","requested_by":"clip-ops","payload":{"publish_job_id":"pubjob_example"}}
```

Publish schedule tick:

```json
{"intent":"publish_schedule_tick","requested_by":"publish-scheduler","payload":{}}
```

Approving a non-demo review kit through the GUI creates or updates its publish package, then schedules one dry-run publish job into the next future local `:14` slot. The default cadence is eight slots per day: `00:14`, `03:14`, `06:14`, `09:14`, `12:14`, `15:14`, `18:14`, and `21:14`. Scheduled dry-runs stay in `publish_jobs` as `scheduled` until `/api/publish/schedule/tick` promotes due jobs into `publish_dry_run` Hermes work.

Live publish is allowed only after the backend publish job exists, the kit is approved, provider key is configured locally, warm-up is complete, live mode is enabled, and the GUI final confirmation has created the `publish_live` job.

## Read-Only Endpoints

Use freely for status:

- `GET /api/health`
- `GET /api/readiness`
- `GET /api/agents`
- `GET /api/jobs`
- `GET /api/review-kits`
- `GET /api/review-schedule`
- `GET /api/review-learning`
- `GET /api/campaign-projects`
- `GET /api/platforms`
- `GET /api/publish/status`
- `GET /api/audit`

## State-Changing Endpoints

Use only when the operator or GUI requested the action:

- `POST /api/jobs`
- `POST /api/jobs/{id}/claim`
- `POST /api/jobs/{id}/heartbeat`
- `POST /api/jobs/{id}/complete`
- `POST /api/jobs/{id}/block`
- `POST /api/jobs/{id}/fail`
- `POST /api/review-schedule/tick`
- `POST /api/review-schedule/{campaign_slug}/pause`
- `POST /api/review-schedule/{campaign_slug}/resume`
- `POST /api/review-kits/{id}/publish-prep`
- `POST /api/review-kits/{id}/approve`
- `POST /api/review-kits/{id}/reject`
- `POST /api/publish/schedule/tick`
- `POST /api/publish/jobs`
- `POST /api/publish/jobs/{id}/confirm-live`

Approval, rejection, and live confirmation are human-owned GUI decisions. Rejection stores learning signal and must not directly revise the killed draft unless the operator explicitly requests a revision pass.
