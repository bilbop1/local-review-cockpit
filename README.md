# Local Review Cockpit

`Clipping Ops Cockpit` is a local macOS control app for campaign discovery, clip indexing, review-first rendering, Hermes orchestration, and guarded publishing prep.

The system follows the PDF rule: index many, render few, publish only with approval. Demo kits are clearly labeled and never treated as campaign output.

This public repo is a source-build handoff. It intentionally contains no API keys, Hermes auth, Discord tokens, browser sessions, Keychain exports, local SQLite database, source media, rendered review videos, or app-support artifacts.

## Public Handoff

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/setup_buddy_no_key.sh
./script/build_and_run.sh --verify
```

Each operator must provide their own Twitch/Kick credentials, Hermes profile, Discord channel IDs/config, and signed-in campaign access. The app is Mac-first SwiftPM source; non-Mac users should treat the backend/scripts/docs as the portable workflow reference and rebuild their own UI.

## Run

```bash
./script/build_and_run.sh
```

The run script starts the local backend at `http://127.0.0.1:8765`, builds the SwiftPM app, stages `dist/Clipping Ops Cockpit.app`, and launches it as a foreground macOS app.

## Architecture

- The Swift app is the human cockpit.
- The local backend and SQLite database are the source of truth.
- Normal user actions enqueue Hermes job intents.
- Hermes claims jobs through the backend; no-agent scripts handle deterministic work such as source checks, media renders, and validation.
- Agent prompts handle judgment, daily briefs, research summaries, and review/risk recommendations.
- Direct backend worker endpoints remain available for advanced local fallback only and do not count as Hermes-native readiness proof.

## Useful Commands

```bash
./script/build_and_run.sh --verify
./script/render_demo_kits.sh
./script/smoke_test.sh
python3 script/desktop_qa.py
./script/setup_buddy_no_key.sh
./script/package_codex_handoff.sh
./script/install_hermes_clip_ops.sh
./script/store_credentials_keychain.sh
./script/install_backend_launch_agent.sh
```

`package_codex_handoff.sh` still exists for private offline source zips, but the preferred handoff is this GitHub source repo. `package_release.sh` is separate: Developer ID signing and notarization are only required when distributing a prebuilt `.app` to normal Mac users.

## Safety Gates

- No autonomous publishing.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render before the Campaign Research Gate passes.
- No Ready To Post state without a local preview video.
- Rejection requires notes and creates a revision request.

## Local Data

Runtime data is stored under:

```text
~/Library/Application Support/ClippingOpsCockpit
```

Do not commit or transfer API keys, Hermes auth, Discord tokens, `.env` files, or Keychain items.

Full setup, campaign, subtitle timing, Hermes, Discord, and safety instructions live in [docs/CODEX_HANDOFF_BOOK.md](docs/CODEX_HANDOFF_BOOK.md).
