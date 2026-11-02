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

The explicit `Release qualification` workflow captures the selected suite once.
Both modes use Xcode 26.2 (17C52), with SDK and Simulator runtime 26.2.
The default Arm profile uses the budgets below; the Intel batch contingency
is described separately.
Batch qualification checks the complete path from selecting existing files to
reviewing, saving and reopening their originals. Before that functional suite,
a separate invocation runs the hosted purchase prerequisite, then the batch-only
`testBatchPrepareFilesProviderDirectly` case. This case opens the existing Debug
Simulator synthetic-PDF exporter, verifies the exact local Files root and an
absent probe folder, and terminates before Save. Its recorded preparation UUID
must be canonical and distinct from the later native-seed UUID. The independent
Recovery and phone preparation paths still exercise backup export through the
share sheet. Batch qualification covers a preinitialized provider, not cold
first use. The first result bundle must contain both exact
passed cases, with the hosted pass before preparation starts, and match the
captured device and runtime before the driver starts.
Default Arm preparation has a 780-second build/test cap and an unchanged
180-second case allowance. The Intel envelope is described below.
A [retained qualification run](https://github.com/4alvit/travel-documents-ios/actions/runs/41415016371)
spent about 531–532 seconds in build and runner startup before its case began; its former 600-second command cap stopped
active preparation at about 68.5 seconds. That failed run did not reach native
seeding or the main batch flow. The command cap now accommodates that observed
startup and the unchanged case allowance within the same 2,400-second work
budget. Admission still reserves the full 1,200-second driver and 120 seconds
for postchecks; result inspection shares the remaining budget and may still
fail. The 180-second cleanup budget and all UI waits remain unchanged. This is
not a claim that startup delay or native Files behavior has been repaired.
The qualification driver next verifies the exact local provider root on that
exclusively owned Simulator. It requires a canonical directory, stable provider
identity, and no entries of any kind. It retains the two synthetic PDF source
copies outside the provider; the host does not create a fixture folder or write
fixture bytes into the provider.

After preparation, the qualifier resolves the actual paths of all three test
targets and records their compiled-product identities. One serial
`test-without-building` invocation reuses those products for native seeding and
the real batch-import case, with no hosted-test phase between preparation and
seeding. Missing products or changed bytes/modes stop qualification; no fallback
build or product copy is substituted. Installed app and data-container identities are recorded. Sharing
one invocation removes the separate seed-to-import launch boundary; it does not
by itself prove that Xcode skipped installation or that a Files error is fixed.

The seed case, `testNativeSaveSeedsBothSyntheticOriginals`, exports each PDF from
an opt-in Debug Simulator view through a document picker in copy mode. The test
selects the exact local root and presses Save once for each file. Before reporting
success, the app requires one matching destination URL and reads that exact URL
through the existing security-scoped, coordinated reader, capped at 1024 bytes.
The complete bytes must match the synthetic source. A missing callback, failed
read or mismatch fails preparation; the destination is never removed by the app.
Its existing 180-second case allowance and destination assertions remain. After all seed
actions succeed, the UI test process records its run identity and terminates the
synthetic app. At the start of the import case, before resetting or launching the
app, the test consumes that same-process record and waits for one host response.
A missing or restarted producer process cannot authorize import.

The host requires the earlier hosted/preparation pass evidence, then the actual
seed XCTest pass followed by the import-case start and its fresh checkpoint
request in the second invocation. It then revalidates the owned destination and
requires exactly the two expected regular files, comparing every byte with the retained sources. Only a successful,
recorded verification permits one response on that run's nonce-specific channel.
The response proves fixture verification, not successful purchase or import.
Missing, duplicated, stale or out-of-order requests fail. The wait has a
60-second transport limit within the import case's unchanged 600 seconds.

The first bundle, `files-prepare.xcresult`, contains the hosted prerequisite and
Files preparation. The second, `Tests.xcresult`, contains native seeding and the
real import case. Each must report exactly two passes. There is no separate
seed result bundle or seed command exit code. Final independent review requires
all four native cases, explicit empty warning/failure arrays, the real log order,
checkpoint evidence, full original-byte comparisons, and visual checks. Prior
one-plus-three or three-bundle captures cannot be relabeled as this control.

After preparation, the target-metadata query uses `generic/platform=iOS Simulator`
with the same Debug configuration, derived-data directory, scheme action and
source-selection settings. `-showBuildSettings` does not build or execute tests;
its existing 30-second work cap and eight-second stop reserve remain. The
returned target paths must still resolve inside the owned build and pass the
same platform, bundle-identity, nesting and product-byte checks. Preparation,
installed-container observations and native tests retain the exact owned
Simulator destination. A generic query avoids selecting that live destination;
it does not guarantee that Xcode performs no Simulator-service work.

The first invocation shares its profile-specific preparation command cap.
The hosted prerequisite retains its 300-second default allowance and Files
preparation retains 180 seconds. Startup, seed, host checkpoint, import and
result inspection share the same 1,200-second driver clock, started before
destination preflight. No phase renews it. Seed retains 180 seconds and import
retains 600 seconds. A 300-second envelope runs from the second native command's
start to the seed pass, including UI-runner startup.
For the default Arm profile, the 2,400-second work budget, 180-second cleanup
budget and UI-action waits remain.
These limits are not a completion guarantee. Failed preparation or fixture
verification prevents the import actions from starting.

The explicitly selected Intel batch profile reserves 3,000 seconds of work
and 600 seconds for the initial boot-readiness check (`simctl bootstatus`). The
separate `simctl boot` command retains its 60-second cap. The work deadline stays
anchored to the original qualification start. Its capture step allows 54 minutes
and its job
65 minutes. A [boot-only observation](https://github.com/4alvit/travel-documents-ios/actions/runs/41456445847)
measured 279.406 seconds for boot, followed by 88.267 seconds for ready inventory.
The original work budget left insufficient room for the then-current
2,100-second reservation for preparation, driver and postchecks. This profile
accommodates that measured startup; it does not establish that the Files failure
is repaired.

Intel batch preparation now has a fixed 1,200-second command envelope, including
build, install, runner startup and both selected cases. In the retained
[`9d8766d` capture](https://github.com/4alvit/travel-documents-ios/actions/runs/41470558345),
the 780-second envelope expired while the Files case was still active at about
148.5 seconds; the hosted prerequisite had passed in 8.419 seconds. These timings
imply approximately 624 seconds outside the two case bodies, not an isolated
compiler benchmark. The new envelope allocates 720 seconds for that overhead
and result finalization, plus the existing 300-second hosted and 180-second
Files allowances. It neither renews a clock nor retries a phase.

Admission reserves the same selected 1,200-second preparation cap, the full
1,200-second driver and 120 seconds for postchecks within the original
3,000-second work deadline. Insufficient remaining time fails before preparation
starts, including after a slow boot. The receipt records the selected phase cap;
the actual command uses that same cap. This allocation is not a guarantee that
preparation, subsequent import or result inspection will finish.

Arm and all biometric captures retain their existing budgets. Native case and
driver limits, the 180-second cleanup budget, runtime matching, source verification
and complete device-inventory checks remain unchanged. The 54-minute capture
and 65-minute job envelopes are unchanged.

The Intel batch build compiles only the complete test source files needed by
this selected suite, plus `LocalizationTests.swift`, whose name also occurs in
the package tests. A validated `EXCLUDED_SOURCE_FILE_NAMES` argument excludes
the other sixteen test files in preparation, build-settings inspection and the
subsequent invocation. It does not exclude production App or TravelCore code,
StoreKit resources, or any of the four selected test methods. The exact source
selection is recorded in the capture receipt. Unexpected test files or an
excluded filename colliding with another tracked source fail before the build.
The tracked project and test plan are unchanged; ordinary full CI, Arm batch
and biometric qualification keep their original compilation scope. This
reduces unnecessary compilation, but does not establish a measured speedup or
a passing native result.

The root fixture mode belongs only to the hosted qualifier's exclusively owned
Simulator. Its driver never removes the provider root or individual root
entries: cleanup is deferred to deletion of that whole owned Simulator. The
complete root and source bytes are checked again after the test writer stops,
even after a native failure. Capture remains incomplete until owned cleanup and
the unchanged inventory of other devices are proved. The standalone
`test-batch-simulator.py` command retains its default two-case invocation and
creation/cleanup of a unique fixture folder.

The real import case still makes its own local Xcode purchase, selects the files,
requires each review and reconfirmation after edits, saves, relaunches and opens
the complete originals. Its 600-second allowance was introduced after a retained
run exhausted the former 300 seconds before completing those checks. The hosted
prerequisite clears its local transactions before the UI makes its own purchase.
Successful purchase setup alone does not qualify the Files workflow.

Earlier Xcode 16.4 captures retain their original producer identity and review
limits. They do not qualify a new 26.2 Release binary. A passing run with either
toolchain does not establish the cause of a failure with the other.

Biometric mode checks privacy across authentication and app transitions.
Each simulated Face ID request has a unique acknowledgement bound to its run, request, sequence
and event. The test waits for the single host event command to complete before
starting its existing 15-second UI postcondition. The 60-second transport limit
covers the two existing 30-second command caps. The editor round-trip case uses
the existing 180-second maximum: one captured run spent 46.6 seconds on its two
event/acknowledgement pairs and reached final UI capture at 127.3 seconds. Other
case allowances and the suite limit remain unchanged. Missing controls are
checked for existence before hittability to avoid implicit lookup retries.
Acknowledgement means command completion, not successful authentication.

For both qualification modes, Xcode 26.2 rejects an explicit schema version
0.4.0, and its default summary-schema documentation contains invalid JSON.
The preflight recognizes the exact captured documentation by SHA-256, retaining
the original bytes. It does not repair result JSON or treat a documentation
hash as proof that tests passed. An unknown document or toolchain fails before
native work. Each mode requires one available pinned runtime compatible
with the host architecture. The capture records the SDK and runtime separately,
including the observed runtime build, and checks those fields against the native
test result. Both profiles require an SDK match. Ordinary CI and the default
`--validate-schemas` command use the same documentation check. The independent
Xcode 27.1 review below must still establish actual results and warnings.

Core/purchase tests, phone guidance and the Release preview use Xcode 26.2
(17C52). Both test jobs require a unique available runtime matching that Xcode's
Simulator SDK, with a compatible iPhone and host architecture. A supplied device
UUID must satisfy the same checks; there is no fallback to another runtime.
Release provenance records the actual producer; test bundles record their actual
devices and runtimes. Each test artifact contains its result bundle plus
`ci-toolchain/simulator-selection.*/`; consumers must select the `.xcresult`
bundle explicitly instead of assuming every archive entry belongs to it.
The phone guidance lane explicitly prepares the selected Simulator's local Files provider
before running the unchanged UI cases. Preparation binds to the recorded
selection and rechecks the complete inventory. It runs the existing recovery
preparation case once: the synthetic app opens Export, Save to Files and the
local provider, checks that its unique sentinel folder is absent, then stops.
The same `xcodebuild` invocation starts the selected device within its existing
phase budget. A separate `simctl bootstatus` call is not a prerequisite. The
exact native case and result validation must pass before post-preparation
identity checks. Xcode may leave a device it started in `Shutdown` after testing.
If the same selected device and data-root inode are unchanged, preparation then
runs one `simctl bootstatus <UUID> -b` command with a 180-second cap and verifies
a fresh complete inventory, Booted state and unchanged root before container
lookup. An already-Booted device receives no additional boot command. These
steps share the existing 900-second work budget; failures are not retried.
The receipt records the observed post-test state, whether a warm boot was needed,
and the resulting state. Final checks still reject changes to any other device.
The preparation creates no backup or Files folder and does not erase or delete
the selected device. Its separate result bundle records this case; the following
guidance cohort retains its own result bundle and reuses the same build products.
The preparation receipt distinguishes owned host-command cleanup from the
Simulator services that remain running for the tests.
When the native Settings list reports a non-hittable wrapper, its scroll helper
first filters geometrically aligned containers by a live, visible descendant,
then requires exactly one active container. Covered containers cannot create
false ambiguity; two active containers are still rejected. The target control
must still be fully inside the safe viewport and hittable before use; the drag
count and per-action deadlines are unchanged. Each scroll observation reuses
its app, navigation, obstruction and selected-container frames. Count rows use one
fresh snapshot for identity, label and value while retaining the global uniqueness
and live hit checks; snapshots are never reused after a drag or a new observation.
Phone preparation has a 900-second work budget and a 780-second build/test command
cap; the shared preparation case has a 180-second allowance. A captured cold phone
run reached local Files checks at 132 seconds, after its former 120-second limit.
That failed run remains failed; no completed preparation is inferred from its
late observations. A later phone run spent about 518 seconds in build and runner
startup before its case began, including a 280-second runner launch call. Its
former 600-second command cap expired during the case. The phone command budget
now accommodates that measured startup and the unchanged case allowance within
the same total work budget. Result inspection, provider checks and final inventory
share the remaining budget and still fail if it expires; their completion is not
guaranteed. The startup delay and the failed run's unconfirmed process-group
cleanup are not claimed fixed. Recovery retains its 600-second command cap; batch release qualification
preparation has the profile-specific cap described above. The guidance test
deadlines and 30-second cleanup budget are unchanged. The phone integration step
has a 40-minute cap within a 60-minute job. A [retained run](https://github.com/4alvit/travel-documents-ios/actions/runs/41440392190)
completed its integration step in 37 minutes 56 seconds but exceeded the former
35-minute job limit. Raw test artifacts upload before optional failure extraction
so that extraction cannot consume the time reserved for preserving the original
results.
The original navigation-readiness, single Cancel action, and dismissal checks
remain unchanged. Provider preparation alone is not UI
acceptance; this lane covers a preinitialized provider, not cold first use.
The recovery compatibility job retains its separately pinned profile.
Privacy/support text reading uses the same one-point inset viewport for scroll
acceptance and coverage checks. Short text must fit completely in that reading
viewport; tall text still requires overlapping coverage. Action-control tolerance,
real hittability, screenshots, hierarchy captures and case deadlines are unchanged.

The iPad driver allows up to 480 seconds for its single fresh build, within the
unchanged 2,100-second work budget and separate 180-second cleanup reserve.
An [observed Russian run](https://github.com/4alvit/travel-documents-ios/actions/runs/41417736277/job/125185590697)
was still compiling when its former 360-second build cap expired. This allocation does not guarantee completion or admission: that
run had about 1,539 seconds left, only 52.1 seconds beyond the mandatory
1,487-second preparation, test and post-validation allowance. Native case
limits, full-budget admission and failure handling remain unchanged; no build
or test is retried or reused from another run.

The opt-in batch and biometric drivers read the complete Simulator inventory
and validate the selected UUID's uniqueness, iOS runtime, availability and
booted state themselves. This avoids the redundant CLI `available` filter;
device validation remains strict. Their initial inventory read has a 120-second
budget, matching the qualifier's existing inventory allowance. A bounded
[post-boot diagnostic](https://github.com/4alvit/travel-documents-ios/actions/runs/41371185617)
completed this single read in 77.3 seconds, exceeding the previous driver cap
of 30 seconds. The hosted adapter grants that allowance only to the exact
`simctl list devices --json` command; other driver commands retain their
30-second cap. Shorter caller deadlines, the eight-second stop reserve, and
the overall work and cleanup deadlines remain in force. No action is retried.
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

Manual release qualification defaults to `macos-15`. Its explicit
`macos-15-intel` choice is a capacity contingency, never an automatic retry or
fallback. The runner label must match its actual architecture. Both choices
retain Xcode 26.2/17C52 and SDK 26.2; Intel additionally requires the installed
26.2 runtime to report build 23C54 before device creation. The official
[Intel image inventory](https://github.com/actions/runner-images/blob/main/images/macos/macos-15-Readme.md)
lists the toolchain and runtime version, but does not establish a particular
job's runtime build or successful execution. Acceptance still requires its own
live preflight, exact source/product evidence, native results, cleanup and
independent 27.1 review. Existing Arm results do not certify Intel execution;
the ordinary CI runner and Release producer are unchanged.

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
and output hashes. The reader must report the exact expected passed cases,
zero failures/skips/expected failures, the captured device, and explicit empty
`runtimeWarnings` and `testFailures` arrays. Missing fields, a reader failure or
any warning block acceptance. Biometric mode requires its six exact cases.
Inspect the retained screenshots and the mode-specific byte/cleanup evidence
too. Batch mode requires two distinct result-bundle reviews, in execution order:

1. `files-prepare.xcresult`: `testVerifiedPurchaseAndRestoreFromLocalHistory`,
   then `testBatchPrepareFilesProviderDirectly`, exactly two passed cases.
2. `Tests.xcresult`: `testNativeSaveSeedsBothSyntheticOriginals`, then
   `testRealFilesBatchRequiresEveryReviewAndPreservesOriginals`, exactly two
   passed cases.

Each bundle must match the same captured source and device, retain an unchanged
original manifest, and have no skips, failures or runtime warnings. Review the
verified empty provider root and unchanged identity, both native Save operations
and their complete-byte proof, and the main test's purchase, import, review,
save and relaunch evidence. The public batch receipt retains the three named
functional methods: hosted purchase/restore, native seeding, and real batch
import. They span the two bundles; the second bundle must not be reported as a
three-case result. Files preparation is a separately required prerequisite.
Only this complete review may produce the separate operator `passed` receipt
described below; never rewrite the raw capture report into a pass. These checks
cover the retained XCTest record, not every application or system-console message.
An empty XCTest warning array does not negate a FileProvider error in retained
application output. Investigate relevant console errors alongside the observed
functional result; do not discard them or convert a failed import into a pass.

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

The batch receipt requires exactly these three passed methods across the two
reviewed result bundles:

- `testVerifiedPurchaseAndRestoreFromLocalHistory`
- `testNativeSaveSeedsBothSyntheticOriginals`
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
