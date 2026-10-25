#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
xcodegen generate
if [[ -z "${TRIPFOLIO_SIMULATOR_ID:-}" ]]; then
  TRIPFOLIO_SIMULATOR_ID=$(xcrun simctl list devices available -j | python3 -c '
import json, sys
devices = json.load(sys.stdin)["devices"]
phones = [d for runtime, items in sorted(devices.items(), reverse=True) if ".iOS-" in runtime
          for d in items if d.get("isAvailable") and "iPhone" in d["name"]]
if not phones:
    sys.exit("No available iOS simulator. Install an iOS runtime in Xcode Settings > Components.")
print(phones[0]["udid"])
')
fi
mkdir -p build
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -configuration Debug -destination "platform=iOS Simulator,id=$TRIPFOLIO_SIMULATOR_ID" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -collect-test-diagnostics never \
  -derivedDataPath build/DerivedData \
  -resultBundlePath "build/Tests-$(date -u +%Y%m%dT%H%M%SZ).xcresult" \
  CODE_SIGNING_ALLOWED=NO test
