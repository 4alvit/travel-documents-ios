#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
# No arguments preserves the complete local test run. CI uses two disjoint
# cohorts so long guidance tests and purchase tests have separate job budgets.
TRIPFOLIO_REQUIRE_SDK_MATCH=0
TRIPFOLIO_PREPARE_FILES=0
if [[ "${1:-}" == "--require-sdk-match" ]]; then
  TRIPFOLIO_REQUIRE_SDK_MATCH=1
  shift
fi
if [[ "${1:-}" == "--prepare-files" ]]; then
  TRIPFOLIO_PREPARE_FILES=1
  shift
fi
if [[ "$TRIPFOLIO_PREPARE_FILES" == 1 && ( "$TRIPFOLIO_REQUIRE_SDK_MATCH" != 1 || $# -ne 2 || "${1:-}" != "--cohort" || "${2:-}" != "ui-guidance" || "${GITHUB_ACTIONS:-}" != true ) ]]; then
  echo "Files preparation requires CI --require-sdk-match --cohort ui-guidance" >&2
  exit 2
fi
TEST_ARGUMENTS=(test)
MAXIMUM_TEST_SECONDS=480
if [[ $# -ne 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--cohort" ]]; then
    echo "Usage: $0 [--require-sdk-match [--prepare-files]] [--cohort core-purchase|ui-guidance]" >&2
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
      MAXIMUM_TEST_SECONDS=600
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
if [[ "$TRIPFOLIO_REQUIRE_SDK_MATCH" == 1 ]]; then
  mkdir -p build/ci-toolchain
  TRIPFOLIO_SELECTION_DIR=$(mktemp -d build/ci-toolchain/simulator-selection.XXXXXX)
  xcrun --sdk iphonesimulator --show-sdk-version > "$TRIPFOLIO_SELECTION_DIR/sdk.txt"
  uname -m > "$TRIPFOLIO_SELECTION_DIR/architecture.txt"
  xcrun simctl list runtimes --json > "$TRIPFOLIO_SELECTION_DIR/runtimes.json"
  xcrun simctl list devicetypes --json > "$TRIPFOLIO_SELECTION_DIR/device-types.json"
  xcrun simctl list devices --json > "$TRIPFOLIO_SELECTION_DIR/devices.json"
  TRIPFOLIO_SELECTION_ARGS=(--inventory "$TRIPFOLIO_SELECTION_DIR")
  if [[ -n "${TRIPFOLIO_SIMULATOR_ID:-}" ]]; then
    TRIPFOLIO_SELECTION_ARGS+=(--requested-udid "$TRIPFOLIO_SIMULATOR_ID")
  fi
  TRIPFOLIO_SIMULATOR_ID=$(python3 -B scripts/select-simulator.py "${TRIPFOLIO_SELECTION_ARGS[@]}")
  if [[ "$TRIPFOLIO_PREPARE_FILES" == 1 ]]; then
    # Explicit preinitialized-provider coverage; not cold first-use acceptance.
    python3 -B scripts/prepare-guidance-files.py --selection-directory "$TRIPFOLIO_SELECTION_DIR"
  fi
elif [[ -z "${TRIPFOLIO_SIMULATOR_ID:-}" ]]; then
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
# Keep the default at 180s. Only the guidance cohort permits the Russian
# maximum-type flow to request 600s; other individual allowances are unchanged.
# Core/local cohorts and the dedicated iPad driver retain their 480s ceilings.
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -configuration Debug -destination "platform=iOS Simulator,id=$TRIPFOLIO_SIMULATOR_ID" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -collect-test-diagnostics never \
  -default-test-execution-time-allowance 180 -maximum-test-execution-time-allowance "$MAXIMUM_TEST_SECONDS" \
  -derivedDataPath build/DerivedData \
  -resultBundlePath "build/Tests-$(date -u +%Y%m%dT%H%M%SZ).xcresult" \
  CODE_SIGNING_ALLOWED=NO "${TEST_ARGUMENTS[@]}"
