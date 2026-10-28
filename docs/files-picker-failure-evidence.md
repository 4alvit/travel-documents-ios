# Files-picker failure evidence

The main CI job keeps its original test command, result and 35-minute deadline.
If that command fails, a diagnostic step reads the existing `Tests-*.xcresult`;
it does not launch Simulator, build, rerun a test, or alter any UI assertion.
The full xcresult upload remains available.

The adapter selects the failed Restore-entry case first. If Restore is absent
or passed, it selects a failed Import-cancellation case. Other failed cases do
not block Restore selection. It exports attachments for that one exact case
once and retains only the uniquely named screenshot and accessibility hierarchy
captured by the existing failed Files-navigation assertion. The pair must match
the actual device and test-plan configuration reported by this result bundle.
Manual `keepAlways` attachments may have `isAssociatedWithFailure: false`; the
receipt records that value and does not relabel it.

`xcresulttool` is resolved from the selected installed Xcode, hashed before use,
and checked before and after each invocation. The existing result bundle has a
strict complete manifest before and after decoding. The receipt binds the actual
checkout, run and attempt, relevant source hashes, bundle manifest, parsed test
tree, actual case/device/configuration and exact retained file hashes. This is
diagnostic provenance, not runtime or release acceptance.

The adapter has one fixed 120-second window: 100 seconds of work and 20 for
cleanup and the final receipt. Commands retain the existing owned-process
helper's eight-second stop reserve, clipped to the original remaining work
deadline. Resource scans also respect the current command's work deadline.
There is no retry, deadline reset, additional job or simulator worker. The
existing job deadline can preempt this diagnostic, particularly on cancellation;
successful extraction is not guaranteed.

New output is sampled against both 32 MiB logical and allocated bytes, 4,096
entries and depth 40, with an 8 GiB free-space floor. This is sampled accounting,
not an instantaneous quota. Each stdout/stderr log is at most 1 MiB, all logs
together at most 8 MiB. Input manifest content is limited to 512 MiB and 4,096
entries without copying the xcresult. Exported JSON is limited to 1 MiB, the
selected PNG to 8 MiB, AX to 2 MiB and public receipt to 16 KiB. Unknown schemas,
ambiguous cases or pairs, links, mismatched identities and incomplete process
cleanup fail closed. Temporary output is removed only after owned-process
reaping and group absence are established, within the original deadline.

The separate `TripDocket-files-picker-failure` artifact includes checkout/run/
attempt in its name and allows only `failure.png`, `failure-ax.txt` and
`evidence.json`. It excludes raw command logs, export directories, other
attachments, arbitrary workspace files and private process diagnostics. An
exclusive attempt directory prevents reusing earlier evidence. Diagnostic or
upload failure cannot change the original failing test step into success.

The existing UI tests use synthetic fixtures. A missing Files-navigation
assertion alone does not establish whether presentation or accessibility
selection failed. The selected pair supplies evidence for that distinction;
this packaging change does not claim to fix the UI failure.
