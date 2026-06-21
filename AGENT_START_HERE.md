# Agent Start Here

You are an incoming Codex, Claude, MiniMax, Hermes-backed, or other coding-agent session. This repo is already the machine. Do not ask the operator to re-explain the clipping pipeline before you read and run the repo instructions.

## First Rule

Work from repository truth:

- Read this file first.
- Read `docs/AI_AGENT_OPERATING_CONTRACT.md` second.
- Run the incoming verification command before claiming anything works.
- Treat SQLite/backend as source of truth.
- Treat Hermes as orchestration.
- Treat `clipping-ops-minimax` / `MiniMax-M3` as the normal Hermes profile/model for Clipping Ops.
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
- Live posting must remain locked until a local operator configures their own Upload-Post key, exact profile, warmed platform, live mode, and auto-post/manual confirmation.

For a friend/buddy install where the operator is ready to provide local keys, use:

```bash
./script/codex_buddy_bootstrap.sh
```

That guided path verifies no-key mode, checks existing MiniMax/Hermes wiring before asking for any MiniMax key, stores local Twitch/Kick/Upload-Post credentials, locks the operator's exact Upload-Post profile, installs startup/Hermes jobs, and queues first campaign research/build jobs. If the operator is not technical, enter installation mode: ask for one credential at a time in plain English and guide them through finding keys in the browser rather than asking them to edit files manually.

## Read These Next

- `docs/COMMAND_COOKBOOK.md` for exact commands.
- `docs/HERMES_JOB_CONTRACT.md` for job/API rules.
- `docs/CODEX_HANDOFF_BOOK.md` for the full incoming operating manual.
- `docs/caption-style.md` for caption/top-card/timing rules.
- `docs/campaign-selection.md` for campaign and source-selection rules.
- `docs/streamer-composition.md` for streamer framing rules.
- `docs/safety-gates.md` for hard stops.

## MiniMax Hermes Factory

Normal production review flow is not a broad 35-day scrape. Hermes should index top Twitch clips from the last 24 hours first, then widen only if supply is stale or empty: 48h, 72h, 4d, then 5d. The review factory target is three active streamer campaigns, one kit per campaign every three hours, capped at eight per campaign and 24 total per local day.

Use `./script/configure_minimax_hermes_local.sh` only on the operator's own machine to store their MiniMax key locally. Then run `./script/verify_minimax_hermes.sh` and `./script/install_hermes_clip_ops.sh`. Never commit or print the key.

## Do Not Improvise

Never invent source proof, campaign rules, subtitles, API success, review approval, or readiness. If something is red or yellow, report the blocker and the exact next safe action.

Never copy or export API keys, Upload-Post keys, Hermes auth, Discord tokens, browser sessions, Keychain items, `.env` files, SQLite databases, source media, or rendered review kits.

Do not run foreground mouse-driven GUI QA on an operator's active Mac unless the operator explicitly asks for it. Prefer backend/API/script verification.

## Current Product Shape

The repo is a source-build local web cockpit plus Python backend, not a media drop and not a native app bundle. Each operator supplies their own credentials, Hermes profile, Discord config, campaign access, account warm-up, and posting enablement. Upload-Post is always locked to one exact local profile name; jobs must not pick alternate Upload-Post profiles.

Normal operation:

```bash
./script/build_and_run.sh --verify
./script/build_and_run.sh
```

Then open `http://127.0.0.1:8765/app`. There is no native Swift/macOS app path in this repo anymore; the browser cockpit is the only supported human UI.

Rejected review kits are killed, not revised directly. The rejection note becomes learning signal for the next cycle. Approved kits are scheduled into future `:14` slots. Live Upload-Post work is intentionally locked until account warm-up is complete, the operator provides their own key locally, the exact profile is configured, and auto-post or manual confirmation is enabled.
