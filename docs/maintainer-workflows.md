# Maintainer Workflows

This repo is early public OSS. It is not being submitted as a high-star dependency. It is being submitted as a working maintainer tool that came out of real agent operations.

The maintenance problem it tackles is simple: agents can move fast, but someone still has to track source material, review outputs, catch failures, keep credentials out of the repo, and decide what is safe to ship. Local Review Cockpit gives that work a home.

## What I maintain

- The macOS cockpit app and its review surfaces.
- The Python backend and local state model.
- Queue, render, preview, audit-log, and safety-gate behavior.
- Setup scripts for new operators.
- Prompt files that give agents narrow jobs instead of open-ended control.
- Release and smoke-test scripts that catch breakage before a user runs the app.

## Where Codex helps

Codex is useful here because a lot of this work is unglamorous and repetitive:

- reviewing pull requests against the safety model
- checking that setup docs still match the scripts
- writing and tightening smoke tests
- explaining failed render or backend checks
- drafting changelog and release notes from commit history
- checking whether a proposed feature accidentally crosses a safety gate
- keeping the macOS UI, backend API, and operator docs in sync

I would use API credits on those maintainer workflows first. More code is easy to generate. The harder part is keeping a local agent tool understandable, testable, and safe enough for another person to run.

## Current boundaries

- Public repo only contains source, docs, and testable scripts.
- Private media, credentials, browser sessions, Keychain material, and local databases are excluded.
- Agents can prepare, review, and recommend work.
- Humans approve publishing, payout-related actions, credential changes, and account-level changes.

That boundary is the project. It is not an afterthought.
