# Implementation contract

Provisional consumer name: **TripDocket**. Planned App Store display title:
**TripDocket: Travel Documents**. A bounded public-name search found no exact
match; App Store Connect reservation and trademark clearance are not confirmed.
Native iOS 17+.
Storage actor is the single writer; UI is MainActor. No network backend.

This consumer-name change leaves technical identifiers intact: repository
`travel-documents-ios`, app module/project/scheme `Tripfolio`, domain module
`TravelCore`, existing filenames including `App/Tripfolio.storekit`, bundle
`com.4alvit.tripfolio`, and product `com.4alvit.tripfolio.pro`.

## Core API owned by storage contributor

Public Codable, Equatable, Sendable models with public initializers:

- `Trip`: `id: UUID`, `title: String`, `departureDate: Date?`
- `Traveler`: `id: UUID`, `name: String`
- `DocumentKind: String, Codable, CaseIterable, Sendable` cases passport,
  insurance, ticket, booking, other. `displayName: String`.
- `TravelDocument`: `id`, `tripID`, optional `travelerID`, `title`, `kind`,
  optional `expiryDate`, `originalFilename`, `storedFilename`, `byteCount: Int`,
  `sha256: String`, `importedAt: Date`.
- `LibrarySnapshot`: `schemaVersion: Int`, `trips`, `travelers`, `documents`;
  `static var empty: LibrarySnapshot`.
- `DocumentReadiness`: `documentID: UUID`, `state: ReadinessState`, `checkedAt: Date`.
  `ReadinessState: String` cases ready, missing, modified, unreadable.

`public actor DocumentRepository` with throwing `init(rootURL: URL)`:

```swift
func load() throws -> LibrarySnapshot
func createTrip(title: String, departureDate: Date?) throws -> Trip
func addTraveler(name: String) throws -> Traveler
func importDocument(data: Data, originalFilename: String, tripID: UUID,
 travelerID: UUID?, title: String, kind: DocumentKind, expiryDate: Date?) throws -> TravelDocument
func documentData(id: UUID) throws -> Data
func verifyReadiness(tripID: UUID) throws -> [DocumentReadiness]
func exportBackup(documentIDs: Set<UUID>?) throws -> Data
func restoreBackup(_ data: Data) throws -> LibrarySnapshot
func deleteDocument(id: UUID) throws
```

Limits: max 16 MiB/document, 64 MiB total original data, bounded encoded backup
input (96 MiB). PDF/JPEG/PNG only for v0.1, validated file signatures. Persisted
names are generated IDs, never caller paths. Human filenames are display-only.
`documentData` and readiness read and hash the COMPLETE original, not a thumbnail.
Validate references, unique IDs/names, hashes, lengths and sizes on restore before
committing. Restore replaces the library atomically; failed restore preserves the
old one. A fresh repository can restore a portable archive. Use atomic catalog
writes and iOS complete file protection. Backup format has no encryption promise.
Provide LocalizedError storage failures without exposing document content.

## UI API owned by integrating contributor

`@MainActor @Observable final class AppModel` published properties:
`library: LibrarySnapshot`, `readiness: [UUID: DocumentReadiness]`,
`isBusy: Bool`, `errorMessage: String?`, `notice: String?`.
Methods are async:
`refresh()`, `createTrip(title:departureDate:)`, `addTraveler(name:)`,
`importFile(url:tripID:travelerID:title:kind:expiryDate:)`,
`importData(_:filename:tripID:travelerID:title:kind:expiryDate:)`,
`checkReadiness(tripID:)`, `deleteDocument(id:)`,
`makeBackup(documentIDs:) -> URL?`, `restoreBackup(url:)`,
`previewURL(documentID:) -> URL?`.
Free limits enforced by AppModel before additions: 1 trip, 2 travelers, 8 docs;
restoring/viewing/deleting/exporting remains available. `canAddTrip`,
`canAddTraveler`, `canAddDocument` booleans; `purchases: PurchaseManager`.

App shell initializes AppModel and supplies it using `.environment(model)`.
UI entry `RootView()` reads `@Environment(AppModel.self)`.
Use async Task actions and display `errorMessage` alerts. Authored interface,
error, privacy and permission text is localized in English and Russian. Use the
first supported system/per-app language, with English development fallback.
`L10n` combines that language's wording/plural rules with the user's regional
formats; never translate persisted names, filenames, identifiers or enum keys.
Core resources live in the SwiftPM bundle. Notification keys live in the main
app's `Localizable.strings` and use Apple's deferred notification localization
API so language selection happens at delivery. StoreKit owns the displayed
product price. No app-owned language selector or global language override.
UI implementation owns App/Views.swift, App/Scanner.swift, App/OCRService.swift.
Show explicit plaintext/export warning before sharing or backup. Restore requires
replacement confirmation. No silent OCR dates; all proposed text is editable.

## Purchases/privacy contributor

Own App/PurchaseManager.swift, App/PrivacyLock.swift, App/ReminderService.swift,
App/Tripfolio.storekit. `@MainActor @Observable final class PurchaseManager`
exposes `isPro: Bool`, `displayPrice: String?`, `statusMessage: String?`,
`isBusy: Bool`, async `load()`, `purchase()`, `restore()`.
SKU `com.4alvit.tripfolio.pro`, non-consumable, config price $24.99.
`PrivacyLockView<Content: View>` initializer `init(@ViewBuilder content: () -> Content)`
wraps root, device authentication at launch/resume; inactive snapshot cover.
DEBUG-only test-unlock flag allowed, never in Release.
`ReminderService.schedule(document:travelerName:canSchedule:isCurrentDocument:)`
requests permission only on explicit UI action; generic notification text that
does not reveal names/document titles, user-confirmed date. Pro only creation;
existing scheduled reminders are not removed due to entitlement expiry. The
MainActor caller supplies current Pro and full-document-snapshot predicates.
Scheduling revalidates across suspension points and serializes each document's
add/cleanup work. Deletion, edits and restore invalidate pending intents, remove
accepted notifications immediately, and clean late additions before newer work.
`cancel` and `cancelAll` return awaitable cleanup tasks; ordinary UI callers need
not wait for cleanup to invalidate the intent.

## Parallel ownership

Storage contributor: Sources/TravelCore and Tests/TravelCoreTests only.
UI contributor: the three UI files above only.
Purchases/privacy contributor: the four files above only.
Integrator: project, app model/entry, resources, CI, docs, final validation.

## Core lifecycle additions

The storage actor also provides these public methods. Update return values are
`@discardableResult`; callers can use the returned model or reload the snapshot.

```swift
func deleteTrip(id: UUID) throws
func deleteTraveler(id: UUID) throws
func updateTrip(id: UUID, title: String, departureDate: Date?) throws -> Trip
func updateTraveler(id: UUID, name: String) throws -> Traveler
func updateDocument(id: UUID, title: String, travelerID: UUID?,
    kind: DocumentKind, expiryDate: Date?) throws -> TravelDocument
```

Trip deletion atomically removes the trip and all of its documents. Other trips,
their documents, and all travelers remain. Normal successful publication retires
the old generation; cleanup is best-effort if storage errors prevent removal.
Deleting a traveler preserves every document and clears that traveler's document
references to `nil`. The UI obtains explicit confirmation for deletions.

Updates trim and validate human-readable names, validate dates and references,
and preserve original bytes. Document updates cannot change its ID, trip ID,
original/stored filenames, length, hash, or import timestamp. Use `nil` to clear
an optional date or traveler assignment. Missing subjects produce localized
`tripNotFound`, `travelerNotFound`, or `documentNotFound` errors. A missing new
traveler assignment produces `missingReference`. Failed validation or writes
before publication leave the previous snapshot active.

These lifecycle operations have no entitlement dependency. The integrating UI
must keep editing/deletion/recovery and existing-original access available after
an entitlement change; additions continue to use the existing free limits.

## Civil-day convention

Departure and expiry dates use `Date` at the Swift API boundary but represent
Gregorian calendar days encoded as 12:00 UTC. `TravelDate.stored(from:calendar:)`
converts DatePicker values before repository writes; `TravelDate.local(from:calendar:)`
converts for display, editing and reminder scheduling. Import/readiness timestamps
remain absolute instants. Never format stored civil-day values in an arbitrary
current time zone without conversion.

## Atomic multi-file import

`DocumentImportInput` contains complete `Data`, originalFilename, optional
travelerID, title, kind and optional stored expiryDate. The actor method
`importDocuments(_:tripID:) throws -> [TravelDocument]` accepts 1–10 inputs,
validates all references, metadata, original content and aggregate limits before
one atomic generation publication, and returns models in input order. Single
import delegates to the same path. Cooperative cancellation is checked before
publication; no cancellation error is reported after a committed publication.
`DocumentRepository.validateImportData(_:)` permits off-main-thread preparation
using the same complete-original parser.

The MainActor model owns one bounded, nonpersisted `BatchImportDraft` and its
preparation task. File-picker, cancel and commit entry points carry the draft ID,
so a late callback from an old picker cannot change a newer draft. Each item
stores a confirmation snapshot; changing metadata removes its confirmation.
Pro gates new batch preparation and save, never old-data access or recovery.
The batch editor and existing-document editor are mutually exclusive. Privacy
view teardown keeps the model draft; explicit cancel, completed save or source
library changes discard it. Individual previews follow existing cache cleanup.
