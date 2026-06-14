# Changelog

All notable operator-facing and friend-installable changes are tracked here.

## v0.2.0 - 2026-06-14

### Added

- Local browser cockpit as the primary Clipping Ops UI, served from `http://127.0.0.1:8765/app`.
- MiniMax/Hermes setup and verification scripts for the `clipping-ops-minimax` profile.
- Fresh review factory scheduling: three active campaigns, eight kits per campaign per local day, 24 review kits max per day.
- Freshness ladder and quota recovery for clip sourcing: 24h, 48h, 72h, 4d, 5d, then older recovery windows when newer supply is exhausted.
- Deterministic hook-quality gate that blocks generic, duplicated, raw-title, quote-dump, or internal-language hooks before render.
- Approval-to-publish queue: approved kits automatically create Upload-Post publish packages and scheduled dry-run jobs.
- Publish slots ending in `:14`, defaulting to `00:14`, `03:14`, `06:14`, `09:14`, `12:14`, `15:14`, `18:14`, and `21:14`.
- Future scheduled dry-run rebalancing to avoid back-to-back same-streamer posts when another approved campaign is available.
- Publish schedule tick that promotes due scheduled dry-runs into Hermes `publish_dry_run` jobs.
- Backlog self-heal: already-approved unslotted kits are picked up by the publish schedule tick.
- Web/browser QA scripts and route smoke tests for GitHub-bound verification.

### Changed

- Removed the retired SwiftPM native cockpit from the shipped repo; the supported app is now the local web cockpit.
- Review approval copy now reflects the real behavior: approval schedules dry-run prep, not live posting.
- Settings publish controls now use backend modes `dry_run` and `live`.
- Review cards and detail panels show publish slot, state, and stage.
- Hermes installer now creates both the review scheduler tick and publish schedule tick as no-agent cron jobs.
- Release metadata bumped to `0.2.0`; backend API version is `2026-06-14-approval-slots-04`.

### Safety

- Live Upload-Post remains blocked unless the kit is approved, provider key exists locally, warm-up is complete, live mode is enabled, and the GUI final confirmation queues a live job.
- Dry-run jobs validate request payloads and sidecars without uploading.
- Secrets, runtime media, browser state, local databases, and generated review artifacts remain excluded from GitHub.

### Verification

- `PYTHONPATH=backend backend/.venv/bin/python -m unittest tests.test_backend_smoke` passed with 81 tests and 1 expected skip.
- `npm run build` passed for the web cockpit.
- `./script/build_and_run.sh --verify` passed against the local backend and built app.
- `script/web_app_smoke.py` passed all six routes.
- `script/web_browser_qa.mjs` passed desktop routes, mobile dashboard, review filters/search, platform overlays, and console/page-error checks.
- `script/security_scan.py` reported `finding_count=0`.

### Compatibility Notes

- Existing local installs should rerun `./script/install_hermes_clip_ops.sh` so the new `clip-ops publish schedule tick` cron exists.
- Any already-approved unslotted kits can be backfilled by running `PYTHONPATH=backend backend/.venv/bin/python script/publish_schedule_tick.py --json`.
- GitHub Releases should use `docs/release-notes/v0.2.0.md` as the human-readable release body.
