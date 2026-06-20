# Safety Gates

The backend blocks or refuses work when an action would mutate an external account or claim an unverified production state.

## Readiness Standard

- Green means a feature has a live test, local artifact, screenshot, ffprobe result, API check row, or audit event behind it.
- Yellow means the local/demo surface works, but production evidence is incomplete.
- Red means the system must not be represented as production-ready.

Blocked by default:

- Social posting unless the review kit is approved, the Upload-Post/provider key is configured outside the repo, the exact local Upload-Post profile is configured, selected-platform warm-up is complete, live mode is enabled, and the GUI final confirmation is given
- Payout submission
- Account connection
- Account rebrand
- Gambling or affiliate approval
- Clipping.net submission automation
- Campaign-specific Hermes memory before feeder qualification
- Real campaign rendering before campaign rules and source routes are verified

Allowed locally:

- Health checks
- Demo renders from local media
- Demo review-kit approval as `demo_reviewed`
- Manual publishing prep and Upload-Post dry-run validation only for approved non-demo kits after campaign gate qualification
- Confirmation-gated Upload-Post live jobs after selected-platform warm-up and provider readiness
- Rejection with notes
- Audit logging

## Required CEO Evidence

- `/api/health`, `/api/readiness`, and `/api/platforms` JSON from the running backend.
- web build/typecheck, backend unit tests, `/app` smoke proof, and non-foreground browser QA when available.
- Redacted Twitch and Kick smoke check rows with HTTP status and rate-limit/degraded-state details.
- Review-kit files: `review.mp4`, `caption.txt`, `transcript.txt`, `checklist.md`, `source.md`, and `risk.md`.
- `ffprobe` JSON proving H.264/AAC 1080x1920 output.
- Campaign evidence screenshots and extracted text before any real campaign render.
- Secret scan proving no API keys, tokens, browser sessions, or Keychain items are exported.
- Publish status proof from `/api/publish/status` showing dry-run/live provider readiness without exposing API keys.

AI agents must also follow `docs/AI_AGENT_OPERATING_CONTRACT.md`. If a model is unsure whether an action is allowed, the action is blocked until the operator explicitly approves it.
