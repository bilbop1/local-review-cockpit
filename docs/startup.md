# Startup Agents

Clipping Ops Cockpit uses two per-user macOS LaunchAgents so the local appliance comes online after login:

- `com.bilbop.ClippingOpsCockpit.backend` keeps the localhost API alive at `http://127.0.0.1:8765`.
- `com.bilbop.ClippingOpsCockpit.web` waits for the API, then opens the browser cockpit at `http://127.0.0.1:8765/app`.

Install or repair both agents from the workspace:

```bash
./script/install_startup_agents.sh
```

Check startup health:

```bash
./script/check_startup_agents.py
cat artifacts/startup/startup-agents.json
```

Logs live under:

```text
~/Library/Application Support/ClippingOpsCockpit/logs/
```

The web opener LaunchAgent does not build from source at login. It opens the built web cockpit created during installation, which keeps startup fast and avoids running project build commands at login. Re-run `./script/install_app_launch_agent.sh` after code changes when you want the login web bundle refreshed.
