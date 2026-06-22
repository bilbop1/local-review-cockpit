# AI Agent Operating Contract

This contract is for any incoming model working from this GitHub repo, including weaker or cheaper models. Follow it literally.

## Non-Negotiables

- Backend/SQLite is the source of truth. Do not use Discord, prose, or memory as state.
- Hermes is orchestration. Deterministic scripts do source checks, downloads, transcription, rendering, validation, and tests.
- Clipping Ops Hermes must use the local `clipping-ops-minimax` profile with MiniMax for normal operation. Codex/OpenAI fallback is not green readiness proof.
- Existing Hermes installs are user-owned. Do not delete, rename, overwrite, repair, or reconfigure default/other Hermes profiles, auth files, aliases, unrelated `.env` files, or non-Clipping-Ops cron jobs. Install Clipping Ops as a sidecar under `clipping-ops-minimax`.
- GUI approval is human-owned. Agents may recommend, queue, validate, or report. Agents may not approve review kits or confirm live posts.
- No fake readiness. Green means fresh proof from tests, API responses, artifacts, or backend records.
- No source invention. A clip is not production-proof until it has campaign rules, source URL, provenance, local media, transcript timing, rendered video, sidecars, and validation.
- No content generation for clipping campaigns unless the campaign explicitly provides that brief and the operator approves that new lane. The normal lane is clipping verified source media.
- No key transfer. Never copy, print, commit, zip, diagnose, or export API keys, Upload-Post keys, Hermes auth, Discord tokens, browser cookies, Keychain items, `.env` values, SQLite databases, source media, or rendered kits.
- No live posting unless the backend gates pass: approved kit, provider key configured locally, exact local Upload-Post profile configured, account warm-up complete, live provider readiness, and local auto-post enablement or final GUI confirmation.
- No payouts, account connections, account rebrands, gambling/affiliate/legal clearance, or revenue guarantees.
- No foreground mouse-driven GUI testing unless the operator explicitly grants permission for that run.

## Stop And Report Table

| State | Meaning | Required Agent Behavior |
| --- | --- | --- |
| Red readiness row | Blocked or false | Stop that lane, report blocker and exact next safe command. |
| Yellow readiness row | Not done or missing proof | Do not call ready; report missing proof. |
| Missing credentials in no-key mode | Expected | Say setup is isolated correctly; ask operator to provide their own keys only when needed. |
| Metadata-only clip | Index candidate only | Do not render as production proof. |
| Missing local source media | Source not verified | Run source discovery/download route or report blocked. |
| Subtitle verifier failure | Render not acceptable | Rebuild transcript/timing/render; do not approve. |
| Campaign lacks linked media/source route | Source proof missing | Exclude or keep yellow; do not content-generate filler. |
| Hermes unavailable/degraded | Orchestration not ready | Keep direct fallback advanced-only; do not claim Hermes-native ready. |
| MiniMax profile missing | Wrong model lane | Configure local Hermes/MiniMax; do not spend Codex quota as the normal path. |
| Fresh 24h clips missing | Supply thin | Expand only to 48h, 72h, 4d, then 5d; do not jump to old broad lookbacks. |
| Upload-Post key missing/warm-up incomplete | Live posting locked | Keep auto-post off and use package checks only. |

## Required Incoming Flow

1. Read `AGENT_START_HERE.md`.
2. Run `./script/verify_incoming_clone.sh`.
3. If it fails, fix only the reported local setup issue, then rerun.
4. Read `/api/health`, `/api/readiness`, and `/api/agents` before making readiness claims.
5. Use `docs/COMMAND_COOKBOOK.md` for commands instead of inventing your own.
6. Use `docs/HERMES_JOB_CONTRACT.md` for jobs instead of bypassing the job ledger.
7. Use `docs/caption-style.md`, `docs/campaign-selection.md`, and `docs/streamer-composition.md` before rendering or judging clips.
8. Use rejection notes as future-selection learning signal. Do not directly revise killed drafts unless the operator explicitly asks.

## Output Format For Agent Reports

Use this shape when reporting status:

```text
Status: green|yellow|red
Evidence: endpoint/artifact/command used
Blockers: exact blockers or none
Next safe action: one command or one GUI action
No-go actions: keys/auth/posting/payout/account actions that remain blocked
```

Do not bury uncertainty in optimistic language. Truth beats momentum.
