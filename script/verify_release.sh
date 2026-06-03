#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="adhoc"
if [[ "${1:-}" == "--mode" ]]; then
  MODE="${2:-adhoc}"
  shift 2
fi
APP_BUNDLE="${1:-$ROOT_DIR/dist/release/Clipping Ops Cockpit.app}"
ZIP_PATH="${2:-$ROOT_DIR/dist/release/ClippingOpsCockpit-release.zip}"
OUT_DIR="$ROOT_DIR/artifacts/distribution"
OUT_FILE="$OUT_DIR/release-verify.json"

mkdir -p "$OUT_DIR"

python3 - "$ROOT_DIR" "$APP_BUNDLE" "$ZIP_PATH" "$OUT_FILE" "$MODE" <<'PY'
import hashlib
import json
import plistlib
import subprocess
import sys
import time
import zipfile
from pathlib import Path

root = Path(sys.argv[1])
bundle = Path(sys.argv[2])
zip_path = Path(sys.argv[3])
out_file = Path(sys.argv[4])
mode = sys.argv[5]
expected_bundle_id = "com.bilbop.ClippingOpsCockpit"
expected_executable = "ClippingOpsCockpit"


def run(command):
    return subprocess.run(command, text=True, capture_output=True, timeout=60)


info_path = bundle / "Contents" / "Info.plist"
binary = bundle / "Contents" / "MacOS" / expected_executable
bundle_ok = bundle.is_dir() and info_path.exists() and binary.exists()
info = {}
if info_path.exists():
    with info_path.open("rb") as handle:
        info = plistlib.load(handle)

codesign_verify = run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(bundle)]) if bundle.exists() else None
codesign_detail = run(["codesign", "-dv", "--verbose=4", str(bundle)]) if bundle.exists() else None
codesign_text = ((codesign_detail.stdout if codesign_detail else "") + (codesign_detail.stderr if codesign_detail else ""))
signed_ok = bool(codesign_verify and codesign_verify.returncode == 0)
signing_identity = "unknown"
for line in codesign_text.splitlines():
    if line.startswith("Authority="):
        signing_identity = line.split("=", 1)[1].strip()
        break
    if "Signature=adhoc" in line:
        signing_identity = "adhoc"
hardened_runtime_ok = "runtime" in codesign_text.lower()
developer_id_ok = signing_identity.startswith("Developer ID Application:")

stapler = run(["xcrun", "stapler", "validate", str(bundle)]) if bundle.exists() else None
notarized_ok = bool(stapler and stapler.returncode == 0)
spctl = run(["spctl", "--assess", "--type", "execute", "--verbose=4", str(bundle)]) if bundle.exists() else None
spctl_ok = bool(spctl and spctl.returncode == 0)
zip_ok = zip_path.exists() and zip_path.stat().st_size > 0
zip_sha256 = ""
zip_contents_ok = False
zip_has_appledouble = False
if zip_ok:
    zip_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
        zip_has_appledouble = any("/._" in name or name.startswith("__MACOSX/") for name in names)
        zip_contents_ok = any(name.endswith(".app/Contents/Info.plist") for name in names) and not zip_has_appledouble
    except Exception:
        zip_contents_ok = False

blockers = []
if not bundle_ok:
    blockers.append("app bundle structure is incomplete")
if info.get("CFBundleIdentifier") != expected_bundle_id:
    blockers.append("bundle id mismatch")
if info.get("CFBundleExecutable") != expected_executable:
    blockers.append("executable mismatch")
if not signed_ok:
    blockers.append("codesign verification failed")
if not developer_id_ok:
    blockers.append("release is not signed with Developer ID Application")
if not hardened_runtime_ok:
    blockers.append("hardened runtime flag not detected")
if not notarized_ok:
    blockers.append("notarization/stapler validation is missing")
if not spctl_ok:
    blockers.append("spctl acceptance failed")
if not zip_ok:
    blockers.append("release zip missing")
if zip_ok and not zip_contents_ok:
    blockers.append("release zip contains bad metadata or is missing app contents")

dev_blockers = []
if not bundle_ok:
    dev_blockers.append("app bundle structure is incomplete")
if info.get("CFBundleIdentifier") != expected_bundle_id:
    dev_blockers.append("bundle id mismatch")
if info.get("CFBundleExecutable") != expected_executable:
    dev_blockers.append("executable mismatch")
if not signed_ok:
    dev_blockers.append("codesign verification failed")
if not hardened_runtime_ok:
    dev_blockers.append("hardened runtime flag not detected")
if not zip_ok or not zip_contents_ok:
    dev_blockers.append("clean release zip missing")

payload = {
    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "mode": mode,
    "bundle_path": str(bundle),
    "zip_path": str(zip_path),
    "zip_sha256": zip_sha256,
    "bundle_ok": bundle_ok,
    "bundle_id": info.get("CFBundleIdentifier", ""),
    "executable": info.get("CFBundleExecutable", ""),
    "signed_ok": signed_ok,
    "signing_identity": signing_identity,
    "developer_id_ok": developer_id_ok,
    "hardened_runtime_ok": hardened_runtime_ok,
    "notarized_ok": notarized_ok,
    "spctl_ok": spctl_ok,
    "zip_ok": zip_ok,
    "zip_contents_ok": zip_contents_ok,
    "zip_has_appledouble": zip_has_appledouble,
    "dev_release_ready": not dev_blockers,
    "customer_ship_ready": not blockers,
    "blockers": blockers if mode == "customer" else dev_blockers + [item for item in blockers if item in {"release is not signed with Developer ID Application", "notarization/stapler validation is missing", "spctl acceptance failed"}],
    "customer_blockers": blockers,
    "dev_blockers": dev_blockers,
    "codesign_verify": {
        "returncode": codesign_verify.returncode if codesign_verify else None,
        "stderr": (codesign_verify.stderr if codesign_verify else "")[-2000:],
    },
    "stapler": {
        "returncode": stapler.returncode if stapler else None,
        "stderr": (stapler.stderr if stapler else "")[-2000:],
    },
    "spctl": {
        "returncode": spctl.returncode if spctl else None,
        "stderr": (spctl.stderr if spctl else "")[-2000:],
    },
}
out_file.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(out_file)
raise SystemExit(0 if (not dev_blockers if mode != "customer" else not blockers) else 1)
PY
