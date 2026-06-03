#!/usr/bin/env bash
set -euo pipefail

SERVICE="com.bilbop.ClippingOpsCockpit"

store_prompt() {
  local account="$1"
  local label="$2"
  local value
  read -rsp "$label: " value
  printf '\n'
  security add-generic-password -U -a "$account" -s "$SERVICE" -w <<<"$value
$value
" >/dev/null
}

store_literal() {
  local account="$1"
  local value="$2"
  security add-generic-password -U -a "$account" -s "$SERVICE" -w <<<"$value
$value
" >/dev/null
}

echo "Stores Clipping Ops OAuth credentials in macOS Keychain service: $SERVICE"
store_prompt "twitch.client_id" "Twitch client ID"
store_prompt "twitch.client_secret" "Twitch client secret"
store_literal "twitch.redirect_uri" "http://localhost:8765/auth/twitch/callback"
store_literal "twitch.scopes" ""

store_prompt "kick.client_id" "Kick client ID"
store_prompt "kick.client_secret" "Kick client secret"
store_literal "kick.redirect_uri" "http://localhost:8765/auth/kick/callback"
store_literal "kick.scopes" "user:read channel:read"

echo "Stored credentials and default redirect URIs. Secrets were not written to repo files."
