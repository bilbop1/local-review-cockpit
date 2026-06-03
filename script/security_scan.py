#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "security" / "security-scan.json"
TEXT_SUFFIXES = {
    "",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".swift",
    ".toml",
    ".txt",
    ".rtf",
    ".yml",
    ".yaml",
    ".env",
}
SKIP_PARTS = {
    ".build",
    ".git",
    ".run",
    ".venv",
    "__pycache__",
    "dist",
    "node_modules",
}
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PRIVATE )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{12,}", re.IGNORECASE),
    re.compile(r"(access_token|refresh_token|discord_token|bot_token|authorization)\s*[:=]\s*[\"'][^\"']{8,}[\"']", re.IGNORECASE),
    re.compile(r"(client_secret|kick_secret|twitch_secret|secret)\s*[:=]\s*[\"'](?!configured|missing|redacted)[^\"']{8,}[\"']", re.IGNORECASE),
    re.compile(r"\b(?:xox[baprs]-|gh[pousr]_|sk-[A-Za-z0-9])[A-Za-z0-9_-]{16,}\b", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{64}\b", re.IGNORECASE),
]
ALLOWLIST = {
    "backend/uv.lock",
    "artifacts/desktop-qa/manifest.json",
    "artifacts/security/security-scan.json",
}
HIGH_ENTROPY_CONTEXT_KEYS = (
    "token",
    "secret",
    "authorization",
    "password",
    "private_key",
    "client_secret",
)
PUBLIC_SOURCE_URL_DOMAINS = (
    "twitch.tv/",
    "youtube.com/",
    "youtu.be/",
    "kick.com/",
)


def entropy(text: str) -> float:
    if not text:
        return 0.0
    counts = {char: text.count(char) for char in set(text)}
    length = len(text)
    return -sum((count / length) * math.log2(count / length) for count in counts.values())


def redacted_excerpt(line: str) -> str:
    compact = line.strip()
    if len(compact) <= 24:
        return "<redacted>"
    return f"{compact[:8]}...<redacted>...{compact[-6:]}"


def is_public_source_url_line(line: str) -> bool:
    lowered = line.lower()
    return any(key in lowered for key in ('"source_url"', '"clip_source_url"', '"media_url"')) and any(
        domain in lowered for domain in PUBLIC_SOURCE_URL_DOMAINS
    )


def should_scan(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in SKIP_PARTS for part in rel.parts):
        return False
    if str(rel) in ALLOWLIST:
        return False
    if path.name.startswith(".env"):
        return True
    if path.suffix not in TEXT_SUFFIXES:
        return False
    return path.is_file()


def main() -> int:
    findings = []
    for path in ROOT.rglob("*"):
        if not should_scan(path):
            continue
        rel = str(path.relative_to(ROOT))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            if "sha256" in lowered or "checksum" in lowered:
                continue
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    findings.append(
                        {
                            "path": rel,
                            "line": line_number,
                            "pattern": pattern.pattern,
                            "excerpt": redacted_excerpt(line),
                        }
                    )
            if "secrets_transferred=false" in lowered or '"secrets_transferred": false' in lowered:
                continue
            if is_public_source_url_line(line):
                continue
            if not any(key in lowered for key in HIGH_ENTROPY_CONTEXT_KEYS):
                continue
            for token in re.findall(r"[A-Za-z0-9_+/=-]{32,}", line):
                if entropy(token) >= 4.2:
                    findings.append(
                        {
                            "path": rel,
                            "line": line_number,
                            "pattern": "high_entropy_token",
                            "excerpt": redacted_excerpt(line),
                        }
                    )
                    break
    payload = {
        "ok": not findings,
        "finding_count": len(findings),
        "findings": findings[:100],
        "note": "Scans repo text artifacts for common token/secret shapes. Keychain and browser sessions are intentionally not read.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(OUT)
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
