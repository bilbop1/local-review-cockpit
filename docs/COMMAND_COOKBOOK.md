# Command Cookbook

Use these commands exactly before improvising. Run from the repository root.

## Fresh Clone Verification

```bash
./script/verify_incoming_clone.sh
```

Runs no-key setup, build/test/smoke/security checks, and prints the next missing operator actions. Success still reports credentials as missing because this repo does not ship secrets.

## Build And Launch

```bash
./script/build_and_run.sh --verify
```

Builds the browser cockpit, starts the backend, and verifies `/app` loads from `http://127.0.0.1:8765/app`.

```bash
./script/build_and_run.sh
```

Starts the backend, builds the browser cockpit, and prints the local URL for normal operator use.

```bash
./script/build_and_run.sh --dev
```

Runs Vite at `http://127.0.0.1:5173/app` with `/api` and `/media` proxied to the local backend. Use this when changing the UI.

## Backend Health

```bash
./script/start_backend.sh start
curl -s http://127.0.0.1:8765/api/health
curl -s http://127.0.0.1:8765/api/readiness
curl -s http://127.0.0.1:8765/api/agents
```

Use these before claiming readiness. Red/yellow rows are blockers or missing proof.

## Tests

```bash
npm --prefix web run typecheck
npm --prefix web run build
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s tests -v
./script/smoke_test.sh
backend/.venv/bin/python script/web_app_smoke.py
backend/.venv/bin/python script/security_scan.py
```

These are the baseline non-foreground checks. Do not replace them with visual confidence.

## No-Key Proof

```bash
CLIPPING_OPS_NO_KEY=1 ./script/setup_buddy_no_key.sh
```

Expected: Twitch, Kick, and Upload-Post credentials are missing; production/live posting remains blocked; demo/local proof can run.

## Guided Buddy Install

Give a non-technical operator this Codex starting command first:

```text
Get into Clipping Ops installation mode for https://github.com/bilbop1/local-review-cockpit. Assume I am not technical. Clone the repo, read AGENT_START_HERE.md and docs/codex-buddy-bootstrap.md, then run ./script/codex_buddy_bootstrap.sh. Ask me for one thing at a time in plain English: MiniMax API key, Twitch client ID/secret, Kick client ID/secret if I have Kick, Upload-Post API key, exact Upload-Post profile name, TikTok warm-up status, and whether to turn on approved-kit auto-posting. Do not print, commit, or store secrets in repo files.
```

```bash
./script/codex_buddy_bootstrap.sh
```

Runs the friend-install rail: no-key verification, local MiniMax/Hermes setup, Keychain credential prompts, exact Upload-Post profile lock, startup/Hermes job installation, and starter campaign job queueing. Use `--dry-run` to print the plan without changing local settings.

## Credential Storage

```bash
./script/store_credentials_keychain.sh
```

Stores the local operator's Twitch/Kick/optional Upload-Post values in macOS Keychain under this app's service. Do not commit, print, or export those values. Add Upload-Post last; TikTok is the default publish platform, and Instagram/YouTube/Facebook/X should stay blocked for posting until each account is warmed locally.

The Upload-Post profile name is not a secret, but it is a safety lock. Set it through the Settings page or through `./script/codex_buddy_bootstrap.sh`; every publish request uses that one local profile.

## Hermes Local Checks

```bash
./script/configure_minimax_hermes_local.sh
./script/verify_minimax_hermes.sh
hermes status
hermes cron list
./script/install_hermes_clip_ops.sh
PYTHONPATH=backend backend/.venv/bin/python script/hermes_job_dispatcher.py --limit 1 --json
```

`install_hermes_clip_ops.sh` installs Clipping Ops jobs under `clipping-ops-minimax` by default. A local Hermes install must already exist on the operator's machine. The MiniMax key must be supplied locally; never paste it into repo files.

## Queue A Job

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"intent":"review_risk_sweep","requested_by":"incoming-agent","payload":{}}'
```

Queues work through the Hermes-native ledger. Do not bypass this path in normal workflow.

## Review Factory Scheduler

```bash
curl -s http://127.0.0.1:8765/api/review-schedule
PYTHONPATH=backend backend/.venv/bin/python script/review_schedule_tick.py --json
PYTHONPATH=backend backend/.venv/bin/python script/queue_buddy_campaign_kickoff.py --dry-run --json
```

Expected normal behavior: scheduler queues due `scheduled_campaign_review_build` jobs only, capped at 8 per campaign and 24 total per local day. Fresh indexing uses 24h first, then 48h, 72h, 4d, and 5d.

## Caption And Composition Audits

```bash
PYTHONPATH=backend backend/.venv/bin/python script/verify_burned_in_captions.py
PYTHONPATH=backend backend/.venv/bin/python script/verify_streamer_composition.py
PYTHONPATH=backend backend/.venv/bin/python script/audit_live_top_cards.py --refresh
```

Use after real review kits exist. Sidecar text alone does not prove visible subtitles or top-card parity.

## Publish Status And Auto-Post Gates

```bash
curl -s http://127.0.0.1:8765/api/publish/status
PYTHONPATH=backend backend/.venv/bin/python script/publish_schedule_tick.py --json
```

Expected before warm-up/key setup: yellow, key missing, warm-up incomplete, live not ready. That is correct. Expected before auto-post: approved jobs can be slotted, but due jobs do not live-post unless provider key, exact Upload-Post profile, warmed target platform, live mode, and local auto-post/manual confirmation all pass.

## GUI QA Boundary

Use `node script/web_browser_qa.mjs` for non-foreground web cockpit QA. There is no supported native desktop harness.
