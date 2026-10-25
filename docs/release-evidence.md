# Release evidence

Current stage: local development preview. No GitHub or App Store release has
been verified. **Cold-device StoreKit testing is blocked; the overall release
gate is not green.** Passing tests on a previously configured simulator do not
establish a reproducible clean CI environment.

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

## StoreKit limitation

The local configuration alone has not produced reliable cold-device CLI
behavior on this toolchain. A synthetic `.xcode` transaction is not
by itself proof that a subsequent application API uses the same store.
No fake entitlement or production bypass has been added.
The handwritten StoreKit entry in the test plan has not been established as a
supported activation mechanism; no test-plan UI switch is asserted here.

Apple has discussed a related CLI configuration issue and an earlier-version
fix in [Developer Forums](https://developer.apple.com/forums/thread/826971).
That report is context, not proof of the cause on Xcode 27. A clean-device
purchase/restore run and an actual published CI result remain required.

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

Public repository provisioning is managed through Terraform outside this
source tree and is blocked on workspace access. There is no verified public
remote, published app CI result or GitHub release. Do not label this preview
stable or ready for sale.

The preview package records its exact source commit/toolchain in `BUILD.txt`
and artifact digests in `SHA256SUMS`. `scripts/package-preview.sh` runs core
checks and the Release build; it does not override the StoreKit or device gates
above. Source archives are rebuildable; binaries are not claimed to be
bit-for-bit reproducible.
