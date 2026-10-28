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
Xcode phase has at most 600 seconds including process stop; each test has 300.
The initial runtime discovery has a 120-second command cap: 112 seconds for
work and the existing 8-second stop reserve. A returned inventory at or after
its original command work deadline is rejected before parsing or selection.
This is a finite scheduling-policy change from 60 seconds; the earlier hosted
query timed out with no output at its 52-second work bound. That evidence does
not establish the cause or that 120 seconds would suffice. There is no retry,
warmup query, runtime fallback or download. The separate capability preparation
stage remains limited to 60 seconds.

The initial owned Files `launch` has a 120-second command cap: 112 seconds of
work and the existing 8-second stop reserve. This is a finite cold-start policy
allowance, changed from 60 seconds after two hosted attempts exhausted the old
52-second work window with no output; another attempt launched successfully in
30.44 seconds. The cause and whether 120 seconds suffices remain unestablished.
The required final Files `terminate` keeps its 60-second cap. The one exact owned Files
group-container lookup has a 60-second cap (52 seconds of work plus the same
8-second stop reserve), after a hosted query exhausted the prior 22-second work
window with zero output. This finite policy does not establish the cause or
guarantee completion. The export/restore AUT app and data container lookups
and all other default command caps remain 30 seconds. Global time,
ownership and cancellation checks can shorten or prevent any command. Files
termination is still attempted after an uncertain launch outcome when those
checks permit it; a secondary termination failure cannot replace the original
launch/provider failure. No command or Simulator creation is retried. Before spawning, work commands force one existing
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

The separate iPad guidance driver gives only its initial runtime query a
120-second wait timeout, increased from 60 after a zero-output initial query
timed out before any device or test was reached. This is a finite scheduling
policy, not a claim about the native service or a guarantee of success. It
rejects completion or JSON parsing at or after the effective wait deadline
before issuing the next command or selecting a device. There is no retry.
Its other defaults remain 30 seconds, with 1,440 seconds
of work and 180 seconds reserved for cleanup. Each command leaves up to 7 seconds
inside its phase budget for existing TERM/KILL handling. Stop receipts summarize
the existing poll, group probe and signal calls in four bounded slots; an EPERM
is a failure, and only ESRCH establishes group absence. A primary timeout remains
visible alongside secondary stop or receipt-write errors. These are cooperative
deadline checks between operations; they do not preempt a blocked OS syscall.
The effective initial wait is min(120, remaining work minus seven seconds);
the stop reserve is additional to that wait but stays inside the work budget.
Each extra second spent discovering runtimes reduces time available for later
build, EN and RU work; their configured caps and the cleanup deadline do not grow.

The first EN iPad XCTest command has a 600-second wait allowance instead of
450, to allow more time for initial test-runner startup. A recorded run finished
bootstrapping about 374 seconds after that command began and reached about
60 seconds of testcase progress before the old wait expired. This supports a
finite scheduling-policy proposal, not a guarantee that 600 seconds succeeds
or an explanation of the startup delay. No warmup, retry or runtime selection
change is added. RU keeps its existing 570-second wait allowance. Both exact
test methods, UI assertions, content-size settings and XCTest default180/max480
execution allowances remain unchanged.

These waits still fit inside the shared 1,440-second work deadline, with the
existing seven seconds reserved for each stop and 180 seconds for final cleanup.
They are upper bounds, not separately reserved time. At the recorded EN start
about 358 seconds into work, using all600 seconds would leave at most482 seconds
before evidence processing and RU preparation; the next wait has at most475
seconds after its stop reserve, and less if intervening work consumes time.
The unchanged global clamp may therefore shorten RU below570 seconds. Increasing
both cases is unsupported by this evidence because RU was not reached. A command
return still requires the original result/provenance validation before a case
can pass; partial testcase progress is not acceptance.

One complete resource sample has a fixed five-second cooperative allowance,
clipped to the overall work limit and any pending command's original work
deadline. It covers both free-space reads and the full output traversal; it is
never restarted within a sample. The next ordinary sample remains due one
second after a completed sample. This is an explicit scheduling policy change
from two seconds, while all byte, entry, depth, command, phase and cleanup limits
remain fixed. A failed hosted scan exceeded the old allowance after 328 complete
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
same complete five-second scan, with the same allocation, entry, depth, command,
cleanup and test-result checks. Compilation, linking, Debug settings and both
selected UI cases remain required. Other CI builds keep their existing settings.
This targets observed index-store traversal overhead; it does not establish
that every future filesystem or scheduler delay will fit the unchanged budget.

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
`validate` (including ordinary integration/StoreKit), `privacy_ipad`, new
`recovery`, then `CI gate`. Gate now requires all three jobs to succeed; no
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

The initial Files preparation treats one specific `simctl terminate` reply as
already stopped: exit 3 with the exact `NSPOSIXErrorDomain` code 3 diagnostic
that says `found nothing to terminate` for `com.apple.DocumentsApp`. This
classification applies only inside the current preparation after its successful
owned-device launch and group-container lookup. It requires the original owned
command process to be reaped, its process group confirmed absent, empty stdout,
and the complete matching stderr from the same bounded log file. The raw exit
code and diagnostic hash remain in `accepted_nonzero_exit`; the raw diagnostic
still follows the Files-only publication allowlist.

The command must still pass stop, stream closure, resource/finalization, receipt
and deadline checks. All other nonzero responses, permission errors and timeouts
fail. No command, retry or budget is added. Provider and folder identity checks,
export/restore assertions, final simulator cleanup and independent UI/pixel
review remain required. This handles the terminal response; it does not establish
why the Files application had stopped or claim that recovery tests passed.

The Files launch allowance does not extend the total work deadline. At the
observed prelaunch elapsed time of 132.3 seconds, 1,247.7 seconds remain before
the 1,380-second work limit. If launch/provider lookup/termination consume their
full 120/60/60-second caps, only 1,007.7 seconds remain for export, restore and
evidence processing. The two 600-second phase caps therefore cannot both be
consumed in full, even before parser/comparator work. They remain maxima clipped
to the original remaining work time, not separately reserved allocations. Every
command still needs more than its 8-second stop reserve before admission and
again before spawn. Cleanup retains its original 120 seconds within the same
1,500-second executor limit; no retry or extra worker is introduced.

The iPad driver gives each existing fresh installed-AUT container lookup a
60-second wait, increased from the generic 30-second default after the second
locale's pre-test lookup timed out. This is a finite scheduling allowance, not
a demonstrated application bug or a guarantee of completion. It applies only
to `get_app_container <owned UUID> com.4alvit.tripfolio app` within `installed()`,
called before and after each of the two locale cases. Other default command
waits stay 30 seconds. The same fresh path, bundle identifier and complete
built-versus-installed byte comparison remain mandatory.

The four existing lookups can together consume up to 120 additional seconds
relative to the old per-call caps; those seconds come from the same 1,440-second
work budget. All waits remain clipped to work deadline minus the original
7-second stop reserve. The 180-second cleanup allowance, EN600/RU570 waits,
XCTest assertions and one-attempt behavior do not change. The observed single
EN XCTest pass does not establish that the RU case executed or passed.


Files provider readiness uses only the unused part of the original `files-group`
lookup work deadline (52 seconds within the 60-second Files group command cap).
The clock starts when that original command starts; readiness never receives
a renewed 52-second window after the lookup returns.
After one successful launch and group lookup, the wrapper pins the exact owned
group and observes only its `File Provider Storage` leaf. Initial leaf absence
may settle within that existing deadline; the wrapper never creates the provider,
relaunches Files, repeats a command, chooses another provider, or renews the clock.
A missing/replaced group, symlink, permission error, or disappearance after the
provider identity was observed fails immediately. The original work limit is
restored before the existing termination and cleanup paths. Bounded receipt
fields retain the failure stage, safe owned-relative filename, observation count,
and original deadline. This readiness policy does not establish that delayed
provider initialization caused any earlier hosted failure. UI export/restore
assertions, exclusive test-folder creation, other command caps, global budgets,
and cleanup proofs remain required.
