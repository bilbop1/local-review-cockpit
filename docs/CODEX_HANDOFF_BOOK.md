# Clipping Ops Cockpit Incoming Codex Book

You are an incoming Codex or Hermes-backed coding session taking over a cloned copy of Clipping Ops Cockpit. Read this as your operating manual, not as instructions to create another handoff.

If you are a weaker or cheaper model, follow the files below in order and do not improvise:

1. `AGENT_START_HERE.md`
2. `docs/AI_AGENT_OPERATING_CONTRACT.md`
3. `docs/COMMAND_COOKBOOK.md`
4. `docs/HERMES_JOB_CONTRACT.md`
5. This book

Repository:

```text
https://github.com/bilbop1/local-review-cockpit
```

This repo is a source-build project, not a media drop and not a prebuilt notarized app. It contains the web cockpit, backend, scripts, docs, tests, and Hermes prompts needed to rebuild and operate the same local pipeline without inheriting the original operator's secrets.

Your job as the incoming session:

1. Clone the repo.
2. Run no-key setup and build verification.
3. Help the local operator add their own API keys, Hermes profile, Discord config, and campaign access.
4. Keep the backend/SQLite as source of truth.
5. Use Hermes as the normal orchestration layer.
6. Never publish before an approved review kit, configured provider, completed account warm-up, and final GUI confirmation; never submit payouts, connect accounts, rebrand accounts, or claim revenue guarantees.

## Truth Snapshot

Do not rely on a dated chat summary for current state. After cloning, read current state from:

- `GET /api/health`
- `GET /api/readiness`
- `GET /api/agents`
- `GET /api/review-kits`
- `GET /api/publish/status`

Historical note: the originating operator previously approved a best-current batch for manual prep, but this GitHub repo does not include those rendered videos, source media, local database rows, API keys, Hermes auth, Discord auth, or browser sessions. Every new operator must generate and approve their own local proof.

Do not call the system production-ready until `/api/readiness` says the intended target is green with fresh local proof.

## First Run

Start here after cloning:

```bash
./script/verify_incoming_clone.sh
```

That is the low-quota one-command path. If you need the expanded baseline, run:

```bash
./script/setup_buddy_no_key.sh
./script/build_and_run.sh --verify
npm --prefix web run typecheck
npm --prefix web run build
PYTHONPATH=backend backend/.venv/bin/python -m unittest discover -s tests -v
./script/smoke_test.sh
backend/.venv/bin/python script/web_app_smoke.py
backend/.venv/bin/python script/security_scan.py
```

If the local operator has review kits and media, also run:

```bash
backend/.venv/bin/python script/verify_burned_in_captions.py
backend/.venv/bin/python script/verify_streamer_composition.py
```

No-key mode should show missing Twitch/Kick/Upload-Post credentials. That is correct until the operator supplies their own keys.

## What The System Is

Clipping Ops Cockpit is a local-first macOS clipping operations appliance.

The intended architecture is:

- Web cockpit: simple human review cockpit at `http://127.0.0.1:8765/app`.
- SQLite/backend: source of truth, safety gates, media records, audit log, job ledger, and artifacts.
- Hermes: normal orchestration layer for campaign refreshes, source discovery, review sweeps, and daily operations.
- Deterministic scripts: source download, transcription, ffmpeg rendering, validation, packaging, and tests.
- Discord: notifications only.
- Human operator: the only entity allowed to approve review kits and confirm live publishing.

The system is not:

- A cloud SaaS.
- A blind autopublisher that can post without review approval, provider readiness, warm-up completion, and final human confirmation.
- A payout submitter.
- A campaign account manager.
- A revenue guarantee.
- A way to transfer another user’s API keys or browser sessions.

## No-Key Buddy Setup

This repo is for your Codex session to build locally.

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

If you have not cloned it yet:

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/setup_buddy_no_key.sh
./script/build_and_run.sh
```

No-key mode should show Twitch/Kick/Upload-Post credentials as missing. That is correct. The local web cockpit should open at `http://127.0.0.1:8765/app`; production campaign and publish jobs must block or dry-run until the local operator supplies their own credentials, source access, account warm-up completion, and final confirmations.

## Credential Setup Expectations

Each operator must provide their own platform credentials.

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

The canonical campaign-selection standard lives in `docs/campaign-selection.md`. If this book and that file ever differ, use `docs/campaign-selection.md`.

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

- YourRAGE: 1,350 views.
- PlaqueBoyMax: 1,500 views.
- JasonTheWeen: 2,000 views.
- Max automatic duration: 52 seconds unless a deliberate shorter manual cut is stored with `clip_start_seconds` / `clip_end_seconds`.

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

The canonical caption standard lives in `docs/caption-style.md`. If this book and that file ever differ, use `docs/caption-style.md`.

Current renderer rules:

- Font: TikTok Sans 36pt Black.
- Output size: 1080x1920.
- Campaign final renders must include a persistent top summary hook card plus burned-in subtitles.
- The top hook should create context and tension without spoiling the payoff, matching the TikTok reference direction from `https://www.tiktok.com/t/ZTBDvvEfD/`.
- The top hook card should visually match the reference: author the white rounded rectangle in 720x1280 source-design space, then upscale it into the 1080x1920 render with the video. Do not draw the hook as crisp native-1080 text. In final output the white card sits at x=99-980, y=336-493 and stays centered. Shorter hooks shrink to the visible text plus reference padding instead of carrying dead white space. In source space, use bundled TikTok Sans Bold at 34px, near-black text at RGB 22/22/22, 40px emoji raised 5px above the text visual top, white-card y=223, visual text y=237, 21px text inset, a 548px source-space text line cap, a 10px two-line gap, visual text width plus roughly 46px card padding, a 587px source-space max card width, a 330px source-space minimum card width, and a 14px card radius. After upscale, apply the top-anchored 5.2% visible-card vertical stretch; do not apply the old half-resolution bicubic softening pass, because it makes the glyph edges lighter and mushier than the TikTok reference. This lands around 51px text, 60px emoji, text y=358, a 15px gap, and a white-card fill whose decoded bbox matches the reference instead of being padded by shadow pixels. The 548px line cap is required so live hooks do not crowd the right card edge. TikTok Sans SemiBold, Avenir Next Demi Bold, and SFNS Semibold are fallbacks for machines without the bundled bold font; Arial Bold is emergency fallback only. Do not regress to native-1080 Arial, the old small pill-style TikTok ExtraBold overlay, the old 48px fallback, tiny pill cards, dead-space cards, over-softened glyph edges, compressed card/text height, shadow-measured green checks, or loose vertical padding inside the white card.
- The top hook copy should read like a native human setup card: streamer/person + situation + tension. Avoid stiff report language like "messy detail," "story somehow turned," "proof," "review," or "selected feeder."
- Top-card parity proof must come from `script/audit_top_card_reference.py` plus `script/audit_live_top_cards.py --refresh`; do not rely on sidecar text or regenerated overlays without decoded `review.mp4` frames.
- The campaign final canvas should match the reference stack: blurred full-screen source background, sharp 16:9 source foreground at x=0, y=513, width=1080, height=607. Do not use the old vertically centered foreground layout for campaign finals.
- Campaign final renders include exactly one public-facing identity watermark in the lower blurred section. If a campaign supplies a required watermark asset, use that asset in the lower reference-style slot; otherwise use the generated `@handle` lower watermark. Do not add a second top-left/top-edge logo in the campaign-short lane.
- No internal labels in frames.
- No “selected feeder,” “proof,” “review kit,” “demo,” or “review-safe” text in rendered video.
- Maximum 2 words on screen per caption beat.
- Maximum 1 subtitle line visible at a time.
- Target maximum 12 characters for normal two-word beats.
- Use 1 word only for long words, emphasis, or timing.
- Captions should sit in the reference-style gap below the foreground frame and above the lower identity watermark, currently y=1128-1235 with visual center near y=1184 on a 1080x1920 render. They should not overlap the creator watermark, sit dead center, or get buried under TikTok/IG/Shorts UI.
- Use platform overlay previews in the GUI to verify subtitles are not covered.
- Timing should follow word-level transcript timing with the renderer's late-pop display windows. Do not solve early captions by shifting everything earlier or later blindly.
- Ensemble-consensus captions must still receive the render-time visual/audio delay. Do not bypass `apply_caption_audio_sync_delay()` just because multiple transcription models agree.
- Suspicious long word spans must be capped near the word end before caption grouping, otherwise subtitles can appear early while still passing naive sidecar checks.
- Big pauses between words must split caption groups. Do not join words across silence just to satisfy the two-word preference.
- One-vote and high-spread timing beats should be dropped or rejected for revision, not forced into a render.
- The verifier must pass `script/verify_burned_in_captions.py`; sidecar text alone does not prove visible subtitles.
- Any future caption timing changes must be validated against video pixels and audio, not just JSON.

Production subtitle variant:

- Default review-kit style: B, white TikTok Sans with yellow emphasis on the second word.

Keep campaign review kits on this single style unless the operator explicitly starts an analytics experiment. Optional experiment variants:

- A: white TikTok Sans with black stroke.
- D: white caption card with black text.
- E: white caption with cyan underline/accent.

Variant C is excluded. Mixed variants are not a parity-ready default.

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

Approval does not publish. It marks the kit as approved for preparation; live Upload-Post jobs still require provider readiness, account warm-up completion, and a final GUI confirmation.

## Upload-Post Autopost Readiness

Upload-Post is the first live posting provider. This repo ships the dry-run/live provider interface, but it does not ship API keys or connected social accounts.

Incoming operators should:

1. Finish their own platform account warm-up.
2. Add their Upload-Post API key through macOS Keychain account `uploadpost.api_key` or private runtime env `UPLOAD_POST_API_KEY`.
3. Set the Upload-Post user/profile in Settings.
4. Keep provider mode as `Dry Run` until dry-run jobs pass on approved kits.
5. Switch Settings to `Live` only when account warm-up is complete.
6. Confirm each live post from the Review Kits publish panel.

Discord and Hermes may report publish job status, but SQLite remains the source of truth.

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

## Repo Boundary Rules

This repository has already been published as a source-build repo. Do not treat this section as instructions to create another repo.

Keep out of git:

- API keys.
- Hermes auth.
- Discord tokens or webhook URLs.
- `.env` files.
- macOS Keychain items.
- Signed-in browser sessions.
- Local SQLite databases.
- Downloaded source media.
- Rendered review kits.
- Generated artifacts unless the operator explicitly asks for a local proof file.

You may use `./script/package_codex_handoff.sh` only as a private offline source snapshot fallback. The normal workflow is to work from this GitHub clone.

Developer ID signing and notarization matter only for distributing a prebuilt `.app` to normal Mac users. They are not required for a Codex/Hermes source-build clone.

## Operating Checklist

Before claiming a local system is ready:

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
- Desktop QA is green if the operator explicitly permits foreground GUI automation; otherwise report GUI click coverage as not rerun rather than taking over the desktop.
- No-key installer proof is green.
- Hermes job execution works or readiness honestly says Hermes is degraded.
