# TripDocket 0.1.0 development preview

TripDocket keeps a family's travel documents in a local iPhone/iPad library.
Create trips and people; import PDF, JPEG and PNG originals or scan paper;
correct details and confirmed expiry dates; search and verify complete files;
export a chosen packet or backup and restore it into a fresh library.

The preview includes StoreKit 2 one-time Pro and device authentication. Free
includes 1 trip, 2 people and 8 documents. Viewing, editing, deleting, basic
export and recovery remain available without Pro. All libraries are limited
to 64 MiB of originals, with a 16 MiB per-file cap.
Restoration accepts encoded backups up to 96 MiB. A device passcode is required
to unlock the release app. Pro's actual purchase price is supplied by the App
Store; the local test configuration does not establish a live storefront price.

Exported packets are unencrypted. Choose a trusted destination and keep a
backup before deleting the app or replacing its library.

This is a development preview, not an App Store release. The simulator package
is unsigned and cannot be installed on a physical iPhone. StoreKit configuration
purchases are tests, not real sales. See [release evidence](docs/release-evidence.md)
for completed checks and remaining device/distribution work. Use synthetic
files for evaluation while physical-device validation is pending.

Latest fixes keep a valid library available when disposable cache cleanup fails,
and prevent delayed reminder operations from restoring deleted or cancelled
notifications. Independent source reviews found no open issues in these fixes.
The targeted iPhone Simulator run passed 61/61: AppModel and batch import 35,
reminder lifecycle and dates 26. Core tests previously passed 32/32; packaging
runs them again with the generic unsigned Release build.

Earlier source-pinned evidence includes actual local Xcode purchases, a complete
Files batch-import scenario and selected privacy/accessibility UI checks. These
are not a new payment or UI acceptance run of the latest fixes. Fresh-device
StoreKit probes failed to establish the test environment. The cold-device
payment and overall release gates are **not green**; no live purchase or
production release has been verified.

TripDocket is the provisional consumer name; the planned App Store title is
“TripDocket: Travel Documents”. A bounded public-name search found no exact
match, but App Store Connect reservation and trademark clearance are not
confirmed. An Apple Account has been selected; paid Apple Developer Program
membership is not yet active. Physical-device QA, signing, a configured live in-app product,
required account agreements, public support/privacy URLs, final metadata,
published-commit CI and App Store acceptance remain release requirements.

Technical repository, module, project/scheme, filenames, bundle and product
identifiers remain unchanged by this consumer-name update. Three targeted
nonpayment iPhone UI cases passed at `f3b5688`; the new Pro, lock and readiness
captures were visually reviewed. See the source-pinned release evidence.
