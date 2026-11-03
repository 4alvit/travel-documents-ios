# Hosted recovery regression

This job exercises the two opt-in recovery cases described in
`recovery-ui-regression.md`. It is separate from the ordinary Simulator preview
and existing StoreKit tests. A successful job is pending independent review of
the ordered UI attachments and actual rendered PDF pixels; it is not App Store
or payment acceptance.

## Profile and dependencies

The job uses the existing standard `macos-15` runner class. The reviewed profile
requires the actual runner context to report `github-hosted` and `ARM64`, and
Python to observe `arm64`. Image OS/version are recorded. The profile is a
requirement checked in the job, not evidence that the future host satisfies it.

Only the image's already selected Xcode is used. The job records and freezes its
canonical developer directory, version/build, Simulator SDK version/path and
tool hashes. It requires one available installed iOS runtime whose complete
numeric version equals the SDK version, with the observed architecture and
`iPhone-16-Pro` in its supported types. It does not round versions, select the
latest runtime, switch Xcodes, download components or try another device.

The checked-in `Tripfolio.xcodeproj` already references `BatchImportUITests.swift`.
This job does not run XcodeGen, Homebrew, pip, `verify.sh`, or another preparatory
build. Python 3.11+ and its standard library, Git and Xcode must already exist.
The other CI jobs retain their existing generation and dependency steps.

GitHub currently documents `macos-15` as standard ARM64 and standard macOS storage
as 14 GB. Consequently **16 GiB free is not guaranteed**. The job measures the
actual filesystem and refuses admission below 16 GiB; it never lowers the guard
or removes preinstalled/unrelated data. Official references:
[runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[image inventory](https://github.com/actions/runner-images/blob/main/images/macos/macos-15-arm64-Readme.md).
Image inventories change and do not substitute for the measurements in this job.

## Source identity

Checkout uses the event's default commit and depth two. For a pull request this
is the actual GitHub merge commit, distinct from the signed PR head. The runner
hashes the raw commit object and records its tree and ordered parents, requiring
those parents to equal the event's base/head. It separately records the raw PR
head and requires a signature record. Signature presence is **not** cryptographic
verification: the coordinator must verify the signed head before authorizing
the push. Push and merge-group events bind their own event SHA explicitly.

The clean checkout's tracked regular files are copied to a separate `Source`
directory. Every file is checked against its Git blob ID and executable bit;
a SHA-256 manifest binds the tested copy. Links, submodules, unexpected paths,
dirty source and a missing checked-in project fail. The tested snapshot and
checkout bytes are rechecked throughout the sequence; final HEAD and clean
status are checked too. No exported pre-commit candidate is described as a
Git commit. Generated results live only under the ignored, run-and-attempt-specific
`build/RecoveryHosted-<run-id>-<run-attempt>` directory.

## Explicit workflow attempts and process capability

`python3 -B scripts/recovery_hosted.py` is inert without `--run`. Runtime also
requires the expected CI job/repository/profile and a positive canonical decimal
`GITHUB_RUN_ATTEMPT` from the actual GitHub job. Standard explicitly requested
GitHub reruns are admitted; each job still executes one bounded recovery sequence
with one export case and one restore case. The owned-device identity, output
directory, persisted job context and published artifact name bind the actual
run and attempt. An existing directory for that same attempt is rejected, and
evidence from a different attempt is never reused. All CI artifact names include
the run ID and attempt so their evidence remains distinguishable.
There is no separate local grant file, imported local capability record or
automatic workflow rerun. These context checks are assertions about the job,
not cryptographic remote attestation. The reviewed workflow plus the approved
source/push are the execution authority.

One bounded preparation stage in the same job validates the actual process
boundary. It runs one normally exiting group and one deliberately timed-out
group with a descendant, using the same extracted `RealOps` and command/stop
methods. Child lineage, TERM then KILL, leader reap, whole-group absence and the
persisted failure receipt must all agree. The children also have finite self
expiration. This stage is limited to 60 seconds inside the existing total work
budget; no clock is reset afterwards. Injected Ops cannot produce actual
capability approval. Unknown ownership prevents further process creation.

`recovery_process.py` retains the reviewed process ownership, stop algorithm
and bounded observation records. Its command admission and finalization also
protect partial log setup and retain primary plus secondary failures.
`recovery_core.py` retains the reviewed recovery behavior,
with explicit source inputs and the validated host architecture. The wrapper
adds CI/source/profile preparation and excludes raw host process listings from
published artifacts. It does not replace the UI flows with direct service calls.

## Bounds and evidence

The whole executor has 1,500 seconds, with work ending by 1,380 and 120 seconds
reserved for owned cleanup, including a final 10-second receipt reserve. Each
Xcode phase has at most 600 seconds including process stop; the preparation
test has 180 seconds and export/restore each have 300.
Recovery discovery uses one fixed 300-second window after source/toolchain
preflight. It covers the first runtime query, profile parsing/selection, the
existing capability check, runtime recheck, baseline device inventory, one
create, created-device inventory and exact owned-root verification. Every
discovery command shares this deadline and retains its 8-second stop reserve;
the initial query therefore has at most 292 seconds of work, with later calls
receiving only the remaining time. A late response, parse, selection or owned
root check cannot admit boot or UI work. The window ends before the pre-boot
Files absence proof. Failure restores the original work limit before the
unchanged owned-device cleanup path; the discovery window never renews.

In run 41328552226 the initial runtime query returned no bytes before the old
112-second work deadline, so no device or UI phase was started. Its process was
stopped and reaped. Earlier identical queries completed in 7.7–63.4 seconds.
These observations justify a bounded startup policy, but do not prove the OS
cause or that 300 seconds will always suffice. There is no retry, warmup query,
runtime fallback or download. The capability stage keeps its own 60-second cap
inside the shared discovery window. The original 1,380-second work deadline is
unchanged: fully consuming discovery leaves at most 1,080 seconds minus
preflight for boot, UI phases and evidence. The per-phase maxima are ceilings,
not a guarantee that all can run for their maximum duration in one attempt;
later commands remain clipped to available work time and cleanup is reserved.

Files preparation first runs the real provider initialization UI case, which
reaches the exact local root, proves the run-UUID name absent and stops the
fixture. After its exact PASS and process cleanup, the host performs one exact
owned DocumentsApp group-container lookup with the existing 60-second cap
(52 seconds of work plus the 8-second stop reserve). It pins the existing local
provider, exclusively creates only an empty run-UUID leaf and independently
rechecks its original inode, all ancestors and complete emptiness before export.
It does not launch or terminate Files separately, create Apple roots, adopt an
existing name or prepare any backup bytes. Provider readiness uses only the
unused lookup work budget. No total, case or cleanup limit is increased.

Native Apple Files New Folder/name-commit remains unverified; failed diagnostic
attempts are not product acceptance. Folder creation is now deterministic test
setup, while the actual app Save-to-Files, import/restore, catalog/original-byte
comparisons and rendered PDF checks remain mandatory. This source policy is
still pending native end-to-end acceptance.

The export/restore AUT app and data container lookups and all other default
command caps remain 30 seconds. Global time, ownership and cancellation checks
can shorten or prevent any command. Before spawning, work commands force one existing
resource scan after intent/log setup and recheck cancellation and the remaining
stop reserve. Ordinary sampled scans and the cleanup bypass remain enabled. Command failures retain the primary cause plus separate log-close,
stdout-read, receipt, finalization and cap errors. Both log closes are attempted.
The capability validator rejects any such secondary failure even when the main
failure is the deliberately expected timeout.

A command receipt is a snapshot: a final write failure or overrun may be observed
after its contents were serialized. Inspect command records, top-level errors
and the actual failed CLI result together; an earlier receipt is not a success
signal. These source changes do not establish the cause or resolution of the
previous output-scan deadline or EPERM failures.

Recovery process cleanup also retains read-only confirmation after a successful
TERM wrapper if a subsequent group probe reports EPERM. This UNKNOWN state may
settle only within the original five-second TERM grace and original stop
deadline, with the exact owned Popen object. Confirmation requires both actual
leader reaping and ESRCH-derived group absence. Once TERM becomes unknown, no
KILL escalation is allowed; unknown at the deadline fails closed and keeps
ownership unresolved. EPERM before TERM, from signal delivery or from polling,
and other probe errors remain failures. The existing post-KILL confirmation and
capability acceptance rules are unchanged. This secondary cleanup correction
cannot erase the primary scan failure or prove cleanup for an older run.

The iPad guidance driver uses one fixed 300-second discovery phase after its
source/toolchain preflight. An earlier initial runtime query produced no output
within 120 seconds, before any device or test existed. The larger phase is a
bounded scheduling policy; the service's underlying delay and eventual success
are not established. There is no warmup, retry or alternate runtime fallback.

The shared phase covers runtime and device-type inventories, architecture and
pair selection, baseline devices, owned-device creation and identity validation.
Queries, JSON parsing, selection and ownership writes consume the same deadline;
none renews it. Each command leaves seven seconds inside the phase for existing
process-stop handling. The initial runtime request therefore waits at most 293
seconds; later command caps stay unchanged and are clipped to the shared
remaining time. A late parse or selection cannot admit another query or device
creation. If the deadline expires after creation, the existing cleanup still
owns that exact device.

Overall work deadlines remain fixed at driver start: 2,100 seconds for each
locale, including discovery. Both reserve 180 seconds for cleanup.
The phase is also clipped to that overall work deadline. Stop receipts summarize
the existing poll, group probe and signal calls in four bounded slots; an EPERM
is a failure, and only ESRCH establishes group absence. A primary timeout remains
visible alongside secondary stop or receipt-write errors. These are cooperative
checks between operations, not preemption of a blocked OS syscall. Releasing the
discovery phase before boot/build never renews the overall clock; longer discovery
still consumes time available for the complete case admission below.

Both iPad XCTest commands have a 900-second host wait. A fresh Russian run took
239 seconds from process spawn to XCTest start and was interrupted by its old
570-second wait while making UI progress at 331 seconds. A later English run
passed discovery in 10.2 seconds but took 299.814 seconds from test-process spawn
to XCTest start. Its old 600-second wait interrupted active UI work at 300.30
seconds. Neither interrupted run completed its result bundle or retained usable
screenshot payloads. These are startup-budget failures, not passing UI evidence.

The shared 900-second wait accommodates the observed roughly 300-second startup,
the unchanged 480-second XCTest ceiling and up to 120 seconds of result-finishing
headroom. This is a finite allowance, not a guarantee about future startup time
or a passing result. Exact test methods, UI assertions, content-size settings,
XCTest default 180/max 480 execution allowances and no-retry behavior are unchanged.

Each test must fit inside its locale's absolute work deadline, including its
seven-second process-stop reserve and mandatory post-test validation. Admission
is checked before preparation and again immediately before spawn. A terminal
test-process poll at or after its wait deadline fails, even with exit code 0.
Both locales use 40-minute workflow steps and 46-minute jobs.

Guidance tab transitions retain a five-second observation deadline and one tap.
A failed English run showed a fully rendered Settings screen: the selected-tab
snapshot was followed by a second remote navigation-bar query that exhausted
the deadline. The transition now requires the selected tab and exactly one
matching, nonempty, in-bounds navigation bar in the same immutable snapshot.
The existing bounded traversal and strict deadline checks remain; a late
snapshot, ambiguous title or missing navigation bar still fails. Fixture tests
execute the actual Swift helper and reject those states without another remote
query or another tap.
The step limits include each locale's work and 180-second cleanup budgets; the
job limits also leave time for toolchain setup and artifact upload. A command
return still requires the original result/provenance validation before a case
can pass; partial testcase progress is not acceptance.

One complete resource sample normally has a fixed five-second cooperative
allowance. During an unfinished `phase-prepare`, `phase-export` or `phase-restore` command,
including its admission and finalization, the explicit ceiling is thirty
seconds. An active owned `boot-ready` process waiting for
`simctl bootstatus <owned UUID> -b` retains its separate fifteen-second ceiling;
its admission and post-process samples keep five seconds. Every sample is clipped to the overall work limit, the actual command
owner's limit and its original work deadline, preserving the stop reserve. The
one fixed deadline covers both free-space reads and the full uncached output
traversal; its deadline is never renewed within a sample. Capability, other preparation and
evidence commands retain five seconds; a finished phase grants no later sample
an extended allowance. The next ordinary sample remains due one
second after a completed sample. The ordinary five-second allowance replaced an earlier two-second limit,
while byte, entry, depth, command, phase and cleanup limits remained fixed. A failed hosted scan exceeded the old allowance after 328 complete
samples; the last completed sample counted 5,132 entries and 307,924,992 allocated
bytes. The old receipt did not retain failed-scan progress, so it establishes
neither the cause of the delay nor that five seconds would have sufficed.

The disposable recovery Debug test builds set
`COMPILER_INDEX_STORE_ENABLE=NO` for both export and restore. Apple's
[build-setting reference](https://developer.apple.com/documentation/xcode/build-settings-reference)
defines this setting as controlling index data emitted while compiling. The
recovery run does not use that editor index. Disabling its generation removes
unneeded index-store writes and traversal work; it does not exclude an existing
index directory from accounting. All output paths still participate in the
same complete scan and phase-specific ceiling, with the same allocation, entry, depth, command,
cleanup and test-result checks. Compilation, linking, Debug settings and both
selected UI cases remain required. Other CI builds keep their existing settings.
This targets observed index-store traversal overhead; it does not establish
that every future filesystem or scheduler delay will fit the unchanged budget.


The earlier fifteen-second phase ceiling was based on a
retained hosted failure: one sample took 5.305 seconds in traversal and failed
at 350.670 elapsed, while the original export work deadline was 769.587. Its last
`scandir_open` began at 4.971 seconds and returned 0.334 seconds later; a different
`directory_open` span took 1.175 seconds. These spans include scheduling and do
not isolate syscall latency. Fifteen seconds gives a finite allowance for a
complete scan under such delays; it does not guarantee this or another run
would complete. Partial totals remain invalid and timeouts still fail closed.
No paths, including Build/Products or xcresults, are excluded. Cleanup already
bypasses sampled scans and is unchanged: the retained shutdown/delete/final
inventory timeouts are separate failures, and that run's device cleanup remains
unverified. All whole, phase, command, stop, cleanup and byte/entry/depth limits
remain unchanged; a timeout never causes an automatic sample retry or workflow rerun.

A retained boot-wait failure traversed 221 entries (about 8 MiB of logical
output, with no result bundles) before the final root-identity check crossed
the five-second ceiling at 5.195 seconds. The longest `scandir_next` span was
1.105 seconds; the final root-identity span was 0.575 seconds. This traversal
reads metadata, not those payload bytes. Its elapsed spans include scheduling
and do not establish filesystem latency or another physical cause. The active
owned boot wait retains its separate finite fifteen-second ceiling;
it gains no missing-entry rescan permission. Complete accounting, root/link
checks, command deadlines and cleanup bounds remain required.

[C3 Recovery run 41426294706](https://github.com/4alvit/travel-documents-ios/actions/runs/41426294706)
completed preparation, then stopped during export because a full resource scan
exceeded fifteen seconds. Its failed traversal lasted 16.848 seconds after
503 completed accounting samples; the export command's original work deadline
still had over 470 seconds remaining. The last observed `entry_stat` span began
14.610 seconds into traversal and lasted 1.161 seconds. These spans include
scheduler delay and do not identify a filesystem cause. No traversal restart
occurred. Export produced no final XCTest result; restore never began.

Only unfinished native phase scans now permit thirty seconds, still clipped
to the original command and global deadlines. The boot ceiling remains fifteen
seconds, and other contexts remain five. All entries still receive fresh,
uncached checks; no size, allocation, depth, ownership or cleanup guard is
removed. Thirty seconds does not guarantee completion, and timeouts still fail
without an automatic retry. Completed resource samples now also retain a fixed
set of scalar scan timings, operation/encounter counts, attempts and maximum
depth, so later audits can distinguish completion intervals from traversal time.
The old receipt retained only completion times for successful scans. Its last
complete sample reported about 27.1 GB logical length but 306.3 MB allocated;
the allocated output cap was not reached. Per-file sparse/compression attribution
is unavailable because build intermediates were not retained.

Capability commands keep their own pending-command context when delegating a
resource checkpoint to the parent output scanner. Their admission, execution
and finalization scans use the probe's original work deadline and the parent's
preparation limit. This context is passed for each call, so it cannot leave a
stale deadline on later parent work or change the process-stop grace.

A failed sample is never appended to completed resource accounting. The first
failure retains one bounded diagnostic record: stage, partial counts, relative
path (at most 256 characters), and last/longest filesystem-operation spans.
These elapsed spans include scheduling and wrapper time, not just syscall time.
Only the last and longest spans are retained; there is no per-entry history or
extra diagnostic filesystem probe. Permission, identity, traversal and resource
errors still fail closed. All existing directory handles are closed on failure.
Checks before and after operations cannot preempt a blocked OS call, and partial
counts never establish compliance or UI acceptance.

Live accounting tolerates a confirmed absent regular leaf only within the owned
`DerivedData` build/cache area, excluding `DerivedData/Build/Products` and every
`.xcresult` bundle. Build intermediates, indexing and module-cache writers may
remove an enumerated entry before its stat. Hosted failures observed this race
in both a compiler `.o.tmp` and an index-store leaf; the allowance is scoped by
mutable output ownership, not a temporary filename or index format version.
The vanished encounter still consumes the entry cap. Its original no-follow
DirEntry kind must be regular, a fresh descriptor-relative no-follow stat must
confirm ENOENT, and the named root/parent plus open parent descriptor identities
must match before and after confirmation. Every added operation remains within
the original checkpoint/deadline. Reappearance, unknown kind, links, directories,
permission and other errors fail closed. The scan must still finish completely,
with final root identity checked, before its totals become a resource sample.
Completed samples record a bounded confirmed-absence count; traversal diagnostics
retain the last relative path. This is sampled live disk accounting; source,
payload and evidence manifests and binary verification remain strict and unchanged.

The work free-space floor is 8 GiB. The 8 GiB owned-output disk limit uses
allocated 512-byte blocks, so a sparse DerivedData file's logical length alone
does not consume that budget. Receipts retain separate logical and allocated
totals. Missing, negative or non-integer allocation metadata fails closed;
logical size is not a safe upper bound for allocated storage. Hardlinks remain
conservatively charged per directory entry, with a fresh stat for every entry
and scan so observed growth is charged. This may overcount shared storage.
The 2 GiB xcresult content limit still checks both logical and allocated size;
manifest, archive, input and log-content bounds are unchanged. Each log stream
has a 16 MiB limit and all log streams 64 MiB. Output limits remain
sampled abort thresholds, not a filesystem quota or whole-device allocation
measurement. The workflow's 27-minute execution step and 35-minute job give an
outer deadline plus time for checkout, offline checks and evidence upload.

There is one new owned Simulator, one fixed Files-provider setup, one export
case, a durable verified before-reset snapshot pin, then one restore case.
No reset is permitted before the pin. Original xcresults receive immutable
manifests before diagnostic readers; readers use verified inspection copies.
After restoration the original document bytes, metadata and unchanged backup
are compared and an after snapshot is retained. Failure never becomes UI/PDF
acceptance; cleanup success never removes an earlier failure.

The upload step runs on failure too and uses an explicit allowlist of receipts,
selected Xcode/Files logs, capability evidence, xcresults, snapshots and attachments.
Raw root command logs, including host process listings, are excluded from the
start. Only the two known Xcode phases and exact owned Files launch/terminate
stdout/stderr streams are moved into `PhaseLogs`. The Files route checks the
command label, argv, owned UUID, sequential stream path, byte count and confirmed
process stop/stream closure before moving already bounded logs. Unknown ownership,
replaced paths and existing public filenames fail closed. No new native commands
or log caps are added. A failed move can omit diagnostics but cannot expose a
process listing, and any original Files failure remains primary. The tested source
and DerivedData are also excluded. Hidden bundle
files are included. GitHub artifact transport can normalize permissions; the
original mode metadata remains in the immutable JSON manifests. A raw result
without a completed manifest is diagnostic material only.

## CI integration

One push to the open PR branch triggers the existing `pull_request` workflow:
`validate` (including ordinary integration/StoreKit), `ui_guidance`,
`privacy_ipad` and `recovery`, then `CI gate`. Gate requires all four job
results, including both locales in the iPad matrix, to succeed; no
existing gate, test command or StoreKit rule is relaxed. The workflow also keeps
its existing main-push, dispatch and merge-group triggers.

`cancel-in-progress` becomes false so another push does not cancel a running
recovery during owned cleanup. A newer pending run can replace an older pending
run under GitHub concurrency rules. Manual cancellation, host loss and the hard
job deadline can still interrupt cleanup; those outcomes cannot be accepted.
The authorized first cohort is one push/run, not a series of retries. Any later
failure needs a review of retained evidence before another cohort is authorized.

Offline adapter tests cover new job/profile, toolchain path, source/merge,
capability-proof and artifact-exclusion boundaries. They deliberately forbid
real process creation/signals. They do not establish host readiness or replace
the inherited recovery tests and independent native UI review.

The retained command-level classifier for the exact already-stopped Files
termination diagnostic is not used by provider-only preparation. Its strict
owned-command, complete-log, exit, deadline and closure checks remain unchanged;
it does not permit a nonzero group lookup. The existing Files log-publication
allowlist is also unchanged. Group lookup output remains a private root log,
not a new public artifact route.

Removing the forced 120-second launch and 60-second termination does not extend
the total work deadline or reserve new time for a later phase. At the observed
preparation start of 148.57 seconds, 1,231.43 seconds remain before the original
1,380-second work limit. A full 60-second group lookup leaves at most 1,171.43
seconds for export, restore and evidence processing; the two 600-second phase
caps still cannot both be consumed in full. They remain maxima clipped to the
original remaining work time. Every command still needs more than its 8-second
stop reserve before admission and again before spawn. Cleanup retains its
original 120 seconds within the same 1,500-second executor limit. No additional
worker, Simulator, test attempt or runtime fallback is introduced.

Each iPad guidance locale now runs in a separate fresh driver and owned device.
Its single `build-for-testing` command uses the dedicated `Tripfolio-iPad`
scheme and UI-only plan, selecting the same exact locale test method as
`test-without-building` and retaining the 360-second build cap. A prior unscoped
build exhausted that cap while compiling the unused hosted AppTests target.
The iPad plan retains the default plan's configuration and options, but the
scheme and plan include only the UI-test target and its app dependencies. The
core/purchase job continues to build and run all hosted AppTests through the
unchanged default plan. Generated iPad metadata must contain exactly the UI-test
target; a full-scheme result is rejected rather than silently accepted.
The fixed EN/RU CI matrix has `max-parallel: 1` and `fail-fast: false`: a failed
English lane cannot prevent Russian from running, and the existing CI gate
requires the aggregate matrix result to be `success`. Each artifact includes its
locale, source SHA, run ID and attempt; the receipt records the exact locale,
method, one-case count, source manifests, built/installed bytes and owned UUID.
No case is inferred from the other locale's result.

This corrects an observed allocation defect: English took 590 seconds including
bootstrap; Russian was then admitted with only 357 seconds of work even though
its requested command allowance was 570 seconds. Its timeout was subsequently
masked by an installed-AUT lookup that could not fit. Fresh drivers now use
2,100-second work budgets and the same 180-second cleanup reserve.
Both command waits are 900 seconds; XCTest's 480-second maximum is unchanged. Before
case preparation, the driver requires the full command budgets and each 7-second
stop reserve, plus 30 seconds for local manifests/copy/validation: 1,487 seconds
for either locale. Immediately before test spawn it again requires the full
test wait, its 7-second stop reserve and 238 seconds for post-test validation
(two installed lookups of 60 seconds, result summary 30, result tests 30, four 7-second stops
and 30 seconds of local evidence work). These are admissions within each locale's absolute work
limit, not renewed deadlines or guarantees against cooperative syscall stalls.
Insufficient budget fails before starting the case/test. Post-test evidence is
still mandatory; its errors are retained separately and cannot replace the
original test timeout, nonzero exit or process cleanup error.

A later Russian attempt exited 65 before any test case started: FrontBoard
reported `com.4alvit.tripfolio.uitests.xctrunner` as unknown. The AUT had been
installed and its bytes verified, but there was no independent installed-runner
receipt. This proves a runner launch failure, not a particular OS compatibility
defect or whether runner bytes were absent versus unregistered.

Each locale now explicitly installs the built AUT and built UI-test runner once
before test launch. The generated runner's Info.plist must contain the exact
expected identifier. Fresh 60-second container lookups before and after the test
verify both identifiers, bundle paths and complete built-versus-installed bytes;
they do not reuse a path that xcodebuild may replace. The added runner install
and lookups are included in the case and post-test admissions above. Installation
or readback failure cannot become test success. The original generated xctestrun,
900-second host wait, native assertions, exact result checks and no-retry behavior
are unchanged. This explicit setup requires new hosted evidence; it does not
retroactively validate the failed launch or guarantee against service failures.
The separate guidance cohort and two iPad locale builds give five macOS jobs:
three with 35-minute limits and two iPad jobs with 46-minute limits,
at most 197 aggregate job-minutes. The workflow permits
up to four concurrent macOS jobs: core/purchase, guidance, recovery and one iPad
locale, subject to account runner capacity. There are six jobs including the
Ubuntu gate. The bounded observer retains its original 120-minute admission
window and records both locale jobs separately; it must not declare a complete
cohort when one locale is missing, skipped or failed. This is a scheduling-policy
change requiring new runtime evidence, not acceptance of either failed old run.


Files provider readiness uses only the unused part of the original `files-group`
lookup work deadline (52 seconds within the 60-second Files group command cap).
The clock starts when that original command starts; readiness never receives
a renewed 52-second window after the lookup returns.
After the single successful group lookup, the wrapper pins the exact owned
group and observes only its `File Provider Storage` leaf. Initial leaf absence
may settle within that existing deadline; the wrapper never creates the provider,
relaunches Files, repeats a command, chooses another provider, or renews the clock.
A missing/replaced group, symlink, permission error, or disappearance after the
provider identity was observed fails immediately. The original work limit is
restored before subsequent preparation and the existing cleanup paths. Bounded receipt
fields retain the failure stage, safe owned-relative filename, observation count,
and original deadline. This readiness policy does not establish that delayed
provider initialization caused any earlier hosted failure. UI export/restore
assertions, exclusive test-folder creation, other command caps, global budgets,
and cleanup proofs remain required.

While an owned export/restore XCTest command is active, one confirmed vanished
regular `*.xcresult/Data/_tmp.*` direct leaf may abort the current live resource
traversal and trigger one complete fresh traversal. The private six-case runner
uses the same rule for its active `selected-tests` command. All partial logical,
allocated, entry and bundle totals are discarded; neither a skipped leaf nor a
previous completed sample can become the new accounting result. The second pass
uses the original scan/command deadline, the same byte/depth limits, and one
cumulative encounter budget across both passes. A second disappearance fails.
The existing no-follow fresh-absence, known-regular kind and root/parent/open-FD
identity checks apply before the first pass can be discarded. Permission,
directory/open/scandir, unknown-kind, reappearance and identity errors remain
strict. Immutable manifests and scans without an active owned test context do
not permit this restart. This responds to an actual entry-stat ENOENT in
`Tests.xcresult/Data/_tmp.IJNVOw` after 0.0258 seconds; it does not change any
scan allowance, native attempt count or test assertion, and does not establish
that another run will pass.

The same complete-scan restart applies to a confirmed missing known regular
file or directory in the top-level result bundle's `Staging` directory. During
an active owned test command, a confirmed missing known regular file below
`DerivedData/Build/Products` may also request this restart. Xcode rebuilds those
products between recovery phases: main run `41346633231` removed a test bundle's
`TravelCore_TravelCore.bundle/Info.plist` during the export build, and the former
strict absence rule stopped the build before XCTest began. The product case
does not permit missing directories, symlinks, unknown kinds or nested result
bundles. Products and result bundles share one restart, the original deadline
and cumulative encounter budget; a second disappearance still fails. The
replacement sample must traverse the entire output and charge all current
bytes. Immutable product manifests, permission errors, identity checks and
native phase/test counts remain unchanged.

A biometric bridge checkpoint retains the parent's active owned
`selected-tests` writer identity when the bridge is explicitly linked to that
parent and its shared biometric report/clock. The child itself is not treated
as the xcresult writer. The scan remains limited to five seconds and to both
the primary and child original work deadlines; neither stop reserve may be
borrowed. An ended or absent primary, unrelated report/parent or missing owned
process cannot inherit restart permission.
