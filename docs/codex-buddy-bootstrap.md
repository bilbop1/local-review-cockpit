# Codex Buddy Bootstrap

Use this when a friend gives Codex the GitHub repo and wants their own local Hermes/MiniMax clipping pipeline installed. The goal is simple: they provide local keys and profile names, Codex handles the rest, and they review the first kits later from the web cockpit.

## Give Codex This Starting Command

```text
Get into Clipping Ops installation mode for this repo:
https://github.com/bilbop1/local-review-cockpit

Assume I am not technical. Clone the repo, then read AGENT_START_HERE.md and docs/codex-buddy-bootstrap.md before changing anything. Explain in plain English what you need, ask me for one thing at a time, and do not ask me to edit files manually unless there is no safer option.

After the no-key clone check passes, run ./script/codex_buddy_bootstrap.sh and guide me through the prompts. First verify whether Hermes is already wired to the `clipping-ops-minimax` / MiniMax-M3 profile. Only ask me for a MiniMax API key if Hermes is not already wired or Codex cannot use the existing MiniMax setup. Otherwise ask me for: Twitch client ID and secret, Kick client ID and secret if I have Kick, Upload-Post API key, exact Upload-Post profile name, whether TikTok is warmed, and whether to turn on approved-kit auto-posting. If I do not know where to find one of those, walk me through it in the browser.

Never print, commit, or store secrets in repo files. Store secrets only through the provided local scripts/Keychain flow. Keep posting TikTok-only unless I explicitly say another platform is warmed. When setup is done, verify http://127.0.0.1:8765/app works, queue starter campaign research/build jobs, and tell me to review first kits at http://127.0.0.1:8765/app/reviews in about 45-90 minutes.
```

## What The Friend Gives

- MiniMax API key only if the local Hermes `clipping-ops-minimax` / MiniMax-M3 setup is missing or unusable.
- Twitch client ID and client secret.
- Kick client ID and client secret, if Kick monitoring/source checks are wanted.
- Upload-Post API key.
- Exact Upload-Post profile name for this one local operator.
- A yes/no answer for TikTok warm-up. Instagram, YouTube, Facebook, and X stay blocked for posting until explicitly warmed later.

That is the normal input surface. Clipping.net browser sign-in may still be needed if the campaign dashboard is private, but Codex must not export cookies or browser sessions. If the operator does not understand any credential name, Codex should pause setup and guide them in plain English through finding or creating that credential.

## One Command

```bash
git clone https://github.com/bilbop1/local-review-cockpit.git
cd local-review-cockpit
./script/codex_buddy_bootstrap.sh
```

The script does the boring parts in order:

1. Verifies the source clone in no-key mode.
2. Builds and starts the local web cockpit.
3. Configures the local MiniMax-backed Hermes profile.
4. Stores Twitch, Kick, and Upload-Post credentials in macOS Keychain.
5. Locks the exact Upload-Post profile into local backend settings.
6. Keeps posting limited to TikTok unless another platform is warmed and enabled later.
7. Installs backend/web LaunchAgents and Hermes cron jobs.
8. Queues starter campaign refresh, source discovery, and one first review-kit build per active campaign.

For a non-mutating check:

```bash
./script/codex_buddy_bootstrap.sh --dry-run
PYTHONPATH=backend backend/.venv/bin/python script/queue_buddy_campaign_kickoff.py --dry-run --json
```

## Posting Safety

Upload-Post is profile-locked per local install. Every package check or live upload uses the single configured profile name from local backend settings. Jobs do not choose a different Upload-Post profile.

Approved clips only become live posts when all of these are true:

- The kit was approved in the local review cockpit.
- The Upload-Post API key exists locally.
- The exact Upload-Post profile is configured.
- The target platform is warmed and marked ready.
- Provider mode is live.
- The local auto-post switch is on, or the operator manually confirms the post in the GUI.

Fresh installs default to a blocked or check-only posting state unless the operator explicitly says TikTok is warmed and enables auto-posting. Instagram, YouTube, Facebook, and X are URL-capture columns at first, not posting targets.

## After Setup Checks

```bash
curl -s http://127.0.0.1:8765/api/health
curl -s http://127.0.0.1:8765/api/readiness
curl -s http://127.0.0.1:8765/api/publish/status
hermes -p clipping-ops-minimax cron status
PYTHONPATH=backend backend/.venv/bin/python script/queue_buddy_campaign_kickoff.py --dry-run --json
```

Open:

```text
http://127.0.0.1:8765/app/reviews
```

If source credentials, campaign routes, Hermes, ffmpeg, and media download paths are healthy, the first real review kits should appear after the starter jobs run. A practical expectation is 45-90 minutes for the first pass, not instant output.
