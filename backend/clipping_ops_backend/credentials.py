from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


SERVICE = "com.bilbop.ClippingOpsCockpit"

TWITCH_AUTH_BASE = "https://id.twitch.tv/oauth2"
TWITCH_API_BASE = "https://api.twitch.tv/helix"
KICK_AUTH_BASE = "https://id.kick.com"
KICK_API_BASE = "https://api.kick.com/public/v1"

DEFAULT_TWITCH_REDIRECT = "http://localhost:8765/auth/twitch/callback"
DEFAULT_KICK_REDIRECT = "http://localhost:8765/auth/kick/callback"
DEFAULT_TWITCH_SCOPES = ""
DEFAULT_KICK_SCOPES = "user:read channel:read"


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    auth_base: str
    api_base: str
    client_id_account: str
    client_secret_account: str
    redirect_account: str
    scopes_account: str
    app_token_account: str
    app_token_expiry_account: str
    user_token_account: str
    user_refresh_account: str
    user_token_expiry_account: str
    oauth_state_account: str
    default_redirect: str
    default_scopes: str


SPECS = {
    "twitch": ProviderSpec(
        name="twitch",
        auth_base=TWITCH_AUTH_BASE,
        api_base=TWITCH_API_BASE,
        client_id_account="twitch.client_id",
        client_secret_account="twitch.client_secret",
        redirect_account="twitch.redirect_uri",
        scopes_account="twitch.scopes",
        app_token_account="twitch.app_access_token",
        app_token_expiry_account="twitch.app_token_expires_at",
        user_token_account="twitch.user_access_token",
        user_refresh_account="twitch.user_refresh_token",
        user_token_expiry_account="twitch.user_token_expires_at",
        oauth_state_account="twitch.oauth_state",
        default_redirect=DEFAULT_TWITCH_REDIRECT,
        default_scopes=DEFAULT_TWITCH_SCOPES,
    ),
    "kick": ProviderSpec(
        name="kick",
        auth_base=KICK_AUTH_BASE,
        api_base=KICK_API_BASE,
        client_id_account="kick.client_id",
        client_secret_account="kick.client_secret",
        redirect_account="kick.redirect_uri",
        scopes_account="kick.scopes",
        app_token_account="kick.app_access_token",
        app_token_expiry_account="kick.app_token_expires_at",
        user_token_account="kick.user_access_token",
        user_refresh_account="kick.user_refresh_token",
        user_token_expiry_account="kick.user_token_expires_at",
        oauth_state_account="kick.oauth_state",
        default_redirect=DEFAULT_KICK_REDIRECT,
        default_scopes=DEFAULT_KICK_SCOPES,
    ),
}


def no_key_mode() -> bool:
    return os.environ.get("CLIPPING_OPS_NO_KEY") == "1"


def _env_name(account: str) -> str:
    return account.upper().replace(".", "_")


def read_secret(account: str) -> str:
    if no_key_mode() and (account.startswith("twitch.") or account.startswith("kick.")):
        return ""
    env_value = os.environ.get(_env_name(account))
    if env_value:
        return env_value
    result = subprocess.run(
        ["security", "find-generic-password", "-a", account, "-s", SERVICE, "-w"],
        text=True,
        capture_output=True,
        timeout=8,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.rstrip("\n")


def write_secret(account: str, value: str) -> None:
    if no_key_mode() and (account.startswith("twitch.") or account.startswith("kick.")):
        raise RuntimeError("no-key mode blocks credential writes")
    proc = subprocess.run(
        ["security", "add-generic-password", "-U", "-a", account, "-s", SERVICE, "-w"],
        input=f"{value}\n{value}\n",
        text=True,
        capture_output=True,
        timeout=10,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"Unable to write {account} to Keychain")


def has_secret(account: str) -> bool:
    return bool(read_secret(account))


def value_or_default(account: str, default: str) -> str:
    return read_secret(account) or default


def mask_present(value: str, *, visible: int = 4) -> str:
    if not value:
        return "missing"
    if len(value) <= visible:
        return "configured"
    return f"configured (...{value[-visible:]})"


def provider_status(provider: str) -> Dict[str, Any]:
    spec = SPECS[provider]
    client_id = read_secret(spec.client_id_account)
    client_secret = read_secret(spec.client_secret_account)
    app_token = read_secret(spec.app_token_account)
    expiry = read_secret(spec.app_token_expiry_account)
    user_token = read_secret(spec.user_token_account)
    user_refresh = read_secret(spec.user_refresh_account)
    user_expiry = read_secret(spec.user_token_expiry_account)
    redirect_uri = value_or_default(spec.redirect_account, spec.default_redirect)
    scopes = value_or_default(spec.scopes_account, spec.default_scopes)
    ok = bool(client_id and client_secret)
    token_expired = False
    if expiry:
        try:
            token_expired = int(float(expiry)) <= int(time.time())
        except ValueError:
            token_expired = True
    user_token_expired = False
    if user_expiry:
        try:
            user_token_expired = int(float(user_expiry)) <= int(time.time())
        except ValueError:
            user_token_expired = True
    return {
        "ok": ok,
        "client_id": mask_present(client_id),
        "client_secret": "configured" if client_secret else "missing",
        "redirect_uri": redirect_uri,
        "scopes": scopes,
        "auth_base": spec.auth_base,
        "api_base": spec.api_base,
        "app_token": "configured" if app_token else "missing",
        "app_token_expires_at": expiry_timestamp(expiry),
        "app_token_expired": token_expired,
        "user_token": "configured" if user_token else "missing",
        "user_refresh_token": "configured" if user_refresh else "missing",
        "user_token_expires_at": expiry_timestamp(user_expiry),
        "user_token_expired": user_token_expired,
    }


def all_status() -> Dict[str, Any]:
    return {
        "service": SERVICE,
        "no_key_mode": no_key_mode(),
        "providers": {provider: provider_status(provider) for provider in SPECS},
        "required_redirects": {
            "twitch": DEFAULT_TWITCH_REDIRECT,
            "kick": DEFAULT_KICK_REDIRECT,
        },
        "notes": [
            "Credentials are read from macOS Keychain first, then matching environment variables.",
            "Kick authorization-code user tokens require PKCE; app tokens use client_credentials.",
            "Twitch public clip/source research can start with an app access token.",
        ],
    }


def expiry_timestamp(raw: str) -> str:
    if not raw:
        return ""
    try:
        return datetime.fromtimestamp(int(float(raw)), tz=timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return raw


def form_post(url: str, data: Dict[str, str]) -> Dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload


def safe_form_post(url: str, data: Dict[str, str]) -> Dict[str, Any]:
    try:
        return {"ok": True, "payload": form_post(url, data), "http_status": 200}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(detail)
        except json.JSONDecodeError:
            payload = detail[:800]
        return {"ok": False, "payload": payload, "http_status": exc.code}
    except Exception as exc:
        return {"ok": False, "payload": {"error": type(exc).__name__, "detail": str(exc)}, "http_status": 0}


def refresh_app_token(provider: str) -> Dict[str, Any]:
    if no_key_mode():
        return {"status": "blocked", "provider": provider, "detail": "no-key mode blocks token refresh"}
    spec = SPECS[provider]
    client_id = read_secret(spec.client_id_account)
    client_secret = read_secret(spec.client_secret_account)
    if not client_id or not client_secret:
        return {"status": "blocked", "provider": provider, "detail": "client_id and client_secret are required"}

    if provider == "twitch":
        payload = form_post(
            f"{TWITCH_AUTH_BASE}/token",
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
        )
    elif provider == "kick":
        payload = form_post(
            f"{KICK_AUTH_BASE}/oauth/token",
            {
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
        )
    else:
        return {"status": "blocked", "provider": provider, "detail": "unknown provider"}

    token = str(payload.get("access_token", ""))
    expires_in = int(payload.get("expires_in", 0) or 0)
    if not token:
        return {"status": "failed", "provider": provider, "detail": "provider did not return access_token"}
    expires_at = str(int(time.time()) + max(0, expires_in - 60))
    write_secret(spec.app_token_account, token)
    write_secret(spec.app_token_expiry_account, expires_at)
    return {
        "status": "succeeded",
        "provider": provider,
        "token_type": payload.get("token_type", "bearer"),
        "expires_at": expiry_timestamp(expires_at),
        "scope": payload.get("scope", ""),
    }


def token_for(provider: str, kind: str = "app") -> str:
    spec = SPECS[provider]
    if kind == "user":
        return read_secret(spec.user_token_account)
    return read_secret(spec.app_token_account)


def client_id_for(provider: str) -> str:
    return read_secret(SPECS[provider].client_id_account)


def app_token_expired(provider: str) -> bool:
    expiry = read_secret(SPECS[provider].app_token_expiry_account)
    if not expiry:
        return True
    try:
        return int(float(expiry)) <= int(time.time())
    except ValueError:
        return True


def ensure_app_token(provider: str) -> Dict[str, Any]:
    if token_for(provider, "app") and not app_token_expired(provider):
        return {"status": "ready", "provider": provider, "detail": "app token configured"}
    return refresh_app_token(provider)


def store_user_token(provider: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    spec = SPECS[provider]
    token = str(payload.get("access_token", ""))
    refresh = str(payload.get("refresh_token", ""))
    expires_in = int(payload.get("expires_in", 0) or 0)
    if not token:
        return {"status": "failed", "provider": provider, "detail": "provider did not return access_token"}
    expires_at = str(int(time.time()) + max(0, expires_in - 60))
    write_secret(spec.user_token_account, token)
    write_secret(spec.user_token_expiry_account, expires_at)
    if refresh:
        write_secret(spec.user_refresh_account, refresh)
    return {
        "status": "succeeded",
        "provider": provider,
        "token_type": payload.get("token_type", "bearer"),
        "expires_at": expiry_timestamp(expires_at),
        "scope": payload.get("scope", ""),
        "refresh_token": "configured" if refresh else "missing",
    }


def exchange_authorization_code(provider: str, code: str, state: str = "") -> Dict[str, Any]:
    if no_key_mode():
        return {"status": "blocked", "provider": provider, "detail": "no-key mode blocks OAuth token exchange"}
    spec = SPECS[provider]
    expected_state = read_secret(spec.oauth_state_account)
    if expected_state and state and expected_state != state:
        return {"status": "blocked", "provider": provider, "detail": "OAuth state mismatch"}
    client_id = read_secret(spec.client_id_account)
    client_secret = read_secret(spec.client_secret_account)
    redirect_uri = value_or_default(spec.redirect_account, spec.default_redirect)
    if not client_id or not client_secret:
        return {"status": "blocked", "provider": provider, "detail": "client_id and client_secret are required"}
    if not code:
        return {"status": "blocked", "provider": provider, "detail": "authorization code is required"}

    body = {
        "grant_type": "authorization_code",
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if provider == "kick":
        verifier = read_secret("kick.pkce_code_verifier")
        if not verifier:
            return {"status": "blocked", "provider": provider, "detail": "Kick PKCE code verifier is missing; generate a fresh authorization URL"}
        body["code_verifier"] = verifier

    url = f"{spec.auth_base}/oauth/token" if provider == "kick" else f"{TWITCH_AUTH_BASE}/token"
    result = safe_form_post(url, body)
    if not result["ok"]:
        return {
            "status": "failed",
            "provider": provider,
            "http_status": result["http_status"],
            "detail": result["payload"],
        }
    stored = store_user_token(provider, result["payload"])
    stored["http_status"] = result["http_status"]
    return stored


def refresh_user_token(provider: str) -> Dict[str, Any]:
    if no_key_mode():
        return {"status": "blocked", "provider": provider, "detail": "no-key mode blocks user token refresh"}
    spec = SPECS[provider]
    client_id = read_secret(spec.client_id_account)
    client_secret = read_secret(spec.client_secret_account)
    refresh = read_secret(spec.user_refresh_account)
    if not client_id or not client_secret or not refresh:
        return {"status": "blocked", "provider": provider, "detail": "client_id, client_secret, and refresh token are required"}
    url = f"{spec.auth_base}/oauth/token" if provider == "kick" else f"{TWITCH_AUTH_BASE}/token"
    result = safe_form_post(
        url,
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
        },
    )
    if not result["ok"]:
        return {
            "status": "failed",
            "provider": provider,
            "http_status": result["http_status"],
            "detail": result["payload"],
        }
    stored = store_user_token(provider, result["payload"])
    stored["http_status"] = result["http_status"]
    return stored


def pkce_pair() -> Dict[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return {"code_verifier": verifier, "code_challenge": challenge}


def authorization_url(provider: str) -> Dict[str, Any]:
    spec = SPECS[provider]
    client_id = read_secret(spec.client_id_account)
    redirect_uri = value_or_default(spec.redirect_account, spec.default_redirect)
    scopes = value_or_default(spec.scopes_account, spec.default_scopes)
    state = secrets.token_urlsafe(24)
    if not client_id:
        return {"status": "blocked", "provider": provider, "detail": "client_id is required"}
    write_secret(spec.oauth_state_account, state)

    if provider == "twitch":
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
        }
        url = f"{TWITCH_AUTH_BASE}/authorize?{urllib.parse.urlencode(params)}"
        return {
            "status": "ready",
            "provider": provider,
            "url": url,
            "state": state,
            "redirect_uri": redirect_uri,
            "scopes": scopes,
            "pkce_required": False,
        }

    pkce = pkce_pair()
    write_secret("kick.pkce_code_verifier", pkce["code_verifier"])
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "code_challenge": pkce["code_challenge"],
        "code_challenge_method": "S256",
        "state": state,
    }
    url = f"{KICK_AUTH_BASE}/oauth/authorize?{urllib.parse.urlencode(params)}"
    return {
        "status": "ready",
        "provider": provider,
        "url": url,
        "state": state,
        "redirect_uri": redirect_uri,
        "scopes": scopes,
        "pkce_required": True,
    }
