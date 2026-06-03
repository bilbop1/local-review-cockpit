# OAuth Credentials

Store OAuth credentials in macOS Keychain under service:

```text
com.bilbop.ClippingOpsCockpit
```

## Local Redirect URLs

```text
Twitch: http://localhost:8765/auth/twitch/callback
Kick:   http://localhost:8765/auth/kick/callback
```

The backend API still listens on:

```text
http://127.0.0.1:8765
```

Use `localhost` for the OAuth redirect URLs, especially Kick.

## Keychain Accounts

```text
twitch.client_id
twitch.client_secret
twitch.redirect_uri
twitch.scopes
twitch.app_access_token
twitch.app_token_expires_at

kick.client_id
kick.client_secret
kick.redirect_uri
kick.scopes
kick.app_access_token
kick.app_token_expires_at
kick.pkce_code_verifier
```

## Default Scopes

Twitch app-token research uses no user scopes. Add user scopes later only for user-authorized actions.

Kick default user scopes:

```text
user:read channel:read
```

Kick bot/chat scopes are intentionally not requested by default. Add `chat:write` and `events:subscribe` only when bot behavior is explicitly needed.

## API Helpers

```text
GET  /api/auth/status
GET  /api/auth/twitch/authorize-url
GET  /api/auth/kick/authorize-url
POST /api/auth/twitch/app-token
POST /api/auth/kick/app-token
```

App tokens are stored back into Keychain. Responses never include token values.
