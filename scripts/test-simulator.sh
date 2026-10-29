#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# No arguments preserves the complete local test run. CI uses two disjoint
# cohorts so long guidance tests and purchase tests have separate job budgets.
TEST_ARGUMENTS=(test)
if [[ $# -ne 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--cohort" ]]; then
    echo "Usage: $0 [--cohort core-purchase|ui-guidance]" >&2
    exit 2
  fi
  case "$2" in
    core-purchase)
      TEST_ARGUMENTS=(test
        -only-testing:TripfolioTests
        -only-testing:TripfolioUITests/PurchaseUITests
        -only-testing:TripfolioUITests/TripfolioUITests)
      ;;
    ui-guidance)
      TEST_ARGUMENTS=(test
        -only-testing:TripfolioUITests
        -skip-testing:TripfolioUITests/PurchaseUITests
        -skip-testing:TripfolioUITests/TripfolioUITests)
      ;;
    *)
      echo "Unknown test cohort: $2" >&2
      exit 2
      ;;
  esac
fi
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
# Keep the default at 180s while allowing the Russian maximum-type guidance
# flow to request 480s. Other tests retain their existing individual allowances.
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -configuration Debug -destination "platform=iOS Simulator,id=$TRIPFOLIO_SIMULATOR_ID" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -collect-test-diagnostics never \
  -default-test-execution-time-allowance 180 -maximum-test-execution-time-allowance 480 \
  -derivedDataPath build/DerivedData \
  -resultBundlePath "build/Tests-$(date -u +%Y%m%dT%H%M%SZ).xcresult" \
  CODE_SIGNING_ALLOWED=NO "${TEST_ARGUMENTS[@]}"
