# Clipping Ops Cockpit Operator Runbook

## Start

1. Run `./script/install_backend_launch_agent.sh`.
2. Run `./script/build_and_run.sh --verify`.
3. Open `http://127.0.0.1:8765/app` and confirm Settings shows local readiness red/yellow until every review and source gate has fresh proof.

## Daily Workflow

1. Review Dashboard for blockers and job status.
2. Use Campaigns to refresh the current active streamer-first project set: YourRAGE, PlaqueBoyMax, JasonTheWeen.
3. Use Sources only for advanced API checks, watchlist candidates, and future creator campaigns.
4. Keep demo/local proof kits out of the production Review Kits surface; build campaign review kits only after source provenance and local media are stored.
5. Review videos in Review Kits; approval enables publish prep only, and live posting still needs provider readiness, completed warm-up, and final confirmation.

## Hard Stops

- No posting before approved kit, Upload-Post/provider readiness, completed warm-up, and final GUI confirmation.
- No payout submission.
- No account connection or account rebrand.
- No real campaign render without stored campaign rules, source URL, provenance, and source availability.
- No Ready To Post without playable H.264/AAC 1080x1920 preview and all kit files.
