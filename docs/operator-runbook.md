# Clipping Ops Cockpit Operator Runbook

## Start

1. Run `./script/install_backend_launch_agent.sh`.
2. Run `./script/build_and_run.sh --verify`.
3. Open the app and confirm Settings shows local readiness red/yellow until every review and source gate has fresh proof.

## Daily Workflow

1. Review Dashboard for blockers and job status.
2. Use Campaigns to refresh the current active streamer-first project set: YourRAGE, PlaqueBoyMax, JasonTheWeen.
3. Use Sources only for advanced API checks, watchlist candidates, and future creator campaigns.
4. Keep demo/local proof kits out of the production Review Kits surface; build campaign review kits only after source provenance and local media are stored.
5. Review videos in Review Kits; approval never publishes.
6. Reject weak clips even when the render is technically valid. Mechanical proof is not the same as a clip worth posting.

## Current Acceptance Target

The default product target remains 15 approved reviews: 5 YourRAGE, 5 PlaqueBoyMax, and 5 JasonTheWeen.

The originating operator approved the current active validated batch before publishing this source clone, instead of padding to 15 with weaker clips:

- JasonTheWeen: 4 approved active kits.
- YourRAGE: 3 approved active kits.
- PlaqueBoyMax: 3 approved active kits.
- 2 timing-unsafe/rejected kits remain rejected for revision and are not part of the inherited approved batch.

If this operator wants the full 15-kit target, build only stronger new candidates. Do not pad with low-view, generic-title, overlong, mistimed, or visually pointless filler. If the active batch is weaker than expected, keep the batch smaller instead of padding.

## Campaign Selection Rules

- Prefer streamer-native campaigns with daily clip supply and clear viewer motivation.
- Avoid brand/product campaigns with no organic reason to watch.
- Exclude campaigns that need original content generation instead of clipping existing approved media.
- Haste remains excluded until it provides a verifiable source pack or approved source media.
- Lacy remains demoted unless a candidate truly satisfies the arrested/missing-in-action brief.
- Do not let stale Kalshi/Dunkman/Haste automation paths create active Review Kits.

## Caption Review Rules

- TikTok Sans Black, max 2 words per caption beat.
- One subtitle line only.
- Captions must sit in the platform-safe lower-third band and pass TikTok, Instagram, and YouTube Shorts overlay checks.
- No internal labels in the video: no proof, demo, review kit, selected-feeder, or review-safe text.
- Timing must be checked by watching the video with audio. Passing JSON is not enough.
- Ensemble-consensus captions still need render-time visual/audio delay; do not bypass the delay just because multiple transcription models agree.
- Reject or rebuild clips with long fake ASR word spans, one-vote timing beats, or high-spread timing votes.
- `script/verify_burned_in_captions.py` must be green for all active kits before any readiness claim.

## Hard Stops

- No autopublish.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render without stored campaign rules, source URL, provenance, and source availability.
- No Ready To Post without playable H.264/AAC 1080x1920 preview and all kit files.
- No readiness claim until the chosen review target is explicit and the active kits have been reviewed.
