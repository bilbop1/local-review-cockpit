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

Builds the SwiftPM app, stages `dist/Clipping Ops Cockpit.app`, starts the backend, and verifies launch wiring.

```bash
./script/build_and_run.sh
```

Starts the backend and opens the macOS app for normal operator use.

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
swift build
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s tests -v
./script/smoke_test.sh
backend/.venv/bin/python script/security_scan.py
```

These are the baseline non-foreground checks. Do not replace them with visual confidence.

## No-Key Proof

```bash
CLIPPING_OPS_NO_KEY=1 ./script/setup_buddy_no_key.sh
```

Expected: Twitch, Kick, and Upload-Post credentials are missing; production/live posting remains blocked; demo/local proof can run.

## Credential Storage

```bash
./script/store_credentials_keychain.sh
```

Stores the local operator's Twitch/Kick/optional Upload-Post values in macOS Keychain under this app's service. Do not commit, print, or export those values.

## Hermes Local Checks

```bash
hermes status
hermes cron list
./script/install_hermes_clip_ops.sh
PYTHONPATH=backend backend/.venv/bin/python script/hermes_job_dispatcher.py --limit 1 --json
```

`install_hermes_clip_ops.sh` is optional convenience. A local Hermes profile must already exist on the operator's machine.

## Queue A Job

```bash
curl -s -X POST http://127.0.0.1:8765/api/jobs \
  -H 'Content-Type: application/json' \
  -d '{"intent":"review_risk_sweep","requested_by":"incoming-agent","payload":{}}'
```

Queues work through the Hermes-native ledger. Do not bypass this path in normal workflow.

## Caption And Composition Audits

```bash
PYTHONPATH=backend backend/.venv/bin/python script/verify_burned_in_captions.py
PYTHONPATH=backend backend/.venv/bin/python script/verify_streamer_composition.py
PYTHONPATH=backend backend/.venv/bin/python script/audit_live_top_cards.py --refresh
```

Use after real review kits exist. Sidecar text alone does not prove visible subtitles or top-card parity.

## Publish Dry-Run Status

```bash
curl -s http://127.0.0.1:8765/api/publish/status
```

Expected before warm-up/key setup: yellow, key missing, warm-up incomplete, live not ready. That is correct.

## GUI QA Boundary

Do not run `script/desktop_qa.py` on an active user desktop unless the operator explicitly approves foreground interaction. Prefer API/script proof for incoming setup.
