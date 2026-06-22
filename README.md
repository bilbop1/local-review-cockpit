# Local Review Cockpit

Local Review Cockpit is a browser-based local control cockpit and backend for running agent-assisted review work while keeping private account credentials and posting power locked to the local operator's machine.

I built it because most agent demos stop at "the model wrote a draft." The work after that is where things usually break: source checks, queue state, review notes, retry logic, rendered previews, safety gates, and a human sign-off that is hard to skip by accident.

The current build is aimed at short-form video operations, but the pattern is broader than that. Keep the sensitive data local. Let agents propose, prepare, and schedule work. Make deterministic scripts handle the parts that need to be repeatable. Put posting behind profile locks, warm-up checks, and explicit local approval.

This public repo is source-only. It does not include API keys, Upload-Post keys, Hermes auth, Discord tokens, browser sessions, Keychain exports, private SQLite data, source media, rendered videos, payout pages, or account credentials.

## AI Agents Start Here

If you are Codex, Claude, MiniMax, Hermes-backed, or another coding agent, read [AGENT_START_HERE.md](AGENT_START_HERE.md) before doing anything else.

The low-quota incoming path is:

```bash
./script/verify_incoming_clone.sh
```

That command verifies the source-build clone without requiring secrets. Missing Twitch/Kick/Upload-Post credentials are expected in no-key mode.

For a guided new-operator install, hand Codex the repo URL plus the install-mode prompt below. The setup flow verifies no-key mode first, verifies existing Hermes/MiniMax without disturbing other Hermes profiles, stores local Twitch/Kick/Upload-Post credentials, locks one Upload-Post profile, then queues the first campaign research/build wave.

## Give Codex This Starting Command

```text
Get into Clipping Ops installation mode for this repo:
https://github.com/bilbop1/local-review-cockpit

Assume I am not technical. Clone the repo, then read AGENT_START_HERE.md and docs/codex-buddy-bootstrap.md before changing anything. Explain in plain English what you need, ask me for one thing at a time, and do not ask me to edit files manually unless there is no safer option.

After the no-key clone check passes, run ./script/codex_buddy_bootstrap.sh and guide me through the prompts. First verify whether Hermes is already wired to the `clipping-ops-minimax` / MiniMax-M3 profile. Only ask me for a MiniMax API key if Hermes is not already wired or Codex cannot use the existing MiniMax setup. Otherwise ask me for: Twitch client ID and secret, Kick client ID and secret if I have Kick, Upload-Post API key, exact Upload-Post profile name, whether TikTok is warmed, and whether to turn on approved-kit auto-posting. If I do not know where to find one of those, walk me through it in the browser.

Be careful with my existing Hermes install. Do not delete, rename, overwrite, repair, or reconfigure my existing Hermes profiles, default profile, cron jobs, auth files, aliases, or unrelated profile `.env` files. Install Clipping Ops beside them under its own `clipping-ops-minimax` sidecar profile and Clipping Ops scripts/jobs only. If that sidecar profile is missing, create only that profile after explaining it. Leave everything else in Hermes running and operable as-is.

Never print, commit, or store secrets in repo files. Store secrets only through the provided local scripts/Keychain flow. Keep posting TikTok-only unless I explicitly say another platform is warmed. When setup is done, verify http://127.0.0.1:8765/app works, queue starter campaign research/build jobs, and tell me to review first kits at http://127.0.0.1:8765/app/reviews in about 45-90 minutes.
```

## What Is In The Repo

- A React/Vite browser cockpit in `web/`, served locally at `http://127.0.0.1:8765/app`.
- A Python backend in `backend/clipping_ops_backend` with SQLite-backed state, render queue handling, platform models, credentials helpers, publish gates, and local API routes.
- Hermes prompt files in `hermes/` for research, review, and ops work.
- Scripts for setup, smoke tests, headless web QA, render validation, source reconciliation, and review-kit generation.
- Operator docs for startup, safety gates, OAuth setup, caption style, Discord handoff, incoming agent setup, and release readiness.

## Why It Exists

Agents are useful when they can do boring maintenance work all day and still leave a clear trail for the person responsible. This project is my attempt to make that real in a local tool:

- Review queues are visible instead of buried in chat history.
- Agent jobs are explicit instead of vague instructions.
- Rendered outputs need local previews before they can move forward.
- Risky actions stay behind hard gates.
- The operator can see what changed, what failed, and what still needs a decision.

## Quick Start

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/setup_buddy_no_key.sh
./script/build_and_run.sh --verify
```

For the streamlined buddy install that asks for local keys and queues the first review work:

```bash
./script/codex_buddy_bootstrap.sh
```

Run the cockpit:

```bash
./script/build_and_run.sh
```

The run script starts the local backend at `http://127.0.0.1:8765`, builds the web app, and prints the browser URL:

```text
http://127.0.0.1:8765/app
```

For UI development, use:

```bash
./script/build_and_run.sh --dev
```

That starts Vite at `http://127.0.0.1:5173/app` with API proxying to the local backend. The built `/app` remains dynamic through API polling; it is not a static screenshot dashboard.

## Useful Commands

```bash
./script/verify_incoming_clone.sh
./script/smoke_test.sh
./script/setup_buddy_no_key.sh
./script/codex_buddy_bootstrap.sh
./script/install_hermes_clip_ops.sh
./script/configure_minimax_hermes_local.sh
./script/verify_minimax_hermes.sh
./script/store_credentials_keychain.sh
PYTHONPATH=backend backend/.venv/bin/python script/queue_buddy_campaign_kickoff.py --dry-run --json
./script/install_backend_launch_agent.sh
./script/run_ceo_readiness_suite.sh
./script/security_scan.py
./script/render_demo_kits.sh
```

The supported UI is the browser cockpit. Native Swift/macOS app code has been removed from the repo.

## Safety Model

- No posting before approved review kit, provider readiness, exact Upload-Post profile lock, selected-platform warm-up, and either local auto-post arming or final GUI confirmation.
- Upload-Post defaults to TikTok only; Instagram, YouTube, Facebook, and X stay blocked for posting until each account is warmed and explicitly enabled in local settings.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render before the campaign research gate passes.
- No "ready to post" state without a local preview video.
- Rejections require notes and become future-selection learning signal, not a direct draft revision.

The point is not to make the agent timid. The point is to give it a real lane.

## Daily Review Factory

The supported production rhythm is MiniMax-powered Hermes indexing top streamer clips from the freshest window first: 24h, then 48h, 72h, 4d, and 5d only when the fresher windows are empty or stale. The scheduler queues at most one review kit per active campaign every three hours: three campaigns, eight per campaign, 24 max per local day. The user approves winners and kills weak kits with notes; approvals auto-create publish prep and schedule the next future local `:14` slot. If the local profile is live-ready and auto-post is armed, due approved jobs post through Upload-Post; otherwise they stay in check/manual-confirm mode.

## Local Data

Runtime data lives under:

```text
~/Library/Application Support/ClippingOpsCockpit
```

Do not commit or transfer `.env` files, API keys, Upload-Post keys, Hermes auth, Discord tokens, Keychain items, local databases, browser profiles, source media, or rendered review kits.

## Maintainer Notes

For the OpenAI Codex for Open Source program and similar maintainer reviews, see [docs/maintainer-workflows.md](docs/maintainer-workflows.md).

Full setup, campaign, subtitle timing, Hermes, Discord, and safety instructions live in [docs/CODEX_HANDOFF_BOOK.md](docs/CODEX_HANDOFF_BOOK.md).

Canonical agent docs:

- [Agent start here](AGENT_START_HERE.md)
- [AI agent operating contract](docs/AI_AGENT_OPERATING_CONTRACT.md)
- [Command cookbook](docs/COMMAND_COOKBOOK.md)
- [Hermes job contract](docs/HERMES_JOB_CONTRACT.md)
- [Codex buddy bootstrap](docs/codex-buddy-bootstrap.md)
- [Codex first-time setup](docs/codex-first-time-setup.md)
- [v0.3.2 release notes](docs/release-notes/v0.3.2.md)
- [Campaign selection standard](docs/campaign-selection.md)
- [Caption style standard](docs/caption-style.md)
- [Streamer composition standard](docs/streamer-composition.md)
