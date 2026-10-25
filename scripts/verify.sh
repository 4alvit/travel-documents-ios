#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/check-localizations.py
swift test
xcodegen generate
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -configuration Release -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
plutil -lint App/Info.plist App/PrivacyInfo.xcprivacy
python3 -m json.tool App/Tripfolio.storekit >/dev/null
TRIPFOLIO_BINARY=build/DerivedData/Build/Products/Release-iphonesimulator/Tripfolio.app/Tripfolio
if [[ ! -s "$TRIPFOLIO_BINARY" || ! -x "$TRIPFOLIO_BINARY" ]]; then
  echo 'ERROR: the expected Release executable is missing, empty, or not executable.' >&2
  exit 1
fi
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
