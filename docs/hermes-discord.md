# Hermes Discord Shape

Discord is a messaging surface, not the database.

Use one category:

```text
CLIPPING OPS
```

Use exactly three channels:

```text
clip-ops-alerts
clip-ops-daily-brief
clip-ops-approvals
```

Errors and winners route into alerts or daily briefs to stay inside the channel limit. Approvals must map back to backend records before they can change state.

Hermes role prompts live under `hermes/`. Install the scheduled lanes with:

```bash
./script/install_hermes_clip_ops.sh
```

The installer creates:

- `clip-ops daily brief`
- `clip-research campaign gate sweep`
- `clip-review kit risk sweep`
- `clip-ops job dispatcher`

The dispatcher is a Hermes `--no-agent` job. It claims queued backend job intents, runs deterministic local worker code for downloads/renders/checks, and writes completion/blocker state back to the backend. Agent prompts handle judgment and briefs; scripts handle mechanical media work.
