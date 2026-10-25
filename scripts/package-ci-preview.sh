#!/bin/bash
# Run immediately after the workflow's successful Verify step, from a checkout.
set -euo pipefail
cd "$(dirname "$0")/.."
TRIPDOCKET_COMMIT=$(git rev-parse HEAD)
TRIPDOCKET_TREE=$(git rev-parse 'HEAD^{tree}')
TRIPDOCKET_STATUS=$(git status --porcelain)
TRIPDOCKET_APP=build/DerivedData/Build/Products/Release-iphonesimulator/Tripfolio.app
TRIPDOCKET_OUTPUT=build/ci-preview
[[ -z "$TRIPDOCKET_STATUS" ]] || { echo 'ERROR: source checkout is not clean.' >&2; exit 1; }
[[ -d "$TRIPDOCKET_APP" && ! -L "$TRIPDOCKET_APP" && -s "$TRIPDOCKET_APP/Tripfolio" && -x "$TRIPDOCKET_APP/Tripfolio" ]] || {
  echo 'ERROR: expected existing Release Simulator app and executable.' >&2; exit 1;
}
TRIPDOCKET_VERIFIED_COMMIT=$(cat build/ci-toolchain/verified-commit.txt)
[[ "$TRIPDOCKET_VERIFIED_COMMIT" == "$TRIPDOCKET_COMMIT" ]] || {
  echo 'ERROR: successful Verify receipt does not match this checkout.' >&2; exit 1;
}
[[ ! -e "$TRIPDOCKET_OUTPUT" && ! -L "$TRIPDOCKET_OUTPUT" ]] || {
  echo 'ERROR: preserve the existing preview output before packaging again.' >&2; exit 1;
}
TRIPDOCKET_STAGING=$(mktemp -d build/.ci-preview.XXXXXX)
trap 'rm -rf -- "$TRIPDOCKET_STAGING"' EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
ditto -c -k --sequesterRsrc --keepParent "$TRIPDOCKET_APP" "$TRIPDOCKET_STAGING/TripDocket-Simulator.zip"
python3 - "$TRIPDOCKET_APP" "$TRIPDOCKET_STAGING" "$TRIPDOCKET_COMMIT" "$TRIPDOCKET_TREE" <<'PY'
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import stat
import subprocess
import sys
import zipfile

app, output = map(Path, sys.argv[1:3])
commit, tree = sys.argv[3:5]

def require(condition, message):
    if not condition:
        raise SystemExit("ERROR: " + message)

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def members(path):
    mode = path.lstat().st_mode
    require(stat.S_ISREG(mode) or stat.S_ISDIR(mode), "unsupported app entry: " + str(path.relative_to(app)))
    yield path, mode
    if stat.S_ISDIR(mode):
        with os.scandir(path) as entries:
            for entry in entries:
                yield from members(Path(entry.path))

# Read/stat/traversal/ZIP errors propagate. Nothing is repaired or chmodded.
source = {"Tripfolio.app" + ("/" + str(p.relative_to(app)) if p != app else ""):
          (p, mode) for p, mode in members(app)}
require(stat.S_ISREG(source["Tripfolio.app/Tripfolio"][1]), "main executable is not a regular file")
info = plistlib.loads((app / "Info.plist").read_bytes())
require(info.get("CFBundleExecutable") == "Tripfolio", "unexpected bundle executable")
require(info.get("CFBundlePackageType") == "APPL", "unexpected bundle type")
require(info.get("DTPlatformName") == "iphonesimulator", "bundle is not a Simulator build")
require(info.get("CFBundleSupportedPlatforms") == ["iPhoneSimulator"], "unexpected supported platforms")
archive = output / "TripDocket-Simulator.zip"
with zipfile.ZipFile(archive) as zipped:
    seen = set()
    for entry in zipped.infolist():
        name = entry.filename.rstrip("/")
        parts = PurePosixPath(name).parts
        require(parts and not name.startswith("/") and ".." not in parts, "unsafe ZIP path")
        require(name not in seen, "duplicate ZIP entry")
        seen.add(name)
        if parts[0] == "__MACOSX":  # ditto's optional AppleDouble metadata
            continue
        require(name in source, "unexpected ZIP entry: " + name)
        path, mode = source[name]
        require(stat.S_IFMT(entry.external_attr >> 16) == stat.S_IFMT(mode), "ZIP entry type changed: " + name)
        require(stat.S_IMODE(entry.external_attr >> 16) == stat.S_IMODE(mode), "ZIP permissions changed: " + name)
        if stat.S_ISREG(mode):
            require(zipped.read(entry) == path.read_bytes(), "ZIP bytes changed: " + name)
    require(set(source).issubset(seen), "ZIP omitted app entries or the .app root")

toolchain = {}
for tool in ("xcode", "swift"):
    value = Path("build/ci-toolchain/" + tool + ".txt").read_text().strip()
    require(bool(value), "missing recorded " + tool + " version")
    toolchain[tool] = value
ci_keys = ("GITHUB_REPOSITORY", "GITHUB_WORKFLOW", "GITHUB_JOB", "GITHUB_RUN_ID",
           "GITHUB_RUN_ATTEMPT", "GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA")
provenance = {
    "schema_version": 1,
    "packaged_at_utc": datetime.now(timezone.utc).isoformat(),
    "source": {"commit": commit, "tree": tree, "clean_checkout": True,
               "parents": subprocess.check_output(["git", "show", "-s", "--format=%P", commit], text=True).strip().split()},
    "artifact": {"filename": archive.name, "sha256": sha256(archive.read_bytes()),
                 "bundle_root": "Tripfolio.app", "executable_sha256": sha256((app / "Tripfolio").read_bytes()),
                 "app_file_count": sum(stat.S_ISREG(mode) for _, mode in source.values()),
                 "source_bytes_and_unix_modes_match_zip": True},
    "build": {"configuration": "Release", "sdk": "iphonesimulator", "code_signing_allowed": False,
              "producer": "scripts/verify.sh", "successful_verify_receipt_commit": commit,
              "build_or_tests_repeated_by_packager": False,
              "toolchain_recorded_by_workflow": toolchain,
              "bundle_metadata": {key: info.get(key) for key in ("DTXcode", "DTXcodeBuild", "DTSDKName", "DTSDKBuild")}},
    "ci": {key: os.environ.get(key) for key in ci_keys},
    "status": {"kind": "unsigned Simulator preview", "app_store_release": False,
               "runtime_accepted": False, "ci_result_at_packaging": "not_final"},
    "limits": ["Source identity is the actual checkout HEAD, including a merge commit when checked out; GITHUB_SHA is event metadata only.",
               "The Verify receipt and recorded toolchain depend on the immediately preceding workflow steps, not independent attestation.",
               "No Apple distribution signing, device installation, runtime acceptance or public release is implied."]
}
(output / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
(output / "SHA256SUMS").write_text("".join(
    sha256((output / name).read_bytes()) + "  " + name + "\n"
    for name in (archive.name, "provenance.json")))
PY
TRIPDOCKET_CURRENT_COMMIT=$(git rev-parse HEAD)
TRIPDOCKET_STATUS=$(git status --porcelain)
[[ "$TRIPDOCKET_CURRENT_COMMIT" == "$TRIPDOCKET_COMMIT" && -z "$TRIPDOCKET_STATUS" ]] || {
  echo 'ERROR: source changed during packaging.' >&2; exit 1;
}
[[ ! -e "$TRIPDOCKET_OUTPUT" && ! -L "$TRIPDOCKET_OUTPUT" ]] || { echo 'ERROR: output appeared during packaging.' >&2; exit 1; }
mv "$TRIPDOCKET_STAGING" "$TRIPDOCKET_OUTPUT"
echo "Packaged $TRIPDOCKET_OUTPUT/TripDocket-Simulator.zip for checkout $TRIPDOCKET_COMMIT"
