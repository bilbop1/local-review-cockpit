# Codex First-Time Setup

Use this when a new operator gives Codex the GitHub link and asks it to install the local review cockpit on their Mac.

## Pasteable Operator Prompt

```text
Clone https://github.com/bilbop1/local-review-cockpit and set it up locally. Start in no-key mode, run the clone verification, and only ask me for credentials after the source build passes. Do not print, commit, or store secrets in repo files. Guide me through Hermes/MiniMax setup first, then Twitch/Kick if needed, and ask for Upload-Post last after I confirm which social accounts are warmed.
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

5. Add Upload-Post last. TikTok is the default publish platform. Set the exact Upload-Post profile name for this local operator, then leave Instagram, YouTube, and Facebook blocked until those accounts have their own warm-up evidence.

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
