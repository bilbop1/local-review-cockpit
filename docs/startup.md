# Startup Agents

Clipping Ops Cockpit uses two per-user macOS LaunchAgents so the local appliance comes online after login:

- `com.bilbop.ClippingOpsCockpit.backend` keeps the localhost API alive at `http://127.0.0.1:8765`.
- `com.bilbop.ClippingOpsCockpit.app` waits for the API, then opens `dist/Clipping Ops Cockpit.app`.

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

The app LaunchAgent does not build from source at login. It opens the staged app bundle created during installation, which keeps startup fast and avoids macOS provenance restrictions on project shell scripts. Re-run `./script/install_app_launch_agent.sh` after code changes when you want the login app bundle refreshed.
