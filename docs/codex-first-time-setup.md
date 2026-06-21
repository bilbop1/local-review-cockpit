# Codex First-Time Setup

Use this when a new operator gives Codex the GitHub link and asks it to install the local review cockpit on their Mac.

For the shortest guided install, give Codex the starting command in [docs/codex-buddy-bootstrap.md](codex-buddy-bootstrap.md). After cloning, Codex should run:

```bash
./script/codex_buddy_bootstrap.sh
```

## Pasteable Operator Prompt

```text
Get into Clipping Ops installation mode for https://github.com/bilbop1/local-review-cockpit. Assume I am not technical. Clone the repo, read AGENT_START_HERE.md and docs/codex-buddy-bootstrap.md, then run ./script/codex_buddy_bootstrap.sh. Ask me for one thing at a time in plain English: MiniMax API key, Twitch client ID/secret, Kick client ID/secret if I have Kick, Upload-Post API key, exact Upload-Post profile name, TikTok warm-up status, and whether to turn on approved-kit auto-posting. Do not print, commit, or store secrets in repo files.
```

## Agent Setup Order

1. Clone the repo and run the isolated no-key check.

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/verify_incoming_clone.sh
```

2. Start the local cockpit.

```bash
./script/build_and_run.sh --verify
```

3. Configure Hermes and MiniMax locally.

```bash
./script/configure_minimax_hermes_local.sh
./script/verify_minimax_hermes.sh
./script/install_hermes_clip_ops.sh
```

4. Store source credentials only after no-key proof passes.

```bash
./script/store_credentials_keychain.sh
```

5. Add Upload-Post last. TikTok is the default publish platform. Set the exact Upload-Post profile name for this local operator, then leave Instagram, YouTube, Facebook, and X blocked for posting until those accounts have their own warm-up evidence.

6. Queue the first campaign research/build wave.

```bash
PYTHONPATH=backend backend/.venv/bin/python script/queue_buddy_campaign_kickoff.py --json --force-new
```

The helper queues campaign refresh, source discovery, and one first review-kit build per active campaign through the Hermes job ledger. Codex may also use the browser to help the operator sign in to clipping.net and inspect campaign pages, but it must not export cookies or browser sessions.

## Upload-Post Rules

- The repo never includes Upload-Post keys or connected account sessions.
- `UPLOAD_POST_API_KEY` is allowed only as a private runtime environment variable.
- The macOS Keychain account is `uploadpost.api_key`.
- The Upload-Post profile is a local app setting. Publish jobs do not choose or override it; every package-check/live request uses the single configured profile for that local install.
- The default live-ready platform is TikTok only.
- Approving a kit schedules it into the next local `:14` slot.
- Live upload still requires provider key, configured Upload-Post profile, platform warm-up, live mode, and the local auto-post switch or a final GUI confirmation.

## Local Checks

Open:

```text
http://127.0.0.1:8765/app/settings
```

Expected before credentials:

- Twitch, Kick, and Upload-Post show missing.
- Publish readiness is yellow or blocked.
- Demo/local proof still runs.

Expected after TikTok Upload-Post readiness:

- `/api/publish/status` shows `default_platforms=["tiktok"]`.
- `/api/publish/status` shows the operator's configured Upload-Post profile.
- TikTok can become live-ready.
- Instagram, YouTube, and Facebook remain blocked unless the operator warms and enables them locally.
