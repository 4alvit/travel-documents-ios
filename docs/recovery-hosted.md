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
The initial runtime discovery and the two owned Files preparation commands
(`launch` and the required final `terminate`) each have a 60-second command cap:
52 seconds for work and the existing 8-second stop reserve. Other default
command caps remain 30 seconds, including Files provider lookup. Global time,
ownership and cancellation checks can shorten or prevent any command. Files
termination is still attempted after an uncertain launch outcome when those
checks permit it; a secondary termination failure cannot replace the original
launch/provider failure. No command or Simulator creation is retried. Before spawning, work commands force one existing
resource scan after intent/log setup and recheck cancellation and the remaining
stop reserve. Ordinary sampled scans, scan bounds and the cleanup bypass do not
change. Command failures retain the primary cause plus separate log-close,
stdout-read, receipt, finalization and cap errors. Both log closes are attempted.
The capability validator rejects any such secondary failure even when the main
failure is the deliberately expected timeout.

A command receipt is a snapshot: a final write failure or overrun may be observed
after its contents were serialized. Inspect command records, top-level errors
and the actual failed CLI result together; an earlier receipt is not a success
signal. These source changes do not establish the cause or resolution of the
previous output-scan deadline or EPERM failures.

The separate iPad guidance driver gives only its initial runtime query a
60-second wait timeout. Its other defaults remain 30 seconds, with 1,440 seconds
of work and 180 seconds reserved for cleanup. Each command leaves up to 7 seconds
inside its phase budget for existing TERM/KILL handling. Stop receipts summarize
the existing poll, group probe and signal calls in four bounded slots; an EPERM
is a failure, and only ESRCH establishes group absence. A primary timeout remains
visible alongside secondary stop or receipt-write errors. These are cooperative
deadline checks between operations; they do not preempt a blocked OS syscall.

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
Xcode phase logs, capability evidence, xcresults, snapshots and attachments.
Raw root command logs, including host process listings, are excluded from the
start. Only the two known Xcode phase logs are moved into `PhaseLogs`; a failed
move can omit diagnostics but cannot expose a process listing. The tested source
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
