#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/artifacts/handoff"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
ZIP_PATH="$OUT_DIR/ClippingOpsCockpit-codex-handoff-$STAMP.zip"
MANIFEST_PATH="$OUT_DIR/codex-handoff.json"

mkdir -p "$OUT_DIR"

python3 - "$ROOT_DIR" "$ZIP_PATH" "$MANIFEST_PATH" <<'PY'
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

root = Path(os.path.realpath(sys.argv[1]))
zip_path = Path(sys.argv[2])
manifest_path = Path(sys.argv[3])

skip_parts = {
    ".build",
    ".git",
    ".run",
    ".venv",
    "__pycache__",
    "artifacts",
    "dist",
    "node_modules",
}
skip_globs = {
    ".DS_Store",
    ".env",
    ".env.*",
    "*.log",
    "*.pyc",
    "*.sqlite3",
    "*.sqlite3-shm",
    "*.sqlite3-wal",
    "*.zip",
    "*.rtf",
}
include_roots = {
    ".codex",
    "backend",
    "docs",
    "hermes",
    "script",
    "tests",
    "web",
}
include_files = {
    ".gitignore",
    "AGENT_START_HERE.md",
    "README.md",
}
forbidden_parts = {
    ".env",
    "Keychains",
    "Cookies",
    "Login Data",
    "Local State",
    "Discord",
}


def should_skip(rel: Path) -> bool:
    parts = set(rel.parts)
    if parts & skip_parts:
        return True
    name = rel.name
    if any(fnmatch.fnmatch(name, pattern) for pattern in skip_globs):
        return True
    if any(part in forbidden_parts for part in rel.parts):
        return True
    if rel.parts and rel.parts[0] in include_roots:
        return False
    return str(rel) not in include_files


files = []
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue
    rel = path.relative_to(root)
    if should_skip(rel):
        continue
    files.append((path, rel))

zip_path.parent.mkdir(parents=True, exist_ok=True)
tmp_zip = zip_path.with_suffix(".zip.tmp")
if tmp_zip.exists():
    tmp_zip.unlink()
with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path, rel in files:
        archive.write(path, f"ClippingOpsCockpit/{rel.as_posix()}")
tmp_zip.replace(zip_path)

sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
entries = []
with zipfile.ZipFile(zip_path) as archive:
    entries = archive.namelist()

bad_entries = [
    entry
    for entry in entries
    if any(part in entry.split("/") for part in [".git", "artifacts", "dist", ".run", ".venv", "__pycache__"])
    or "/.env" in entry
    or entry.endswith(".sqlite3")
    or entry.endswith(".sqlite3-wal")
    or entry.endswith(".sqlite3-shm")
    or entry.startswith("__MACOSX/")
    or "/._" in entry
]

payload = {
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "mode": "source_build_handoff",
    "zip_path": str(zip_path),
    "zip_sha256": sha256,
    "file_count": len(files),
    "source_build_handoff_ready": not bad_entries and len(files) > 0,
    "requires_developer_id": False,
    "requires_notarization": False,
    "secrets_transferred": False,
    "excluded": sorted(skip_parts | skip_globs),
    "bad_entries": bad_entries[:50],
    "ok": not bad_entries and len(files) > 0,
    "note": "For buddy Codex sessions: unzip or clone, install local dependencies, provide their own Twitch/Kick/Upload-Post API keys plus Hermes/Discord config, and run the local web cockpit. This is source-build web software, not a native app bundle.",
}
manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(manifest_path)
raise SystemExit(0 if payload["ok"] else 1)
PY
