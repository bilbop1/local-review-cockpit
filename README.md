# Local Review Cockpit

Local Review Cockpit is a browser-based local control cockpit and backend for running agent-assisted review work without letting the agent publish, spend money, or touch private account credentials.

I built it because most agent demos stop at "the model wrote a draft." The work after that is where things usually break: source checks, queue state, review notes, retry logic, rendered previews, safety gates, and a human sign-off that is hard to skip by accident.

The current build is aimed at short-form video operations, but the pattern is broader than that. Keep the sensitive data local. Let agents propose and prepare work. Make deterministic scripts handle the parts that need to be repeatable. Put the final call in front of a human.

This public repo is source-only. It does not include API keys, Upload-Post keys, Hermes auth, Discord tokens, browser sessions, Keychain exports, private SQLite data, source media, rendered videos, payout pages, or account credentials.

## AI Agents Start Here

If you are Codex, Claude, MiniMax, Hermes-backed, or another coding agent, read [AGENT_START_HERE.md](AGENT_START_HERE.md) before doing anything else.

The low-quota incoming path is:

```bash
./script/verify_incoming_clone.sh
```

That command verifies the source-build clone without requiring secrets. Missing Twitch/Kick/Upload-Post credentials are expected in no-key mode.

## What Is In The Repo

- A React/Vite browser cockpit in `web/`, served locally at `http://127.0.0.1:8765/app`.
- A Python backend in `backend/clipping_ops_backend` with SQLite-backed state, render queue handling, platform models, credentials helpers, publish gates, and local API routes.
- A legacy SwiftPM macOS cockpit in `Sources/ClippingOpsCockpit`, preserved as reference only during the web migration.
- Hermes prompt files in `hermes/` for research, review, and ops work.
- Scripts for setup, smoke tests, optional desktop QA, release checks, render validation, source reconciliation, and review-kit generation.
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
./script/install_hermes_clip_ops.sh
./script/store_credentials_keychain.sh
./script/install_backend_launch_agent.sh
./script/run_ceo_readiness_suite.sh
./script/verify_release.sh
./script/security_scan.py
./script/render_demo_kits.sh
```

Do not run `python3 script/desktop_qa.py` on an active user desktop unless the operator explicitly approves foreground GUI interaction. The supported UI is the browser cockpit.

`script/package_release.sh` is legacy/separate: Developer ID signing and notarization are only required when distributing a prebuilt native `.app`, not for this source-build web cockpit.

## Safety Model

- No posting before approved review kit, provider readiness, completed account warm-up, and final GUI confirmation.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render before the campaign research gate passes.
- No "ready to post" state without a local preview video.
- Rejections require notes and create a revision request.

The point is not to make the agent timid. The point is to give it a real lane.

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
- [Campaign selection standard](docs/campaign-selection.md)
- [Caption style standard](docs/caption-style.md)
- [Streamer composition standard](docs/streamer-composition.md)
