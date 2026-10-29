# Full-backup recovery UI regression

Status: the three-phase preparation policy is a source candidate. It has not
yet passed a native run or independent pixel review. The current hosted driver
is `python3 -B scripts/recovery_hosted.py --run` in the Recovery CI job; it binds
the actual checkout, runner profile and attempt before any simulator action.
This document does not authorize a local invocation or claim release acceptance.

## What this closes when actually executed

Run three explicitly ordered selected cases in `BatchImportUITests`:

1. `testRecoveryCreateOwnedFilesDestination`: existing synthetic demo, Free
   counts and disclosure, real Save to Files, native creation of the exact
   `TripDocket-Recovery-<run-UUID>` folder. After exact committed folder/title
   proof and capture, the case terminates the fixture without tapping Save,
   verifies the app stopped and must pass before the host proceeds. This
   preparation boundary does not claim Save-picker Cancel coverage.
2. Host discovers exactly one matching folder under the owned simulator local
   provider. Named paths and open descriptors must keep their identities, and
   a complete stable directory iteration must prove the folder empty. There
   is no observation race with the still-running preparation test.
3. `testRecoveryExportFullBackupThroughFiles`: existing synthetic demo plus one
   unassigned person, observed Free gate, full-backup disclosure, actual share
   sheet, Save to Files, exact fresh owned folder.
4. Host compares the resulting backup to the active source catalog and original
   bytes, saves immutable evidence and pins its manifest hash **before reset**.
5. `testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal`: reset to an empty
   Free library, actual Files import, replacement disclosure, application
   validation, successful restore, relaunch without fixtures, original readiness
   check and Quick Look preview.
6. Host compares all restored catalog metadata and original bytes with the
   pre-reset snapshot; independent review checks the actual PDF pixels and
   ordered UI evidence.

The full fixture is one `Coast weekend` trip, `Alex Example`, an unattached
`Recovery Sentinel`, and `Weekend reservation` (`sample-reservation.pdf`,
Booking, assigned to Alex, no expiry). The unattached person distinguishes a
complete backup from a selected-trip export. UUIDs, dates and PDF bytes are
generated at runtime; capture them, never hardcode a reference hash.

No new application hooks are added. Existing Debug `--demo` seeds the empty
preparation library; export reuses it without resetting. `--ui-testing-reset`
is used only in restore. All phases share the newly created simulator.
`--ui-testing-unlocked` skips device authentication. All export/restore paths
and their validation remain real. No recovery case invokes `localStoreSession`, `buyProduct`, transaction clearing
or Restore purchases. Startup may query StoreKit; this is not a network-isolation
test. A clean dedicated simulator and visible second-trip Free gates establish
the entitlement scope. App-data reset alone does not clear purchase history.

## Admission before any native action

The hosted entrypoint validates the admitted CI event/profile, exact source
manifest and host process capability. A separate local run still requires an
exact approved bounded controller and resource admission. This document is
not permission to run ad-hoc commands or reuse an existing simulator.

Before admission, bind the candidate commit/tree and input hashes, Xcode path,
runtime identifier, device type, unique result root and unique folder name
`TripDocket-Recovery-<run-UUID>`. Record the actual native compilation outcome. No successful build is assumed.
Use one newly created simulator with no prior app or StoreKit history; never
adopt an existing UUID, booted device, folder, result bundle or baseline. No
purchase tests may run in this attempt. Do not share the simulator with CI.

The driver records original command deadlines, output and disk caps, ownership,
reaping and cleanup. The prepare case uses a 120-second XCTest maximum;
export/restore retain 300 seconds each. Every xcodebuild invocation retains a
600-second ceiling, clipped to the original remaining work deadline with an
8-second owned stop reserve. Total time remains 1,500 seconds: 1,380 seconds of
work and 120 seconds reserved for cleanup. These three command ceilings cannot
all be consumed. No phase resets the clock; phase_budget records remaining
work before/after the command and evidence handling.

All three invocations reuse the same DerivedData directory with compiler index
generation disabled; no clean or duplicate cold build is requested. Incremental
reuse and total fit require actual runtime evidence. The original limits remain
16 MiB per stream, 64 MiB aggregate logs, 2 GiB per xcresult, 8 GiB complete owned
output (including DerivedData and evidence copies), 16 GiB admission free space
and 8 GiB continuing free space. A failed operation ends the attempt after
bounded evidence/cleanup. There are no automatic retries or slot expansion.

## Ordered inputs and hosted command construction

Arguments below are arrays, not shell fragments. Substitute only recorded,
validated identifiers/absolute paths. Do not execute while this packet remains
source-only.

1. Create the admitted new simulator and bind its UUID and baseline inventory.
   Before first boot starts populating AppGroup, a bounded read-only scan proves
   the exact run folder name absent and pins any existing ancestors. Then boot
   the device and wait for boot readiness. Those pins remain mandatory after
   preparation; newly created ancestors do not replace an existing pin. The
   prepare case opens the real Save UI, creates that exact folder
   through native New Folder, verifies the committed name and navigation title,
   captures that state, then terminates the fixture without tapping Save. After
   its exact single-case PASS and stopped-app check, a bounded no-follow host scan finds
   the unique local-provider folder and proves it empty, with group/provider/
   folder descriptor and named-path identities. Missing/ambiguous/nonempty or
   changed directories fail. The host does not call DocumentsApp group lookup,
   launch Files, create Apple storage, or prepopulate a backup.

2. Export environment additions (preserve only reviewed base environment):

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
    "-resultBundlePath", "<RESULT_ROOT>/export.xcresult",
    "-only-testing:TripfolioUITests/BatchImportUITests/testRecoveryExportFullBackupThroughFiles",
    "COMPILER_INDEX_STORE_ENABLE=NO", "CODE_SIGNING_ALLOWED=NO", "test"]
   ```

   Preparation uses the same constructed argv and DerivedData, with phase
   `prepare`, result `prepare.xcresult`, selected case
   `testRecoveryCreateOwnedFilesDestination`, and both XCTest allowances 120.
   Export uses `export.xcresult`; restore uses `restore.xcresult`. The driver
   constructs these arrays from its fixed CASES map, not user-supplied shell text.

3. After xcodebuild exits, preserve the original xcresult and record a complete
   file manifest before invoking any result reader. Read only a separately
   copied bundle whose bytes match that manifest; keep the original unchanged.
   Include the original, working copy and manifests within the result-root cap.
   Require xcodebuild exit zero and exact Export case PASS, zero failures and
   zero skips, with no extra executed tests. Parse summary and tests from that
   verified copy and preserve raw bounded outputs. A skipped opt-in is not
   success. Confirm the app is stopped after the test's defer and record
   app-bundle identity. Apply this evidence-preservation rule to all three phases. Preparation
   does not take an application-library snapshot.

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
   before restore. Record original UI-exported backup SHA, folder identity and
   source `active.json` generation. The verifier reads the pointer's generation,
   not the newest directory. Never reset if this snapshot is incomplete.

5. Restore: same device, candidate app identity, owned Files folder and pinned
   baseline. Change only environment phase to `restore`, result path to
   `restore.xcresult`, and `-only-testing` to
   `TripfolioUITests/BatchImportUITests/testRecoveryRestoreIntoEmptyFreeLibraryAndOpenOriginal`.
   Same exact zero-failure/zero-skip/single-case acceptance. The test resets via
   the existing Debug flag, proves zero counts and performs the real import.
   Do not install a host-made catalog or invoke repository APIs from this test.

6. Re-resolve app data after restore (do not assume the container path survived
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

7. Extract ordered PNG and AX attachments from all three actual xcresults for
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

New Folder/name selection/commit and fixture shutdown, Save-to-Files, exact folder navigation,
Settings counts and single-file selection require current runtime confirmation. Before Save,
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
Source is a Debug candidate, not acceptance of any Release binary.

Offline self-check only:
`python3 -B scripts/test-verify-recovery-evidence.py`.
These synthetic temporary-byte tests do not run XCTest or validate PDF pixels.
