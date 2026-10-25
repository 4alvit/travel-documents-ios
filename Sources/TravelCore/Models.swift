import Foundation

public struct Trip: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var title: String
    public var departureDate: Date?

    public init(id: UUID = UUID(), title: String, departureDate: Date? = nil) {
        self.id = id
        self.title = title
        self.departureDate = departureDate
    }
}

public struct Traveler: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var name: String

    public init(id: UUID = UUID(), name: String) {
        self.id = id
        self.name = name
    }
}

public enum DocumentKind: String, Codable, CaseIterable, Sendable {
    case passport, insurance, ticket, booking, other

    public var displayName: String { localizedDisplayName() }

    func localizedDisplayName(preferredLanguages: [String]? = nil) -> String {
        switch self {
        case .passport:
            CoreLocalization.text("documentKind.passport",
                                  defaultValue: "Passport",
                                  preferredLanguages: preferredLanguages)
        case .insurance:
            CoreLocalization.text("documentKind.insurance",
                                  defaultValue: "Insurance",
                                  preferredLanguages: preferredLanguages)
        case .ticket:
            CoreLocalization.text("documentKind.ticket",
                                  defaultValue: "Ticket",
                                  preferredLanguages: preferredLanguages)
        case .booking:
            CoreLocalization.text("documentKind.booking",
                                  defaultValue: "Booking",
                                  preferredLanguages: preferredLanguages)
        case .other:
            CoreLocalization.text("documentKind.other",
                                  defaultValue: "Other",
                                  preferredLanguages: preferredLanguages)
        }
    }
}

public struct TravelDocument: Codable, Equatable, Sendable, Identifiable {
    public var id: UUID
    public var tripID: UUID
    public var travelerID: UUID?
    public var title: String
    public var kind: DocumentKind
    public var expiryDate: Date?
    public var originalFilename: String
    public var storedFilename: String
    public var byteCount: Int
    public var sha256: String
    public var importedAt: Date

    public init(id: UUID = UUID(), tripID: UUID, travelerID: UUID? = nil,
                title: String, kind: DocumentKind, expiryDate: Date? = nil,
                originalFilename: String, storedFilename: String,
                byteCount: Int, sha256: String, importedAt: Date = Date()) {
        self.id = id
        self.tripID = tripID
        self.travelerID = travelerID
        self.title = title
        self.kind = kind
        self.expiryDate = expiryDate
        self.originalFilename = originalFilename
        self.storedFilename = storedFilename
        self.byteCount = byteCount
        self.sha256 = sha256
        self.importedAt = importedAt
    }
}

public struct LibrarySnapshot: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var trips: [Trip]
    public var travelers: [Traveler]
    public var documents: [TravelDocument]

    public init(schemaVersion: Int = 1, trips: [Trip] = [], travelers: [Traveler] = [], documents: [TravelDocument] = []) {
        self.schemaVersion = schemaVersion
        self.trips = trips
        self.travelers = travelers
        self.documents = documents
    }

    public static var empty: LibrarySnapshot { LibrarySnapshot() }
}

public enum ReadinessState: String, Codable, Equatable, Sendable {
    case ready, missing, modified, unreadable
}

public struct DocumentReadiness: Codable, Equatable, Sendable {
    public var documentID: UUID
    public var state: ReadinessState
    public var checkedAt: Date

    public init(documentID: UUID, state: ReadinessState, checkedAt: Date = Date()) {
        self.documentID = documentID
        self.state = state
        self.checkedAt = checkedAt
    }
}

public enum RepositoryError: Error, LocalizedError, Equatable, Sendable {
    case invalidImportCount
    case invalidName, unsupportedFileType, invalidFile, documentTooLarge, libraryTooLarge, archiveTooLarge
    case invalidArchive, invalidCatalog, unsupportedSchema, missingReference, duplicateIdentifier
    case documentNotFound, tripNotFound, travelerNotFound
    case originalMissing, originalModified, unreadableOriginal, storageUnavailable, saveFailed

    public var errorDescription: String? { localizedErrorDescription() }

    func localizedErrorDescription(preferredLanguages: [String]? = nil) -> String {
        switch self {
        case .invalidImportCount:
            CoreLocalization.text("repositoryError.invalidImportCount",
                                  defaultValue: "Choose between 1 and 10 documents for one import.",
                                  preferredLanguages: preferredLanguages)
        case .invalidName:
            CoreLocalization.text("repositoryError.invalidName",
                                  defaultValue: "Enter a nonempty name of at most 200 characters and use a simple filename.",
                                  preferredLanguages: preferredLanguages)
        case .unsupportedFileType:
            CoreLocalization.text("repositoryError.unsupportedFileType",
                                  defaultValue: "Only PDF, JPEG, and PNG originals are supported.",
                                  preferredLanguages: preferredLanguages)
        case .invalidFile:
            CoreLocalization.text("repositoryError.invalidFile",
                                  defaultValue: "This file cannot be opened safely. Use an unlocked PDF or a complete JPEG/PNG image of at most 32 megapixels.",
                                  preferredLanguages: preferredLanguages)
        case .documentTooLarge:
            CoreLocalization.text("repositoryError.documentTooLarge",
                                  defaultValue: "Each original must be no larger than 16 MiB.",
                                  preferredLanguages: preferredLanguages)
        case .libraryTooLarge:
            CoreLocalization.text("repositoryError.libraryTooLarge",
                                  defaultValue: "This library exceeds its storage or item limit. Export a backup before removing documents.",
                                  preferredLanguages: preferredLanguages)
        case .archiveTooLarge:
            CoreLocalization.text("repositoryError.archiveTooLarge",
                                  defaultValue: "The backup exceeds the 96 MiB input limit.",
                                  preferredLanguages: preferredLanguages)
        case .invalidArchive:
            CoreLocalization.text("repositoryError.invalidArchive",
                                  defaultValue: "The backup is incomplete or invalid. Your current library has not been replaced.",
                                  preferredLanguages: preferredLanguages)
        case .invalidCatalog:
            CoreLocalization.text("repositoryError.invalidCatalog",
                                  defaultValue: "The saved library cannot be read safely. Keep your backup and try restoring it.",
                                  preferredLanguages: preferredLanguages)
        case .unsupportedSchema:
            CoreLocalization.text("repositoryError.unsupportedSchema",
                                  defaultValue: "This library uses an unsupported format version.",
                                  preferredLanguages: preferredLanguages)
        case .missingReference:
            CoreLocalization.text("repositoryError.missingReference",
                                  defaultValue: "A referenced trip or traveler does not exist.",
                                  preferredLanguages: preferredLanguages)
        case .duplicateIdentifier:
            CoreLocalization.text("repositoryError.duplicateIdentifier",
                                  defaultValue: "The library contains duplicate identifiers or stored filenames.",
                                  preferredLanguages: preferredLanguages)
        case .documentNotFound:
            CoreLocalization.text("repositoryError.documentNotFound",
                                  defaultValue: "This document no longer exists in the library.",
                                  preferredLanguages: preferredLanguages)
        case .tripNotFound:
            CoreLocalization.text("repositoryError.tripNotFound",
                                  defaultValue: "This trip no longer exists in the library.",
                                  preferredLanguages: preferredLanguages)
        case .travelerNotFound:
            CoreLocalization.text("repositoryError.travelerNotFound",
                                  defaultValue: "This traveler no longer exists in the library.",
                                  preferredLanguages: preferredLanguages)
        case .originalMissing:
            CoreLocalization.text("repositoryError.originalMissing",
                                  defaultValue: "The complete original is missing. Restore it from a backup.",
                                  preferredLanguages: preferredLanguages)
        case .originalModified:
            CoreLocalization.text("repositoryError.originalModified",
                                  defaultValue: "The complete original has changed or is damaged. Restore it from a backup.",
                                  preferredLanguages: preferredLanguages)
        case .unreadableOriginal:
            CoreLocalization.text("repositoryError.unreadableOriginal",
                                  defaultValue: "The complete original cannot be read. Unlock your device and try again.",
                                  preferredLanguages: preferredLanguages)
        case .storageUnavailable:
            CoreLocalization.text("repositoryError.storageUnavailable",
                                  defaultValue: "Local storage cannot be accessed. Unlock your device and try again.",
                                  preferredLanguages: preferredLanguages)
        case .saveFailed:
            CoreLocalization.text("repositoryError.saveFailed",
                                  defaultValue: "The change could not be saved. Check available storage and try again; the previous library is preserved.",
                                  preferredLanguages: preferredLanguages)
        }
    }
}
