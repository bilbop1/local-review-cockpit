# Clipping Ops Cockpit Codex Handoff Book

Generated for the local Clipping Ops Cockpit project. This is the guide to hand to another Codex or Hermes-backed coding session after the project is published as a public-but-lowkey source repo. It explains what the system is, what is intentionally not included, how to configure a no-key local copy, and how to keep campaign review quality high instead of filling the queue with random valid-but-boring clips.

Public source handoff target:

```text
https://github.com/bilbop1/local-review-cockpit
```

This repo is a source-build handoff, not a media drop and not a prebuilt notarized app. It contains the app/backend/scripts/docs/Hermes prompts needed for another session to rebuild and configure the same style of local pipeline without inheriting the original operator's secrets.

## Current Handoff Status

Current truthful state from the live backend on June 3, 2026:

- Buddy no-key setup: green.
- Codex source/build handoff: green.
- Public GitHub source handoff: green once the public repo is pushed and security scan is clean.
- Active validated review surface: 10 rendered campaign review kits.
- Operator approval: 10 active validated kits approved for manual prep.
- Rejected/unsafe review kits: 2 remain rejected for revision and are not part of the approved handoff batch.
- Active campaign counts in the approved batch: JasonTheWeen 4, YourRAGE 3, PlaqueBoyMax 3.
- Burned-in subtitle proof: green after fresh verification across all 10 active non-rejected kits.
- Internal local readiness: still yellow if the product target remains 5 kits per campaign / 15 total. The approved source handoff is allowed because the user intentionally accepted the current best batch instead of padding with weak filler.
- Customer/prebuilt app ship: yellow unless a Developer ID signed and notarized `.app` is produced. This does not block source-build GitHub handoff.

Do not call the system production-ready until `/api/readiness` says the intended target is green with fresh proof.

## What Must Happen Before Public Repo Handoff

1. Mark only validated active review kits approved. Do not approve kits that failed subtitle/editorial proof.
2. Keep generated review videos, downloaded source media, local SQLite, artifacts, Keychain items, Hermes auth, Discord tokens, and browser sessions out of git.
3. Regenerate or update docs so they describe source-build GitHub handoff, not a secret-bearing local zip.
4. Run the public-source checks:

```bash
swift build
cd backend && uv run python -m unittest discover -s ../tests -v
cd ..
./script/smoke_test.sh
./script/security_scan.py
uv run python script/verify_burned_in_captions.py
uv run python script/verify_streamer_composition.py
```

5. Create/push the public repo:

```bash
gh repo create bilbop1/local-review-cockpit --public --source=. --remote=origin --push
```

If the repo already exists, add it as `origin` and push `main`.

## What The System Is

Clipping Ops Cockpit is a local-first macOS clipping operations appliance.

The intended architecture is:

- Swift macOS GUI: simple human review cockpit.
- SQLite/backend: source of truth, safety gates, media records, audit log, job ledger, and artifacts.
- Hermes: normal orchestration layer for campaign refreshes, source discovery, review sweeps, and daily operations.
- Deterministic scripts: source download, transcription, ffmpeg rendering, validation, packaging, and tests.
- Discord: notifications only.
- Human operator: the only entity allowed to approve review kits.

The system is not:

- A cloud SaaS.
- An autopublisher.
- A payout submitter.
- A campaign account manager.
- A revenue guarantee.
- A way to transfer another user’s API keys or browser sessions.

## No-Key Buddy Setup

The public repo is for another Codex session that will build locally.

It must not include:

- Twitch or Kick secrets.
- Hermes auth.
- Discord tokens.
- `.env` files.
- macOS Keychain items.
- Browser session data.
- Signed-in Clipping.net cookies.
- Downloaded source videos.
- Rendered review videos.
- SQLite databases or app-support state.

The buddy’s Codex should clone the source package, install dependencies, and run:

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/setup_buddy_no_key.sh
./script/build_and_run.sh
```

No-key mode should show Twitch/Kick credentials as missing. That is correct. Demo mode can open and render local proof kits; production campaign jobs must block until the buddy supplies their own credentials and source access.

## Credential Setup Expectations

Each buddy must provide their own platform credentials.

Twitch:

- Client ID.
- Client secret.
- App token generated through the local credential script.
- Optional user OAuth only if future features need user-scoped actions.

Kick:

- Client ID.
- Client secret.
- App token/PKCE setup if their provider path requires it.
- Current status is monitor-only until Kick clip/source ingestion produces local media proof.

Hermes:

- A local Hermes installation.
- A working Hermes profile, usually `default`.
- Hermes cron/jobs installed from this repo.
- No copied auth from the original machine.

Discord:

- Exactly three clipping channels if Discord notifications are enabled:
  - `clip-ops-alerts`
  - `clip-ops-daily-brief`
  - `clip-ops-approvals`
- Discord never stores state. It only receives notifications that link back to backend records.

## Campaign Best Practices

Only build around campaigns that have a real viewer reason to watch.

Good campaign targets:

- Streamer-native.
- Daily or near-daily source supply.
- Public clips or VOD moments available through a verifiable route.
- Clear campaign brief and source permission expectations.
- Clips that can stand alone without long setup.
- Strong enough source velocity to reject most candidates.

Weak campaign targets:

- Brand/product explainers with no organic hook.
- Campaigns that require content generation rather than clipping source media.
- Campaigns with no linked source pack, no obvious source route, and no clear brief.
- Campaigns whose brief is so narrow that normal daily clips are invalid.
- Campaigns with no reason a normal Shorts/TikTok viewer would stop scrolling.

Current active campaigns and campaign URLs:

- YourRAGE: `https://clipping.net/dashboard/campaigns/yourrage-x-clipping`; active Twitch source route through `yourragegaming`; current high-quality candidate supply is thinner than expected.
- PlaqueBoyMax: `https://clipping.net/dashboard/campaigns/plaqueboymax-x-clipping`; active Twitch source route; watermark required.
- JasonTheWeen: `https://clipping.net/dashboard/campaigns/jasontheween-x-clipping`; active Twitch source route; watermark required; strongest current kit supply.

Current excluded or demoted campaigns:

- Lacy: demoted because the brief requires arrested/missing-in-action moments; normal Lacy clips do not count.
- Haste: excluded because no linked media/source pack was proven; making content from scratch is out of scope.
- Kalshi/Dunkman: archived from active review because they are less streamer-native and lower viewer-impetus for the current product goal.
- Doublelift: watchlist until fresh status and budget/freshness are reconfirmed.

## Source Verification Rules

A source is not verified just because a title exists in an API response.

A production review kit requires:

- Stored campaign rules.
- Source URL.
- Source route/provenance.
- Local media file.
- Source media provenance flag.
- Word-timed transcript.
- Rendered 1080x1920 H.264/AAC review video.
- Thumbnail/contact sheet.
- `ffprobe.json`.
- `caption.txt`.
- `transcript.txt`.
- `checklist.md`.
- `source.md`.
- `risk.md`.
- `style_critique.md`.
- `render_text_manifest.json`.
- `editorial_review.json`.

Metadata-only clips are useful for indexing, but they do not count as review proof.

## Editorial Gate Rules

This is the most important lesson from the build.

Mechanical validity is not editorial quality. A clip can pass ffprobe, subtitles, local media, and GUI playback while still being bad.

The system must reject:

- Random long VOD slices.
- Low-view clips below the campaign floor.
- Overlong clips above the current 52 second gate unless manually revised.
- Weak/generic titles like `a`, `.`, `gff`, `w`, `lol`, or similar.
- Metadata-only clips.
- Needlessly split facecam-top compositions.
- Clips that look like screen sampling instead of a coherent moment.
- Clips that are only included to hit a numeric target.

Current editorial floors:

- YourRAGE: 1,500 views.
- PlaqueBoyMax: 1,500 views.
- JasonTheWeen: 2,000 views.
- Max automatic duration: 52 seconds.

The system should prefer 9 good kits over 15 padded kits.

Do not let an automation create filler to satisfy a numeric target. If the suite is short, the correct state is yellow, not a pile of weak videos.

## Streamer Composition Rules

Default composition should preserve the natural source frame.

Do not automatically create a facecam top band just because a facecam-like corner was detected. That produced bad review kits.

Use split facecam only when all are true:

- The source is native landscape streamer footage.
- The main content would be lost in a normal vertical crop.
- The facecam is clearly separate and meaningful.
- The editor intentionally enables the split layout.
- A human visual review confirms the result is stronger.

For now, split facecam is disabled by default with `CLIPPING_OPS_ALLOW_FACE_CAM_SPLIT` unset.

## Caption Best Practices

Caption style is a production gate.

Current renderer rules:

- Font: TikTok Sans 36pt Black.
- Output size: 1080x1920.
- Burned-in subtitles only for campaign final renders.
- No internal labels in frames.
- No “selected feeder,” “proof,” “review kit,” “demo,” or “review-safe” text in rendered video.
- Maximum 2 words on screen per caption beat.
- Maximum 1 subtitle line visible at a time.
- Target maximum 12 characters for normal two-word beats.
- Use 1 word only for long words, emphasis, or timing.
- Captions should sit in the platform-safe lower-third band, currently y=1210-1400 on a 1080x1920 render, not dead center and not buried under TikTok/IG/Shorts UI.
- Use platform overlay previews in the GUI to verify subtitles are not covered.
- Timing should follow word-level transcript timing with the renderer's late-pop display windows. Do not solve early captions by shifting everything earlier or later blindly.
- Ensemble-consensus captions must still receive the render-time visual/audio delay. Do not bypass `apply_caption_audio_sync_delay()` just because multiple transcription models agree.
- Suspicious long word spans must be capped near the word end before caption grouping, otherwise subtitles can appear early while still passing naive sidecar checks.
- Big pauses between words must split caption groups. Do not join words across silence just to satisfy the two-word preference.
- One-vote and high-spread timing beats should be dropped or rejected for revision, not forced into a render.
- The verifier must pass `script/verify_burned_in_captions.py`; sidecar text alone does not prove visible subtitles.
- Any future caption timing changes must be validated against video pixels and audio, not just JSON.

Production A/B variants:

- A: white TikTok Sans with black stroke.
- B: yellow emphasis on the second word.
- D: white caption card with black text.
- E: white caption with cyan underline/accent.

Variant C is excluded.

## Review Workflow

The GUI Review Kits page is the human gate.

For each kit:

1. Watch the video with audio.
2. Check subtitles for timing, spelling, two-word rule, and safe placement.
3. Toggle TikTok/Instagram/YouTube Shorts overlays to check platform UI collisions.
4. Confirm the moment is actually compelling.
5. Confirm campaign and source details.
6. Approve only if it is worth manual prep.
7. Reject with notes if anything feels off.

Approval does not publish. It only marks the kit as approved for manual preparation.

## Readiness Rules

Green means backed by evidence. Yellow means not done. Red means blocked or false.

Important endpoints:

- `/api/readiness`
- `/api/review-kits`
- `/api/campaign-projects`
- `/api/platforms`
- `/api/agents`

Important artifacts:

- `artifacts/desktop-qa/manifest.json`
- `artifacts/review-kit-audit/latest.json`
- `artifacts/review-kit-audit/burned-caption-verification.json`
- `artifacts/review-kit-audit/streamer-composition-verification.json`
- `artifacts/security/security-scan.json`
- `artifacts/product-proof/artifact-summary.json`
- `artifacts/handoff/codex-handoff.json`

## Publication Rules

There are two different shipping lanes.

Public GitHub source handoff:

- Publish source/build scripts/docs to `bilbop1/local-review-cockpit`.
- No secrets.
- No downloaded source media.
- No rendered review videos.
- No local SQLite/app-support state.
- No Developer ID required.
- Buddy’s Codex/Hermes-backed session rebuilds locally.
- This is the intended buddy handoff.

Private offline Codex source zip:

- Optional fallback through `./script/package_codex_handoff.sh`.
- Same no-secret/no-media/no-database rules.
- Useful if GitHub is unavailable or a buddy cannot access the public repo.

Prebuilt Mac app handoff:

- Requires signed/notarized app for normal Mac users.
- Developer ID signing and notarization only matter here.
- This is not required for a Codex-to-Codex source handoff.

## Final Handoff Checklist

Before packaging:

- Active review surface has only current campaign kits.
- No demo/local proof kits appear in active Review Kits.
- No irrelevant old Lacy/TikTok/local clips appear.
- Every active kit has `editorial_review.json`.
- Every active kit has visible burned-in subtitles.
- Every active kit uses safe caption placement.
- Every active kit is source-backed.
- Every active kit has been reviewed in the GUI.
- Final target is explicit: either 15 approved kits or a user-approved smaller batch.
- `/api/readiness` matches the chosen target.
- Security scan is green.
- Desktop QA is green.
- No-key installer proof is green.
- Public GitHub source repo is clean, pushed, and cloneable.

Only then publish:

```bash
gh repo create bilbop1/local-review-cockpit --public --source=. --remote=origin --push
```
