# Release evidence

This document records development and device evidence, including historical
results from [PR #1](https://github.com/4alvit/travel-documents-ios/pull/1).
For the current source/Simulator stage, use
[GitHub releases](https://github.com/4alvit/travel-documents-ios/releases) and
their exact-source acceptance records under the
[source/Simulator channel policy](github-releases.md). Live Apple distribution
and physical-device gates remain open. Historical failures below remain
attached to their original runs.

## Source/Simulator integration and qualification evidence

The matched Xcode 26.2 workflow and its native fixture-preparation phases define
a candidate validation path, not an acceptance record. Release acceptance still
requires complete CI and the ordinary Release smoke at the exact integrated
main commit, plus the required independent qualification reviews. Results from
different source trees cannot be combined into a passing candidate.

The separate [matched-core control](https://github.com/4alvit/travel-documents-ios/actions/runs/41395856175)
at `786555b` passed all 130 core/purchase cases with no skips. Its retained
Release package and results were independently checked, including explicit
empty XCTest warning and failure arrays using Xcode 27.1. The same workflow's
English guidance case failed: short text was accepted at the edge of an expanded
scroll viewport but was not fully covered by the inset reading viewport.
The geometry correction aligns these two checks without reducing text coverage
or changing action deadlines. Neither the passing core job nor the correction's
offline checks establish a successful integrated workflow.

Historical batch results distinguish setup success from completed import.
[The earlier control](https://github.com/4alvit/travel-documents-ios/actions/runs/41385834936)
passed Files selection but exhausted its former 300-second case allowance before
save/relaunch and byte verification completed. Later controls with host-created
fixtures and with native Save both failed after one valid Open action. Retained
application output records FileProvider bookmark-resolution failures before
selected URLs reached the app. The opaque provider item identifier was not
mapped to a particular file or folder; these observations do not establish an
application dismissal defect or prove that a compiler/runtime mismatch caused it.
The [matched native Save control](https://github.com/4alvit/travel-documents-ios/actions/runs/41395661985)
also failed at that boundary, so native saving and matching the SDK alone did not
establish successful import.

A subsequent four-phase control replaced the remaining host-created fixture
folder with native New Folder, followed by native Save. Its required evidence was
**one Files preparation case + one native folder case + one native seed case +
two main cases**, in four separate original result bundles. Every phase needs
exact-source/device, result, immutable-manifest and independent warning review;
folder/seed phases additionally require destination identity and complete-byte
checks. No passing outcome for this control is asserted here. A later accepted
record must identify its exact run/attempt and final source, retain functional
and visual evidence, and preserve the earlier failed controls as failures.

The [first native-folder run](https://github.com/4alvit/travel-documents-ios/actions/runs/41398340866)
passed Files preparation but stopped before Done: the keyboard's first-use
swipe-typing introduction covered that control. Screenshots and native
accessibility hit checks confirmed the obstruction. A subsequent correction
acknowledged only that exact introduction once and verified its dismissal and
the unchanged folder name. The [following run](https://github.com/4alvit/travel-documents-ios/actions/runs/41400000817)
delivered the single Done key event, but the editor and keyboard remained
active. Neither failed run executed native seeding or the main import tests.
The next control replaced Done with one tap in a verified empty part of the
Files grid, retaining the editor-dismissal, exact-destination and host
empty-folder checks. Its [first run](https://github.com/4alvit/travel-documents-ios/actions/runs/41403200979)
failed before typing: a remote Files snapshot took about 29 seconds, and the
retained state showed an untitled folder without an editor. The [same-source
repeat](https://github.com/4alvit/travel-documents-ios/actions/runs/41405086602)
failed earlier, with the export share sheet still visible after Save to Files.
Neither run reached the new end-editing action, native seed or main import.

A later control removed that extra fixture-folder creation. After real
Files preparation, native Save places two synthetic PDFs directly in the
verified empty provider root of an exclusively owned Simulator. It requires
three distinct bundles: one preparation case, one native-seed case, and the
two main purchase/import cases. Exact provider identity, complete source and
imported bytes, visual review, and deletion of only the owned Simulator remain
required. The driver never removes the provider root itself. This simplifies
the fixture setup; it does not establish the cause of earlier Files errors or
assert that the new control has passed.

The [native-root control](https://github.com/4alvit/travel-documents-ios/actions/runs/41408007587)
at `7cb01f1` passed Files preparation, native saving of both PDFs and the hosted
purchase prerequisite. The batch case failed after Open: retained system output
again reported a FileProvider resolution failure and an empty URL array. Both
source PDFs remained intact and owned-device cleanup passed. Seed and main used
different build directories and installed app bundle paths. The next control uses the same prepared
products for both phases, retaining all three result bundles and all byte,
identity, deadline and cleanup checks. This tests a remaining lifecycle boundary;
it does not establish that the boundary caused the failure.

In the same candidate's [CI](https://github.com/4alvit/travel-documents-ios/actions/runs/41408003034),
Recovery passed all three phases and independent original-byte and cleanup checks.
Core passed 129 of 130 cases. The no-diagnostics purchase test stopped before its
first purchase because the open Pro screen still showed a disabled price button
and a loading indicator. Retained logs did not identify the suspended StoreKit
operation. Bounded Debug Simulator stdout observations now distinguish load
invocations and their entitlement/catalog await boundaries. They add no retries,
UI diagnostic values or Release behavior, and do not relax the 15-second test
condition. The [subsequent Core run](https://github.com/4alvit/travel-documents-ios/actions/runs/41411424834/job/125165114095)
at `3b467b8` passed all 130 iOS cases, including that purchase test, and 38 package
cases. This successful observation does not establish that diagnostic logging
fixed the earlier load stall.

The [same-product batch control](https://github.com/4alvit/travel-documents-ios/actions/runs/41411434684)
at `3b467b8` passed Files preparation, native saving of both PDFs and the hosted
purchase prerequisite. All four compiled products retained identical bytes and
Unix modes across the three observations; installed app content matched them.
Xcode still changed the installed app and data container paths, so using the
same products did not eliminate that lifecycle boundary. The data directory's
recorded inode remained the same; path changes alone do not establish data loss.

This attempt failed before Files selection: after the sole Unlock tap, Xcode's
payment service returned `AMSErrorDomain` code 10, `Presentation failed`, wrapped
in `ASDErrorDomain` code 5115. The app displayed its purchase-failure alert.
Both catalog loads had completed; no purchase transaction or batch import was
accepted. The original PDFs remained intact and all owned processes and the
Simulator were cleaned up.

The next candidate supplied StoreKit's SwiftUI environment `PurchaseAction`
to the existing purchase manager. Its [Xcode 16.4 Recovery build](https://github.com/4alvit/travel-documents-ios/actions/runs/41415005661/job/125176604610)
at `f507c1c` failed before XCTest: that SDK's nonisolated async method rejected
the main-actor-isolated, non-Sendable action. No recovery case executed. All
owned process groups stopped and the complete Simulator inventory was restored.
A successful local compile with a newer SDK did not establish this compatibility.

The Pro screen instead retains a weak reference to its own attached UIKit
controller. Purchases use that controller on iOS 18.2 and later, or its attached
window scene on iOS 17 through 18.1. These are Apple's
[explicit-context purchase APIs](https://developer.apple.com/documentation/storekit/product/purchase(confirmin:options:)-6dj6y).
Missing, inactive or dismissing presentation context fails through the existing
purchase-error path; there is no global scene lookup or contextless fallback.
The manager retains its busy guard, verified-entitlement checks, transaction
finishing and error handling; non-UI hosted calls retain their existing default.
No unsafe Sendable conformance or concurrency-check suppression is added.
The earlier payment-service error did not establish a missing scene as its
precise cause. This correction still requires fresh native validation; it adds
no automatic purchase retry and does not relax payment or Files assertions.

The [following batch run](https://github.com/4alvit/travel-documents-ios/actions/runs/41416599960)
at `afd2dc1` passed preparation, native seeding and the hosted purchase prerequisite.
The UI completed the local Xcode purchase and reached Files with both PDFs
selected. After the single Open action, FileProvider again reported code -1005
with resolver code -1012, then attempted an empty selected-URL callback. The
app's retained importer state still recorded no callback. All source PDFs and
compiled-product bytes remained unchanged; installed container paths changed
between the separate invocations. This establishes the observed failure boundary,
not a causal proof about installation or the opaque provider item identifier.

The C3 control kept the hosted prerequisite, native seed and real import as
three separate XCTest cases in one invocation, after separate Files preparation.
A checkpoint at import entry requires the seed's actual pass marker, a record
from the same UI test process, and a host comparison of both complete destination
files before import actions begin. Its evidence layout was one preparation
case plus one three-case bundle; no separate seed result was fabricated.

The [C3 Arm run](https://github.com/4alvit/travel-documents-ios/actions/runs/41426202230)
passed preparation and the hosted purchase prerequisite. The first native PDF
seed then reached an incomplete Save to Files screen: On My iPhone and the
filename were visible, but its provider root, file grid and Save action were
absent. Application output recorded a SaveToFiles hosted-scene action timeout.
The seed failed after 65.552 seconds; the import case correctly rejected the
missing successful producer before requesting a checkpoint or importing files.
This did not exercise the seed-to-import continuity hypothesis and does not
establish the cause of the native scene timeout.

The next controlled run moves the hosted prerequisite before Files preparation
in the first invocation, followed by native seed and real import in one
uninterrupted UI-test invocation. Both original bundles must contain exactly
two passes, with all four cases, cross-phase order and the host checkpoint
verified. The three functional methods in the public batch receipt span both
bundles; preparation remains an additional required case. This ordering change
preserves the native actions, case allowances, process ownership and work/cleanup
budgets. It is not a demonstrated fix; a fresh complete capture and independent
review are still required.

An earlier main-branch CI stopped in its subprocess capability probe before
creating a Simulator or running recovery tests. The command woke after its work
deadline and entered another resource scan, so the expected command timeout was
misclassified as a scan deadline failure. The loop now checks the unchanged work
deadline before draining output or scanning resources. The eight-second stop
reserve, genuine scan failures and complete process-cleanup requirements remain.
Offline boundary tests cover both an exact-deadline wakeup and an oversleep; they
do not substitute for a successful hosted recovery run.

## Release preparation — 1 November 2026

The reviewed PR head `45521e62198e113820a54af1bb84f6bf97b51337` passed all six
jobs in [CI 41333949690](https://github.com/4alvit/travel-documents-ios/actions/runs/41333949690).
Independent source and security reviews found no confirmed actionable findings.
The merge commit `3b223e483879df48fd9c12000ba532700e83eba1` has the same source tree,
`931c603dd8d128153cbd110a9e01220ec4c1f035`.

The subsequent [main CI 41346633231](https://github.com/4alvit/travel-documents-ios/actions/runs/41346633231)
failed recovery, English iPad guidance and the phone Files import layout case.
These newer failures block promotion;
the prior successful run does not replace them. Recovery's resource traversal
encountered a disappearing regular file inside an actively rebuilt test product
and stopped the export command before XCTest. The English guidance case retained
its website confirmation after one Cancel tap. Its screenshots and event record
do not distinguish an undelivered action from failed presentation dismissal.
Neither result establishes an application data-loss defect or a private Apple
framework cause. Fixes and diagnostic additions require fresh exact-source CI.

The phone failure was an early 30-second navigation wait inside a helper with
an existing 40-second total readiness budget. The retained video shows a blank
Files sheet through that early cutoff, followed by the real navigation and
Cancel before the total budget expired. The helper now observes both required
elements within one monotonic 40-second deadline, rejecting observations that
finish after it. It retains the unique enabled/hittable typed Cancel, one tap,
navigation dismissal and return-to-presenter checks.

The two affected Import/Restore layout cases then passed locally on one fresh
iOS 27.0 (24A434) Simulator using Xcode 27.1 (27A9275), SDK 27.1. Files was not
prewarmed. Readiness took 5.385 and 5.057 seconds respectively; the complete
XCTest result contains two passes, no failures/skips and no runtime warnings.
Source hashes were unchanged, the owned device was removed, and the full final
device inventory matched its baseline. This is Debug fixture-based layout
validation of the follow-up change, not release or authentication acceptance.

The recovery monitor now permits one complete rescan after a confirmed missing
regular build-product leaf while its owned writer is active; all time, byte and
entry limits still apply. Opt-in Debug Simulator guidance values distinguish
received Cancel actions, cleared selection and completed dismissal. Localization
attachments log the screenshot request and return boundaries, without dropping
an attachment, assertion or timeout. These observations are not substitutes for
successful native tests, and do not claim a root cause for the historical
Files inline-editor or screenshot-service failures in issues #3 and #4.

The guidance test now attaches the complete bounded diagnostic values separately:
XCTest's hierarchy description truncates them. A local English iPad execution
passed its existing assertions in 178.215 seconds and recorded all four Cancel
actions, cleared selections and completed dismissals. The post-cancel images
show the guidance page with the confirmation closed. Its owned device was
removed and the full final inventory matched the baseline. This focused local
Debug run does not replace final-candidate hosted or Release qualification.

Hosted preflight established two Xcode 26.2 (17C52) compatibility problems:
an explicit schema 0.4.0 request is unsupported, and the default summary-schema
documentation is malformed. The latter was captured in
[CI 41352317506](https://github.com/4alvit/travel-documents-ios/actions/runs/41352317506),
artifact `13100939614`. Its schema also omits the documented warning field;
that omission alone does not establish what an actual result contains.

The revised preflight recognizes the exact producer documentation without
loosening result JSON parsing. Hosted qualification captures native results,
source/product identities and cleanup evidence with status
`captured_pending_review`. It never claims release acceptance. An independent
Xcode 27.1 reader must verify the same retained result bundle, all expected
cases and explicit empty warning/failure arrays, followed by visual and
original-byte review, before the separate operator receipt may pass. The
[channel policy](github-releases.md) specifies this boundary. No pending or
failed run is promoted by this compatibility change.

Subsequent hosted guidance runs exposed additional failures. The `334d993`
English iPad run completed all four Cancel transitions but exceeded its
six-minute XCTest allowance; its finalized result is failed. The `8b3e5ec`
English iPad run failed earlier: a correctly targeted Settings entry tap did
not open guidance, with no delayed transition in the retained video. Neither
result is accepted, and the evidence does not establish a private framework
root cause.

The next iPad candidate pins Xcode 26.2 (17C52) and selects only an available
runtime matching its Simulator SDK. This keeps iPadOS 26.2 coverage while
changing the compiler, linked SDK and XCTest framework from the previous
Xcode 16.4 runs. It is a controlled environment change requiring fresh native
and visual validation; it does not prove the older pairing was unsupported.
All case assertions and time allowances remain in place. CI concurrency is
scoped by commit so a new candidate can start while older owned cleanup
finishes, without cancelling active work.

## Accepted executable baseline and ordinary Release launch — 25 October 2026

The accepted executable baseline is `674cbb6`. [CI 40169628635](https://github.com/4alvit/travel-documents-ios/actions/runs/40169628635)
passed 38 core tests, 95 phone tests with zero failures and seven expected opt-in
skips, and two separately selected iPad guidance tests. All seven StoreKit cases
passed. The tested merge `5cb2d0a9` has the same tree as that source commit.
Earlier failures remain historical evidence. Later documentation or source
commits require their own checks; these results are not relabelled as new runs.

The reviewed source head is `674cbb6cf655242838686fc6f0a50b6c2eff0492`;
the binary was built from merge `5cb2d0a9f0a5593c85bda0fe7e20b714731a909a`.
Both have tree `92013978c35e79058f65c82e77ae656aae9ac590`.
The Simulator ZIP SHA-256 is
`f232351349677cb9a4ea5caa779f6941c4440e8892e2990564d4afc96e83cc1a`.
Source and installed payload checks covered all 22 app files.

The complete smoke attempt for one ordinary launch of that unchanged Release
ZIP took 73.246 seconds, including setup, installation, observation and cleanup;
this is not a measurement of app startup latency.
Three actual screenshots show the app locked/authenticating at approximately
2 seconds, then the system passcode prompt at 10 and 30 seconds. The 22 commands
completed within their limits, and the fresh owned simulator was deleted with
baseline/final inventories equal. Independent execution and pixel review were
accepted for this narrow scope. Root acceptance SHA-256:
`5774577defa2b2019932c2372dde70cb7f1bc958beaf64f803e2754393bca7c7`.
The original receipt remains unchanged; later acceptance is a separate record.

No credential was entered. This is not evidence of successful authentication,
full unlocked workflows, real purchases, continuous liveness, physical devices,
TestFlight or App Store acceptance. Whole-device allocation was not measured;
the original allocation requirement remains incomplete. Earlier unsuccessful
allocation-limited attempts remain failures and are not replaced by this run.

## Bundled privacy and support — 25 October 2026

Settings starts with a free English/Russian privacy and support page. Its text
is bundled; it has no library or purchase dependency and does not fetch web
content. The existing app-wide StoreKit startup task is unchanged. External
buttons show a fixed public GitHub destination and require a separate explicit
Open action. Cancel stays in the app. The published documents are explicitly
preview drafts pinned to the accepted `1391b307` commit, not final store policies.

All six distinct URLs returned HTTP 200 anonymously without redirects. The
three targeted resource/URL/standalone-host tests passed locally. The UI suite
checks normal English and maximum-size Russian text, full scroll coverage,
Free access, four confirmation/cancellation paths and return navigation.
Initial development runs exposed excessive test-driver AX traversal and a
Settings entry too far below large text; the driver was simplified and the
entry moved to the first section. Those initial failed runs are retained;
only later passing results qualify the revised implementation.

The published `ed32af0` [CI run](https://github.com/4alvit/travel-documents-ios/actions/runs/40161817332)
was cancelled at the job's 25-minute limit. Core 38 tests, Release verification
and its 22-file metadata scan passed. The logs show 82 hosted tests passed,
including the three guidance tests and all seven StoreKit cases. UI logs show
six passes, one failure, one expected opt-in skip, two incomplete guidance cases
and ten cases not started. The uploaded result bundle was not finalized, so
these are log-derived observations, not complete xcresult totals.

The existing complete-backup-warning case crossed its 120-second allowance
before completing its assertions around 125 seconds. English guidance crossed
240 seconds before reaching the final return around 269 seconds. Russian
maximum-type guidance was interrupted partway through the text. Neither a
post-timeout attachment nor a partial walkthrough counts as a passing test.
The follow-up test changes preserve full text/frame coverage and explicit
cancellation checks, use larger overlapping slices for tall paragraphs, and
allow 180 seconds for the backup-warning case and 360 for each guidance case.
The ordinary default stays 180 seconds; the runner ceiling is 360 and the CI job
budget is 35 minutes. These are finite validation budgets, not accepted runtime
results; the current PR checks must establish the revised result.

The subsequent `3540791` [CI run](https://github.com/4alvit/travel-documents-ios/actions/runs/40163641612)
finished with a finalized result bundle: 102 unique tests, 94 passed, one failed
and seven expected opt-in skips. The only failure was Russian maximum-type
guidance exceeding 360 seconds. English guidance passed in 220.55 seconds;
the complete-backup-warning case passed in 63.46 seconds, and all three
guidance unit tests passed. Russian guidance reached its final return and
attachments around 396.64 seconds, after its timeout. Its observed text slices
covered all 24 blocks with overlap, but post-timeout coverage is diagnostic
evidence and does not turn the failed case into a pass.

Only that Russian maximum-type case now requests 480 seconds, with a matching
runner ceiling. English guidance remains at 360 seconds, the ordinary default
at 180 seconds, and the job at 35 minutes. The preceding job took 30m55s. The
additional case margin is based on observed completion time; no assertion,
scenario, attachment, retry policy or unrelated case allowance changed. At that stage the
new published revision still required its own successful CI result; the later
accepted baseline is recorded above.

Use the [current PR checks](https://github.com/4alvit/travel-documents-ios/pull/1/checks)
for validation of the published revision. No physical-device, VoiceOver speech,
actual external-app handoff, network-denial or live-purchase acceptance is
inferred from this feature's tests. Source review and bundled-resource checks
support the page's offline design, not a claim that the entire app makes zero
network requests. The earlier release package remains tied to its own source;
these changes do not silently update or relabel that binary.

## Accepted hosted baseline — 25 October 2026

At signed `1391b30776cd6ea48eab97cd92d4b098ff8f9474`, ordinary hosted
[CI 40159228298](https://github.com/4alvit/travel-documents-ios/actions/runs/40159228298)
passed: core **38/38**, unsigned Release build and metadata scan, simulator
**90 passed / 0 failed / 7 expected opt-in skips** (97 unique cases).
All seven StoreKit and eleven ordinary UI cases passed. Tested merge tree
`5218e837e45cd6464562526c3fbe8de5abd0ba9b` matched the published head tree.
This closes the earlier hosted StoreKit fixture acceptance gap, without proving
live purchases, physical-device behavior or private StoreKit implementation.
Later pushes require their own ordinary CI; use the PR checks for current status.

## Historical publication baseline — 25 October 2026

The public repository is provisioned and [draft PR #1](https://github.com/4alvit/travel-documents-ios/pull/1)
contains the development preview. The completed hosted baseline at
`ddd92406f630994a631c09fa773957e271496ca6` is
[CI run 40155191653](https://github.com/4alvit/travel-documents-ios/actions/runs/40155191653):
core **38/38 passed**, unsigned Release build and distribution-metadata scan
passed, and the simulator result bundle reports **97 tests: 86 passed,
4 failed, 7 expected opt-in skips**. All 11 ordinary UI cases passed.

The four failures are ordinary StoreKit purchases in the price/sync-error,
refund, unverified-purchase and purchase/restore scenarios. Their verified
synthetic Xcode preflights passed, but the local Xcode server cancelled the app's
purchase calls. This is distinct from the historical cold-runtime routing
failure below. Ask to Buy passed; the real notification callback test passed in
the unauthorized branch, without establishing notification scheduling or delivery.

The job was cancelled near its 25-minute limit, after the complete test result
reported failure. About 11 minutes elapsed between the build and the first
XCTest. Neither that startup delay nor the purchase-cancellation cause is
established. A local run of all 17 PlatformTests at the same source passed on
the configured iOS 27 simulator; it does not replace hosted acceptance.

The following test-fixture change reapplies the checked-in StoreKit defaults
after awaited fault cleanup and records public state around that reset. It
retains verified-entitlement guards and all purchase assertions. This is a
compatibility candidate, not a proven explanation of private StoreKit behavior.
The accepted hosted baseline above supersedes this failed fixture candidate.
Fresh independent PR approval and the device/distribution gates below remain
required before release.

The current provisional consumer brand is **TripDocket**, with planned storefront
title **TripDocket: Travel Documents**. The earlier evidence below was produced
under the **Tripfolio** brand and remains tied to its original source commits.
Technical project, scheme, bundle, SKU and storage identifiers remain unchanged.
App Store Connect name reservation and trademark clearance are not confirmed.

## English and Russian localization — 21 October 2026

The application follows the first supported system/per-app language, falling
back to English. App catalogs contain 202 UI and 68 service entries; the core
resource bundle has 25 presentation entries. Both languages also include four
InfoPlist entries and two generic deferred-notification entries. The app has no
custom language selector. Regional formats remain independent of interface
language; persisted names, original files, schema, IDs and StoreKit SKU stay
unchanged. Prices still come from `Product.displayPrice`.

- Core: **38/38 passed**, including six actual resource, language-selection and
  schema-preservation tests.
- Integrated iPhone: **71/71 passed**, zero failures/skips: 21 AppModel, 14 batch,
  16 reminder-lifecycle, 10 existing reminder/date and 10 localization checks.
  Localization includes Russian 0/1/2/5/21 and second-argument plural rules,
  English with a Russian region, Russian with a US region, fallback/permissions,
  and real Vision recognition of synthetic Russian and English text.
- Targeted UI: **3/3 passed on each of iPhone and iPad**, zero failures/skips.
  Four ordinary launches use `ru-RU,en-US`, `en-GB,ru-RU`, `fr-FR,ru-RU,en-US`
  and `fr-FR`, resolving to Russian, English, Russian and English. The ordinary
  launch case omits Debug authentication bypass and leaves the app locked.
  Fixture cases use Debug bypass and synthetic data to check readiness, import
  cancellation, Pro dismissal and complete Russian backup-warning coverage at
  maximum Dynamic Type. No purchase, restore, Files selection or confirmed
  export is performed by this suite.
- Initial pixel review found a clipped Russian import title on iPhone; the
  initial iPad run passed 2/3 and detected an export button extending 46 points
  below its action pane at maximum type. A dedicated shorter import heading
  and the shorter action 'Экспорт' address those two text-layout defects.
  The intermediate 'Экспорт…' caption still wrapped on iPad; its separate failed
  run is retained in the test index.
  The complete warning text remains unchanged. The final 3/3 runs above follow
  these fixes, including a corrected hidden-content AX sentinel.
- Independent visual review of all 36 final iPhone and 28 iPad screenshots and
  paired accessibility hierarchies confirms the complete import heading,
  export action and overlapping warning text. At maximum type, the iPhone
  export action wraps onto two fully visible lines; iPad uses one line.
  Native authentication overlays limit what can
  be concluded from ordinary-launch pixels; lock-state assertions also use AX.
- Independent source/resource review found no actionable issues. An independent
  native Foundation probe passed 263 assertions across all eight UI plural
  templates, both languages and US/Russian regions. This probe is distinct from
  the app and UI test counts above.

Runtime source inventories are frozen before/after each run. Model, service,
core, localization-helper and AppTests inputs are unchanged. The later UI delta
adds the UI suite/project reference, gives the import sheet a shorter Russian
heading and shortens the Russian export action. The final full UI suite reruns
both devices after those presentation-only changes. Exact inputs and result
bundles are recorded in `automated-checks.json`. Earlier payment, privacy
transition and broad UI results below retain their original source attribution.

Notifications now use `NSString.localizedUserNotificationString` and main-app
Localizable keys. Actual delivery after changing language is still a manual
check. These simulator checks do not establish physical-device authentication,
VoiceOver correctness, camera OCR quality or App Store distribution readiness.

To repeat only the new language checks on an available simulator, use the normal
project/scheme and destination options with
`-only-testing:TripfolioTests/LocalizationTests`
`-only-testing:TripfolioUITests/LocalizationUITests`
and `-maximum-test-execution-time-allowance 240`.

## Cache and reminder edge cases — 21 October 2026

Signed fix `37f8f08a3890041989e7210a4b428e2b5eca4ab1` makes startup cleanup
of disposable presentation copies best-effort. A cleanup failure no longer
prevents opening a valid persistent library. Preview and export still report
errors if their protected temporary destination cannot be written.

Signed fix `6d8cbc586cb676e15a9e2e703c7a4bc33bdc219d` rejects reminder work
whose document, request or task changed while awaiting permission or an add.
Deletion and restore remove accepted reminders immediately and clean up late
adds before newer valid requests proceed. Losing Pro alone does not remove an
already accepted reminder. Notification text remains generic.

- Integrated iPhone: **61/61 passed**, zero failures/skips, in
  `build/EdgeHardening-f0cfe49b-a1aa-48aa-93c5-26839db5cbdf/Tests.xcresult`.
  Counts: AppModel 21, BatchImport 14, new reminder lifecycle 16 and existing
  reminder/date checks 10. Runtime: iPhone 17 Pro, arm64, iOS 27.0 (24A434),
  UUID `37D49EA4-2641-446F-81DB-1907F6EEFA2D`; Xcode 27.0 (27A266a).
  Test execution was 16:40:33–16:41:07 UTC; no UI or StoreKit cases were selected.
- The cache regression uses a real, nonempty private directory with POSIX 0500
  permissions and requires deletion to actually fail. It checks loading,
  complete-original readiness and recovery despite that failure; preview/export
  fail honestly until permission repair, then succeed on the same model.
  A new repository restores the exported exact original bytes.
- Lifecycle tests hold permission/add completions to exercise deletion, edits,
  identical-content restore, replacement requests, cancellation while queued,
  late completion and partial-add failure. The final 16 cases also passed in an
  isolated native host run. Removing cancellation forwarding made the dedicated
  negative-control test fail with three assertions on the earlier 14-case
  candidate; this is not represented as a mutation of the final 16-case suite.
- The iOS run used a frozen working candidate based on `87fac0f`, with identical
  71-file inventories before and after. Its seven changed app/test/project files
  were committed without alteration in the two fixes above. Three independent
  scoped reviews found no remaining actionable finding; see the file hashes and
  relative test command in `automated-checks.json`.

These controlled notification-client tests establish in-process ordering, not
actual OS delivery or physical-device permission behavior. Pending system calls
must eventually complete for their queue to progress. The actual Files/StoreKit
UI evidence below remains tied to its earlier sources and was not rerun for
this change. Cold-device, physical-device and distribution gates remain open.

## Import cancellation and batch follow-up — 21 October 2026

Signed bugfix `42e636855f32405d6df0fb9d068d3d558d60e877` rechecks free
capacity after asynchronous source reading and propagates cancellation before
submitting an import or replacement restore. A held-reader regression reproduced
a ninth document being added after Pro loss; two cancellation regressions
reproduced writes after cancellation. The unchanged failure cases passed after
the fix. These use controlled entitlement/read dependencies with the real
repository; they do not simulate or certify actual StoreKit revocation.

Signed feature `fa21d26750a7e536446afd875aa28da7966253a2` adds Pro import
of 1–10 files, bounded preparation, explicit per-file metadata review, and one
atomic batch publication. Tests exercise invalid input, aggregate capacity,
cancellation, stale callbacks, review invalidation, entitlement loss, storage
failure/retry and exact original recovery. Independent source reviews of both
commits found no remaining confirmed issues. UI and generated-project changes
are recorded in the subsequent verification commit.

- Core: **32/32 passed**, zero failures, `swift test`.
- Integrated iPhone: **36/36 passed**, zero failures/skips,
  `build/Batch-Model-Warning-Phone.xcresult`: AppModel 20, BatchImport 14,
  maximum-type complete backup warning/cancellation 1, and restore Files
  cancellation/tab navigation 1. Destination is the existing iPhone 17 Pro
  simulator, iOS 27.0 (24A434), UUID `37D49EA4-2641-446F-81DB-1907F6EEFA2D`.
- The warning check requires uninterrupted coverage of the exact full warning
  using overlapping portions of its actual native scroll pane, plus reachable
  export and cancellation controls. Six phone captures cover all 1044.67 points
  of the warning body. It never taps the export action.
- A preceding mixed run passed all 20 AppModel cases and covered the warning,
  but failed later while waiting for Files Cancel. Its screenshot had no usable
  Cancel button. The tests were separated and given a distinct bounded Files
  presentation wait before control discovery; the full subsequent run passed.
  An earlier XCTest selector crash occurred before warning coverage. Neither
  failed attempt is counted as a passing suite.

These maximum-type checks use the synthetic library and Debug authentication
bypass. They establish selected simulator layout/navigation behavior, not
VoiceOver, physical biometrics or full device acceptance. The batch model tests
establish model retention across an unchanged refresh, not normal-authentication
UI teardown. Physical batch/privacy checks remain explicitly pending.

### Complete warning and export-action visibility

The initial iPad follow-up passed both warning and restore/navigation cases in
`build/Batch-Warning-iPad.xcresult`, but independent screenshot review found the
old export caption extended 46 points below its action pane. Signed fix
`a01542df63f6d0601cbafcce8dd82f45705c0189` shortens both packet and backup
actions to `Export…`. The action still opens the explicit destination picker.
The strengthened test requires the entire button inside its pane, dialog and
window both before and after scrolling the full warning body.

- `build/Final-Export-Warning-Phone.xcresult`: **1/1 passed**, zero skips.
  Thirteen overlapping captures cover all 1798.67 points of the warning text
  in this narrower native layout. The complete two-line action fits its pane.
- `build/Final-Export-Warning-iPad.xcresult`: **1/1 passed**, zero skips.
  Seven overlapping captures cover all 1450.5 points of warning text. The
  108.5-point-tall action fits fully inside its 202.5-point pane.

Independent review checked all 26 screenshots and their accessibility trees.
Both runs dismiss through the native popover dismissal region; neither performs
an export. App `Views.swift` and `AccessibilityUITests.swift` match the signed
fix exactly. These runs used a working candidate that also contained the later
batch UI test and generated project references, not a pristine whole-commit
checkout. The final verification commit reconciles those files.

### Real Files batch acceptance

The complete strict batch scenario passed **1/1, zero failures or skips**, in
`build/BatchSimulator-1275fb8d-d06f-4ab8-be19-5b07ace862b5/Tests.xcresult`
on the same configured iPhone 17 Pro simulator. This uses real Files provider
selection and an actual local Xcode StoreKit purchase; it does not inject a Pro
flag or write directly to the app library. The source inventory was identical
before and after the run. The tested candidate contained the generated project
references and new test/driver before their final verification commit.

The run checks the free Pro gate, a positively identified Xcode purchase sheet,
one local product transaction, two selected PDFs, disabled Save at zero and one
confirmation, and enabled Save only after both confirmations. It changes title,
type and person, explicitly enables an expiry date for the second document, then
edits an already confirmed title and requires confirmation again. Save persists
both documents alongside the existing demo. After a relaunch without reset,
all three complete originals verify and both new PDF previews open.

A separate read-only audit compared actual stored bytes with retained source
fixtures and checked the full catalog, references and metadata. The ticket is
713 bytes (SHA-256 `4fb43e6f3ff91e8d6eaea5a92986c2f8372fe7bb7cac9c38809abd78a06f2817`);
the insurance is 716 bytes
(`0d32682ac225ba276b506fc648b3e7dd4b27993f847751373532847cb826c08b`).
The demo's full document model and bytes, trip and person match a contemporaneous
baseline captured before import. The two original Files sources also retained
their hashes before the driver removed its own temporary fixture folder.
Insurance expiry is stored as the explicitly selected 21 October 2026 civil day
at UTC noon. No OCR date inference is claimed.

Earlier strict attempts failed in test selectors for native Files navigation,
picker button types, already selected options, text selection and the nested
switch/date control. Their failed results remain recorded; no passing result is
inferred from them. An initial driver preflight rejected a toolchain-specific
`simctl` group lookup before seeding or buying; the driver now parses the exact
group from the supported group listing. Independent review also caught a driver
cleanup defect: descendants could outlive the xcodebuild leader. An isolated
real-process regression failed both cases before the fix and passed both after;
the final accepted run uses that fix.

The test is opt-in via `scripts/test-batch-simulator.py` and uses Debug
authentication bypass. It does not establish cold-device StoreKit, batch draft
privacy under real authentication, physical-device behavior or live sales.
Failure atomicity is covered by the core tests, not inferred from this successful
UI save. Independent inspection of all 15 screenshots and their accessibility
trees confirmed both distinct, readable PDF pages after relaunch, the review
gating and later reconfirmation, with no findings. The first two-of-two state
before editing is supported by the passed assertion and log; only the final
reconfirmed two-of-two state has its own screenshot. Some explanatory text and
the lower saved-document row extend beyond individual captures, so complete
simultaneous visibility is not claimed. The `87fac0f` app, test, driver and
generated project files match all 26 recorded H source hashes in
automated-checks.json; later changes do not inherit that whole-source UI
acceptance.

## TripDocket consumer-name verification

- App/test source: `f3b56885a1bd7ae721764389a2a7490778d5a31b`.
- Result: **3/3 passed**, zero failures/skips, `build/TripDocketBrandUI.xcresult`.
- Run: 2026-10-21 02:51:23–02:53:12 UTC, including test setup.
- Destination: existing iPhone 17 Pro Simulator `37D49EA4-2641-446F-81DB-1907F6EEFA2D`,
  arm64, iOS 27.0 (24A434).
- Selected suite: `-only-testing:TripfolioUITests/TripfolioUITests`; creation/free
  quota, Lock now, full-original readiness and export warning/dismissal.
- New Pro, lock and readiness captures were visually checked under the new
  brand. See [screenshots](screenshots/README.md). The local test catalog supplies
  the displayed $24.99 price; no purchase was attempted in this run.
- An independent review confirmed consumer-copy changes only; technical IDs,
  storage locations and backup format remain unchanged. The new archive names
  use TripDocket while the contained technical app folder remains `Tripfolio.app`.
- This targeted run does not replace the historical full suite or establish
  clean-device payment, physical-device or App Store acceptance.

## Privacy and maximum-type follow-up — 21 October 2026

This nonpayment audit started from `cae4e2b5d53fbfe5e53b824c4143f5a7ae869e9a`.
It used explicit owned simulator UUIDs through CLI/XCTest; no global Xcode UI,
StoreKit purchase/restore or cold-device payment rerun was performed.

Two reproduced product defects were fixed in
`cd38df2bcb80935e560a4c19d309415c0e1ae2b4`: maximum-size lock-screen content now
scrolls within the safe area, and a bounded RAM document draft survives the
sensitive view's removal during background locking. The authentication controller
and opaque privacy cover remain unchanged. Drafts are invalidated when stale,
after successful restore, or on explicit cancellation; failed saves preserve
editable input. No draft is serialized before Save.

- **AppModel: 14/14 passed**, no failures/skips, `build/DraftModel-D.xcresult`.
  The tested app/test source was committed unchanged as `cd38df2`. Eight added
  cases cover save/validation, exact original preservation, refresh/cancel,
  source/traveler invalidation and successful/failed restore.
- **Normal simulated authentication on iPhone: 6/6 passed**, no failures/skips,
  clean `cd38df2` before and after the run, 03:47:52–03:50:53 UTC.
  Result: `build/PrivacySimulator-20261021T034747Z-be59c2ba/Tests.xcresult`.
  The driver recorded 10 match and 2 failure events. Cases cover original
  preview, export share sheet, editor, failure/cancel/retry, large-text locking
  and exact unsaved-draft retention after reauthentication. Settled captures
  show the rendered original and opaque app-switcher cards; the editor card
  is blank white, rather than a claimed visible lock message.
- **Maximum-type iPhone: 3/3 passed**, no failures/skips, at
  `d04676555501d16887cbddb7c62a327cc3a2ad93`.
  Result: `build/MaximumTypePhone-C.xcresult`. The complete Free card and local
  library notice are visible above the floating tabs at their captured scroll
  positions. Readiness, Files import/restore cancellation, navigation,
  backup-warning controls and Pro dismissal passed.
- **Maximum-type iPad: two cases passed** at
  `26590ec1b1cdfa44181c46d9e19e6bc5e7aafeff` in
  `build/MaximumTypePad-B.xcresult`: readiness/import and backup/restore/navigation.
  That run's Free-card case failed because the scripted drag produced no scroll.
  The targeted Free-card/Pro case then **passed 1/1**, no failures/skips, at
  `4ed4554a0d080564c5f9b18efa7157a4e82ee6bc` in
  `build/MaximumTypePad-Free-C.xcresult`. A bounded fallback drag from the visible
  inert notice reached the full card. This does not establish why the earlier
  gesture failed. These are three covered scenarios across two runs/revisions,
  not one 3/3 run on the last revision.
- **Normal-authentication iPad lock check: 1/1 passed**, no failures/skips,
  clean `4ed4554` before/after, 04:03:43–04:04:16 UTC.
  Result: `build/PrivacySimulator-20261021T040343Z-70f92ef2/Tests.xcresult`.
  Maximum-type Unlock is fully visible and hittable in portrait and landscape
  after a failed/cancelled attempt. Tapping it in landscape reaches the real
  authentication prompt. There were zero match events and one
  failure event; this case deliberately does not claim a successful iPad unlock.

The iPhone destinations were the existing iPhone 17 Pro simulators used by the
preceding checks; the iPad was the existing 11-inch iPad Pro (M5). All ran iOS
27.0 (24A434), with Xcode 27.0 (27A266a). Durable logs, result bundles, source
provenance and independently reviewed screenshot hashes are retained in local QA
artifacts. Product and AppModel-test source did not change after `cd38df2`;
`d046765`, `26590ec` and `4ed4554` adjust only the accessibility test driver.

### Scope and unsuccessful attempts

The privacy suite uses the normal system authentication flow with simulator
biometric events and no test-unlock flag. The accessibility suite deliberately
uses the Debug test-unlock flag and a separate synthetic library. Neither
establishes physical-device biometric/passcode security, power-button locking,
VoiceOver or complete accessibility coverage.

The visual captures establish reachable controls and selected complete labels.
The long Pro footer and backup warning's explanatory body are only partly visible
in the captured positions; complete disclosure readability/scrollability remains
unverified. The iPad Pro capture shows the unavailable-price state, not a live
price or purchase. No payment was attempted in this audit.

Earlier failed/partial runs are retained. The baseline privacy run passed 4/6 and
reproduced the two product defects above. An earlier privacy attempt needed
corrections to background, share-sheet and authentication selectors. Initial
maximum-type tests needed bounded scrolling, iPad Files sidebar cancellation and
child-based hit testing. One AppModel build failed Swift isolation checking before
any tests ran; the draft's immutable identifier was corrected before the 14/14
run. Failed attempts are not counted as passing regression evidence.

Independent source and screenshot reviews found no remaining blocking finding
within this bounded change. All StoreKit, physical-device and distribution gates
below remain in force; these targeted checks are not a new full-suite result.

## Historical Tripfolio results

- Xcode 27.0 (27A266a), Swift 6.4, XcodeGen 2.46.0.
- `swift test`: 23 passed — 20 repository and 3 civil-date tests.
- Generic iOS Simulator Debug `build-for-testing` passed for arm64 and x86_64.
- Generic iOS Simulator Release build passed; plist and StoreKit JSON validate.
- On an existing iPhone 17 Pro Simulator, iOS 27.0 (24A434), a complete run
  passed **27/27**, with zero failures or skips: AppModel 6, Platform 17, UI 4.
  This includes real local StoreKit purchase/restore, live refund and approval
  updates, verification/network failures, and cancellation using the system
  Xcode payment sheet. Refund/approval tests observe the transaction listener
  without calling `load()` while waiting.
- Five independent implementation review findings were fixed and rechecked:
  interrupted first save, temporary-copy lifetime, civil dates across time
  zones, non-Gregorian reminder triggers, and Pro revocation during notification
  authorization.
- Two release-script findings were fixed: archive/source SHA drift and a
  fail-open binary scan. Ten isolated mock shell scenarios passed: normal
  package, source mutation after verification/during archive, HEAD mutation,
  failed binary scan, missing executable, DEBUG flag, ZIP/build/Git failures.
  These are script-control checks, not additional app runtime tests.

## Runtime records

All destinations below are **simulators, not physical devices**. Result bundles
are generated under `build/` and excluded from source control. Durable copies
and logs are retained with the local task's QA artifacts. Dates below are UTC.

### Existing-device full run: passed with an environment qualification

- App/test source: `17025401b1958266ba5e5eb4273a80d83dbd2a27`.
  During this run only release packaging scripts advanced to
  `25ac66c6e8d2253e09a69bb30d4fb9b748bdea9c`; app/tests were unchanged.
- Destination: `37D49EA4-2641-446F-81DB-1907F6EEFA2D`, iPhone 17 Pro,
  arm64, iOS 27.0 (24A434).
- 2026-10-21 02:31:43–02:36:03; 27 passed, 0 failed, 0 skipped.
- Command: `TRIPFOLIO_SIMULATOR_ID=<destination> bash scripts/test-simulator.sh`.
- Result: `build/Tests-20261021T023126Z.xcresult`.
- This device had prior application/test launches. **This is not cold-device
  StoreKit acceptance.**

### Fresh iPhone StoreKit probe: blocked before app purchase/restore

- App/hosted-test source: `934f09a` (later `42bf9fc` changes only UI selectors).
- New destination: `25E7B822-8574-4B3E-B955-6E91B8D09E9B`, iPhone 17 Pro,
  arm64, iOS 27.0 (24A434); no previous application or Xcode Run action.
- 2026-10-21 02:39:59–02:41:25; 0 passed, 1 failed, 0 skipped.
- Selected test: `PlatformTests/testVerifiedPurchaseAndRestoreFromLocalHistory`.
- Result: `build/ColdStoreKit.xcresult`.
- The synthetic `SKTestSession.buyProduct` transaction passed the `.xcode`
  environment check, but no verified current entitlement appeared within five
  seconds. The log also recorded a Sandbox storefront error. The guard stopped
  before the app purchase or `AppStore.sync`; no account credentials were used.
- Command: `xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio
  -testPlan Tripfolio -configuration Debug -destination 'platform=iOS Simulator,id=<destination>'
  -parallel-testing-enabled NO -collect-test-diagnostics never
  -derivedDataPath build/DerivedData -resultBundlePath build/ColdStoreKit.xcresult
  -only-testing:TripfolioTests/PlatformTests/testVerifiedPurchaseAndRestoreFromLocalHistory
  CODE_SIGNING_ALLOWED=NO test`.

### Fresh iPad first run and corrective UI checks

- Destination: `A967A695-67C1-4D6F-BE3A-9B376048861F`, iPad Pro 11-inch (M5),
  iOS 27.0 (24A434); no prior application Run action.
- Initial result: `build/iPadUI.xcresult`, 2026-10-21 02:36:26–02:39:33;
  2 passed, 2 failed, 0 skipped.
- System purchase cancellation stopped during preflight with `notEntitled`,
  before launching the app. This is an unresolved test-environment failure.
- Creation/free-limit and original-readiness/export-warning tests passed.
- Lock test assumed an iPhone `TabBar`; iPad exposes top navigation buttons.
  The selector was corrected using the actual accessibility tree. This does
  not establish that the corrected test passed; its result is recorded below.
- Corrected nonpayment UI result: **3/3 passed**, zero failures/skips,
  `build/iPadUIVerified.xcresult`, 2026-10-21 02:41:50–02:44:12 UTC.
  App/test source `42bf9fcebda6516a0fee003fc6fecf0fa0465d63`.
  Selected suite: `-only-testing:TripfolioUITests/TripfolioUITests`; payment
  tests were intentionally excluded and remain blocked as recorded above.
- Updated iPhone UI/copy verification: **3/3 passed**, zero failures/skips,
  `build/iPhoneUIVerified.xcresult`, 2026-10-21 02:44:24–02:46:13 UTC.
  Source `a14974554de95606a504caec8a691203d9ba2c1f`; same selected nonpayment UI suite.
- Both corrected runs cover creation/free quota, Lock now, full-original
  readiness and explicit export warning/dismissal. Screenshots were visually
  checked and use fictional data; see [captures](screenshots/README.md).
  Camera, share completion, accessibility and physical-device checks remain
  outside those three automated UI cases; selected later checks are recorded above.

### Earlier failed attempts retained

An earlier run used Sandbox instead of the local store and was stopped without
signing in. Another run passed AppModel 6/6, Platform 16/17 and UI 2/3: simulated
`.userCancelled` surfaced as a generic StoreKit failure, and the export dialog
omitted the expected Cancel button. The former was replaced by a separately
named network-failure check plus a real system cancellation UI test; the latter
now uses the observed `PopoverDismissRegion`. A subsequent two-test run passed
real cancellation but caught an ineffective navigation-bar dismissal; the
existing-device full run above verifies the corrected dismissal. Failed runs
are not relabeled as successful runs.

## StoreKit unit-test startup — 1 November 2026

A fresh minimal app-hosted control on Xcode 27.1 (27A9275), iOS 27.0
(24A434), with the same product and configuration, observed its verified Xcode
non-consumable entitlement on the first poll (25 ms). Adding only an early
StoreKit updates observer and completing entitlement/catalog reads before
creating SKTestSession reproduced the failure: the synthetic purchase was in
Xcode, but the entitlement stream stayed empty for five seconds. A subsequent
finish call reported a sandbox/no-account error. Thus the runtime can deliver
local entitlements; early application API access can select a different store
before the test session exists.

Debug hosted unit tests now defer AppModel construction only when Xcode injects
the exact `TripfolioTests.xctest` bundle. The test bundle initializes local
StoreKit through its `NSPrincipalClass` before any test starts, including model
tests that create purchase managers. This uses Apple's documented
[pretesting global setup](https://developer.apple.com/documentation/xctest/xctestobservationcenter).
The app retains its shared model lifecycle for ordinary launches, UI tests and
Release; StoreKitTest is imported only by tests. Existing five-second verified
entitlement preflights and scenario reset checks remain in force.

This fixes the early entitlement initialization demonstrated by the control;
it does not make the full local StoreKit suite pass. A selected application test
confirmed bootstrap completion before the first test, then successful reset,
synthetic purchase, verified entitlement, transaction finish, clear and empty
entitlement readback. Catalog loading also completed. The subsequent
`Product.purchase` call did not return within the unchanged 60-second test
allowance. An earlier full-suite attempt had reached that first purchase case
after 61 passing tests and showed an Apple Account sign-in prompt.

An independent minimal UIKit host reproduced the purchase problem with no TripDocket
code, no early StoreKit calls and only one SKTestSession. After resetting the
session, both `disableDialogs` and `askToBuyEnabled` read back as true. The real
catalog returned the configured product and price, but `Product.purchase`
presented Apple Account sign-in instead of returning `.pending`. That control
was stopped without interacting with the prompt; it is not a passing test or
a completed XCTest result. This is evidence of a remaining local Xcode
27.1/iOS 27 purchase-routing limitation, independently of the app's startup
and multi-session test fixture. No credentials or AppStore.sync were used.
Full purchase acceptance still requires the current hosted CI result; neither
successful entitlement preflight nor the non-purchase checks substitute for it.

The bootstrap change passed all 93 selected local non-Platform unit tests
(AppLaunch, AppModel, BatchImport, Localization, NotificationSystem,
PrivacySupport, PurchaseFeedback and ReminderLifecycle), with no failures or
skips. The existing maximum-type import and restore Files open/cancel UI cases
then passed 2/2 on the same fresh simulator. Their successful ordinary UI-test
app launch confirms that the exact unit-host guard does not suppress UI-test
startup. Source hashes remained unchanged across both runs; these results do
not include the Platform purchase scenarios or physical-device behavior.

The local Xcode 27.1 test-plan decoder/encoder silently removes the handwritten
`defaultOptions.storeKitConfiguration` key while preserving supported options.
That unsupported entry is removed. The scheme retains its Run-action StoreKit
configuration; unit tests explicitly initialize their bundled configuration.
A synthetic `.xcode` transaction alone still does not prove that subsequent
application APIs use the same store, and no entitlement bypass is added.

Apple has discussed a related CLI configuration issue and an earlier-version
fix in [Developer Forums](https://developer.apple.com/forums/thread/826971).
That report is context, not an explanation of the remaining local purchase behavior. The historical
cold-device CLI probes did not establish their local test environment. Later
accepted historical hosted CI passed all seven StoreKit cases. No physical-device or
live-store acceptance follows from that result.

## Distribution and physical-device limits

Physical-device authentication, background sharing, camera, VoiceOver, large
Dynamic Type, fresh-install recovery and reboot-plus-airplane-mode operation
remain pending in [manual device QA](manual-device-test.md). Simulator API error
injection does not prove physical offline behavior.

An Apple Account has been selected by the account holder; paid Apple Developer
Program membership has not yet been activated. Team ID, certificates and App
Store Connect access remain unconfirmed. The account address is private.

A paired iPhone is available, but no valid code-signing identity or signed
physical-device build is verified. Name/trademark clearance, live IAP SKU,
paid-app agreement, public support/privacy URLs, TestFlight and App Review
remain unverified. Test purchases are not sales.

Public repository provisioning was completed through Terraform outside this
source tree. The published `674cbb6` baseline has a successful CI gate and a
verified Simulator package. That historical baseline predates the GitHub
release channel described above. A GitHub source/Simulator release does not
establish App Store availability or readiness for sale; those gates remain
unverified.

The consolidated `674cbb6` preview records its original build provenance in
`provenance.json`, later scoped acceptance in `acceptance.json`, and artifact
digests in `SHA256SUMS`. The historical `scripts/package-preview.sh` format
uses `BUILD.txt` and runs core checks plus a Release build; that script was not
rerun to assemble this consolidated preview. Neither format overrides the
StoreKit or device gates above. Source archives are rebuildable; binaries are
not claimed to be bit-for-bit reproducible.
