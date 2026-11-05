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
# A caller cannot carry hosted Phone scope into preparation or another cohort.
if [[ ${TEST_RUNNER_TRIPDOCKET_PHONE_TIMING+x} || ${TRIPDOCKET_PHONE_TIMING+x} || ${SIMCTL_CHILD_TRIPDOCKET_PHONE_TIMING+x} ]]; then
  echo "Phone timing profile must be selected by this script" >&2
  exit 2
fi
if [[ ${TEST_RUNNER_TRIPDOCKET_CORE_TIMING+x} || ${TRIPDOCKET_CORE_TIMING+x} || ${SIMCTL_CHILD_TRIPDOCKET_CORE_TIMING+x} ]]; then
  echo "Core timing profile must be selected by this script" >&2
  exit 2
fi
TRIPFOLIO_HOSTED_CORE_TIMING=0
TRIPFOLIO_HOSTED_PHONE_TIMING=0
if [[ "$TRIPFOLIO_PREPARE_FILES" == 1 && "${RUNNER_ARCH:-}" == X64 ]]; then
  if [[ "${RUNNER_OS:-}" != macOS || "${RUNNER_ENVIRONMENT:-}" != github-hosted || "${GITHUB_WORKFLOW:-}" != CI || "${GITHUB_JOB:-}" != ui_guidance || "${GITHUB_REPOSITORY:-}" != 4alvit/travel-documents-ios || "$(uname -m)" != x86_64 ]]; then
    echo "Hosted Phone timing requires the exact Intel CI runner" >&2
    exit 2
  fi
  if [[ ${TEST_RUNNER_TRIPDOCKET_IPAD_TIMING+x} || ${TRIPDOCKET_IPAD_TIMING+x} || ${SIMCTL_CHILD_TRIPDOCKET_IPAD_TIMING+x} ]]; then
    echo "Hosted Phone timing cannot inherit an iPad profile" >&2
    exit 2
  fi
  TRIPFOLIO_HOSTED_PHONE_TIMING=1
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
      if [[ "$TRIPFOLIO_REQUIRE_SDK_MATCH" == 1 && "${GITHUB_ACTIONS:-}" == true && "${RUNNER_ARCH:-}" == X64 ]]; then
        if [[ "${RUNNER_OS:-}" != macOS || "${RUNNER_ENVIRONMENT:-}" != github-hosted || "${GITHUB_WORKFLOW:-}" != CI || "${GITHUB_JOB:-}" != validate || "${GITHUB_REPOSITORY:-}" != 4alvit/travel-documents-ios || "$(uname -m)" != x86_64 ]]; then
          echo "Hosted Core timing requires the exact Intel CI runner" >&2
          exit 2
        fi
        if [[ ${SIMCTL_CHILD_TRIPDOCKET_PHONE_TIMING+x} || ${TEST_RUNNER_TRIPDOCKET_IPAD_TIMING+x} || ${TRIPDOCKET_IPAD_TIMING+x} || ${SIMCTL_CHILD_TRIPDOCKET_IPAD_TIMING+x} ]]; then
          echo "Hosted Core timing cannot inherit another timing profile" >&2
          exit 2
        fi
        TRIPFOLIO_HOSTED_CORE_TIMING=1
      fi
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
# Only the final invocation receives its validated hosted cohort profile.
# Preparation uses its own bounded profile; ordinary/local/iPad defaults stay unchanged.
if [[ "$TRIPFOLIO_HOSTED_PHONE_TIMING" == 1 ]]; then
  test "$(cat "$TRIPFOLIO_SELECTION_DIR/architecture.txt")" = x86_64
  export TEST_RUNNER_TRIPDOCKET_PHONE_TIMING=hosted-intel-phone-v1
  MAXIMUM_TEST_SECONDS=1500
fi
if [[ "$TRIPFOLIO_HOSTED_CORE_TIMING" == 1 ]]; then
  test "$(cat "$TRIPFOLIO_SELECTION_DIR/architecture.txt")" = x86_64
  export TEST_RUNNER_TRIPDOCKET_CORE_TIMING=hosted-intel-core-v1
fi
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -configuration Debug -destination "platform=iOS Simulator,id=$TRIPFOLIO_SIMULATOR_ID" \
  -parallel-testing-enabled NO -maximum-concurrent-test-simulator-destinations 1 \
  -collect-test-diagnostics never \
  -default-test-execution-time-allowance 180 -maximum-test-execution-time-allowance "$MAXIMUM_TEST_SECONDS" \
  -derivedDataPath build/DerivedData \
  -resultBundlePath "build/Tests-$(date -u +%Y%m%dT%H%M%SZ).xcresult" \
  CODE_SIGNING_ALLOWED=NO "${TEST_ARGUMENTS[@]}"
