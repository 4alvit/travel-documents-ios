# GitHub source and Simulator releases

This channel distributes reviewed source and an **unsigned iOS Simulator app**.
The app ZIP is not installable on an iPhone or iPad. A GitHub beta, release
candidate, or final release does not establish TestFlight availability, physical
hardware acceptance, App Review approval, or App Store publication. Keep those
checks in [the release checklist](release-checklist.md) and
[manual device QA](manual-device-test.md) explicitly pending until executed.

Each channel advances only when its evidence exists. A passing compiler, one
successful job, or an uploaded CI artifact is insufficient. In particular,
`package-ci-preview.sh` runs before UI tests; its original `provenance.json`
correctly records that runtime acceptance and the overall CI result are not yet
final. Never edit that original file to turn a candidate into an accepted build.

## Channel gates

- **Beta**, for example `v0.1.0-beta.1`: a reviewed candidate, complete successful
  main CI, and a recorded ordinary launch smoke of the exact downloaded Release
  ZIP, including installed-product identity and owned-device cleanup.
- **RC**, for example `v0.1.0-rc.1`: the same published beta payload, plus the real
  Files batch-import scenario and all six simulated authentication/privacy cases
  on the exact candidate source. These are Debug test products; do not describe
  them as executions of the Release binary. Inspect the retained functional,
  original-byte, screenshot and cleanup evidence before approving the receipts.
- **Final**, for example `v0.1.0`: the same published RC payload and a final review
  with no unresolved blocker for this source/Simulator scope. The same validated
  execution receipts may be reused; promotion does not require rebuilding or
  inventing another run.

Beta and RC remain GitHub prereleases. A final GitHub source/Simulator release
must retain its distribution scope prominently in its title and notes. It does
not complete the separate application RC/device/distribution gates. If code or
payload changes, create and qualify a new beta candidate; do not overwrite an
old tag or relabel an old binary as fixed.

## Prepare without publishing

The explicit `Release qualification` workflow pins Xcode 26.2 (17C52) and
captures the selected suite once. This Xcode rejects an explicit schema version
0.4.0, and its default summary-schema documentation contains invalid JSON.
The preflight recognizes the exact captured documentation by SHA-256, retaining
the original bytes. It does not repair result JSON or treat a documentation
hash as proof that tests passed. An unknown document or toolchain fails before
native work. Ordinary CI performs the same read-only preflight using an
explicit Xcode 26.2 environment. Core/purchase tests and the Release preview
pin Xcode 16.4 (16F6) and retain their previously validated runtime selection;
this compatibility lane does not claim that the runtime matches its SDK.
Its result bundle records the actual device/runtime, and the original Release
provenance records the producer.

The phone guidance job pins Xcode 26.2 (17C52) and requires a unique available
runtime matching that Xcode's Simulator SDK, with a compatible iPhone and host
architecture. A supplied device UUID must satisfy the same checks; there is no
fallback to another runtime. Its test artifact contains the result bundle plus
`ci-toolchain/simulator-selection.*/`; consumers must select the `.xcresult`
bundle explicitly instead of assuming every archive entry belongs to it.
The recovery compatibility job retains its separately pinned profile.

The opt-in batch and biometric drivers read the complete Simulator inventory
and validate the selected UUID's uniqueness, iOS runtime, availability and
booted state themselves. This avoids the redundant CLI `available` filter;
it does not relax device validation or the existing command deadlines.
If owned-device shutdown fails, qualification retains that error and checks
that all owned command processes have stopped before reading a fresh inventory.
It may delete only the same owned device now confirmed `Shutdown`; an already
absent device requires an unchanged baseline. A still-booted or changed device
is left untouched. Final inventory equality remains mandatory, and recovered
cleanup never turns the original failed qualification into a successful capture.

These records identify the build/test environments; they do not establish that
the previous compiler/runtime pairing caused a blank Files sheet or was
unsupported. Changing the core toolchain changes the Release producer and
requires fresh full CI, exact-source artifact checks and release qualification.
Earlier compiler results are not acceptance of the new binary. Local
`test-simulator.sh` behavior is unchanged unless `--require-sdk-match` is passed.

Successful hosted capture has status `captured_pending_review`, never `passed`.
It requires successful native execution, exact case counts and device identity,
unchanged source, matching built/installed products, the batch original-byte
proof where applicable, a complete result-bundle manifest and verified cleanup.
Reported runtime warnings or test failures block capture; an omitted warning field is
recorded as unavailable, not as an empty list. Workflow success and exit code
zero establish capture completion only. They do not authorize promotion.

Before accepting a Debug execution receipt, independently read a copy of that
same retained bundle with Xcode 27.1 (27A9275), whose result summary provides an
explicit `runtimeWarnings` array. Verify the Actions artifact digest, exact
run/attempt/source commit and tree, and the original bundle's complete file
manifest before making the copy. Preserve the original unchanged and verify
its manifest again after review. Record the reader version, commands, schema
and output hashes. The reader must report the exact expected one or six passed
cases, zero failures/skips/expected failures, the captured device, and explicit
empty `runtimeWarnings` and `testFailures` arrays. Missing fields, a reader
failure or any warning block acceptance. Inspect the retained screenshots and
the mode-specific byte/cleanup evidence too. Only this complete review may
produce the separate operator `passed` receipt described below; never rewrite
the raw capture report into a pass. These checks cover the retained XCTest
record, not every application or system-console message.

`scripts/prepare-release.py` uses Python's standard library, local Git objects,
and authenticated `gh` **GET** requests to github.com. Actions artifact downloads
use `Accept: application/vnd.github+json`; release asset downloads use
`Accept: application/octet-stream`. It does not build, execute
an app, modify remote state, switch branches, or publish a release. Existing
working-tree changes are untouched. Source archives read the selected commit's
Git blobs directly, so uncommitted files and export attributes cannot change
release contents. The tar prefix and all tar/gzip timestamps are fixed.

The script requires:

- The full candidate commit already present in the local repository.
- A completed successful `.github/workflows/ci.yml` main push or main manual
  dispatch run whose `head_sha` is exactly that commit. PR synthetic merge
  artifacts are deliberately not treated as the PR head.
- All six expected jobs successful in the same run attempt: core/purchase,
  guidance, iPad EN, iPad RU, recovery, and the final CI gate.
- The exact nonexpired `TripDocket-simulator-COMMIT-RUN-ATTEMPT` artifact, its
  GitHub digest, original checksums/provenance, and valid Simulator bundle.
- Operator-reviewed execution receipts described below.
- A new absolute output directory outside the repository, with an existing
  parent. Existing paths and symbolic-link parent paths are rejected.

Example, after replacing the placeholders with real identities:

```sh
mkdir -p "$HOME/.codex/artifacts/travel-documents-release/packages"
python3 -B scripts/prepare-release.py \
  --commit FULL_CANDIDATE_SHA \
  --run-id SUCCESSFUL_MAIN_CI_RUN \
  --stage beta --version 0.1.0 \
  --evidence "$HOME/.codex/artifacts/travel-documents-release/evidence.json" \
  --output "$HOME/.codex/artifacts/travel-documents-release/packages/beta.1"
```

For RC, pass `--stage rc --predecessor-tag v0.1.0-beta.1`. For final, pass
`--stage stable --predecessor-tag v0.1.0-rc.1`. Each needs a different new output
path. The predecessor must be a published prerelease at the same commit. Its
assets, checksums, acceptance record, and execution receipts are downloaded
and verified; missing, changed, unexpected or duplicate assets fail preparation.

The payload consists of `TripDocket-Simulator.zip`, `TripDocket-source.tar.gz`,
and the unchanged producer `provenance.json`. Those bytes must match across
promotions. `acceptance.json`, execution receipts, and `SHA256SUMS` describe the
particular stage and may differ. Do not compare GitHub's automatically generated
tag archives: their prefixes depend on the tag; use the explicit source asset.

ZIP validation rejects traversal, noncanonical names, duplicate entries,
file/directory collisions, symlinks, special files, encrypted files, excessive
counts/sizes, unexpected bundle roots, and a missing or nonexecutable app binary.
Checksums are integrity checks; the operator evidence below is not a signed
attestation or independent proof that someone performed a test.

## Operator evidence schema

Create a small, sanitized `evidence.json`. Paths are local input only and are not
copied into `acceptance.json`. All placeholders below are intentionally invalid;
replace them with independently checked values, not guessed results.

```json
{
  "schema_version": 1,
  "review": {"status": "approved", "blockers": []},
  "receipts": {
    "release-smoke": {"path": "smoke.json", "sha256": "REAL_FILE_SHA256"},
    "batch-import": {"path": "batch.json", "sha256": "REAL_FILE_SHA256"},
    "privacy-biometric": {"path": "privacy.json", "sha256": "REAL_FILE_SHA256"}
  }
}
```

Only `release-smoke` is mandatory for beta; all three are mandatory for RC/final.
Relative receipt paths resolve beside `evidence.json`. Files and their parents
must be regular/non-symlink paths. The script hashes every receipt before reading
its meaning. Calculate these hashes only after finalizing the real records.

The receipt schema is closed: exactly the fields shown below are accepted,
including within `source`, each `tests` item, and `tested_product`. For Debug
receipts omit `tested_product.archive_sha256`; that field is required only for
the Release smoke. Extra metadata or raw command fields are rejected.

Each receipt has this structure:

```json
{
  "schema_version": 1,
  "kind": "release-smoke",
  "source": {"commit": "FULL_CANDIDATE_SHA", "tree": "FULL_TREE_SHA"},
  "release_artifact_sha256": "REAL_RELEASE_ZIP_SHA256",
  "status": "passed",
  "cleanup_verified": true,
  "tests": [{"name": "ordinary-release-launch", "result": "passed"}],
  "runtime_warnings": [],
  "tested_product": {
    "configuration": "Release",
    "archive_sha256": "REAL_RELEASE_ZIP_SHA256",
    "files_manifest_sha256": "REAL_INSTALLED_FILE_MANIFEST_SHA256"
  },
  "limitations": ["Describe precisely what the observation did and did not prove."]
}
```

The smoke receipt identifies the exact Release ZIP and installed-product file
manifest. If the app only reached the system authentication screen, say so in
`limitations`; do not imply unlocked workflows or successful authentication.
Keep the underlying screenshots, command/result records and manifest accessible
for review. The preparer checks receipt identities and conclusions; it does not
interpret screenshots or replace the test drivers' independent verification.

For `batch-import` and `privacy-biometric`, use `configuration: "Debug"` and the
actual tested Debug product's file-manifest hash. The top-level
`release_artifact_sha256` associates source-equivalent test evidence with the
candidate being considered; it does **not** claim the Release ZIP was executed
by those tests. The source commit/tree must still match exactly. Preserve any
remaining runtime/toolchain limitations.

The batch receipt requires exactly this passed method:

- `testRealFilesBatchRequiresEveryReviewAndPreservesOriginals`

The biometric receipt requires all six distinct passed methods:

- `testFailedAndCancelledAuthenticationKeepDocumentsPrivate`
- `testOriginalPreviewIsPrivateAcrossBackgroundAndReturn`
- `testExportShareIsPrivateAcrossBackgroundAndReturn`
- `testEditDraftIsPrivateAcrossBackgroundAndReturn`
- `testUnsavedDocumentDraftSurvivesBackgroundAfterAuthentication`
- `testMaximumTypeUnlockIsReachablePortraitAndLandscapeWithoutAuthenticationSuccess`

Missing, duplicated, skipped, failed or unexpected methods, unsuccessful cleanup,
or runtime warnings fail the receipt gate. The last biometric case does not
require authentication success; retain its actual scope. Reformatting older
results into this schema must not hide a failure, change source identity, or
convert an unsupported observation into a pass. Execution receipt files are copied byte-for-byte into the prepared package and
will become public when it is published. Use normalized public records with
synthetic data only: no private paths, credentials, account identifiers, or raw
host logs. Keep the raw qualification evidence separately in its private task
artifact directory; hash/reference the appropriate sanitized records for release.
`limitations` accepts at most 20 nonempty, single-line strings of at most 2,000
characters. Conservative checks reject absolute local paths, command-dump field
markers, and common credential/token forms in this free text. These checks are
not a complete secret or personal-data detector; the operator must still review
every public receipt before preparing or publishing it.

## Publication and verification

The operator publishes only a successfully prepared package. Create the intended
annotated tag at the exact candidate, push it, and resolve its remote target
before using `gh release create --verify-tag --notes-file ...`. Use
`--prerelease --latest=false` for beta/RC. Select final/latest intentionally only
after final acceptance. Never use force tags or clobber previous assets.
[GitHub CLI documents these flags and the non-atomic asset-upload sequence](https://cli.github.com/manual/gh_release_create).

After publication, verify the resolved tag commit, release flags, complete asset
names and sizes, and GitHub asset digests where available. Download every public
asset into a new directory and check `SHA256SUMS`; inspect the published
acceptance record and compare its payload hashes with the prepared package.
If publication partially fails, inspect its actual state before another action;
do not report success or blindly create/overwrite it again.
[GitHub exposes release-asset digests and public downloads](https://docs.github.com/en/rest/releases/assets).

Run the offline regression checks with:

```sh
python3 -B scripts/test-prepare-release.py
```

These use only synthetic temporary Git repositories and mocked read responses;
they create no GitHub releases and run no native builds or Simulator tests.
