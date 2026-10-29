# TripDocket: Travel Documents

Keep a family's travel documents together and check that the complete originals
are available on the device before departure. Original SwiftUI application for
iPhone and iPad, with a separately testable Swift domain package.

**Development preview.** App Store distribution and live purchases are not yet
configured. A source release or successful simulator build is not an App Store
release. See [release evidence](docs/release-evidence.md) for verified status.

TripDocket is the provisional consumer name. A bounded public-name search found
no exact match, but App Store Connect reservation and trademark clearance are
not confirmed. The account holder has selected an Apple Account; paid Apple
Developer Program membership is not yet active.

## Product

- Trips, travelers, PDF/JPEG/PNG documents and human-confirmed expiry dates.
- Files import and document scanning. Local OCR proposes editable text.
- Pro batch import: choose up to 10 files, review each document, then save all
  originals together. Failed preparation or storage does not add a partial batch.
- A readiness check reads and hashes each complete original. It is a check of
  local file integrity, not a check that travel documents are valid or sufficient.
- Selective portable packets and full backup/restore with validation before
  replacement. [Understand the backup contract](docs/data-and-recovery.md).
- Device authentication and a privacy cover when the app becomes inactive.
- Free, offline English/Russian privacy and support guidance in Settings; public
  web destinations open only after an explicit confirmation.
- Optional, explicit local expiry reminders with generic notification text.
- StoreKit 2 one-time Pro: more than one trip, two people or eight documents.
  Pro also enables batch import and explicitly scheduled expiry reminders.
  Viewing, editing, deleting, basic export and recovery do not require Pro.

The interface supports English and Russian and follows the first supported
language in iOS settings, including the standard per-app language setting.
Other languages fall back to English. Regional date and number preferences are
preserved; saved names and document contents are not translated.
There is no backend, mandatory app account,
automatic email access, flight feed, visa advice, or collaborative sync.
Libraries are limited to 64 MiB of originals and 16 MiB per document in this
preview. These bounds keep imports and portable restore predictable on device.

## Build

The repository, module, Xcode project/scheme, filenames, bundle identifier and
StoreKit product identifier retain their existing technical names. The consumer
name change does not rename `Tripfolio`, `com.4alvit.tripfolio` or
`com.4alvit.tripfolio.pro`.

Requires macOS, Xcode with Swift 6, and XcodeGen 2.46 or compatible. Minimum iOS
deployment target is 17.0; the installed Xcode SDK is used.

```sh
swift test
xcodegen generate
xcodebuild -project Tripfolio.xcodeproj -scheme Tripfolio \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath build/DerivedData CODE_SIGNING_ALLOWED=NO build
```

Open `Tripfolio.xcodeproj` in Xcode and choose an installed iPhone/iPad simulator.
For a physical device, select your own signing team. Do not commit provisioning
profiles, keys or personal documents. `App/Tripfolio.storekit` provides local
test products; its transactions never count as sales.

Run `bash scripts/test-simulator.sh` with an installed runtime to execute app,
StoreKit and UI tests serially. `TRIPFOLIO_SIMULATOR_ID` can select a specific
device. The result bundle is written under `build/`.

The accepted executable baseline is `674cbb6`. [CI 40169628635](https://github.com/4alvit/travel-documents-ios/actions/runs/40169628635)
passed 38 core tests, 95 phone tests with zero failures and seven expected opt-in
skips, and two separately selected iPad guidance tests. All seven StoreKit cases
passed. The tested merge `5cb2d0a9` has the same tree as that source commit.
Earlier failures remain historical evidence. Later documentation or source
commits require their own checks; these results are not relabelled as new runs.

This exact Release ZIP subsequently passed one ordinary Simulator launch to the
system passcode prompt and verified cleanup. Authentication was not completed;
unlocked workflows, physical devices and live purchases remain unverified.

In **Debug builds only**, `--ui-testing-unlocked` skips authentication and uses
a separate synthetic library; `--ui-testing-reset` clears that test library.
`--demo` installs fictional sample content into an empty library. Never use
Debug builds with real sensitive documents. Release builds omit these flags.

## Targeted checks

The hosted iPad guidance job runs the existing English normal-size and Russian
maximum Dynamic Type cases with `bash scripts/test-privacy-support-ipad.sh`.
It creates a dedicated compatible iPad, builds once, sets and reads back the
system text size before each separate test, then deletes only that simulator
and checks that its UUID is absent. Both CI jobs must succeed. Evidence under
`build/PrivacySupport-iPad/` includes original result bundles, separate reader
copies, source/product hashes and cleanup records. These Debug tests use the
synthetic library and authentication bypass; they do not establish real
security, VoiceOver speech, offline network denial or purchase behavior.

The real Files batch-import scenario is opt-in and uses the local StoreKit
purchase UI. On an explicitly selected, already booted test simulator, run:

```sh
xcodegen generate
python3 scripts/test-batch-simulator.py --device <simulator-uuid>
```

The driver creates a unique Files folder with two fictional PDFs, records their
hashes, runs exactly one case and removes only its own folder. Its source
inventory, fixture copies, log and result bundle remain under `build/`. The case
requires an actual local Xcode purchase, confirms each document individually,
checks that later edits require confirmation again and opens the saved originals
after relaunch. It skips unless explicitly enabled by the driver environment.
Debug authentication bypass is
used for this functional scenario; it does not verify privacy, physical-device
behavior or live purchases. Rendered PDF screenshots need separate visual review.

The privacy driver exercises system LocalAuthentication with synthetic Face ID
match/failure events on an explicitly selected, already booted simulator:

```sh
python3 scripts/test-privacy-simulator.py --device <simulator-uuid>
```

It records the exact source, destination and test results under `build/`, restores
the previous simulated enrollment state, and rejects skipped or incomplete runs.
The simulator notifications were validated on iOS 27.0; other runtimes are not
certified. Directly running this suite without its driver skips the tests.
The suite uses fictional demo content and **does not use the test-unlock flag**.
Simulated Face ID does not establish physical biometric or passcode behavior.

`TripfolioUITests/AccessibilityUITests` covers selected navigation, import/restore
cancellation, backup-warning controls, Free-card reachability and Pro dismissal
at the maximum Accessibility Dynamic Type category. These layout checks use the
separate synthetic library and **Debug test-unlock mode**. They do not test
privacy, purchases, VoiceOver or the readability of every disclosure. Exact
passing revisions and remaining limits are in [release evidence](docs/release-evidence.md).

## Data protection

Local library files use Apple's complete file protection and the app sandbox.
The UI uses device-owner authentication, not a separate vault password. Set a
device passcode. This app does not claim zero-knowledge encryption or protection
against a compromised OS/unlocked device.

**Exported packets and backups are plaintext containers.** Anyone who receives
one can read it. Choose the destination and recipients deliberately. An exported
copy cannot be remotely revoked. Originals stay in the source app when imported.
The privacy cover does not prevent somebody photographing an unlocked screen.

An unfinished document import or edit survives background locking in RAM within the same
running process. The sensitive view is removed while locked and recreated after
authentication. Save persists the document; Cancel discards the draft. Process termination
loses an unsaved draft. Deleting/changing its source or successfully restoring a
backup invalidates the old draft. An import keeps its chosen file reference or
scanned bytes, editable details and OCR text only in memory until Save.

When selecting documents for export, searching limits both **Select all results**
and the exported selection to visible matches. Filtering out a selected document
removes it from the selection; clearing the search does not select it again.

See [privacy policy](docs/privacy.md), [support](docs/support.md),
[product scope](docs/product-scope.md), and [release checklist](docs/release-checklist.md).

## Contributing and security

Use only generated, fictional fixtures. Run `scripts/verify.sh` before opening a
pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).
Code is MIT licensed. Repository infrastructure is maintained separately through
Terraform; this repository never contains its state or credentials.

For a clean, committed checkout, `bash scripts/package-preview.sh` produces a
source archive, unsigned simulator app and SHA-256 checksums under `dist/`.
Physical-device distribution requires separate Apple signing and review.

Hosted CI packages the Release app immediately after verification, before UI
tests. The `TripDocket-simulator` artifact contains `TripDocket-Simulator.zip`,
`provenance.json` and `SHA256SUMS`. The inner ZIP preserves the `.app` directory
and executable permissions; its bytes and modes are checked before upload.
Provenance identifies the actual tested checkout, which can be a PR merge commit.
It is an unsigned Simulator candidate: a successful CI upload does not establish
physical-device, App Store or separate release-smoke acceptance.
