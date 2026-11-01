#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
TRIPFOLIO_INITIAL_STATUS=$(git status --porcelain)
if [[ -n "$TRIPFOLIO_INITIAL_STATUS" ]]; then
  echo 'Commit the reviewed source first: preview packages require a clean checkout.' >&2
  exit 1
fi
TRIPFOLIO_COMMIT=$(git rev-parse HEAD)
TRIPFOLIO_OUTPUT="dist/$TRIPFOLIO_COMMIT"

require_reviewed_source() {
  local current_commit current_status
  current_commit=$(git rev-parse HEAD)
  current_status=$(git status --porcelain)
  if [[ "$current_commit" != "$TRIPFOLIO_COMMIT" || -n "$current_status" ]]; then
    echo 'Source changed during packaging. Commit and review the changes, then build a new preview.' >&2
    exit 1
  fi
}

mkdir -p dist
TRIPFOLIO_LOCK="dist/.$TRIPFOLIO_COMMIT.package-lock"
if ! mkdir "$TRIPFOLIO_LOCK"; then
  echo 'This commit already has a packaging operation or an interrupted-operation lock.' >&2
  exit 1
fi
TRIPFOLIO_STAGING=''
cleanup() {
  if [[ -n "$TRIPFOLIO_STAGING" ]]; then rm -rf -- "$TRIPFOLIO_STAGING"; fi
  rmdir "$TRIPFOLIO_LOCK"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
if [[ -e "$TRIPFOLIO_OUTPUT" ]]; then
  echo 'A package for this commit already exists. Preserve it or explicitly move it before rebuilding.' >&2
  exit 1
fi

bash scripts/verify.sh
require_reviewed_source
TRIPFOLIO_STAGING=$(mktemp -d "dist/.$TRIPFOLIO_COMMIT.staging.XXXXXX")
git archive --format=tar --prefix=TripDocket-source/ "$TRIPFOLIO_COMMIT" | gzip -n > "$TRIPFOLIO_STAGING/TripDocket-source.tar.gz"
ditto -c -k --sequesterRsrc --keepParent \
  build/DerivedData/Build/Products/Release-iphonesimulator/Tripfolio.app \
  "$TRIPFOLIO_STAGING/TripDocket-Simulator.zip"
TRIPFOLIO_XCODE_VERSION=$(xcodebuild -version)
TRIPFOLIO_SWIFT_VERSION=$(swift --version)
cat > "$TRIPFOLIO_STAGING/BUILD.txt" <<EOF
TripDocket development preview
Source commit: $TRIPFOLIO_COMMIT
Built: $(date -u +%Y-%m-%dT%H:%M:%SZ)
$TRIPFOLIO_XCODE_VERSION
$TRIPFOLIO_SWIFT_VERSION
Unsigned iOS Simulator app; not installable on an iPhone.
No live App Store purchase or release is implied.
Core tests and Release build were run by scripts/verify.sh.
UI / StoreKit runtime results are tracked separately in docs/release-evidence.md.
The source archive can be rebuilt with the same toolchain; binaries are not claimed bit-for-bit reproducible.
EOF
(cd "$TRIPFOLIO_STAGING" && shasum -a 256 TripDocket-source.tar.gz TripDocket-Simulator.zip BUILD.txt > SHA256SUMS)
require_reviewed_source
if [[ -e "$TRIPFOLIO_OUTPUT" ]]; then
  echo 'A package appeared at the destination during the build; refusing to replace it.' >&2
  exit 1
fi
mv "$TRIPFOLIO_STAGING" "$TRIPFOLIO_OUTPUT"
TRIPFOLIO_STAGING=''
echo "Preview package: $TRIPFOLIO_OUTPUT"
