# Streamer Composition Standard

Streamer clips should preserve the actual moment first. Facecam extraction is optional, not automatic.

Rules:

- Prefer native landscape Twitch/Kick source media when available.
- Do not use Twitch `portrait-*` mobile/cropped formats as final production source if native `1080` or `720` formats exist.
- Default campaign renders should keep the natural source frame and crop for the strongest visible subject/action.
- Do not create a top facecam band just because a detector saw a possible facecam. That produced bad review kits.
- Use `streamer_split_facecam_top` only when a human or future Hermes critique explicitly decides that the split frame makes the clip stronger.
- If no confident facecam corner is detected, keep the native source visible and record `streamer_center_screen_no_facecam_detected` with probe frames for human review.
- If source media is already portrait/cropped, record `portrait_source_facecam_unrecoverable` and treat it as a production blocker unless the user explicitly accepts it.
- Never fake a facecam crop from unrelated on-screen media.

Split facecam is disabled by default. Set `CLIPPING_OPS_ALLOW_FACE_CAM_SPLIT=1` only for an intentional revision pass.

Verification:

```bash
PYTHONPATH=backend backend/.venv/bin/python script/verify_streamer_composition.py
```

The verifier writes `artifacts/review-kit-audit/streamer-composition-verification.json` plus sample frames.
