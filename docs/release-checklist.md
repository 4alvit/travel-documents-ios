# TripDocket release checklist

Record exact commit, OS, Xcode and tests in release-evidence.md. Advance a release
channel only after its evidence exists; never relabel an unverified build stable.
Checked historical items below retain their recorded source/scope; they are not
whole-suite acceptance of the current PR. The accepted executable baseline
passed at `674cbb6`; see [current evidence](release-evidence.md#accepted-executable-baseline-and-ordinary-release-launch--25-october-2026).
Every later push requires its own ordinary CI.

- [x] Public repository provisioned through Terraform; development preview in draft PR #1.
- [ ] Fresh independent approval of the final PR push, with repository protection retained.

- [x] Core tests: 38 passed, including atomic batches, cancellation, failed-restore
      preservation and exact originals.
- [x] AppModel tests: 21 passed plus 14 batch-model cases, including free-capacity
      recovery, cancellation/revocation during reads, draft review and retry.
- [x] Cache-failure recovery and 26 reminder/date cases passed in the integrated
      61-test iPhone run, including real denied cleanup, stale work and queued
      cancellation. Independent source reviews accepted the frozen candidate.
- [x] Strict real Files batch scenario: 1/1 passed with actual local Xcode purchase,
      per-file metadata confirmation, edit invalidation, Save and relaunch.
      Actual original bytes and pre-existing demo preservation checked separately.
- [x] Generic simulator Release build passes without signing.
- [x] Existing-device full app/platform/UI suite: 27/27 passed on iPhone Simulator.
- [x] Actual system purchase cancellation passed on that configured simulator,
      with the result bundle recorded.
- [x] Ordinary hosted StoreKit fixture suite passes at the accepted baseline.
      Earlier cold local probes remain historical evidence, not a current
      request for repeated diagnostics. Live/physical-device validation remains open.
- [x] Three selected nonpayment UI scenarios pass on iPhone and iPad Simulators.
- [ ] Complete iPhone and iPad UI coverage: import/scan, people/trips, readiness, preview,
      explicit sharing, restore cancellation/replacement, error and empty states.
- [x] Normal simulated authentication: six iPhone privacy/draft cases pass with
      preview/share/editor app-switcher evidence and failure/cancel/retry.
- [x] Maximum-type Unlock is fully visible and hittable in both orientations on
      iPhone and iPad Simulators. Tapping it in landscape opens system
      authentication; no Debug unlock bypass in these cases.
- [x] Three selected maximum-type layout scenarios covered on iPhone/iPad using
      Debug test-unlock mode; Free card fully visible without navigation overlap.
      Exact separate
      runs and partial-disclosure limits are recorded in release-evidence.md.
- [x] Complete backup-warning text and whole export action visible at maximum
      type on iPhone and iPad; targeted 1/1 runs and independent pixel review.
- [ ] Physical-device lock and app-switcher cover checked with presented sheets.
- [ ] Complete Dynamic Type disclosures and VoiceOver navigation checked.
- [ ] StoreKit purchase, restore, pending, cancellation, refund/revocation and
      offline entitlement behavior checked on a simulator/device.
- [x] Five implementation review findings fixed and independently rechecked;
      two release-script findings fixed with ten mock smoke checks.
- [x] Follow-up lock-layout and unsaved-draft defects fixed with targeted regression
      and independent source/screenshot review.
- [ ] All relevant regression suites pass on the final release candidate commit.
- [ ] Exact simulator/runtime, commands, test totals and result bundles are linked
      in release-evidence.md, including failures and isolated reruns.
- [x] Published executable baseline `674cbb6` has a successful CI gate and verified
      source/Simulator archives with checksums and build instructions.
- [x] Exact Release ZIP ordinary launch reached system authentication; three
      captures and owned-device cleanup were independently reviewed.
- [ ] GitHub prerelease publication and its downloadable assets are verified.
- [ ] Final release-candidate validation includes the separately enabled scenarios
      and remaining physical-device/distribution checks.
- [x] Only fictional screenshots/fixtures; source scan found no secrets or private paths.

- [x] English/Russian resources and system-language fallback verified: core 38/38,
      app/model 71/71, targeted UI 3/3 on each iPhone/iPad.
- [ ] Deliver a scheduled notification after changing per-app language on a device.

## App Store distribution requirements

- [x] The account holder selected an Apple Account for distribution.
- [ ] Paid Apple Developer Program membership is activated; not yet active.
- [ ] TripDocket / “TripDocket: Travel Documents” is reserved in App Store Connect
      and trademark clearance is resolved. A bounded search found no exact
      match; neither reservation nor clearance is currently confirmed.
- [ ] Physical-device checks in manual-device-test.md are completed with evidence.
- [ ] Signing team, bundle ID and distribution profile are available.
- [ ] Account holder completes any required Paid Apps Agreement and tax/banking.
- [ ] Non-consumable SKU `com.4alvit.tripfolio.pro` exists and is approved.
- [ ] The actual App Store Connect product price/territories and localized price
      display are verified. The local StoreKit configuration is not a live price.
- [x] Bundled EN/RU privacy/support guidance and confirmed public preview links
      are available at the top of Settings without Pro.
- [ ] Final privacy/support URLs, actual legal/contact/retention details, metadata
      and screenshots are approved for submission; preview documents are not final.
- [ ] Final-build privacy labels, permissions, age rating and account details
      are completed accurately; no untested security or unlimited-storage claims.
- [ ] Export-compliance answers reviewed for actual use of Apple system crypto.
- [ ] Signed archive validates and the intended TestFlight build is available
      for pre-release validation where used.
- [ ] App Review accepted; actual storefront release verified.

Do not accept legal agreements or pay enrollment fees on the account holder's
behalf. A GitHub prerelease, simulator app or sandbox purchase satisfies none of
the live-store steps by itself.
