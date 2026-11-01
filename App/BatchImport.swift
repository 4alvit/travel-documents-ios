import Foundation
import Observation
import TravelCore

/// Unsaved, bounded originals live here only for this process. Nothing in this
/// draft is serialized; the model survives the privacy view's teardown.
@MainActor @Observable
final class BatchImportDraft: Identifiable {
    enum Phase: Equatable { case choosing, preparing, reviewing, committing }

    nonisolated let id = UUID()
    let tripID: UUID
    let sourceLibrary: LibrarySnapshot
    var phase: Phase = .choosing
    var items: [BatchImportItem] = []
    var preparedCount = 0
    var selectedCount = 0
    var errorMessage: String?

    var canSave: Bool {
        phase == .reviewing && !items.isEmpty && items.allSatisfy(\.isReviewed)
    }

    init(tripID: UUID, sourceLibrary: LibrarySnapshot) {
        self.tripID = tripID
        self.sourceLibrary = sourceLibrary
    }
}

@MainActor @Observable
final class BatchImportItem: Identifiable {
    nonisolated let id = UUID()
    let filename: String
    let originalData: Data
    let fileExtension: String
    var byteCount: Int { originalData.count }

    var title: String { didSet { if title != oldValue { confirmedMetadata = nil } } }
    var kind: DocumentKind = .other { didSet { if kind != oldValue { confirmedMetadata = nil } } }
    var travelerID: UUID? { didSet { if travelerID != oldValue { confirmedMetadata = nil } } }
    var hasExpiry = false { didSet { if hasExpiry != oldValue { confirmedMetadata = nil } } }
    var expiryDate: Date = .now { didSet { if expiryDate != oldValue { confirmedMetadata = nil } } }
    private var confirmedMetadata: Metadata?

    private struct Metadata: Equatable {
        let title: String
        let kind: DocumentKind
        let travelerID: UUID?
        let hasExpiry: Bool
        let expiryDate: Date
    }

    private var metadata: Metadata {
        Metadata(title: title, kind: kind, travelerID: travelerID,
                 hasExpiry: hasExpiry, expiryDate: expiryDate)
    }

    var isReviewed: Bool { confirmedMetadata == metadata }

    init(filename: String, data: Data) {
        self.filename = filename
        self.originalData = data
        self.title = String(URL(fileURLWithPath: filename).deletingPathExtension().lastPathComponent.prefix(200))
        // The model calls the repository's full parser first. Extensions are
        // derived from validated bytes, never the external filename.
        if data.starts(with: Data("%PDF-".utf8)) { fileExtension = "pdf" }
        else if data.starts(with: [0x89, 0x50, 0x4e, 0x47]) { fileExtension = "png" }
        else { fileExtension = "jpg" }
    }

    func confirm() { confirmedMetadata = metadata }

    func validateMetadata(in library: LibrarySnapshot) throws {
        let cleaned = title.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cleaned.isEmpty, cleaned.count <= 200, cleaned.utf8.count <= 800,
              !cleaned.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) }),
              !hasExpiry || expiryDate.timeIntervalSinceReferenceDate.isFinite else {
            throw BatchImportError.invalidMetadata
        }
        guard travelerID == nil || library.travelers.contains(where: { $0.id == travelerID }) else {
            throw BatchImportError.missingTraveler
        }
    }

    func importInput() -> DocumentImportInput {
        DocumentImportInput(data: originalData, originalFilename: filename,
            travelerID: travelerID, title: title.trimmingCharacters(in: .whitespacesAndNewlines),
            kind: kind, expiryDate: hasExpiry ? TravelDate.stored(from: expiryDate) : nil)
    }
}

enum BatchImportError: LocalizedError {
    case proRequired, invalidSelection, noSpace, invalidFilename, invalidMetadata
    case missingTraveler, reviewRequired, libraryChanged

    var errorDescription: String? {
        switch self {
        case .proRequired:
            L10n.service("services.batch.proRequired", defaultValue: "Pro is required to prepare and save multiple files. No files were added.")
        case .invalidSelection:
            L10n.service("services.batch.invalidSelection", defaultValue: "Choose between 1 and 10 files. No files were prepared or added.")
        case .noSpace:
            L10n.service("services.batch.noSpace", defaultValue: "These files exceed the remaining space in the 64 MiB library. Choose fewer or smaller files. No files were added.")
        case .invalidFilename:
            L10n.service("services.batch.invalidFilename", defaultValue: "A selected filename cannot be imported. Rename it in Files and choose the files again. No files were added.")
        case .invalidMetadata:
            L10n.service("services.batch.invalidMetadata", defaultValue: "Enter a title of at most 200 characters without control characters, and confirm a valid expiry date if you need one.")
        case .missingTraveler:
            L10n.service("services.batch.missingTraveler", defaultValue: "Choose a person currently in the library or Everyone / unassigned.")
        case .reviewRequired:
            L10n.service("services.batch.reviewRequired", defaultValue: "Review and confirm every remaining document before saving.")
        case .libraryChanged:
            L10n.service("services.batch.libraryChanged", defaultValue: "The library changed while you were preparing files. Start a new batch using its current trips and people. No files were added.")
        }
    }
}
