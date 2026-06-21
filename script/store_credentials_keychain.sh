#!/usr/bin/env bash
set -euo pipefail

SERVICE="com.bilbop.ClippingOpsCockpit"

store_prompt() {
  local account="$1"
  local label="$2"
  local value
  read -rsp "$label: " value
  printf '\n'
  security add-generic-password -U -a "$account" -s "$SERVICE" -w "$value" >/dev/null
}

store_optional_prompt() {
  local account="$1"
  local label="$2"
  local value
  read -rsp "$label (leave blank to skip): " value
  printf '\n'
  if [[ -z "$value" ]]; then
    echo "Skipped $account"
    return
  fi
  security add-generic-password -U -a "$account" -s "$SERVICE" -w "$value" >/dev/null
}

store_optional_pair() {
  local account_one="$1"
  local label_one="$2"
  local account_two="$3"
  local label_two="$4"
  local value_one
  local value_two
  read -rsp "$label_one (leave blank to skip this provider): " value_one
  printf '\n'
  if [[ -z "$value_one" ]]; then
    echo "Skipped $account_one and $account_two"
    return 1
  fi
  read -rsp "$label_two: " value_two
  printf '\n'
  if [[ -z "$value_two" ]]; then
    echo "Skipped $account_one and $account_two because the secret was blank"
    return 1
  fi
  security add-generic-password -U -a "$account_one" -s "$SERVICE" -w "$value_one" >/dev/null
  security add-generic-password -U -a "$account_two" -s "$SERVICE" -w "$value_two" >/dev/null
}

store_literal() {
  local account="$1"
  local value="$2"
  security add-generic-password -U -a "$account" -s "$SERVICE" -w "$value" >/dev/null
}

echo "Stores Clipping Ops OAuth credentials in macOS Keychain service: $SERVICE"
store_prompt "twitch.client_id" "Twitch client ID"
store_prompt "twitch.client_secret" "Twitch client secret"
store_literal "twitch.redirect_uri" "http://localhost:8765/auth/twitch/callback"
store_literal "twitch.scopes" ""

if store_optional_pair "kick.client_id" "Kick client ID" "kick.client_secret" "Kick client secret"; then
  store_literal "kick.redirect_uri" "http://localhost:8765/auth/kick/callback"
  store_literal "kick.scopes" "user:read channel:read"
fi

store_optional_prompt "uploadpost.api_key" "Upload-Post API key"

echo "Stored provided credentials and default redirect URIs. Secrets were not written to repo files."
