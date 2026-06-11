# Agent Start Here

You are an incoming Codex, Claude, MiniMax, Hermes-backed, or other coding-agent session. This repo is already the machine. Do not ask the operator to re-explain the clipping pipeline before you read and run the repo instructions.

## First Rule

Work from repository truth:

- Read this file first.
- Read `docs/AI_AGENT_OPERATING_CONTRACT.md` second.
- Run the incoming verification command before claiming anything works.
- Treat SQLite/backend as source of truth.
- Treat Hermes as orchestration.
- Treat scripts as deterministic media/test workers.
- Treat Discord as notifications only.
- Treat the browser cockpit at `http://127.0.0.1:8765/app` as the human approval surface.

## One Command Start

From a fresh clone:

```bash
./script/verify_incoming_clone.sh
```

Expected result in a no-key clone:

- Build/tests/smoke/security should pass.
- Twitch, Kick, Upload-Post, Clipping.net, and social-account credentials should be reported missing or blocked.
- Missing credentials are expected blockers, not setup failure.
- Live posting must remain locked.

## Read These Next

- `docs/COMMAND_COOKBOOK.md` for exact commands.
- `docs/HERMES_JOB_CONTRACT.md` for job/API rules.
- `docs/CODEX_HANDOFF_BOOK.md` for the full incoming operating manual.
- `docs/caption-style.md` for caption/top-card/timing rules.
- `docs/campaign-selection.md` for campaign and source-selection rules.
- `docs/streamer-composition.md` for streamer framing rules.
- `docs/safety-gates.md` for hard stops.

## Do Not Improvise

Never invent source proof, campaign rules, subtitles, API success, review approval, or readiness. If something is red or yellow, report the blocker and the exact next safe action.

Never copy or export API keys, Upload-Post keys, Hermes auth, Discord tokens, browser sessions, Keychain items, `.env` files, SQLite databases, source media, or rendered review kits.

Do not run foreground mouse-driven GUI QA on an operator's active Mac unless the operator explicitly asks for it. Prefer backend/API/script verification.

## Current Product Shape

The repo is a source-build local web cockpit plus Python backend, not a prebuilt notarized app and not a media drop. Each operator supplies their own credentials, Hermes profile, Discord config, campaign access, account warm-up, and final posting confirmations.

Normal operation:

```bash
./script/build_and_run.sh --verify
./script/build_and_run.sh
```

Then open `http://127.0.0.1:8765/app`. The Swift app in `Sources/ClippingOpsCockpit` is legacy reference during migration, not the supported buddy UI.

Live Upload-Post work is intentionally locked until account warm-up is complete and the operator provides their own key locally.
