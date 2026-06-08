# Contributing

Thanks for taking a look at Local Review Cockpit.

This project is built around local-first agent operations, so contributions should keep three rules intact:

- Do not add code that publishes, submits payouts, changes credentials, or rebrands accounts without an explicit human gate.
- Do not commit private media, local databases, browser profiles, API keys, OAuth material, Keychain exports, or `.env` files.
- Keep scripts and docs in sync. If setup changes, update the setup docs in the same pull request.

## Useful checks

Run the checks that match the area you touched:

```bash
./script/smoke_test.sh
python3 script/desktop_qa.py
./script/verify_release.sh
./script/security_scan.py
```

For UI changes, include a short note about what you tested on macOS. For backend changes, include the route or workflow you exercised.

## Pull requests

Small pull requests are easier to review. A good PR explains:

- what changed
- which safety gate or workflow it affects
- what command or manual check passed
- what still needs review

If you are not sure where to start, docs and tests are welcome. This repo is still young, so clear maintenance work helps a lot.
