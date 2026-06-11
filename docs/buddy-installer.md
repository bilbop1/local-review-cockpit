# Incoming No-Key Setup

You are an incoming Codex/Hermes-backed session setting this repo up on a new operator's machine. The main operating manual lives in `docs/CODEX_HANDOFF_BOOK.md`. Treat that book as the source of truth for campaign choice, caption rules, Hermes setup, and readiness gates.

If you are an AI agent, start with `AGENT_START_HERE.md` and run:

```bash
./script/verify_incoming_clone.sh
```

Use `script/setup_buddy_no_key.sh` to install and verify the same local system shape without transferring secrets.

Clone the public GitHub source repo and build locally:

```text
https://github.com/bilbop1/local-review-cockpit
```

`script/package_codex_handoff.sh` remains available for a private offline source snapshot, but GitHub clone is the normal path. Source-build setup does not require Developer ID signing or notarization. Apple signing/notarization only matters for a prebuilt `.app` handed to a normal Mac user outside the Codex rebuild workflow.

The originating operator approved the current active validated review batch for manual prep before publishing this source repo. The repository still does not include those review videos or source media.

The setup checks for npm, `uv`, Python, `ffmpeg`, `ffprobe`, and Hermes, then builds the web cockpit, starts the local backend, renders demo kits, and runs smoke tests. It runs with `CLIPPING_OPS_NO_KEY=1` and an isolated `CLIPPING_OPS_HOME` so ambient Keychain credentials are ignored.

It intentionally does not copy:

- API keys
- Upload-Post keys or connected social account sessions
- Hermes auth files
- Discord tokens or webhook URLs
- `.env` files
- macOS Keychain items
- signed-in browser sessions
- local SQLite databases
- downloaded source media
- rendered review kits

Real campaign ingestion remains blocked until the local operator signs into their own services and provides their own credentials. Upload-Post live posting remains locked until the local operator provides their own key, completes account warm-up, switches live mode on, and confirms each post. The demo review-kit path works from local/sample media only.

Normal app actions queue Hermes job intents. The local operator must configure their own Hermes profile/provider locally; this repo never transfers Hermes auth, model provider auth, Discord gateway credentials, or API keys.

The source repo includes the caption standard and vendored TikTok Sans font files. Campaign renders should keep TikTok Sans Black subtitles, max 2 words per beat, platform-safe lower-third placement, and no internal proof/review labels unless the local operator explicitly redesigns the caption style after their own review.

The current campaign standard is streamer-first: YourRAGE, PlaqueBoyMax, and JasonTheWeen are active; Haste stays excluded unless a real linked source pack appears; Lacy stays demoted unless a clip actually matches the arrested/missing-in-action brief.

No-key mode must show Twitch, Kick, and Upload-Post credentials as missing. That is success, not failure.

## Command

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/setup_buddy_no_key.sh
```

## After Setup

```bash
./script/build_and_run.sh
```

Open `http://127.0.0.1:8765/app/settings` to see which capabilities are ready, degraded, or blocked.
