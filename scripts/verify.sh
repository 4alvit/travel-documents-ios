#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/check-localizations.py
swift test
xcodegen generate
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -configuration Release -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO \
  ENABLE_CODE_COVERAGE=NO DEPLOYMENT_POSTPROCESSING=YES \
  STRIP_INSTALLED_PRODUCT=YES build
plutil -lint App/Info.plist App/PrivacyInfo.xcprivacy
python3 -m json.tool App/Tripfolio.storekit >/dev/null
TRIPFOLIO_BINARY=build/DerivedData/Build/Products/Release-iphonesimulator/Tripfolio.app/Tripfolio
if [[ ! -s "$TRIPFOLIO_BINARY" || ! -x "$TRIPFOLIO_BINARY" ]]; then
  echo 'ERROR: the expected Release executable is missing, empty, or not executable.' >&2
  exit 1
fi
python3 - "$TRIPFOLIO_BINARY" "$PWD" <<'PY'
from pathlib import Path
import os
import stat
import sys

app = Path(sys.argv[1]).parent

def regular_files(directory):
    # Propagate traversal/stat/read failures instead of silently skipping files.
    with os.scandir(directory) as entries:
        for entry in entries:
            mode = entry.stat(follow_symlinks=False).st_mode
            if stat.S_ISDIR(mode):
                yield from regular_files(Path(entry.path))
            elif stat.S_ISREG(mode):
                yield Path(entry.path)
            else:
                raise SystemExit(f"ERROR: unsupported Release app entry: {Path(entry.path).relative_to(app)}")

markers = {
    "user home path": b"/Users/",
    "CI home path": b"/home/runner/",
    "build root": sys.argv[2].encode(),
    "coverage counter": b"___profc_",
    "coverage mapping": b"__llvm_cov",
    "coverage profile": b"__llvm_prf",
}
failures = []
checked = 0
for path in regular_files(app):
    data = path.read_bytes()
    checked += 1
    for label, marker in markers.items():
        if marker in data:
            failures.append(f"{path.relative_to(app)}: {label}")
if failures:
    raise SystemExit("ERROR: build metadata found in Release app:\n" + "\n".join(failures))
if not checked:
    raise SystemExit("ERROR: Release app has no readable files.")
print(f"Release app metadata scan passed: {checked} files")
PY
TRIPFOLIO_STRINGS_FILE=$(mktemp "${TMPDIR:-/tmp}/tripfolio-release-strings.XXXXXX")
trap 'rm -f -- "$TRIPFOLIO_STRINGS_FILE"' EXIT
# Keep the scanner outside an if condition: a tool/read failure must fail the
# verification rather than look like a successful absence-of-debug-flags check.
strings "$TRIPFOLIO_BINARY" > "$TRIPFOLIO_STRINGS_FILE"
if grep -E -- '--ui-testing-unlocked|--ui-testing-reset|--demo' "$TRIPFOLIO_STRINGS_FILE" >/dev/null; then
  echo 'ERROR: development launch flags were found in the Release binary.' >&2
  exit 1
else
  TRIPFOLIO_SCAN_STATUS=$?
  if [[ "$TRIPFOLIO_SCAN_STATUS" -ne 1 ]]; then
    echo 'ERROR: the development-launch-flag check could not be completed.' >&2
    exit 1
  fi
fi
