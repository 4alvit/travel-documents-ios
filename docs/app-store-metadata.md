# App Store metadata draft

Prepared 20 October 2026 from the implemented preview. This is submission copy,
not evidence of App Store publication. Name availability, trademark clearance,
signing, App Store Connect setup and App Review acceptance are pending.

TripDocket is provisional. A bounded public-name search found no exact match;
it does not establish name availability or trademark clearance. Reservation in
App Store Connect is not confirmed. The account holder selected an Apple Account,
but paid Apple Developer Program membership is not yet active.

## English storefront fields

**App name**

TripDocket: Travel Documents

**Subtitle**

Travel documents, offline

**Promotional text**

Keep your family's travel documents together. Check original files before you leave, confirm expiry dates, and export a backup to a place you trust.

**Keywords**

travel,documents,passport,insurance,tickets,booking,offline,organizer,trip,family,scan

**Description**

Keep the documents for your next trip in one place, ready to open without an
internet connection after import.

TripDocket organizes your family's passports, insurance, tickets and bookings by
trip and person. Import a PDF, JPEG or PNG from Files, or scan a paper document
on a supported device. Give each document a name and confirm any expiry date
yourself. Optional on-device text recognition provides editable suggestions;
it does not fill in dates for you.

BEFORE YOU LEAVE

- Find documents by title, person or type.
- Check each complete original file stored in TripDocket, not just a preview.
- See which originals were verified, missing, changed or unreadable at the last
  check. Open them in Airplane Mode before departure to confirm the contents.
- Correct document details and keep the people and trips in your library tidy.

YOUR DOCUMENTS AND YOUR COPIES

TripDocket does not require a TripDocket account and has no developer-operated
document cloud. Document processing happens on your device. Device
authentication protects access to the app; a device passcode is required.
Documents use iOS file protection.

Export a selected trip packet or a full backup to a destination you choose.
Exports contain readable, unencrypted documents and details, so use a trusted
destination or recipient. Copies you share cannot be revoked from TripDocket.
Restoring a validated backup replaces the receiving device's entire TripDocket
library; it does not merge libraries. Keep a backup before deleting the app or
changing devices.

START FREE, ADD PRO WHEN YOU NEED MORE

Free includes one trip, two people and eight documents. TripDocket Pro is a
one-time, non-consumable in-app purchase that allows more trips, people and
documents, batch import of up to 10 files with individual confirmation, and
expiry reminders you explicitly enable. The purchase screen
shows the current App Store price in your local currency. There is no
subscription.

Viewing, editing, deleting, exporting and restoring existing data remain
available without Pro. All libraries, including Pro libraries, support up to
16 MB per original file and 64 MB of original files in total. A backup selected
for restoration must fit the 96 MB input limit.

Expiry reminders use dates you confirm and generic notification text. Delivery
depends on device permissions and settings. TripDocket does not check visa,
entry or legal requirements, and an expiry date alone does not establish that
a document is valid for a particular journey.

## Submission details to complete

- Suggested primary category: Travel. Final category selection pending.
- Minimum supported version in the project: iOS 17.0. iPhone and iPad layouts
  still require the device QA recorded in `manual-device-test.md`.
- Preview UI languages: English and Russian, selected by iOS system/per-app
  preferences with English fallback. This storefront draft remains English;
  a separate Russian storefront description must be reviewed before submission.
- Support URL: pending a verified public URL for the project support page.
- Privacy policy URL: pending a verified public URL for the project policy.
- Marketing URL: optional; none supplied by this draft.
- Copyright, developer legal name, age-rating questionnaire and territory
  availability: account holder to complete with accurate details.
- Screenshots: use only synthetic, visibly fictional travel data. Do not use
  personal passports, real bookings or private exported packets.
- Validate the final storefront name before reserving or submitting it.
- Keep technical identifiers unchanged: bundle `com.4alvit.tripfolio`, product
  `com.4alvit.tripfolio.pro`, Xcode project/scheme `Tripfolio`, and existing
  repository/module/filenames. Consumer-facing copy uses TripDocket.

## App Review notes draft

TripDocket is a local travel-document organizer. No TripDocket login or reviewer
account is required. Standard Apple purchase authentication may be requested
by the App Store.

Please review on a device with a passcode configured. The release app uses
LocalAuthentication's device-owner authentication policy: Face ID, Touch ID or
the device passcode as available. The app intentionally stays locked when
device-owner authentication cannot be performed. There is no release-build
authentication bypass. Camera scanning requires a supported physical device;
Files import is also available.

To exercise the main workflow:

1. Unlock, create a trip, and add a person on the People tab.
2. In the trip, choose Add document, import a synthetic PDF/JPEG/PNG or scan
   a synthetic paper document, confirm its details, and save.
3. Choose Check all originals, then open the document. After successful import,
   this workflow does not require the network.
4. Use document actions to edit details. Choose Export trip packet or the full
   backup action in Settings. An explicit warning precedes the system share
   sheet. Exports are unencrypted.
5. Settings > Restore from backup accepts a `.tripbackup` file. Confirming
   replacement restores that packet as the whole library. Cancelling preserves
   the current library. Invalid backups are rejected before replacement.

The optional in-app purchase is **TripDocket Pro**, product ID
`com.4alvit.tripfolio.pro`, type **non-consumable**, implemented with StoreKit 2.
It has no renewal or subscription. Free supports 1 trip, 2 people and 8 documents;
Pro permits additional entries, batch import of up to 10 files, and explicitly
enabled local expiry reminders. In a trip, open its actions menu and choose
Import multiple files. Review and confirm each original and its details, then
save the entire batch. Preparation or save failure does not add a partial batch.
All users retain viewing, editing, deletion, export and restore of existing
data. Pro does not remove the storage size limits.

Open Settings > TripDocket Pro, or reach a free addition limit, to see the purchase
screen. Its price comes from the StoreKit product's localized `displayPrice`.
Restore purchases is present in Settings and the Pro screen. Cancelled or
pending purchases do not grant Pro. Only verified active entitlements grant
access; revocation removes Pro access while retaining existing data operations.
Purchase and restore error messages provide retry guidance.

Expiry reminders require Pro and notification authorization requested when
the user explicitly enables a reminder. They use a human-confirmed expiry
date and generic text. The current schedule is 9 AM in the time zone used when
scheduled, 30 days before expiry, or the next 9 AM in that zone before the
expiry day when already inside that window. Traveling to another time zone
does not automatically move the reminder.
Editing a document clears its previous reminder and asks the user to schedule
it again if needed.

The repository's StoreKit configuration is for local testing only. Its test
price is not a live storefront promise. Before submission, create and configure
the matching App Store Connect product, attach it to the submission as needed,
and replace this paragraph with the actual configuration status. A configuration
file or sandbox transaction is not evidence of production purchase readiness.

Technical size limits use binary units: 16,777,216 bytes per original,
67,108,864 bytes of originals per library, and 100,663,296 bytes of encoded
backup input. The app labels these as 16 MB, 64 MB and 96 MB respectively.

Privacy declarations and export-compliance answers must be checked against the
final build and account configuration before submission. This draft does not
complete those questionnaires or accept legal agreements.
