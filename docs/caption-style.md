# Caption Style Standard

This project now treats caption styling as a production gate, not a loose renderer preference.

## Font

- Primary caption font: TikTok Sans 36pt Black.
- Default render size: 62px at 1080x1920.
- Source: official TikTok Sans release, v4.000.
- License: SIL Open Font License 1.1.
- Vendored files live in `backend/clipping_ops_backend/assets/fonts/`.
- Fallbacks, only if the vendored font cannot load: TikTok Sans ExtraBold, Impact, Arial Black, Arial Bold.

The renderer previously used macOS Arial Bold fallback. That was close enough to read, but not the actual TikTok-native family.

## Line Rules

- Maximum 2 words total on screen per caption beat.
- Maximum 1 subtitle line visible at a time.
- Target maximum 12 characters for a two-word beat.
- Prefer exactly 2 words for normal caption beats.
- Use 1 word only when timing, emphasis, or a single long word makes 2 words awkward.
- A single long word may exceed 12 characters, but it must appear alone.
- Campaign final renders must include a persistent top summary hook card plus subtitles. The hook must be viewer-facing context, not an internal label.
- The top hook should summarize the tension without spoiling the payoff, similar to the TikTok reference `https://www.tiktok.com/t/ZTBDvvEfD/`.
- Top hook geometry is part of the standard: on a 1080x1920 render, the white card should sit around x=60, y=336, width about 920, with left-aligned black TikTok Sans ExtraBold text and minimal shadow.
- Internal labels remain blocked: no proof banners, no selected-feeder wording, no review-safe text, no demo wording.
- Captions belong just below the active foreground frame when source media is landscape, or in the lower safe area for vertical media. They must not sit in the center of the screen, cover faces, or dominate the clip.
- Current 1080x1920 safe band: y=1210-1400, with visual center near y=1306.
- The GUI platform overlay toggles for TikTok, Instagram, and YouTube Shorts must be used when judging whether captions are too low.

These constraints intentionally create faster beat timing. That is expected. The caption rhythm should feel like rapid TikTok/Shorts subtitles, not a sentence pasted over video.

## Timing Rules

- Caption beats must be built from word-level transcript timing when available.
- The renderer late-pops each beat near the actual spoken word, then applies the configured audio sync delay. Do not globally shift captions earlier to make them “feel faster.”
- Ensemble-consensus captions are not exempt from render-time sync delay. Even if multiple transcript models agree, the final burned overlay must still pass through `apply_caption_audio_sync_delay()`.
- Suspicious long word spans must be capped near the word end before grouping. A token like `shit` lasting several seconds is almost always an ASR timing artifact, and using its raw start will make the subtitle appear early.
- Caption groups must split across real pauses. Do not keep two words together if the gap between their word timings exceeds the caption gap limit.
- One-vote or high-spread timing beats should be dropped, rebuilt, or rejected for revision. They must not be forced through just to keep a video count high.
- A timing fix is not accepted until `script/verify_burned_in_captions.py` passes and a human watch-through does not catch captions leading the audio.
- If a clip has unreliable transcript timing, reject or rebuild the transcript instead of forcing the render through.
- Sidecar captions are not enough. The verifier must inspect burned-in pixels from `review.mp4`.

## Campaign Rules

- Active campaign renders are streamer-first: YourRAGE, PlaqueBoyMax, and JasonTheWeen.
- Haste stays excluded unless it supplies verified source media; do not content-generate for it.
- Lacy stays demoted unless the clip actually satisfies the campaign brief.
- Kalshi and Dunkman remain archived/non-primary for this source-clone lane.
- The incoming Codex book in `docs/CODEX_HANDOFF_BOOK.md` contains the full campaign and operating rules.

## A/B Variants

Production review renders rotate only these text treatments:

- A: clean white TikTok Sans with black stroke.
- B: yellow emphasis on the second word.
- D: white caption card with black text.
- E: white caption with cyan underline/accent.

Variant C is excluded from production testing. Every rendered kit writes its selected variant into `render_text_manifest.json` under `rendered_text.caption_style.ab_variant`, so later analytics or review polling can compare outcomes without guessing from pixels.

## Handoff Rule

The no-key Codex/GitHub source clone includes the vendored font files and this standard. Incoming sessions must keep the same rule unless the operator explicitly approves a new caption style after reviewing A/B examples and rerunning burned-caption verification.
