# Local Review Cockpit

Local Review Cockpit is a macOS app and local backend for running agent-assisted review work without letting the agent publish, spend money, or touch private account credentials.

I built it because most agent demos stop at "the model wrote a draft." The work after that is where things usually break: source checks, queue state, review notes, retry logic, rendered previews, safety gates, and a human sign-off that is hard to skip by accident.

The current build is aimed at short-form video operations, but the pattern is broader than that. Keep the sensitive data local. Let agents propose and prepare work. Make deterministic scripts handle the parts that need to be repeatable. Put the final call in front of a human.

## What is in the repo

- A SwiftPM macOS cockpit app in `Sources/ClippingOpsCockpit`.
- A Python backend in `backend/clipping_ops_backend` with SQLite-backed state, render queue handling, platform models, credentials helpers, and local API routes.
- Hermes prompt files in `hermes/` for research, review, and ops work.
- Scripts for setup, smoke tests, desktop QA, release checks, render validation, source reconciliation, and review-kit generation.
- Operator docs for startup, safety gates, OAuth setup, caption style, Discord handoff, and release readiness.

This public repo is source-only. It does not include API keys, browser sessions, Keychain exports, private SQLite data, source media, rendered videos, payout pages, or account credentials.

## Why it exists

Agents are useful when they can do boring maintenance work all day and still leave a clear trail for the person responsible. This project is my attempt to make that real in a local tool:

- Review queues are visible instead of buried in chat history.
- Agent jobs are explicit instead of vague instructions.
- Rendered outputs need local previews before they can move forward.
- Risky actions stay behind hard gates.
- The operator can see what changed, what failed, and what still needs a decision.

## Quick start

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/setup_buddy_no_key.sh
./script/build_and_run.sh --verify
```

Run the app:

```bash
./script/build_and_run.sh
```

The run script starts the local backend at `http://127.0.0.1:8765`, builds the SwiftPM app, stages `dist/Clipping Ops Cockpit.app`, and launches it as a foreground macOS app.

## Useful commands

```bash
./script/smoke_test.sh
python3 script/desktop_qa.py
./script/run_ceo_readiness_suite.sh
./script/verify_release.sh
./script/security_scan.py
./script/render_demo_kits.sh
```

## Safety model

- No autonomous publishing.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render before the campaign research gate passes.
- No "ready to post" state without a local preview video.
- Rejections require notes and create a revision request.

The point is not to make the agent timid. The point is to give it a real lane.

## Local data

Runtime data lives under:

```text
~/Library/Application Support/ClippingOpsCockpit
```

Do not commit `.env` files, API keys, Hermes auth, Discord tokens, Keychain items, local databases, browser profiles, or media assets.

## Maintainer notes

For the OpenAI Codex for Open Source program and similar maintainer reviews, see [docs/maintainer-workflows.md](docs/maintainer-workflows.md).

Full setup and operator details live in [docs/CODEX_HANDOFF_BOOK.md](docs/CODEX_HANDOFF_BOOK.md).
