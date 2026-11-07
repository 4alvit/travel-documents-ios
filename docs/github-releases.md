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
must be canonical and distinct from the later native-seed UUID. Dedicated
Recovery preparation and shared guidance Files preparation, including the Phone
bootstrap, also open the Debug exporter without Save. Dedicated Recovery then
requests creation of its owned folder through Files; the host must verify and
adopt the empty folder after preparation stops the app. The later Recovery
export case still checks the production disclosure, share-sheet Save to Files
and destination Save, followed by restore selection and replacement
confirmation. See [the Recovery preparation contract](recovery-hosted.md) for
these separate paths. Batch qualification covers a preinitialized provider,
not cold first use. The first result bundle must contain both exact
passed cases, with the hosted pass before preparation starts, and match the
captured device and runtime before the driver starts.
After relaunch, each saved synthetic original must render its own four exact
fixture markers inside the visible Quick Look preview. A single 20-second
post-tap deadline covers both presentation and pixel observation, replacing the
former 15-second container wait plus five-second sleep. The shared observer
rejects blank, partial, duplicate, wrong-document and late OCR results; it keeps
the exact screenshot that satisfied the checks. Later screenshot/AX captures
are separate observations. Recovery retains its existing marker set and timing.
There is no preview reopening or action retry. This closes the test-acceptance
gap in [issue #44](https://github.com/4alvit/travel-documents-ios/issues/44);
it does not establish the cause of the historical blank Quick Look rendering.

The direct preparation case uses a 45-second initial readiness polling
deadline for the supported Files browser or Recents screen. An in-flight
synchronous XCTest query can return after that deadline, but a late positive
result is rejected before routing continues; the existing outer case and
command bounds still apply. In a retained
[Intel capture](https://github.com/4alvit/travel-documents-ios/actions/runs/41634849458),
native navigation lifecycle events arrived about 18 seconds after polling
started, beyond the former 15-second window; the retained screen was still
blank and did not prove a usable root. A later
[Arm capture, attempt 2](https://github.com/4alvit/travel-documents-ios/actions/runs/42332477749/attempts/2)
recorded 224 fast unsuccessful navigation probes during the 30-second window.
The failure screenshot was blank; native service, browser and navigation
lifecycle events appeared 33–35 seconds after the tap, during teardown.
Those events do not prove a usable root or repair the first attempt's separate
native export cancellation. This scoped startup allowance preserves
the readiness predicates, one exporter tap, subsequent 15-second waits, and
the 180-second case allowance. It neither retries presentation nor establishes
that the native service or full import scenario has been repaired.
The normal folder-based native seed case also allows 30 seconds only for its
initial Files navigation polling. In the retained
[complete ARM flow](https://github.com/4alvit/travel-documents-ios/actions/runs/41598218571),
the first positive navigation query began 14.54 seconds after polling started,
close to the former 15-second allowance. A
[later main capture](https://github.com/4alvit/travel-documents-ios/actions/runs/41738390477)
remained blank at that boundary. This scoped margin preserves the unique
navigation predicate, subsequent 15-second waits, one exporter tap and the
180-second case allowance; it does not establish that the blank presentation
will recover or that its cause has been fixed. As above, an in-flight XCTest
query can finish beyond the polling allowance; outer case and command bounds
still apply.
The separate native-folder creation case also uses the 30-second initial
browser/Recents allowance. In [PR18 Batch attempt 1](https://github.com/4alvit/travel-documents-ios/actions/runs/41742187902),
its single exporter tap led to a blank sheet throughout the 15-second initial
polling window; no folder creation or seed test followed. The same run's
successful direct preparation began polling at 12.94 seconds, reached the
picker-existence query at 25.06 seconds, and proceeded past the initial
predicate by 25.69 seconds. These are query-progression bounds, not exact
rendering times. The extra margin applies only to this initial folder-case
entry: the helper default and subsequent waits remain 15 seconds, all unique
browser/root checks and the single exporter tap remain, and the 180-second
case and enclosing command bounds are unchanged. It does not prove that the
failed blank sheet would recover, and does not change Recovery presentation.
Default Arm preparation has a 780-second build/test cap and an unchanged
180-second case allowance. The Intel envelope is described below.
A [retained qualification run](https://github.com/4alvit/travel-documents-ios/actions/runs/41415016371)
spent about 531–532 seconds in build and runner startup before its case began; its former 600-second command cap stopped
active preparation at about 68.5 seconds. That failed run did not reach native
seeding or the main batch flow. The command cap now accommodates that observed
startup and the unchanged case allowance within the same 2,400-second work
budget. Preliminary admission reserves the base 1,200-second driver and 120
seconds for postchecks. After actual preparation, batch requires room for
the 1,440-second folder-inclusive driver and those same postchecks; it can
still fail closed before allocating that driver. Result inspection shares
the remaining budget and may still
fail. The 180-second cleanup budget and other UI waits remain unchanged. This is
not a claim that startup delay or native Files behavior has been repaired.
The qualification driver next verifies the exact local provider root on that
exclusively owned Simulator and the absence of its UUID-named target folder.
`testNativeCreateOwnedFilesFolder` opens the synthetic exporter without Save,
uses native New Folder, verifies the exact name and editor geometry, requests
end-editing once, and terminates the app. Its capture explicitly says that
host empty-folder verification is pending; it does not assert that the editor
closed or that folder navigation succeeded. A separate canonical source UUID
prevents reuse of the later seed source directory. If Files instead opens the
new empty `untitled folder`, the helper permits one strictly verified return to
its local parent, then requires
the same parent editor or Rename checks. Batch uses one 60-second resolution
window for the initial state, a fresh Rename-candidate confirmation, and this
single return, including a child transition discovered during confirmation.
The clock is never reset; the 180-second case and 240-second native-folder
work budget, plus its eight-second stop reserve, remain. No path authorizes Save. See the
[Recovery preparation contract](recovery-hosted.md) for this separate state and
its retained failure evidence. Only after the case passes
may the host adopt the exact empty, nonsymlink leaf with stable parent and
leaf device/inode identities. The two synthetic source PDFs remain outside
the provider; the host neither creates this leaf nor writes provider files.

After folder adoption, the qualifier resolves the actual paths of all three test
targets and records their compiled-product identities. One serial
`test-without-building` invocation reuses those products for native seeding and
the real batch-import case, with no hosted-test phase between preparation and
seeding. Missing products or changed bytes/modes stop qualification; no fallback
build or product copy is substituted. Installed app and data-container identities are recorded. Sharing
one invocation removes the separate seed-to-import launch boundary; it does not
by itself prove that Xcode skipped installation or that a Files error is fixed.

The seed case, `testNativeSaveSeedsBothSyntheticOriginals`, exports both PDFs from
an opt-in Debug Simulator view through one document picker in copy mode. The test
selects the exact native-created folder and presses Save once. The app requires a nonempty
callback containing at most two unique expected filenames and unique local URLs,
none referring to a source URL. It reads every exact returned URL through the
existing security-scoped, coordinated reader, capped at 1024 bytes per file.
Every read must match its complete synthetic source. A missing callback, invalid
URL, failed read or mismatch fails the seed case; the app never removes a destination
or constructs an unreturned URL. The callback may contain only one of the exported
files: this alone does not prove that both files were saved.

The `nativeSeed.callbackVerified` marker and `BATCH_NATIVE_SEED_CALLBACK` record
report the source names and the successfully read names/count in sorted order.
A per-file `nativeSeed.saved` marker appears only for a returned file that was
actually read successfully. These are app callback proofs, distinct from the
host's two-file proof below. The existing 180-second case allowance and destination
assertions remain. Single-file direct preparation still opens its own exporter
without saving. Optional same-process copy-reopen diagnostics are not enabled by
the normal workflow and require both app readbacks if explicitly requested.
After seed actions succeed, the UI test process records its run identity and
terminates the synthetic app. At the start of the import case, before resetting
or launching the app, the test consumes that same-process record and waits for
one host response. A missing or restarted producer process cannot authorize import.

The host requires the earlier hosted/preparation pass evidence, then the actual
seed XCTest pass followed by the import-case start and its fresh checkpoint
request in the combined seed/import invocation. It then revalidates the owned destination and
requires exactly the two expected regular files, comparing every byte with the retained sources. Only a successful,
recorded verification permits one response on that run's nonce-specific channel.
The response proves fixture verification, not successful purchase or import.
Missing, duplicated, stale or out-of-order requests fail. The wait has a
60-second transport limit within the import case's unchanged 600 seconds.

The three original bundles contain exactly 2+1+2 passes: `files-prepare.xcresult`
holds the hosted prerequisite and direct Files preparation; `native-folder.xcresult`
holds native folder setup; `Tests.xcresult` holds native seeding and real import.
There is no separate seed bundle or seed command exit code. Independent review
requires all five cases, explicit empty warning/failure arrays, actual log order,
host adoption and checkpoint evidence, complete original-byte comparisons,
and visual checks. Historical or diagnostic captures cannot substitute for
a normal qualification of the final integrated source.

After preparation, the target-metadata query uses `generic/platform=iOS Simulator`
with the same Debug configuration, derived-data directory, scheme action and
source-selection settings. `-showBuildSettings` does not build or execute tests;
that settings query has a 40-second work cap and eight-second stop reserve.
Installed-container queries retain 30 seconds plus the same eight-second
stop reserve. Shared-build admission reserves one 48-second settings RPC
and four 38-second container RPCs in combined mode (six in the legacy path),
inside the original driver and global clocks; it does not renew either. The
returned target paths must still resolve inside the owned build and pass the
same platform, bundle-identity, nesting and product-byte checks. Preparation,
installed-container observations and native tests retain the exact owned
Simulator destination. A generic query avoids selecting that live destination;
it does not guarantee that Xcode performs no Simulator-service work.

The first invocation shares its profile-specific preparation command cap.
The hosted prerequisite retains its 300-second default allowance and Files
preparation retains 180 seconds. Startup, seed, host checkpoint, import and
result inspection share the same 1,440-second driver clock, started before
destination preflight. The folder invocation uses at most 240 seconds and its
case retains 180 seconds. No phase renews the clock. Seed retains 180 seconds
and import retains 600 seconds. A 300-second envelope runs from the combined command's
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
68 minutes. A [boot-only observation](https://github.com/4alvit/travel-documents-ios/actions/runs/41456445847)
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
base 1,200-second driver and 120 seconds for postchecks within the original
3,000-second work deadline. After actual preparation, the same additional
240-second folder allocation must fit before the driver starts. Insufficient remaining time fails before preparation
starts, including after a slow boot. The receipt records the selected phase cap;
the actual command uses that same cap. This allocation is not a guarantee that
preparation, subsequent import or result inspection will finish.

All biometric captures retain their existing native budgets and path. Batch changes
only its initial driver allocation as described above. Native case limits,
the 180-second cleanup budget, runtime matching, source verification
and complete device-inventory checks remain unchanged. The 54-minute capture
envelope is unchanged. The fourteen qualification guard commands share a
five-minute step; the outer job allows 58 minutes, or 68 for Intel batch.
This preserves the four-minute evidence upload allowance and the existing
one-minute margin for checkout and action overhead. It does not guarantee
completion of every command at its maximum allowance.

Both ARM and Intel batch builds compile only the complete test source files needed by
this selected suite, plus `LocalizationTests.swift`, whose name also occurs in
the package tests. A validated `EXCLUDED_SOURCE_FILE_NAMES` argument excludes
the other sixteen test files in preparation, build-settings inspection and the
subsequent invocation. It does not exclude production App or TravelCore code,
StoreKit resources, or any of the five selected test methods. The exact source
selection is recorded in the capture receipt. Unexpected test files or an
excluded filename colliding with another tracked source fail before the build.
The tracked project and test plan are unchanged; ordinary full CI and
biometric qualification keep their original compilation scope. ARM retains
its default preparation, work and cleanup budgets. This
reduces unnecessary compilation, but does not establish a measured speedup or
a passing native result.

The native-folder fixture belongs only to the qualifier's exclusively owned
Simulator. After the last writer stops, the host rechecks both complete PDF
bytes and the parent/leaf identities, including after a native failure. It
removes only its adopted UUID leaf, proves that leaf absent and the provider
unchanged, then deletes the owned Simulator. An unadopted leaf is left for
that device teardown. No provider-root deletion is permitted. Capture remains
incomplete until owned cleanup and the unchanged inventory of other devices
are proved. The standalone
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
(17C52). Core/purchase and phone guidance request standard `macos-15` ARM
runners. Recovery explicitly selects `hosted-arm-v1` on `macos-15`, and both
iPad guidance locales use `macos-15` with their existing ARM profile. Swift
CodeQL retains `macos-15-intel` (x86_64). Earlier ARM runner acquisition failures
motivated the Intel capacity contingency; it was not an iPad architecture
coverage requirement. Repeated Intel pre-build closure stalls in
[#42](https://github.com/4alvit/travel-documents-ios/issues/42), together with
available ARM producers, motivate returning iPad guidance to ARM. This runner
choice does not establish the cause of those stalls or certify a future pass.
The Core/Phone/iPad ARM jobs use their existing ordinary test and preparation
limits, without Intel timing tokens. Core/Phone enclosing workflow limits remain
unchanged. The iPad wrapper now follows its existing ARM work/cleanup profile as
specified below. All test cases and assertions remain unchanged.
Recovery requires the exact `ARM64`/`arm64` hosted context
for its explicit ARM profile, retaining the Intel profile and CLI default. Each cohort requires fresh evidence for the current source;
no previous architecture result is inherited. Neither runner class guarantees
available hosted capacity.
Both iPhone test jobs require a unique available runtime matching that Xcode's
Simulator SDK, with a compatible iPhone and host architecture. A supplied device
UUID must satisfy the same checks; there is no fallback to another runtime.
Release provenance records the actual producer; test bundles record their actual
devices and runtimes. Each test artifact contains its result bundle plus
`ci-toolchain/simulator-selection.*/`; consumers must select the `.xcresult`
bundle explicitly instead of assuming every archive entry belongs to it.
The phone guidance lane explicitly prepares the selected Simulator's local Files provider
before running the unchanged UI cases. Preparation binds to the recorded
selection and rechecks the complete inventory. It runs the existing recovery
preparation case once: the Debug app opens its synthetic-ticket source in the
native exporter without Save, reaches the local provider, checks that its
unique sentinel folder is absent, then stops. This provider-only bootstrap is
separate from the subsequent ordinary guidance cases.
The same `xcodebuild` invocation starts the selected device within its existing
phase budget. A separate `simctl bootstatus` call is not a prerequisite. The
exact native case and result validation must pass before post-preparation
identity checks. Xcode may leave a device it started in `Shutdown` after testing.
If the same selected device and data-root inode are unchanged, preparation then
runs one `simctl bootstatus <UUID> -b` command with a 300-second Intel cap
(180 seconds on Arm) and verifies
a fresh complete inventory, Booted state and unchanged root before container
lookup. An already-Booted device receives no additional boot command. These
steps share the original 1,440-second Intel work deadline (1,080 seconds on Arm).
The immutable profile is selected from matching recorded and actual host
architectures before output creation. Failures are not retried.
The receipt records the observed post-test state, whether a warm boot was needed,
and the resulting state. Final checks still reject changes to any other device.
The preparation creates no backup or Files folder and does not erase or delete
the selected device. Its separate result bundle records this case; the following
guidance cohort retains its own result bundle and reuses the same build products.
The preparation receipt distinguishes owned host-command cleanup from the
Simulator services that remain running for the tests. If the failed warm-boot
child's first stop cannot probe its group because of `EPERM`, final cleanup may
observe that same owned child until the original cleanup deadline. It sends no
further signal or command. Only a fresh reap result and positive group absence
clear ownership; the original failed command, stop record and overall failure
remain unchanged. Terminal-looking stdout alone is never closure evidence.
When the native Settings list reports a non-hittable wrapper, its scroll helper
first filters geometrically aligned containers by a live, visible descendant,
then requires exactly one active container. Covered containers cannot create
false ambiguity; two active containers are still rejected. The target control
must still be fully inside the safe viewport and hittable before use; the drag
count and per-action deadlines are unchanged. Each scroll observation reuses
its app, navigation, obstruction and selected-container frames. Count rows use one
fresh snapshot for identity, label and value while retaining the global uniqueness
and live hit checks; snapshots are never reused after a drag or a new observation.
Phone preparation has a 1,080-second work budget and a 960-second build/test command
cap on Arm; Intel uses 1,440 seconds of work and a 1,080-second command cap.
The preparation case retains a 180-second allowance on Arm. Intel uses the
existing validated hosted Recovery profile with a 300-second prepare allowance,
paired with both xcodebuild execution limits. Only that preparation command gets
the profile token; the provider-only route and its no-Save checks are unchanged.
The command and overall work budgets above still bound startup, execution and
finalization. A captured cold phone
run reached local Files checks at 132 seconds, after its former 120-second limit.
That failed run remains failed; no completed preparation is inferred from its
late observations. A later phone run spent about 518 seconds in build and runner
startup before its case began, including a 280-second runner launch call. Its
former 600-second command cap expired during the case. In
[run 41577208390](https://github.com/4alvit/travel-documents-ios/actions/runs/41577208390),
about 711 seconds elapsed before the preparation case started; the 780-second
command cap then expired after about 61 seconds of case activity. A later Intel
run exhausted the 960-second command before its native case could use 180 seconds:
less than 130 seconds separate the recorded case start and the later shell failure.
Its receipt does not record a UTC origin for the monotonic command clock, so the
exact build/startup split is unknown. The Intel command now allows 1,080 seconds;
Arm retains 960. Each combined command allowance includes its eight-second stop reserve;
it is not a separately enforced startup deadline. The case still has the same
180-second allowance. Result inspection, provider checks and final inventory
share the remaining budget and still fail if it expires; their completion is not
guaranteed. The earlier 600-second failure's unconfirmed process-group cleanup
remains historical evidence. The later 780-second run confirmed its owned group
absent and its leader reaped; neither result proves the startup delay fixed.
Standalone Recovery retains its 780-second prepare command, 600-second later
commands and 180/300-second native allowances. The hosted adapter selects
immutable `hosted-intel-v1` or explicit `hosted-arm-v1`, with identical numeric
bounds and architecture-specific admission, before deriving deadlines from
its original clock: 4,980 seconds of work plus 360 for cleanup, prepare command/case
caps of 1,200/300 seconds and export/restore caps of 900/600 seconds. Commands
retain their eight-second stop reserve. Hosted cleanup alone allows 90 seconds
per owned shutdown/delete action and 60 per recovery/final inventory query;
unresolved ownership still prevents later commands and cleanup acceptance.
Standalone cleanup retains its original 120/30/20-second limits.
The native change requires the exact
matching Debug Simulator architecture and exact profile token; unrelated
callers keep their defaults. The legacy Intel JSON is unchanged; the closed
`--profile` option cannot load arbitrary files. A retained
Intel run spent 713 seconds before the prepare case began and was stopped during
app launch. This profile budgets all three phases, result inspection and cleanup;
it provides bounded startup and native performance margin without guaranteeing
completion. Only the validated hosted adapter gives its initial owned boot wait
600 seconds, including eight seconds for stopping; standalone boot remains 120.
Two prior 300-second waits expired before native tests. The extra 300 seconds
are included in the work and outer envelopes, with unchanged scans and cleanup.
The Recovery workflow reserves 91 native minutes inside a 118-minute
job, including checkout, 15 minutes for all offline guards, evidence upload and
cancellation. Complete-file SDK typechecks allow 180 seconds each after two
hosted compiler commands exceeded their former 45-second limits; fixture
compilation and execution limits remain unchanged.
The dedicated Recovery restore case allows 30 seconds for its initial Files
navigation polling, matching the existing cold seed allowance. Its shared
helper still defaults to 15 seconds; subsequent browser, Recents, folder and
original-data checks, tap counts and outer case/phase limits are unchanged.
In [main run 42070800281](https://github.com/4alvit/travel-documents-ios/actions/runs/42070800281/job/127397854478),
the initial 15-second check failed and a later capture showed native Recents
navigation. That capture does not establish first availability or full browser
readiness. An in-flight synchronous XCTest query can outlast the polling
allowance; the change neither guarantees a hard 30-second return nor establishes
or remedies the cause of the late navigation observation.
Only the full Recovery export case may retry the native **Save to Files**
navigation action once. Its first action and any retry share a 30-second
polling allowance; retry eligibility begins after 15 seconds and requires
three fresh, stable observations matching the original action/header proof,
foreground state, and no Files navigation or picker. Missing, ambiguous,
changed or incomplete observations permanently disable the retry. Each
dispatch intent and any loss of eligibility records its proof or reason;
the native tap event establishes actual execution. Cancellation is checked
immediately before either tap. Preparation opens its synthetic export source
once and does not invoke this Save to Files action. Export confirmation and the
destination's actual Save are never repeated. No new retry starts after the
shared deadline;
a synchronous XCTest action already in flight may overrun it. Existing case,
host and cleanup limits still apply. This permits bounded recovery from the
observed non-transition; it does not establish whether the first native action
was ignored or delayed.
Batch release qualification preparation has the profile-specific cap described above.
Phone bootstrap selects an immutable 1,080-second Intel or 960-second Arm preparation
command cap, with a 300-second Intel or 180-second Arm native preparation
allowance, 30-second cleanup and ten-second receipt limits. Intel
gets 1,440 seconds of work; Arm retains 1,080. The Phone integration step has
108 minutes within a 128-minute job: 1,480 seconds for the complete Intel bootstrap,
4,380 seconds for the nine case ceilings, 600 seconds for selection, generation,
main build/session startup, skipped-case bookkeeping and result finalization,
and 20 seconds for rounding. The Arm bootstrap and ordinary case defaults remain
unchanged. These are planning allocations under one step timer, not independent guarantees.
For example, 1,080 seconds of preparation plus historical other work of 19.4 seconds,
a 78-second warm boot and 58 seconds of final checks total about 1,235 seconds.
If that warm boot instead consumes its full 300-second cap, the projection exceeds
the original 1,440-second deadline by about 17.4 seconds; later work must clip and
fail closed. The larger preparation cap does not reset or extend that deadline.
The surrounding 20 minutes retain checkout, toolchain, cancellation, raw evidence,
optional failure extraction/upload and finalization. Raw test artifacts upload
before optional extraction to preserve originals even if extraction fails.
The original navigation-readiness, single Cancel action, and dismissal checks
remain unchanged. Provider preparation alone is not UI
acceptance; this lane covers a preinitialized provider, not cold first use.
The recovery compatibility job retains its separately pinned profile.

Core's three purchase-failure scenarios retain a 240-second default for the
complete two-alert, postcondition, Free-quota and diagnostic-capture flow. Only
the strictly validated hosted Intel Core invocation selects 360 seconds, through
the final-command `hosted-intel-core-v1` marker. The same marker selects a
30-second guidance-host appearance wait instead of the five-second default;
the UIKit/SwiftUI/no-URL assertions remain required. Missing markers preserve
defaults, and invalid, conflicting or unsupported markers fail before test
side effects. System-sheet cancellation selects a 120-second presentation
observation and a 360-second case allowance only for that validated hosted
profile. Ordinary runs retain the 15-second observation and inherit their
runner's case allowance; Core's CLI still supplies a 180-second default and
480-second maximum. Purchase readiness retains its first 60 and subsequent
15-second checks, including the immediate failure-alert wait. The sheet observer
checks one fixed deadline before and after each existing app/Springboard query;
late matches are rejected. It adds no purchase, cancel or cleanup action.

The integration step is capped at 45 minutes within an 85-minute job. The prior
42/82-minute envelope already included all three 120-second failure-case
increments and the 25-second appearance increment, rounded up. Three more
minutes preserve that envelope plus the cancellation case's 180-second increase.
Separate verification, packaging, cancellation and evidence allowances are documented in
[the hosted budget](recovery-hosted.md). Raw test evidence uploads before
optional extraction. These limits do not guarantee a successful run or permit
incomplete results to satisfy release qualification.

Privacy/support text reading uses the same one-point inset viewport for scroll
acceptance and coverage checks. Short text must fit completely in that reading
viewport; tall text still requires overlapping coverage. Action-control tolerance,
real hittability, screenshots and hierarchy captures remain required.

A [retained Intel Phone run](https://github.com/4alvit/travel-documents-ios/actions/runs/41884508287/job/126785199272)
exceeded four native deadlines before its former 45-minute integration limit.
The complete-warning test reached its final checks at179.23 seconds, then crossed
180 seconds during its final hierarchy capture; a separate termination failure
followed. The Free-card test reached its final hierarchy only at196.27 seconds.
The Russian warning crossed120 seconds before completing all text coverage and
continued diagnostically to150.57 seconds. English guidance crossed480 seconds
after its third cancellation and was interrupted during the fourth confirmation.
None of these post-timeout observations is a successful result.

The later [Phone run 41940543243](https://github.com/4alvit/travel-documents-ios/actions/runs/41940543243/job/126959918553)
completed preparation but exceeded four native allowances: complete-warning 240,
Free-card 240, English guidance 720 and Russian guidance 600 seconds. Free-card
body and AUT shutdown completed by 239.600 seconds, before diagnostic recording
finalization crossed its limit. English reached the fourth confirmation; Russian
reached only the first. Post-timeout continuation is not a passing result.

In [Phone run 41950012017](https://github.com/4alvit/travel-documents-ios/actions/runs/41950012017/job/126991476013),
eight cases passed and readiness/import cancellation crossed its inherited
180-second limit during Files Cancel. Later return actions and a separate failed
termination are not proof of a clean completion. That case now receives a bounded
360-second hosted allowance while preserving its 40-second Files readiness
admission, actions, captures and termination. This does not establish that the
termination failure is fixed.

Only the explicit hosted Intel Phone profile now selects 360 seconds for the
complete-warning, Free-card and readiness/import cancellation cases, 1,080 for
English guidance and 1,500 for Russian guidance. The Russian warning remains 240;
the three other cases retain their limits, including the Russian demo's 120 seconds.
The runner requires the exact repository, host/cohort
and selected iPhone before passing its token only to the final test invocation,
whose CLI maximum is 1,500 seconds. All three inherited Phone token aliases are
rejected at entry; the strict hosted Phone branch also rejects all three iPad
aliases before native tools. The test selector requires the exact token, a Debug
x86_64 Simulator build and iPhone idiom. Missing tokens preserve prior defaults,
including English 480, Russian 600 and the inherited Free-card and readiness
allowances; invalid
or incompatible tokens fail before app launch. Local and Core runs, ARM, and
dedicated iPad tests receive no Phone token. The ordinary test default stays 180,
and the dedicated iPad policies below remain unchanged.

The 600-second non-case allocation is engineering headroom over approximately
351 seconds outside the current failure-associated windows and approximately
464 seconds in an earlier accepted Arm run. It does not presume that the current
post-timeout continuation and restart time is ordinary overhead or will disappear.
The main `test` command shares DerivedData but may still build, install and start
its runner. No measured worst-case completion guarantee is implied.
All text, privacy, Cancel, final Trips, screenshot, hierarchy and termination
checks remain required. These finite margins do not establish the cause of slow
host observations or guarantee a pass; fresh complete native evidence is required.

The iPad driver allows up to 480 seconds on ARM or 1,200 seconds on Intel for
its single fresh build, within its selected work and separate cleanup budgets.
An [observed Russian run](https://github.com/4alvit/travel-documents-ios/actions/runs/41417736277/job/125185590697)
was still compiling when its former 360-second build cap expired. This allocation does not guarantee completion or admission: that
run had about 1,539 seconds left, only 52.1 seconds beyond the mandatory
1,487-second preparation, test and post-validation allowance. This build allowance
leaves the case limits above, full-budget admission and failure handling unchanged;
no build or test is retried or reused from another run.

The driver selects an immutable host profile before allocating its deadline:
ARM retains 2,100 seconds of work and 180 seconds for initial boot readiness;
Intel uses 4,500 and 600 seconds. Captured architecture must match that initial
profile before a device is created. Two Intel runs exhausted the former
180-second boot wait during data migration, while another completed in
118.663 seconds. The added headroom does not establish that delayed boots will
finish. It preserves exact runtime selection, full-case admission
(1,487 seconds on ARM, 1,517 on default Intel, 2,117 for hosted English and 2,417
for hosted Russian) and separate cleanup; it never resets a clock or retries a boot.
A later [Intel run](https://github.com/4alvit/travel-documents-ios/actions/runs/41884508287/job/126784418116)
completed boot in 312.7 seconds but exhausted the 480-second fresh-build limit
before any test. Its final log showed asset catalog compilation, not a compiler
error. The Intel build/work profile leaves 357 seconds beyond the default 4,143-second
command/case envelope for parsing and byte verification. The explicit hosted
locale policies below require earlier admission and can reject late preparation.
Intel cleanup includes final evidence in its 360-second reserve. These finite
margins do not guarantee completion; source, product, original-result and owned
cleanup checks remain mandatory. Phone and separate Batch/Biometric qualification
retain their own existing profiles.
An English iPad case later reached its480-second native limit during retained
second-cancellation evidence; its raw log continued through fourth Cancel near660
seconds but the native result remained failed, without final Trips evidence.
The retained explicit `--hosted-intel-timing` option selects the hosted Intel iPad
native allowances: English at standard type uses 1,200 seconds with a
1,500-second command; Russian at maximum type uses 1,500 seconds with a
1,800-second command. The producer
requires the exact GitHub-hosted macOS/X64 context. Separate
`hosted-intel-ipad-en-v1` and `hosted-intel-ipad-ru-v1` tokens require the matching
locale/type arguments in a Debug x86_64 iPad consumer. The token goes only to the
test runner; inherited/conflicting Phone/iPad tokens fail before launch, and the
app receives none. Current iPad CI uses ARM without this option or timing token;
standalone, ARM and Phone timing remain unchanged.

The Russian case in run `41928330972` reached its 480-second limit during the
first confirmation's public-support warning. A historical complete ARM run used
the same functional UI implementation and took 316.8 seconds. Scaling its
remaining work by the current first-cycle duration gives an illustrative 947.8
seconds, not a measured completion or prediction of a pass. This originally
motivated a 1,200-second Russian allowance without removing captures or checks.
The same run later reported an English pass in 895.949 seconds, just 4.051 below
its former 900-second limit. English receives a 1,200-second allowance. Its artifact
upload failed with `ENOTFOUND`; the log does not replace independent native,
visual or cleanup evidence, and the timing change does not repair upload failures.

The later Russian case in run `41940543243` reached its final accessibility
capture at 1,196.13 seconds, then exceeded the 1,200-second limit during teardown.
Its raw finish at 1,207.926 seconds and command exit 65 after 1,490.126 seconds
remain failed evidence. A prior pass with the same functional source took
981.964 seconds. The additional Russian margin addresses this observed variation
without predicting that a future run will pass.

Full admission is 2,117 seconds for hosted English and 2,417 for hosted Russian,
including 372 seconds of preparation, the selected 1,500/1,800-second command,
its separate 7-second stop reserve, and 238 seconds of post-validation.
The Intel profile retains its original 4,500/360 work/cleanup windows; its former
CI wrapper used an 83-minute step and 95-minute job.
Summed phase maxima reach 4,743 seconds for English and 5,043 for Russian, so late
preparation must fail admission; the larger command does not
extend the original deadline or borrow cleanup time. All 24 text checks, four
Cancels, zero Open actions, final Free/Trips navigation and original-evidence
checks remain mandatory.

After a Russian iPad run exceeded its 60-second AUT installation wait before
any native test, the Intel profile permits 90 seconds for AUT installation only.
This also applies to standalone Intel runs. ARM AUT installation, runner
installation and fresh container lookups retain 60 seconds. Intel preparation
reserves 372 seconds, including the extra 30; the full-case admission and global
margins above include it. A timed-out or nonzero install still stops the case;
installation and owned cleanup must be independently verified.

Current hosted iPad CI verifies both `RUNNER_ARCH=ARM64` and `uname -m=arm64`
before toolchain setup. Each locale retains the ARM profile's 35-minute work and
three-minute cleanup budgets. A 40-minute step includes two minutes of startup
and finalization headroom; the 52-minute job also reserves checkout (two),
toolchain setup (three), artifact upload (two), and cancellation (five).
Both exact native cases, SDK matching, all text/link checks, and verified owned
cleanup remain required. A historical ARM pass does not qualify the new source.

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
independent 27.1 review. Existing Arm results do not certify Intel execution.
The Core/Release producer, Recovery, ordinary phone guidance and both iPad
guidance locales use `macos-15` ARM runners; Swift CodeQL retains `macos-15-intel`.
Each new candidate requires fresh results for its selected runner profiles;
earlier results do not qualify the new candidate.

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
too. Batch mode requires three distinct result-bundle reviews, in execution order:

1. `files-prepare.xcresult`: `testVerifiedPurchaseAndRestoreFromLocalHistory`,
   then `testBatchPrepareFilesProviderDirectly`, exactly two passed cases.
2. `native-folder.xcresult`: `testNativeCreateOwnedFilesFolder`, exactly one passed case.
3. `Tests.xcresult`: `testNativeSaveSeedsBothSyntheticOriginals`, then
   `testRealFilesBatchRequiresEveryReviewAndPreservesOriginals`, exactly two
   passed cases.

Each bundle must match the same captured source and device, retain an unchanged
original manifest, and have no skips, failures or runtime warnings. Review the
verified empty native-created leaf and stable parent/leaf identities, the single two-source native
Save and actual callback readback names, the host's complete two-file byte proof,
and the main test's purchase, import, review,
save and relaunch evidence. The public batch receipt names all five passed
methods across these three bundles. Neither setup case substitutes for the
actual two-file import, review, save and relaunch assertions.
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
- The latest execution of all seven expected jobs successful for that same run
  and source: change scope, core/purchase, guidance, iPad EN, iPad RU, recovery,
  and the final CI gate. The final gate must belong to the current run attempt.
- The exact nonexpired `TripDocket-simulator-COMMIT-RUN-ATTEMPT` artifact, its
  GitHub digest, original checksums/provenance, and valid Simulator bundle.
  `ATTEMPT` is the successful core/purchase build job's actual producer attempt.
- Operator-reviewed execution receipts described below.
- A new absolute output directory outside the repository, with an existing
  parent. Existing paths and symbolic-link parent paths are rejected.

### Partial CI reruns and artifact identity

[GitHub reruns](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs)
retain the original source SHA/ref and preserve outputs of jobs that are not
rerun. A failed iPad job and its dependent gate can therefore be repeated without
rebuilding an already successful Release payload. This does not permit skipping
any required job or accepting a previously failed execution.

The preparer derives the latest execution of every required job from GitHub's
complete `filter=all` history. The separate `filter=latest` view must match either
all those executions or exactly the final attempt's executions; an omitted
current job or stale row is rejected. Untouched earlier jobs are therefore
verified from history even when absent from the final attempt's view. Missing,
duplicate, ambiguous, wrong-source or newer nonpassing jobs are rejected. It binds the artifact
name and the payload's `GITHUB_RUN_ATTEMPT` to the verified build job, rather than
relabeling an older build as the final qualification attempt. `acceptance.json`
records each job's actual attempt, the final CI attempt, and the artifact's
producer job ID/attempt. Both job views and the run identity are checked again
before writing the prepared output; an intervening rerun or changed job aborts
preparation. These are API evidence checks, not a transaction that prevents a
future rerun after preparation.

### Process cleanup and uncertain identity

The iPad, Recovery, Batch and Biometrics drivers retain their existing work,
shutdown and cleanup budgets. Once an owned process leader has been reaped, its
numeric PID/PGID no longer authorizes another TERM or KILL. The drivers either
confirm absence without a destructive signal or retain the uncertainty as a
failure within their existing deadlines. Successful cleanup requires both actual
leader reap and group absence.
This safety rule does not explain or repair the separate hosted RU iPad stall
that exhausted its first stop window before making any process observation.

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

The batch receipt requires exactly these five passed methods across the three
reviewed result bundles:

- `testVerifiedPurchaseAndRestoreFromLocalHistory`
- `testBatchPrepareFilesProviderDirectly`
- `testNativeCreateOwnedFilesFolder`
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
