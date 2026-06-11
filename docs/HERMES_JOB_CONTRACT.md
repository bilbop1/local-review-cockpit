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
| `platform_smoke` | Run Twitch/Kick smoke checks | `{"twitch_login":"yourragegaming"}` or `{"kick_slug":"name"}` |
| `selected_feeder_sweep` | Check configured streamer feeders | `{}` |
| `review_risk_sweep` | Audit review kits and blockers | `{}` |
| `prepare_publish_package` | Prepare an approved kit for posting | `{"kit_id":"kit_x"}` |
| `publish_dry_run` | Validate publish payload without posting | `{"publish_job_id":"pubjob_x"}` |
| `publish_live` | Live Upload-Post job after final confirmation | `{"publish_job_id":"pubjob_x"}` |
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
  -d '{"worker":"hermes-dispatcher","hermes_profile":"default"}'
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

Review/risk sweep:

```json
{"intent":"review_risk_sweep","requested_by":"clip-review","payload":{}}
```

Publish dry-run:

```json
{"intent":"publish_dry_run","requested_by":"clip-ops","payload":{"publish_job_id":"pubjob_example"}}
```

Live publish is allowed only after the backend publish job exists, the kit is approved, provider key is configured locally, warm-up is complete, live mode is enabled, and the GUI final confirmation has created the `publish_live` job.

## Read-Only Endpoints

Use freely for status:

- `GET /api/health`
- `GET /api/readiness`
- `GET /api/agents`
- `GET /api/jobs`
- `GET /api/review-kits`
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
- `POST /api/review-kits/{id}/publish-prep`
- `POST /api/publish/jobs`
- `POST /api/publish/jobs/{id}/confirm-live`

Approval, rejection, and live confirmation are human-owned GUI decisions.
