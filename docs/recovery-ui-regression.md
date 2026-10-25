# Full-backup recovery UI regression

Status: source candidate only. No Swift compilation, native execution, new CI,
StoreKit replay or pixel acceptance is claimed. The accepted `674cbb6` checkout
and its Release artifacts remain unchanged. This patch must first be integrated
into a separate candidate checkout and assigned its own source identity.

## What this closes when actually executed

Run two explicitly ordered, selected cases in `BatchImportUITests`, with a
host snapshot between them:

1. `testRecoveryExportFullBackupThroughFiles`: existing synthetic demo plus one
   unassigned person, observed Free gate, full-backup disclosure, actual share
   sheet, Save to Files, exact fresh owned folder.
2. Host compares the resulting backup to the active source catalog and original
   bytes, saves immutable evidence and pins its manifest hash **before reset**.
3. `testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal`: reset to an empty
   Free library, actual Files import, replacement disclosure, application
   validation, successful restore, relaunch without fixtures, original readiness
   check and Quick Look preview.
4. Host compares all restored catalog metadata and original bytes with the
   pre-reset snapshot; independent review checks the actual PDF pixels and
   ordered UI evidence.

The full fixture is one `Coast weekend` trip, `Alex Example`, an unattached
`Recovery Sentinel`, and `Weekend reservation` (`sample-reservation.pdf`,
Booking, assigned to Alex, no expiry). The unattached person distinguishes a
complete backup from a selected-trip export. UUIDs, dates and PDF bytes are
generated at runtime; capture them, never hardcode a reference hash.

No new application hooks are added. Existing Debug `--demo` seeds only phase 1;
`--ui-testing-reset` is used only in phase 2; phase 1 requires the newly created simulator; `--ui-testing-unlocked` skips device
authentication. All export/restore paths and their validation remain real.
Neither new case invokes `localStoreSession`, `buyProduct`, transaction clearing
or Restore purchases. Startup may query StoreKit; this is not a network-isolation
test. A clean dedicated simulator and visible second-trip Free gates establish
the entitlement scope. App-data reset alone does not clear purchase history.

## Admission before any native action

The current packet authorizes source preparation and offline verifier tests
only. A future coordinator must allocate a resource slot and approve an exact
bounded executor. This document is not that executor or a permission to run
ad-hoc terminal commands. The existing batch driver is a navigation/ownership
reference, not an approved recovery runner.

Before admission, bind the candidate commit/tree and input hashes, Xcode path,
runtime identifier, device type, unique result root and unique folder name
`TripDocket-Recovery-<run-UUID>`. Verify the final patch and native compilation.
Use one newly created simulator with no prior app or StoreKit history; never
adopt an existing UUID, booted device, folder, result bundle or baseline. No
purchase tests may run in this attempt. Do not share the simulator with CI.

The future wrapper needs recorded command deadlines, output and disk caps,
process ownership/reaping, a cleanup reserve, and fresh host checks approved
for this host. Per UI phase set both XCTest default and maximum to 300 seconds;
the plan's default 30/maximum 60 would otherwise truncate this case. Provisional
outer budgets are 600 seconds per xcodebuild invocation and 1,500 seconds total,
including 120 seconds reserved for cleanup. Proposed hard caps are 16 MiB per
command log, 2 GiB per xcresult, 8 GiB for the complete owned result root
(including DerivedData and copied evidence), and at least 16 GiB of free space
at admission, aborting work below 8 GiB free. The future executor must enforce
these with bounded checks and reserve cleanup time; the source packet does not
implement that executor. These caps do not measure the whole simulator device.
The coordinator must approve all limits against actual host conditions before
execution. No retries or automatic slot expansion. A failure ends the attempt
after evidence/cleanup.

## Ordered inputs and command templates for the future wrapper

Arguments below are arrays, not shell fragments. Substitute only recorded,
validated identifiers/absolute paths. Do not execute while this packet remains
source-only.

1. Create/boot the approved new simulator, record its UUID and pre-attempt
   inventory. Resolve the local Files group using:
   `['xcrun', 'simctl', 'get_app_container', UUID, 'com.apple.DocumentsApp', 'groups']`.
   Parse exactly one `group.com.apple.FileProvider.LocalStorage` entry. Require
   its resolved path under this UUID, then the `File Provider Storage` directory.
   Create the unique folder there with exclusive mkdir and record parent/folder
   device+inode. It starts empty; do not put a host-generated backup in it.
   If the provider is unavailable, stop; any bootstrap must be separately
   specified in the wrapper, not improvised by launching arbitrary apps.

2. Phase 1 environment additions (preserve only reviewed base environment):

   ```json
   {
     "TEST_RUNNER_TRIPDOCKET_RECOVERY_UI": "1",
     "TEST_RUNNER_TRIPDOCKET_RECOVERY_PHASE": "export",
     "TEST_RUNNER_TRIPDOCKET_RECOVERY_FOLDER": "TripDocket-Recovery-<run-UUID>",
     "TEST_RUNNER_NSUnbufferedIO": "YES",
     "NSUnbufferedIO": "YES"
   }
   ```

   Candidate checkout is cwd. The exact selected-case argv template is:

   ```json
   ["xcodebuild", "-project", "Tripfolio.xcodeproj", "-scheme", "Tripfolio",
    "-configuration", "Debug", "-destination", "platform=iOS Simulator,id=<UUID>",
    "-destination-timeout", "30", "-parallel-testing-enabled", "NO",
    "-maximum-concurrent-test-simulator-destinations", "1", "-collect-test-diagnostics", "never",
    "-default-test-execution-time-allowance", "300", "-maximum-test-execution-time-allowance", "300",
    "-derivedDataPath", "<RESULT_ROOT>/DerivedData",
    "-resultBundlePath", "<RESULT_ROOT>/Export.xcresult",
    "-only-testing:TripfolioUITests/BatchImportUITests/testRecoveryExportFullBackupThroughFiles",
    "CODE_SIGNING_ALLOWED=NO", "test"]
   ```

3. After xcodebuild exits, preserve the original xcresult and record a complete
   file manifest before invoking any result reader. Read only a separately
   copied bundle whose bytes match that manifest; keep the original unchanged.
   Include the original, working copy and manifests within the result-root cap.
   Require xcodebuild exit zero and exact Export case PASS, zero failures and
   zero skips, with no extra executed tests. Parse summary and tests from that
   verified copy and preserve raw bounded outputs. A skipped opt-in is not
   success. Confirm the app is stopped after the test's defer and record
   app-bundle identity. Apply this same evidence-preservation rule to phase 2.

4. Recheck Files folder ownership and require exactly `Documents.tripbackup`, a
   regular file. Resolve app data via
   `['xcrun','simctl','get_app_container',UUID,'com.4alvit.tripfolio','data']`.
   Validate the exact UUID path. Its library root is
   `Library/Application Support/TripfolioUITesting`.
   Run the pinned Python executable with:

   ```json
   ["<PYTHON>", "-B", "scripts/verify-recovery-evidence.py", "snapshot",
    "--library-root", "<APP_DATA>/Library/Application Support/TripfolioUITesting",
    "--files-folder", "<EXACT_OWNED_FILES_FOLDER>",
    "--output", "<RESULT_ROOT>/BeforeReset"]
   ```

   Require exit zero and comparison PASS. Independently hash the four evidence
   files plus manifest; pin the returned manifest SHA in the wrapper receipt
   before phase 2. Record original UI-exported backup SHA, folder identity and
   source `active.json` generation. The verifier reads the pointer's generation,
   not the newest directory. Never reset if this snapshot is incomplete.

5. Phase 2: same device, candidate app identity, owned Files folder and pinned
   baseline. Change only environment phase to `restore`, result path to
   `Restore.xcresult`, and `-only-testing` to
   `TripfolioUITests/BatchImportUITests/testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal`.
   Same exact zero-failure/zero-skip/single-case acceptance. The test resets via
   the existing Debug flag, proves zero counts and performs the real import.
   Do not install a host-made catalog or invoke repository APIs from this test.

6. Re-resolve app data after phase 2 (do not assume the container path survived
   installation), recheck candidate identity and folder device+inode, then:

   ```json
   ["<PYTHON>", "-B", "scripts/verify-recovery-evidence.py", "compare",
    "--library-root", "<CURRENT_APP_DATA>/Library/Application Support/TripfolioUITesting",
    "--files-folder", "<EXACT_OWNED_FILES_FOLDER>",
    "--baseline", "<RESULT_ROOT>/BeforeReset",
    "--expected-manifest-sha256", "<PINNED_BEFORE_RESET_MANIFEST_SHA256>"]
   ```

   Require exit zero and all equality fields true. Preserve this result and
   copy the after pointer/catalog/original into a new `AfterRestore` evidence
   directory, verify those copies against their input hashes, and bind them in
   the wrapper receipt before deleting the simulator. This copy step belongs
   to the future wrapper; the comparison utility is read-only in compare mode.

7. Extract ordered PNG and AX attachments from both actual xcresults for
   independent inspection: Free gates; complete export warning and Export
   action; selected owned destination; empty restore library; exact backup
   selection; zero-library replacement warning; successful restore; both
   people after relaunch; the readable synthetic PDF after original validation.
   Capture existence or a `QLPreviewControllerView` alone proves no rendering.

8. Stop owned processes, shut down/delete only the created UUID, verify absent
   process groups and restored device inventory, and persist a final receipt
   even on failure. Inspect all copied evidence before claiming acceptance.
   Never mutate the original Release ZIP/source tar or prior receipts.

## Source and evidence limits

Save-to-Files, exact current-folder navigation title, Settings count-row and
single-file selection selectors still need runtime confirmation. Before Save,
file selection or an optional Open, recovery requires the exact owned folder
name as a visible static text in the Files navigation bar. Save is scoped to
that same bar. Tapping the folder row alone does not authorize either action. The shared Files folder navigation comes from the
existing batch test. Unknown surfaces fail with screenshot and AX evidence;
there are no guessed taps, broad alert dismissals or automatic retries. If an
offscreen Save action or a different exporter hierarchy is encountered, review
that captured surface and prepare a separate bounded source revision.

The offline utility compares the entire catalog object (including identities,
relationships, dates and optional fields), every selected fixture original,
and the unchanged exported backup. It detects mismatches; it is not a PDF
validator, UI-provenance authenticator or a hostile-writer sandbox. It expects
resolved owned paths and a stopped app, rejects symlink files, bounds reads,
and never writes input directories. A standalone PASS cannot prove that UI
produced the backup or that the fresh Free state was observed; that requires
the ordered native evidence and host receipt above.

Coverage stays narrow: one valid PDF and two people, one unassigned. This does
not add UI evidence for JPEG/PNG, multiple originals, confirmed non-nil expiry,
corrupt backups, libraries above Free limits, reminders, real device lock,
physical offline mode, purchases, migration, TestFlight or App Store readiness.
Source is a Debug candidate, not the previously accepted Release binary.

Offline self-check only:
`python3 -B scripts/test-verify-recovery-evidence.py`.
These synthetic temporary-byte tests do not run XCTest or validate PDF pixels.
