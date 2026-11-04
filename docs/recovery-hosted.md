# Hosted recovery regression

This job exercises the two opt-in recovery cases described in
`recovery-ui-regression.md`. It is separate from the ordinary Simulator preview
and existing StoreKit tests. A successful job is pending independent review of
the ordered UI attachments and actual rendered PDF pixels; it is not App Store
or payment acceptance.

## Profile and dependencies

The job uses the standard `macos-15-intel` runner class after repeated hosted
ARM runner acquisition failures. The reviewed profile requires the actual
runner context to report `github-hosted` and `X64`, and Python to observe
`x86_64`. Image OS/version are recorded. The profile is a
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

GitHub currently documents `macos-15-intel` as standard Intel and macOS storage
as 14 GB. Consequently **16 GiB free is not guaranteed**. The job measures the
actual filesystem and refuses admission below 16 GiB; it never lowers the guard
or removes preinstalled/unrelated data. Official references:
[runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners),
[image inventory](https://github.com/actions/runner-images/blob/main/images/macos/macos-15-Readme.md).
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

The standalone executor retains its 1,500-second total, 1,380-second work
window and 120-second owned cleanup reserve, including a final 10-second receipt
reserve. Its prepare command/case caps remain 780/180 seconds, and export and
restore each retain 600/300 seconds.

The hosted Intel adapter selects the immutable `hosted-intel-v1` profile before
creating output or deriving deadlines from the original entry clock. It requires
the exact `macos-15-intel` / `X64` / `x86_64` hosted tuple. Unknown profiles,
crossed host identities and changed timing policy are rejected before work.
The selected profile cannot be replaced during the run. It allows 5,040 seconds
total: 4,680 for work and 360 for cleanup. Prepare allows 1,200 command
seconds and 300 native case seconds; export and restore each allow 900 command
seconds and 600 native case seconds. Every command includes the unchanged
eight-second stop reserve and is clipped to the original work deadline. The
native allowances require an exact profile token, the existing Recovery opt-in,
matching phase and canonical folder identity in a Debug Intel Simulator build.
Without that token the standalone native allowances are unchanged.

Only hosted cleanup gives each owned shutdown/delete action 90 seconds and
each recovery/final inventory query 60 seconds, including the same eight-second
stop reserve. Default cleanup retains 30-second actions, 20-second queries and
its 120-second total. In run 41894677683 the shorter action and inventory work
windows expired, while bounded process termination succeeded. Run 41896588489
completed shutdown in 21.55 seconds and verified cleanup. In run 41899787568,
an unobserved 44.23-second gap put shutdown's next observation beyond its entire
30-second command deadline; no stop signal could then be sent. This does not
identify the cause of the gap or prove that more time will complete cleanup.

The hosted cleanup maximum includes optional ownership recovery 60, shutdown
90, delete 90, final inventory 60 and final receipt 10: 310 seconds, leaving 50
seconds for non-command work inside the 360-second window. It remains clipped
to the original overall deadline. The work allocation remains 4,680 seconds
for 4,515 seconds of command ceilings and 165 seconds of non-command margin.
No extra attempt, signal retry, drain or ownership adoption is introduced.
An unresolved process still prevents further commands and cleanup acceptance.

In [run 41884508287](https://github.com/4alvit/travel-documents-ios/actions/runs/41884508287/job/126765257864),
prepare spent 713.25 seconds before its test began, leaving only 58.75 seconds
of command work. The command expired during app launch, before any Files action;
this was not a demonstrated native case timeout. A historical Arm
restore case took 274.88 seconds of its 300-second allowance. The hosted native
increases provide performance margin for slower Intel execution; they do not
prove an application defect or guarantee completion.

The complete hosted work envelope includes 110 seconds for source Git commands,
80 for toolchain checks, 300 for shared discovery, 330 for boot commands, 3,000
for the three phase commands, 360 for result readers, 160 for app-state checks,
135 for result comparators and 40 for final Git checks. Those command ceilings
total 4,515 seconds, leaving 165 for source copying, manifests, parsing and other
in-process verification before cleanup. They remain ceilings rather than new
per-phase clocks. No phase retries or additional workers are introduced.
The immutable hosted Intel profile allows up to 60 seconds for one complete
resource scan during an exact active owned boot wait; the portable profile
retains 15 seconds. Two Intel attempts exceeded 15 seconds before native tests,
including one measured 25.86-second file-stat operation span. These spans include
scheduling and do not establish the underlying cause. The scan still shares the
original 300-second boot command, its eight-second stop reserve and the global
work deadline. Repeated scans cannot renew those clocks. Admission and other
ordinary scans retain five seconds, native phase scans retain 30 seconds, and
all files, byte limits and ownership checks remain required. A synchronous
operation can overrun a cooperative deadline; after it returns, the scan fails
closed rather than accepting partial accounting.
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
inside the shared discovery window. Fully consuming discovery leaves at most
4,380 hosted work seconds minus preflight for boot, UI phases and evidence.
Standalone execution retains its original 1,380-second work deadline. The
per-phase maxima are ceilings, not a guarantee that all can run for their maximum duration in one attempt;
later commands remain clipped to available work time and cleanup is reserved.

Hosted readiness for the newly created, owned Simulator has a separate
300-second command ceiling, including the unchanged eight-second stop reserve.
Only the exact `simctl bootstatus <owned UUID> -b` call receives this allowance;
the portable executor's 120-second default, the initial boot command, UI cases
and all other command caps stay unchanged. Readiness still requires a successful
command exit and verified process closure before building or testing. The
allowance is clipped to the selected original work deadline and introduces
no retry or renewed global clock.

The [successful reference run](https://github.com/4alvit/travel-documents-ios/actions/runs/41781766427/job/126414697445)
spent 106.9 seconds in cold boot readiness, leaving about five seconds under
the former 112-second work allowance. Two attempts of
[run 41790791116](https://github.com/4alvit/travel-documents-ios/actions/runs/41790791116)
then failed before any build or test: the first reached that deadline during a
resource scan, while the second reached it without a scan failure. Both stopped
their owned process groups, but neither verified device deletion or final
inventory. The larger hosted ceiling is a bounded cold-start scheduling policy,
not evidence that the underlying Simulator service problem is fixed. Subsequent
results must retain their actual readiness duration and cleanup outcome.

Dedicated Recovery preparation sets `TRIPDOCKET_RECOVERY_CREATE_FOLDER=1`
only for its existing prepare case. This mode requires the existing Recovery
opt-in, prepare phase and canonical run UUID, with no competing fixture modes.
It opens the existing Debug Simulator direct exporter using one generated,
canonical source UUID distinct from the Recovery destination UUID. It requires
one enabled, hittable synthetic-ticket source and opens it once, then reaches
the exact local root using the existing 30-second initial presentation allowance.
It proves the canonical destination name absent and requests New Folder and
rename through the bounded Files action sequence shared with Batch
qualification. No Save is requested: the direct fixture must report neither an
exported file nor a failure before or after folder creation. Preparation stops
the app before the host can adopt the empty folder.

The shared post-New-Folder readiness observation defaults to a 30-second polling
allowance for standalone and Batch callers. In run 41805678990, about 18 seconds elapsed between the first live
picker-count query starting and the failure capture. That query did not report
exactly one picker, and the previous 15-second window ended before a second
sample. The later failure image showed an inline editor
and keyboard introduction; it does not establish when either became ready.
The new allowance permits another fresh, fully validated picker/application
pair. More and New Folder are still tapped once, and no other wait or outer
case/host cap increases. This is a polling allowance: an in-flight synchronous XCTest query can overrun it under the existing
wait semantics. It does not guarantee remote Files readiness.

The already validated `hosted-intel-v1` Recovery opt-in selects 60 seconds for
this observation only. In run 41899787568, the first bound picker/application
pair included the supported inline editor and keyboard introduction, but its
live binding finished at least 42 seconds after the observation began. The
original 30-second deadline correctly rejected that late result. The hosted
window now gives that same classifier more time; polling and action admission
share one deadline that is never reset. A result arriving after the selected
deadline still cannot authorize readiness or Back. The observation adjustment
leaves initial picker presentation, the native 300-second prepare case and the
1,200-second prepare command unchanged. This change does not establish native success
or resolve the independent unconfirmed Simulator shutdown in that run.

In [main run 41845526416](https://github.com/4alvit/travel-documents-ios/actions/runs/41845526416),
the single New Folder action instead opened an empty `untitled folder` child.
The parent-only editor and Rename checks correctly rejected that state. The
helper now recognizes this separate navigation state using the exact local
provider, child title, parent Back action and visible empty-folder placeholder,
with no cells, editor or keyboard. The remote snapshot may omit the empty
collection view. A fresh bound observation and matching enabled, hittable Back
control permit one return to `On My iPhone`; the child itself is never ready for
rename. The return and subsequent unchanged parent checks share the original
selected observation deadline. A late query, changed control or repeated child state cannot
initiate another Back. New Folder is not repeated, and Save is never pressed.
Exact UUID naming,
editor geometry, fixture termination and host empty-folder adoption remain
required. This handles the observed transition; it does not establish why Files
chose it or prove native acceptance of a new candidate.

The explicit keyboard-introduction state accepts zero or one Keyboard node:
its first-use overlay can be present in a bound application snapshot without a
separate Keyboard node. The unique introduction must have finite, positive bounds
inside the application window, clear of the exact inline editor and local-root
title. Any present keyboard must retain its existing geometry checks. Ordinary
editing still requires exactly one keyboard. The nonediting Rename fallback
rejects an introduction in either snapshot, including when no Keyboard is exposed.
This changes only readiness classification; the single Continue acknowledgment, exact explanation and button,
subsequent dismissal/editor checks, and all action budgets remain required.

The shared guidance preparation invoked by `test-simulator.sh` omits this flag
and uses the same existing Debug Simulator exporter for provider-only preparation. Both prepare modes
require the isolated Recovery opt-in, prepare phase and canonical destination
probe UUID. A separate canonical source UUID opens the synthetic-ticket source
once; preparation never saves it. Provider-only preparation retains its generic
phone/iPad local-root navigation, absent-folder probe and explicit app shutdown,
and never requests folder creation. Ordinary UI cases and actual Recovery
export/restore still use the production Free gate, disclosure, Save-to-Files
and import/replacement paths.

After the single Save tap, the validated `hosted-intel-v1` export case allows
60 seconds for the picker to disappear and Settings to be present; other callers
retain 15 seconds. In run 41928330972, the retained failure image and accessibility
snapshot still showed the owned destination with an in-progress indicator. That
state remains pending, never completion. The extra polling allowance does not
change the predicate, repeat Save or reset the wait deadline. The native
600-second case and 900-second host command remain bounded, and synchronous
XCTest queries retain their existing overrun behavior. This is finite headroom,
not proof that the pending export will finish. A dismissed picker still requires
the host's complete backup metadata and original-byte verification before reset.

After the prepare case passes and its process group closes, the host adopts
exactly one native-created leaf. The pre-boot absence proof, no-follow ancestor
and inode checks, and complete empty-directory check must all pass before export.
Recovery does not create a provider directory on the host, fall back to host
creation, retry the UI action or prepare backup bytes. The three cases, 180-second
prepare allowance, global work deadline and cleanup reserve are unchanged.

Run 41771491849 failed when native Files could not resolve the selected backup
bookmark and returned no usable URL. This boundary precedes application restore;
it does not by itself prove the folder's creation method caused the failure.
The changed setup therefore requires new native end-to-end acceptance. Actual
app Save-to-Files, import/restore, catalog/original-byte comparisons and rendered
PDF checks remain mandatory; a passing folder setup alone is not acceptance.

Run 41773899588 attempts 1 and 2 both stopped during dedicated preparation at
the same live-binding check after the single New Folder action, before keyboard
acknowledgement, name entry, host adoption, export or restore. The direct-exporter
setup removes duplicated Settings/share navigation from preparation; it does
not establish the OS cause of those failures or prove that the changed route
fixes them. In run 41777826319 attempt 1, dedicated preparation and production
export passed, including native empty-folder adoption and complete-original
backup equality. Restore reached file selection and replacement confirmation,
but the coordinated read received Cocoa 4101 with an underlying failure to
connect to Apple's LocalStorage File Provider extension. That result is not
successful recovery and does not establish a deterministic application defect.

The same run's second-attempt Phone bootstrap failed before the ordinary UI
suite: a single correctly targeted Settings tap left Trips selected. Its
provider-only setup now opens the direct exporter without that preliminary
application navigation. This changes preparation, not the ordinary Settings
checks, and does not establish the cause of the native tab non-transition.
The revised shared preparation requires fresh native CI acceptance.

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

Overall work deadlines remain fixed at driver start, including discovery:
2,100 seconds on ARM and 4,500 seconds on Intel for either locale. ARM reserves
180 seconds for cleanup and Intel reserves 360 seconds, including final evidence. The immutable profile is selected from the host
architecture before allocating the deadline, and recorded in the receipt.
The later captured `uname` must match it before device creation; an unknown
architecture or mismatch fails closed. Discovery never changes the profile.
The phase is also clipped to that overall work deadline. Stop receipts summarize
the existing poll, group probe and signal calls in four bounded slots; an EPERM
is a failure, and only ESRCH establishes group absence. A primary timeout remains
visible alongside secondary stop or receipt-write errors. These are cooperative
checks between operations, not preemption of a blocked OS syscall. Releasing the
discovery phase before boot/build never renews the overall clock; longer discovery
still consumes time available for the complete case admission below.

By default, both iPad XCTest commands have a 900-second host wait. A fresh Russian run took
239 seconds from process spawn to XCTest start and was interrupted by its old
570-second wait while making UI progress at 331 seconds. A later English run
passed discovery in 10.2 seconds but took 299.814 seconds from test-process spawn
to XCTest start. Its old 600-second wait interrupted active UI work at 300.30
seconds. Neither interrupted run completed its result bundle or retained usable
screenshot payloads. These are startup-budget failures, not passing UI evidence.

The default 900-second wait accommodates the observed roughly 300-second startup,
the unchanged 480-second XCTest ceiling and up to 120 seconds of result-finishing
headroom. This is a finite allowance, not a guarantee about future startup time
or a passing result. Exact test methods, UI assertions and content-size settings
are unchanged. Default XCTest allowances remain 180/max 480; no run retries a case.

Each test must fit inside its locale's absolute work deadline, including its
seven-second process-stop reserve and mandatory post-test validation. Admission
is checked before preparation and again immediately before spawn. A terminal
test-process poll at or after its wait deadline fails, even with exit code 0.
On Intel, initial boot readiness allows 600 seconds, clipped to the original
work deadline; ARM retains 180 seconds. Two Intel runs exhausted 180 seconds
while reporting data migration. A separate run completed boot readiness in
118.663 seconds. These observations support bounded cold-start headroom, not a
claim that a larger allowance cures a service failure. Initial boot retains
600 seconds on Intel and 180 on ARM. The default test command remains 900 seconds;
full-case admission is 1,487 seconds on ARM and 1,517 on Intel. The explicit
hosted English policy below uses a 1,200-second command and 1,817-second admission.

In [run 41884508287](https://github.com/4alvit/travel-documents-ios/actions/runs/41884508287/job/126784418116),
Intel boot completed in 312.7 seconds, but the fresh build reached its 480-second
limit before any UI case started. The last logged operation was asset catalog
compilation; no compiler error was reported. That log does not identify the
underlying cause of the delay. All 26 process groups closed and the complete
127-device baseline was restored after deleting the owned device.

The selected Intel profile now permits a 1,200-second fresh build inside its
4,500-second work window; ARM retains its 480-second build. Preflight, discovery,
boot, project generation, the build and the complete case admission have combined
command ceilings of 4,143 seconds on Intel under the default native policy,
leaving 357 seconds for manifests, product discovery, parsing and receipt writes.
The explicit hosted English policy increases that sum to 4,443 seconds, leaving
57 seconds while retaining the same original work deadline and strict admission. This is engineering headroom,
not a measured requirement or a guarantee that the next build will complete.
The 360-second Intel cleanup window includes final source/product/original checks:
normal cleanup and four final Git commands have 249 seconds of command ceilings.
An optional ownership recovery and one outstanding group stop add 34 seconds.
Multiple unresolved groups may still exhaust the window and must remain failures.
No command is retried, no clock is reset, and no native assertion is removed.

Both hosted locales use 83-minute steps: 75 minutes of Intel work, six of cleanup
and two for startup/finalization. Their 95-minute jobs allocate two minutes to
checkout, three to toolchain setup, 83 to the driver, two to artifact upload and
five to cancellation/overhead. Insufficient remaining case admission still fails.

Guidance tab transitions retain a five-second observation deadline and one tap.
A failed English run showed a fully rendered Settings screen: the selected-tab
snapshot was followed by a second remote navigation-bar query that exhausted
the deadline. The transition now requires the selected tab and exactly one
matching, nonempty, in-bounds navigation bar in the same immutable snapshot.
The existing bounded traversal and strict deadline checks remain; a late
snapshot, ambiguous title or missing navigation bar still fails. Fixture tests
execute the actual Swift helper and reject those states without another remote
query or another tap.
The step limits include each locale's selected work and cleanup budgets; the
job limits also leave time for toolchain setup and artifact upload. A command
return still requires the original result/provenance validation before a case
can pass; partial testcase progress is not acceptance.

One complete resource sample normally has a fixed five-second cooperative
allowance. During an unfinished `phase-prepare`, `phase-export` or `phase-restore` command,
including its admission and finalization, the explicit ceiling is thirty
seconds. An active owned `boot-ready` process waiting for
`simctl bootstatus <owned UUID> -b` retains its separate fifteen-second ceiling;
its admission and post-process samples keep five seconds. Every sample is clipped to the overall work limit, the actual command
owner's limit and its original work deadline, preserving the stop reserve
during admission and execution. After a zero exit status, verified leader/group
closure, successful pipe and log closure, and successful stdout read, the
existing conditional final checkpoint may use the original total command
deadline. This short-lived in-memory context belongs to that exact command and
process; saved receipt fields cannot grant it. It is cleared even on an exception.
For the exact owned hosted boot wait, one due periodic sample may be deferred
after a successful live process poll while the final pipe data is drained.
The drain keeps its original work deadline, cancellation checks and output caps;
forced samples, delegated commands and any second drain checkpoint still scan.
The sample schedule is not advanced, so successful process and stream closure
must be followed by the still-due complete sample. Failure of that final sample
still fails the command. This avoids starting a traversal before closing an
already-exited boot process when little work time remains; it does not extend
boot time or accept a partial resource scan.
The five/fifteen/thirty-second sample ceilings and total command/global caps do
not change, and no additional sample is forced. One fixed deadline covers both free-space reads and the full uncached output
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
resource checkpoint to the parent output scanner. Their admission and execution
scans use the probe's original work deadline and the parent's preparation
limit. Verified successful finalization may use the probe's original total
command deadline as described above, but an unfinished parent still imposes
its own work deadline. Failed commands, accepted nonzero exits and unresolved
ownership retain the prior limits. This context cannot leave a stale deadline
on later parent work or change the process-stop grace.

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
measurement. The native execution step allows 86 minutes, including two minutes
beyond the 84-minute executor ceiling. The 113-minute job allocates two minutes
to checkout, 15 to offline regressions, 86 to native recovery and five to evidence
upload, plus five minutes for cancellation and step overhead. The executor still
reserves its own cleanup time before the outer workflow deadline.

In [run 41877246834](https://github.com/4alvit/travel-documents-ios/actions/runs/41877246834/job/126739897632),
the first synthetic Swift fixture compilation exceeded its 30-second timeout.
The first three regression suites then reported 125.137 seconds combined,
already exceeding the former two-minute step before the other ten suites ran.
The Files readiness fixture compilers now consistently allow 60 seconds;
five-second fixture executions retain their limit. The three complete-file SDK
typechecks now allow 180 seconds each. A later hosted run exhausted 45 seconds
for both Batch UI checks (ARM default and Intel Debug); this is a compiler-command
timeout, not a native test failure. The 15-minute regression step includes
headroom beyond a conservative 688-second estimate from that run and the other
retained suites. It remains finite and does not guarantee future compiler speed.
These offline allowances do not change native case limits or accept incomplete
regressions. All 13 suites and the subsequent native recovery still require a
fresh passing hosted run; the larger envelope does not guarantee completion.

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

The earlier removal of the forced 120-second launch and 60-second termination
did not extend that run's work deadline or reserve new time for a later phase.
At the observed preparation start of 148.57 seconds, 1,231.43 seconds remained before the original
1,380-second work limit. A full 60-second group lookup leaves at most 1,171.43
seconds for export, restore and evidence processing; the two 600-second phase
caps still cannot both be consumed in full. They remain maxima clipped to the
original remaining work time. Every command still needs more than its 8-second
stop reserve before admission and again before spawn. Cleanup retains its
original 120 seconds within that historical 1,500-second executor limit. The
current hosted profile is specified above. No additional
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
The fixed EN/RU CI matrix has `max-parallel: 2` and `fail-fast: false`: both
independent locale jobs can become eligible together, and a failed English lane
cannot prevent Russian from running. The existing CI gate requires the aggregate
matrix result to be `success`. Each artifact includes its
locale, source SHA, run ID and attempt; the receipt records the exact locale,
method, one-case count, source manifests, built/installed bytes and owned UUID.
No case is inferred from the other locale's result.

This corrects an observed allocation defect: English took 590 seconds including
bootstrap; Russian was then admitted with only 357 seconds of work even though
its requested command allowance was 570 seconds. Its timeout was subsequently
masked by an installed-AUT lookup that could not fit. Fresh drivers use separate
work budgets of 2,100 seconds on ARM or 4,500 on Intel and respective cleanup
reserves of 180 and 360 seconds.
Default command waits are 900 seconds with XCTest's 480-second maximum.
The explicit hosted English policy uses a 1,200-second command and 900-second
XCTest maximum. Before case preparation, the driver requires the full command
budgets and each 7-second stop reserve, plus 30 seconds for local manifests/copy/validation:
1,487 seconds on ARM, 1,517 on default Intel or 1,817 for hosted English.
Immediately before test spawn it again requires the full
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
or readback failure cannot become test success.

The Russian iPad job in run `41899787568` completed boot and build, then exceeded
its 60-second AUT installation wait without reporting an installation error or
success. It reached no native case. Intel AUT installation now allows 90 seconds;
ARM AUT installation, runner installation and every container lookup keep 60.
This is part of the architecture-selected profile, including standalone Intel,
not a hosted-only opt-in. The extra 30 seconds are included in the full-case
admission: Intel preparation is 372 seconds, with the original 7-second stop
reserves and 238-second post-validation budget. Work, cleanup and native limits
are unchanged. The failed run's process and owned-device cleanup completed;
a larger install allowance neither proves installation nor guarantees a pass.

The original generated xctestrun,
selected finite host wait, native assertions, exact result checks and no-retry
behavior remain required. This explicit setup requires new hosted evidence; it does not
retroactively validate the failed launch or guarantee against service failures.
The English iPad case in run `41899787568` reached its 480-second native limit
while saving evidence after the second confirmation cancellation. Its raw log
continued through a fourth Cancel at about 660 seconds, but the retained native
result is failed and contains no final Trips evidence. The command returned 65
after 753.5 seconds; boot and build had completed. This supports additional native
time, not a claim that the unrecorded final navigation succeeded.

Only CI's explicit `--hosted-intel-timing` option admits hosted iPad timing. The
producer checks the exact GitHub-hosted macOS/X64 context, selected locale and
captured architecture; standalone Intel and ARM runs keep their defaults.
Inherited Phone/iPad timing tokens are rejected. Only the final native command
receives `TEST_RUNNER_TRIPDOCKET_IPAD_TIMING`; the app receives no timing token.
The consumer requires Debug x86_64 Simulator and iPad idiom, with the exact
`hosted-intel-ipad-en-v1` token for the English case or
`hosted-intel-ipad-ru-v1` for Russian at maximum type. English retains its
900-second native allowance and 1,200-second command; Russian uses 1,200 and
1,500 seconds respectively. Phone and missing-token timing stay unchanged.

The Russian case in run `41928330972` failed at the 480-second native limit during
the first confirmation's warning, with zero cancellations yet recorded. Its
post-timeout stdout continued only into the second link; those later actions
are not accepted native evidence. A historical ARM pass took 316.8 seconds with
byte-identical functional UI actions and captures. Scaling its remaining three
cycles and final return by the observed first-cycle ratio gives an illustrative
947.8 seconds. This estimate motivates finite headroom, not a guarantee that the
new allowance will complete the case. Captures and geometry checks stay intact.

English admission remains 1,817 seconds; Russian requires 2,117: preparation372,
command1,500, a separate7-second stop reserve and post-validation238. The native
command still has its full1,500-second wait cap, clipped by the original global
deadline; immediate pre-spawn admission protects the stop/post-validation
reserve. Work remains4,500 seconds and cleanup360, with the83-minute step and
95-minute job unchanged. Russian summed phase maxima4,743 exceed the work
window, so a late build must fail admission rather than reset the clock. All24
text checks, four Cancels, zero Open actions and final Free/Trips evidence remain
mandatory. Neither a timeout nor a nonzero result becomes a pass.

The separate guidance cohort and two iPad locale builds give five macOS jobs:
Core has a 75-minute limit, Recovery has 113 minutes, phone guidance has 95 minutes,
and each iPad locale has 95 minutes, at most 473 aggregate job-minutes. All five
jobs can become eligible independently: phone guidance does not consume Core
outputs, and each iPad locale creates its own checkout, build and owned device
without consuming Recovery artifacts. All five use `macos-15-intel` with the same
Xcode 26.2 and SDK-compatible runtime selection after repeated ARM runner
acquisition failures.
There are six jobs including the Ubuntu gate. Both locale jobs remain required;
a missing, skipped or failed locale cannot count as a complete cohort. The
runner change requires fresh runtime evidence and does not validate old failures
or guarantee available hosted capacity.

Independent eligibility removes the former Core-to-Phone and
Recovery-to-serial-iPad scheduling waits; it does not reserve runners. GitHub's
[documented macOS concurrency limits](https://docs.github.com/en/actions/reference/limits#job-concurrency-limits-for-github-hosted-runners)
are five for standard Free, Pro and Team plans and fifty for Enterprise. Actual
account limits and other workflows share that capacity, including Swift CodeQL
and separate Batch/Biometrics qualification. Jobs may queue, so the largest
individual job limit of 113 minutes is not a completion-time guarantee.
Per-job native tests remain serial, with unchanged timeouts, owned-process
cleanup, `!cancelled()` conditions and the final gate's four result checks.

A retry used for complete qualification must run the full CI workflow and
verify all six fresh jobs in the same attempt. Retrying only failed jobs no
longer reruns independent guidance jobs through the removed dependency edges;
copied or earlier successful records are not fresh native evidence.

The hosted Intel Phone guidance profile uses a 75-minute integration step within
that 95-minute job. Its bootstrap is bounded by 1,480 seconds (1,440 work,
30 cleanup and ten receipt), including a 300-second post-preparation warm-boot
command and a 1,080-second combined preparation command. Arm retains 1,080 seconds
of work, a 960-second preparation command and its 180-second warm-boot cap.
Both preparation commands retain the 180-second native allowance. The Intel
increase addresses an outer command timeout before the native allowance elapsed;
it does not change native assertions or guarantee completion. All commands share
the original work deadline and must clip to it, including the later warm boot.
The nine required native case allowances total 2,700 seconds, and 320 seconds remain for
selection, generation, main build/session startup and result finalization. This
is an allocation policy rather than a measured worst-case guarantee. Only the
three short cases that timed out and English guidance receive the explicit
Phone allowances; ordinary runs, Core, ARM and dedicated iPad limits stay intact.
All assertions, diagnostic captures and app termination remain required; see
[the release qualification policy](github-releases.md) for selection and evidence.

In [Core run 41877246834](https://github.com/4alvit/travel-documents-ios/actions/runs/41877246834/job/126739897092),
the English purchase-failure case exceeded its 180-second allowance while
finishing the Free quota check and diagnostic captures. The trace continued to
191 seconds, but that is not a clean pass. The following Russian case had a
launch timeout and XCTest restarted the runner; the 35-minute job limit later
cancelled the incomplete cohort. The trace does not establish that the first
timeout caused the launch failure. The three failure-alert scenarios now request
240 seconds in their shared helper. Both alert cycles, postconditions, Free
quota checks, PNG/AX captures and teardown remain required; the ordinary
180-second default and Core's 480-second maximum are unchanged.

Core's integration step now has a separate 35-minute limit within the
75-minute job. The job envelope is checkout 2, toolchain 5, toolchain evidence 2,
selector checks 2, Verify 10, packaging 2, integration 35, cancellation grace 5,
raw evidence 3, optional failure extraction/upload 3/2, Simulator upload 2 and
finalization 2 minutes. Raw test evidence precedes optional failure extraction.
This is a bounded policy, not a predicted duration: the failed Intel run spent
6 minutes 45 seconds in Verify, about 8 minutes 28 seconds bootstrapping its
first native worker, and 28 minutes 8 seconds in the incomplete integration
step. No assertion or retry policy is changed, and new hosted results are
required to establish completion.


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
