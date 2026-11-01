import Foundation
import XCTest
@testable import TravelCore

final class LocalizationTests: XCTestCase {
    func testBothPackagedTablesContainEveryPresentationKey() throws {
        let module = CoreLocalization.resourceBundle
        XCTAssertEqual(module.developmentLocalization, "en")
        XCTAssertTrue(module.localizations.contains("en"))
        XCTAssertTrue(module.localizations.contains("ru"))
        let keys = DocumentKind.allCases.map { "documentKind.\($0.rawValue)" } + errorKeys
        XCTAssertEqual(keys.count, 25)
        for language in ["en", "ru"] {
            let url = try XCTUnwrap(module.url(forResource: language, withExtension: "lproj"))
            let bundle = try XCTUnwrap(Bundle(url: url))
            // Missing resources must fail even when the production English default hides them.
            for key in keys {
                let value = bundle.localizedString(forKey: key, value: "__MISSING__", table: "Core")
                XCTAssertNotEqual(value, "__MISSING__", "Missing \(language) translation: \(key)")
                XCTAssertNotEqual(value, key)
                XCTAssertFalse(value.isEmpty)
            }
        }
    }

    func testDocumentKindsResolveEnglishAndRussianResources() {
        let names: [(DocumentKind, String, String)] = [
            (.passport, "Passport", "Паспорт"),
            (.insurance, "Insurance", "Страховка"),
            (.ticket, "Ticket", "Билет"),
            (.booking, "Booking", "Бронирование"),
            (.other, "Other", "Другое")
        ]
        for (kind, english, russian) in names {
            XCTAssertEqual(kind.localizedDisplayName(preferredLanguages: ["en"]), english)
            XCTAssertEqual(kind.localizedDisplayName(preferredLanguages: ["ru"]), russian)
            XCTAssertTrue([english, russian].contains(kind.displayName))
        }
    }

    func testRepositoryErrorsRetainEnglishAndResolveRussian() {
        let errors: [(RepositoryError, String)] = [
            (.invalidImportCount, "Choose between 1 and 10 documents for one import."),
            (.invalidName, "Enter a nonempty name of at most 200 characters and use a simple filename."),
            (.unsupportedFileType, "Only PDF, JPEG, and PNG originals are supported."),
            (.invalidFile, "This file cannot be opened safely. Use an unlocked PDF or a complete JPEG/PNG image of at most 32 megapixels."),
            (.documentTooLarge, "Each original must be no larger than 16 MiB."),
            (.libraryTooLarge, "This library exceeds its storage or item limit. Export a backup before removing documents."),
            (.archiveTooLarge, "The backup exceeds the 96 MiB input limit."),
            (.invalidArchive, "The backup is incomplete or invalid. Your current library has not been replaced."),
            (.invalidCatalog, "The saved library cannot be read safely. Keep your backup and try restoring it."),
            (.unsupportedSchema, "This library uses an unsupported format version."),
            (.missingReference, "A referenced trip or traveler does not exist."),
            (.duplicateIdentifier, "The library contains duplicate identifiers or stored filenames."),
            (.documentNotFound, "This document no longer exists in the library."),
            (.tripNotFound, "This trip no longer exists in the library."),
            (.travelerNotFound, "This traveler no longer exists in the library."),
            (.originalMissing, "The complete original is missing. Restore it from a backup."),
            (.originalModified, "The complete original has changed or is damaged. Restore it from a backup."),
            (.unreadableOriginal, "The complete original cannot be read. Unlock your device and try again."),
            (.storageUnavailable, "Local storage cannot be accessed. Unlock your device and try again."),
            (.saveFailed, "The change could not be saved. Check available storage and try again; the previous library is preserved."),
        ]
        for (error, english) in errors {
            XCTAssertEqual(error.localizedErrorDescription(preferredLanguages: ["en"]), english)
            let russian = error.localizedErrorDescription(preferredLanguages: ["ru"])
            XCTAssertNotEqual(russian, english)
            XCTAssertTrue(russian.unicodeScalars.contains { (0x0400...0x04FF).contains($0.value) })
            XCTAssertEqual(error.localizedDescription, error.errorDescription)
        }
        XCTAssertEqual(RepositoryError.invalidArchive.localizedErrorDescription(preferredLanguages: ["ru"]),
                       "Резервная копия неполная или недействительна. Текущая библиотека не заменена.")
        XCTAssertEqual(RepositoryError.originalMissing.localizedErrorDescription(preferredLanguages: ["ru"]),
                       "Полный оригинал отсутствует. Восстановите его из резервной копии.")
    }

    func testLanguagePreferenceAndRegionAreIndependentAndUnsupportedLanguageFallsBack() {
        for preferences in [["ru-US"], ["ru-RU"], ["fr-FR", "ru"], ["ru", "en"]] {
            XCTAssertEqual(DocumentKind.ticket.localizedDisplayName(preferredLanguages: preferences), "Билет")
        }
        for preferences in [["en-RU"], ["fr-FR"], ["zz"], [], ["en", "ru"]] {
            XCTAssertEqual(DocumentKind.ticket.localizedDisplayName(preferredLanguages: preferences), "Ticket")
        }
        XCTAssertEqual(RepositoryError.documentTooLarge.localizedErrorDescription(preferredLanguages: ["fr-FR"]),
                       "Each original must be no larger than 16 MiB.")
    }

    func testMissingKeyUsesReadableEnglishDefaultForEitherLanguage() {
        for language in ["ru", "en", "fr"] {
            XCTAssertEqual(CoreLocalization.text("test.absent.key", defaultValue: "Readable fallback",
                                                preferredLanguages: [language]), "Readable fallback")
        }
    }

    func testLocalizationPreservesRawIdentifiersAndEncodedSchema() throws {
        let rawKinds = ["passport", "insurance", "ticket", "booking", "other"]
        XCTAssertEqual(DocumentKind.allCases.map(\.rawValue), rawKinds)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        for (kind, raw) in zip(DocumentKind.allCases, rawKinds) {
            XCTAssertEqual(String(data: try encoder.encode(kind), encoding: .utf8), "\"\(raw)\"")
            XCTAssertEqual(try JSONDecoder().decode(DocumentKind.self, from: Data("\"\(raw)\"".utf8)), kind)
        }
        for (state, raw) in [(ReadinessState.ready, "ready"), (.missing, "missing"),
                             (.modified, "modified"), (.unreadable, "unreadable")] {
            XCTAssertEqual(String(data: try encoder.encode(state), encoding: .utf8), "\"\(raw)\"")
        }
        let trip = Trip(id: UUID(uuidString: "00000000-0000-0000-0000-000000000001")!, title: "Моя поездка")
        let original = TravelDocument(
            id: UUID(uuidString: "00000000-0000-0000-0000-000000000002")!, tripID: trip.id,
            title: "My original title", kind: .ticket, originalFilename: "Билет.pdf",
            storedFilename: "unchanged.pdf", byteCount: 123, sha256: "unchanged",
            importedAt: Date(timeIntervalSinceReferenceDate: 0))
        let snapshot = LibrarySnapshot(trips: [trip], documents: [original])
        let before = try encoder.encode(snapshot)
        for language in ["ru", "en", "ru-US", "fr"] {
            _ = original.kind.localizedDisplayName(preferredLanguages: [language])
            _ = RepositoryError.invalidArchive.localizedErrorDescription(preferredLanguages: [language])
        }
        XCTAssertEqual(try encoder.encode(snapshot), before)
        let decoded = try JSONDecoder().decode(LibrarySnapshot.self, from: before)
        XCTAssertEqual(decoded, snapshot)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: before) as? [String: Any])
        XCTAssertEqual(Set(json.keys), ["schemaVersion", "trips", "travelers", "documents"])
        XCTAssertEqual(json["schemaVersion"] as? Int, 1)
        let documents = try XCTUnwrap(json["documents"] as? [[String: Any]])
        XCTAssertEqual(Set(try XCTUnwrap(documents.first).keys),
                       ["id", "tripID", "title", "kind", "originalFilename", "storedFilename", "byteCount", "sha256", "importedAt"])
        XCTAssertEqual(documents.first?["kind"] as? String, "ticket")
        XCTAssertEqual(decoded.documents.first?.originalFilename, "Билет.pdf")
    }

    private var errorKeys: [String] {
        ["repositoryError.invalidImportCount",
         "repositoryError.invalidName",
         "repositoryError.unsupportedFileType",
         "repositoryError.invalidFile",
         "repositoryError.documentTooLarge",
         "repositoryError.libraryTooLarge",
         "repositoryError.archiveTooLarge",
         "repositoryError.invalidArchive",
         "repositoryError.invalidCatalog",
         "repositoryError.unsupportedSchema",
         "repositoryError.missingReference",
         "repositoryError.duplicateIdentifier",
         "repositoryError.documentNotFound",
         "repositoryError.tripNotFound",
         "repositoryError.travelerNotFound",
         "repositoryError.originalMissing",
         "repositoryError.originalModified",
         "repositoryError.unreadableOriginal",
         "repositoryError.storageUnavailable",
         "repositoryError.saveFailed"]
    }
}
