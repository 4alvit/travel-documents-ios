import Foundation
import XCTest
import CoreGraphics
import ImageIO
@testable import TravelCore

final class DocumentRepositoryTests: XCTestCase, @unchecked Sendable {
    private func root() throws -> URL {
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("TripfolioTests-" + UUID().uuidString)
        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: url) }
        return url
    }

    private var pdf: Data { Self.syntheticPDF }

    private static let syntheticPDF: Data = {
        let bytes = NSMutableData()
        let consumer = CGDataConsumer(data: bytes)!
        var mediaBox = CGRect(x: 0, y: 0, width: 200, height: 200)
        let context = CGContext(consumer: consumer, mediaBox: &mediaBox, nil)!
        context.beginPDFPage(nil)
        context.setFillColor(CGColor(gray: 0.5, alpha: 1))
        context.fill(CGRect(x: 20, y: 20, width: 160, height: 160))
        context.endPDFPage()
        context.closePDF()
        return bytes as Data
    }()

    private func imageData(type: String, width: Int = 2, height: Int = 2) -> Data {
        let context = CGContext(data: nil, width: width, height: height, bitsPerComponent: 8,
            bytesPerRow: width * 4, space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)!
        context.setFillColor(CGColor(gray: 0.5, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let image = context.makeImage()!
        let data = NSMutableData()
        let destination = CGImageDestinationCreateWithData(data, type as CFString, 1, nil)!
        CGImageDestinationAddImage(destination, image, nil)
        XCTAssertTrue(CGImageDestinationFinalize(destination))
        return data as Data
    }

    private func addDocument(to repository: DocumentRepository, trip: Trip, traveler: Traveler? = nil,
                             filename: String = "synthetic.pdf", title: String = "Synthetic booking") async throws -> TravelDocument {
        try await repository.importDocument(data: pdf, originalFilename: filename, tripID: trip.id,
            travelerID: traveler?.id, title: title, kind: .booking, expiryDate: Date(timeIntervalSince1970: 2_000_000_000))
    }

    private func mutateArchive(_ data: Data, _ mutation: (inout [String: Any]) -> Void) throws -> Data {
        var json = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        mutation(&json)
        return try JSONSerialization.data(withJSONObject: json, options: [.sortedKeys])
    }

    private func originalURL(root: URL, document: TravelDocument) throws -> URL {
        let data = try Data(contentsOf: root.appendingPathComponent("active.json"))
        let pointer = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        let generation = try XCTUnwrap(pointer["generation"] as? String)
        return root.appendingPathComponent(generation).appendingPathComponent(document.storedFilename)
    }

    func testPortableBackupActuallyRestoresFullOriginalsIntoFreshInstallation() async throws {
        let source = try DocumentRepository(rootURL: root())
        let trip = try await source.createTrip(title: "Synthetic trip", departureDate: Date(timeIntervalSince1970: 1_999_000_000))
        let traveler = try await source.addTraveler(name: "Example Traveler")
        let document = try await addDocument(to: source, trip: trip, traveler: traveler)
        _ = try await source.createTrip(title: "Empty future trip", departureDate: nil)
        let expected = try await source.load()
        let backup = try await source.exportBackup(documentIDs: nil)
        let destinationRoot = try root()
        let destination = try DocumentRepository(rootURL: destinationRoot)
        let restored = try await destination.restoreBackup(backup)
        XCTAssertEqual(restored, expected)
        let bytes = try await destination.documentData(id: document.id)
        XCTAssertEqual(bytes, pdf)
        let readiness = try await destination.verifyReadiness(tripID: trip.id)
        XCTAssertEqual(readiness.map(\.state), [.ready])
        let reopened = try DocumentRepository(rootURL: destinationRoot)
        let reopenedLibrary = try await reopened.load()
        let reopenedBytes = try await reopened.documentData(id: document.id)
        XCTAssertEqual(reopenedLibrary, expected)
        XCTAssertEqual(reopenedBytes, pdf)
    }

    func testSelectionIncludesOnlySelectedOriginalsAndReferencedPeopleAndTrips() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let tripA = try await repository.createTrip(title: "First trip", departureDate: nil)
        let tripB = try await repository.createTrip(title: "Second trip", departureDate: nil)
        let travelerA = try await repository.addTraveler(name: "First synthetic person")
        let travelerB = try await repository.addTraveler(name: "Second synthetic person")
        let selected = try await addDocument(to: repository, trip: tripA, traveler: travelerA)
        _ = try await addDocument(to: repository, trip: tripB, traveler: travelerB)
        let backup = try await repository.exportBackup(documentIDs: [selected.id])
        let destination = try DocumentRepository(rootURL: root())
        let restored = try await destination.restoreBackup(backup)
        XCTAssertEqual(restored.trips, [tripA])
        XCTAssertEqual(restored.travelers, [travelerA])
        XCTAssertEqual(restored.documents, [selected])
        let original = try await destination.documentData(id: selected.id)
        XCTAssertEqual(original, pdf)
        do {
            _ = try await repository.exportBackup(documentIDs: [UUID()])
            XCTFail("Unknown selections must not silently produce incomplete exports")
        } catch { XCTAssertEqual(error as? RepositoryError, .documentNotFound) }
    }

    func testReadinessHashesTheWholeOriginalAndRejectsMissingFiles() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let modified = try await addDocument(to: repository, trip: trip)
        let missing = try await addDocument(to: repository, trip: trip)
        let modifiedURL = try originalURL(root: repositoryRoot, document: modified)
        var changedBytes = pdf
        changedBytes[changedBytes.count - 1] ^= 1 // same byte count and same signature
        try changedBytes.write(to: modifiedURL)
        try FileManager.default.removeItem(at: originalURL(root: repositoryRoot, document: missing))
        let readiness = try await repository.verifyReadiness(tripID: trip.id)
        XCTAssertEqual(readiness.map(\.state), [.modified, .missing])
        do {
            _ = try await repository.documentData(id: modified.id)
            XCTFail("Preview must not return damaged originals")
        } catch { XCTAssertEqual(error as? RepositoryError, .originalModified) }
        do {
            _ = try await repository.exportBackup(documentIDs: nil)
            XCTFail("Backup must not certify damaged originals")
        } catch { XCTAssertEqual(error as? RepositoryError, .originalModified) }
    }

    func testSymlinkOriginalIsUnreadableAndNeverFollowed() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let document = try await addDocument(to: repository, trip: trip)
        let file = try originalURL(root: repositoryRoot, document: document)
        let outside = try root().appendingPathComponent("outside.pdf")
        try pdf.write(to: outside)
        try FileManager.default.removeItem(at: file)
        try FileManager.default.createSymbolicLink(at: file, withDestinationURL: outside)
        let readiness = try await repository.verifyReadiness(tripID: trip.id)
        XCTAssertEqual(readiness.map(\.state), [.unreadable])
    }

    func testInvalidReferencesAndSignaturesDoNotAlterLibrary() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let before = try await repository.load()
        for (data, tripID, filename, expected) in [
            (Data("not a PDF".utf8), trip.id, "false.pdf", RepositoryError.unsupportedFileType),
            (pdf, UUID(), "synthetic.pdf", .missingReference),
            (pdf, trip.id, "../outside.pdf", .invalidName)
        ] {
            do {
                _ = try await repository.importDocument(data: data, originalFilename: filename,
                    tripID: tripID, travelerID: nil, title: "Synthetic", kind: .other, expiryDate: nil)
                XCTFail("Invalid input should fail")
            } catch { XCTAssertEqual(error as? RepositoryError, expected) }
        }
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testAllRestoreValidationFailuresPreserveExistingLibraryAndBytes() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let trip = try await repository.createTrip(title: "Existing trip", departureDate: nil)
        let document = try await addDocument(to: repository, trip: trip)
        let before = try await repository.load()
        let backup = try await repository.exportBackup(documentIDs: nil)
        let mutations: [(inout [String: Any]) -> Void] = [
            { json in // reference points outside archive
                var library = json["library"] as! [String: Any]
                var docs = library["documents"] as! [[String: Any]]
                docs[0]["tripID"] = UUID().uuidString
                library["documents"] = docs
                json["library"] = library
            },
            { json in // duplicate document id
                var library = json["library"] as! [String: Any]
                var docs = library["documents"] as! [[String: Any]]
                docs.append(docs[0])
                library["documents"] = docs
                json["library"] = library
            },
            { json in // stored filename path traversal
                var library = json["library"] as! [String: Any]
                var docs = library["documents"] as! [[String: Any]]
                docs[0]["storedFilename"] = "../../escaped.pdf"
                library["documents"] = docs
                json["library"] = library
            },
            { json in // missing complete original
                json["originals"] = []
            },
            { json in // modified complete original
                var originals = json["originals"] as! [[String: Any]]
                originals[0]["data"] = Data("%PDF-1.4\nDifferent synthetic bytes".utf8).base64EncodedString()
                json["originals"] = originals
            },
            { json in // duplicate original ID
                var originals = json["originals"] as! [[String: Any]]
                originals.append(originals[0])
                json["originals"] = originals
            },
            { json in // hostile size cannot overflow a total
                var library = json["library"] as! [String: Any]
                var docs = library["documents"] as! [[String: Any]]
                docs[0]["byteCount"] = Int.max
                library["documents"] = docs
                json["library"] = library
            },
            { json in json["formatVersion"] = 999 }
        ]
        for mutation in mutations {
            let malformed = try mutateArchive(backup, mutation)
            do {
                _ = try await repository.restoreBackup(malformed)
                XCTFail("Invalid archive must fail without replacing live data")
            } catch {}
            let after = try await repository.load()
            let bytes = try await repository.documentData(id: document.id)
            XCTAssertEqual(after, before)
            XCTAssertEqual(bytes, pdf)
        }
    }

    func testImportFailureDoesNotPublishPartialCatalog() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let document = try await addDocument(to: repository, trip: trip)
        let before = try await repository.load()
        let pointerBefore = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        // The existing original becomes unavailable during an attempted update.
        // The transaction may prepare files, but must never publish a new catalog.
        try FileManager.default.removeItem(at: originalURL(root: repositoryRoot, document: document))
        do {
            _ = try await addDocument(to: repository, trip: trip)
            XCTFail("Transaction should abort when a required original is missing")
        } catch { XCTAssertEqual(error as? RepositoryError, .originalMissing) }
        let pointerAfter = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        let after = try await repository.load()
        XCTAssertEqual(pointerAfter, pointerBefore)
        XCTAssertEqual(after, before)
        let children = try FileManager.default.contentsOfDirectory(at: repositoryRoot, includingPropertiesForKeys: nil)
        XCTAssertEqual(children.filter { UUID(uuidString: $0.lastPathComponent) != nil }.count, 1)
    }

    func testDiskFullBeforePublicationPreservesExistingLibraryAndRemovesStaging() async throws {
        let destinationRoot = try root()
        let originalRepository = try DocumentRepository(rootURL: destinationRoot)
        let originalTrip = try await originalRepository.createTrip(title: "Existing trip", departureDate: nil)
        let originalDocument = try await addDocument(to: originalRepository, trip: originalTrip)
        let expected = try await originalRepository.load()
        let pointerBefore = try Data(contentsOf: destinationRoot.appendingPathComponent("active.json"))

        let replacement = try DocumentRepository(rootURL: root())
        let replacementTrip = try await replacement.createTrip(title: "Replacement trip", departureDate: nil)
        _ = try await addDocument(to: replacement, trip: replacementTrip)
        let replacementBackup = try await replacement.exportBackup(documentIDs: nil)

        let failingRepository = try DocumentRepository(rootURL: destinationRoot) { bytes, url in
            // Originals and catalog have already been staged when this fails.
            if url.lastPathComponent.hasPrefix(".pending-") { throw CocoaError(.fileWriteOutOfSpace) }
            try bytes.write(to: url, options: .atomic)
        }
        do {
            _ = try await failingRepository.restoreBackup(replacementBackup)
            XCTFail("Disk-full failure before publication must abort replacement")
        } catch { XCTAssertEqual(error as? RepositoryError, .saveFailed) }
        let recovered = try DocumentRepository(rootURL: destinationRoot)
        let after = try await recovered.load()
        let originalBytes = try await recovered.documentData(id: originalDocument.id)
        XCTAssertEqual(after, expected)
        XCTAssertEqual(originalBytes, pdf)
        XCTAssertEqual(try Data(contentsOf: destinationRoot.appendingPathComponent("active.json")), pointerBefore)
        let children = try FileManager.default.contentsOfDirectory(at: destinationRoot, includingPropertiesForKeys: nil)
        XCTAssertEqual(children.filter { UUID(uuidString: $0.lastPathComponent) != nil }.count, 1)
        XCTAssertFalse(children.contains { $0.lastPathComponent.hasPrefix(".pending-") })
    }

    func testSelectiveBackupCanRecoverHealthyDocumentsBesideCorruptOriginal() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let healthy = try await addDocument(to: repository, trip: trip)
        let damaged = try await addDocument(to: repository, trip: trip)
        try Data("damaged".utf8).write(to: originalURL(root: repositoryRoot, document: damaged))
        let healthyBackup = try await repository.exportBackup(documentIDs: [healthy.id])
        let recovered = try DocumentRepository(rootURL: root())
        let library = try await recovered.restoreBackup(healthyBackup)
        let bytes = try await recovered.documentData(id: healthy.id)
        XCTAssertEqual(library.documents, [healthy])
        XCTAssertEqual(bytes, pdf)
        do {
            _ = try await repository.exportBackup(documentIDs: [damaged.id])
            XCTFail("An explicitly selected damaged original must not be silently omitted")
        } catch { XCTAssertEqual(error as? RepositoryError, .originalModified) }
    }

    func testDeletePreservesOtherDocumentsAndCanRemoveMissingOriginal() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let first = try await addDocument(to: repository, trip: trip)
        let second = try await addDocument(to: repository, trip: trip)
        try FileManager.default.removeItem(at: originalURL(root: repositoryRoot, document: first))
        try await repository.deleteDocument(id: first.id)
        let library = try await repository.load()
        let bytes = try await repository.documentData(id: second.id)
        XCTAssertEqual(library.documents, [second])
        XCTAssertEqual(bytes, pdf)
    }

    func testRecoveryCanReplaceUnreadableCatalog() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let document = try await addDocument(to: repository, trip: trip)
        let backup = try await repository.exportBackup(documentIDs: nil)
        try Data("corrupt pointer".utf8).write(to: repositoryRoot.appendingPathComponent("active.json"))
        do {
            _ = try await repository.load()
            XCTFail("Corruption must not appear as an empty library")
        } catch { XCTAssertEqual(error as? RepositoryError, .invalidCatalog) }
        _ = try await repository.restoreBackup(backup)
        let bytes = try await repository.documentData(id: document.id)
        XCTAssertEqual(bytes, pdf)
    }

    func testMissingPointerPreservesSurvivingOriginalsAndRequiresRecovery() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let document = try await addDocument(to: repository, trip: trip)
        let backup = try await repository.exportBackup(documentIDs: nil)
        let survivingOriginal = try originalURL(root: repositoryRoot, document: document)
        try FileManager.default.removeItem(at: repositoryRoot.appendingPathComponent("active.json"))
        do {
            _ = try await repository.load()
            XCTFail("Missing pointer must not hide a surviving library")
        } catch { XCTAssertEqual(error as? RepositoryError, .invalidCatalog) }
        do {
            _ = try await repository.createTrip(title: "Must not replace survivors", departureDate: nil)
            XCTFail("Mutations must not garbage-collect surviving data")
        } catch { XCTAssertEqual(error as? RepositoryError, .invalidCatalog) }
        let reopened = try DocumentRepository(rootURL: repositoryRoot)
        do {
            _ = try await reopened.createTrip(title: "Still must not replace survivors", departureDate: nil)
            XCTFail("Initialization must not reset a missing pointer beside committed originals")
        } catch { XCTAssertEqual(error as? RepositoryError, .invalidCatalog) }
        XCTAssertEqual(try Data(contentsOf: survivingOriginal), pdf)
        _ = try await repository.restoreBackup(backup)
        let recovered = try await repository.documentData(id: document.id)
        XCTAssertEqual(recovered, pdf)
    }

    func testFailedFreshInitializationCanBeRetried() async throws {
        let repositoryRoot = try root()
        do {
            _ = try DocumentRepository(rootURL: repositoryRoot) { _, _ in
                throw CocoaError(.fileWriteOutOfSpace)
            }
            XCTFail("Bootstrap failure must be reported")
        } catch { XCTAssertEqual(error as? RepositoryError, .storageUnavailable) }
        // An interrupted atomic bootstrap write may leave a temporary file,
        // but cannot have generated any document generation yet.
        try Data("{\"formatVersion\":1".utf8).write(to: repositoryRoot.appendingPathComponent(".bootstrap-interrupted"))
        let reopened = try DocumentRepository(rootURL: repositoryRoot)
        let empty = try await reopened.load()
        XCTAssertEqual(empty, .empty)
        let trip = try await reopened.createTrip(title: "First successful trip", departureDate: nil)
        let library = try await reopened.load()
        XCTAssertEqual(library.trips, [trip])
    }

    func testInterruptedFirstRestoreCanReopenBeforeCatalogAndBeforePublication() async throws {
        let source = try DocumentRepository(rootURL: root())
        let sourceTrip = try await source.createTrip(title: "Portable synthetic trip", departureDate: nil)
        _ = try await addDocument(to: source, trip: sourceTrip)
        let backup = try await source.exportBackup(documentIDs: nil)

        for failureBeforeCatalog in [true, false] {
            let liveRoot = try root()
            let snapshotRoot = try root().appendingPathComponent("interrupted-store", isDirectory: true)
            let failing = try DocumentRepository(rootURL: liveRoot) { data, url in
                let atFailurePoint = failureBeforeCatalog
                    ? url.lastPathComponent == "catalog.json"
                    : url.lastPathComponent.hasPrefix(".pending-")
                if atFailurePoint {
                    // Preserve the actual on-disk transaction state before the
                    // normal error handler removes staging. Reopening this copy
                    // simulates process death with no defer/rollback execution.
                    try FileManager.default.copyItem(at: liveRoot, to: snapshotRoot)
                    throw CocoaError(.fileWriteOutOfSpace)
                }
                try data.write(to: url, options: .atomic)
            }
            do {
                _ = try await failing.restoreBackup(backup)
                XCTFail("The first restore should fail at the injected write boundary")
            } catch { XCTAssertEqual(error as? RepositoryError, .saveFailed) }
            let stillEmpty = try await failing.load()
            XCTAssertEqual(stillEmpty, .empty)

            let interrupted = try DocumentRepository(rootURL: snapshotRoot)
            let afterCrash = try await interrupted.load()
            XCTAssertEqual(afterCrash, .empty, "Incomplete first work must not strand a new installation")
            let newTrip = try await interrupted.createTrip(title: "Continue after interruption", departureDate: nil)
            let newDocument = try await addDocument(to: interrupted, trip: newTrip)
            let afterRetry = try await interrupted.load()
            XCTAssertEqual(afterRetry.trips, [newTrip])
            XCTAssertEqual(afterRetry.documents, [newDocument])
            let bytes = try await interrupted.documentData(id: newDocument.id)
            XCTAssertEqual(bytes, pdf)
        }
    }

    func testTruncatedFilesAreRejectedAndRealImagesSurviveRestore() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        let truncated: [(Data, String)] = [
            (Data("%PDF-1.4\n%%EOF".utf8), "fake.pdf"),
            (Data([0xFF, 0xD8, 0xFF]), "fake.jpg"),
            (Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]), "fake.png"),
            (Data(pdf.prefix(pdf.count / 2)), "cut.pdf")
        ]
        for (bytes, filename) in truncated {
            do {
                _ = try await repository.importDocument(data: bytes, originalFilename: filename,
                    tripID: trip.id, travelerID: nil, title: "Truncated synthetic file", kind: .other, expiryDate: nil)
                XCTFail("A recognizable signature alone is insufficient")
            } catch { XCTAssertEqual(error as? RepositoryError, .invalidFile) }
        }
        let png = imageData(type: "public.png")
        let jpg = imageData(type: "public.jpeg")
        var originals: [UUID: Data] = [:]
        for (bytes, filename) in [(png, "synthetic.png"), (jpg, "synthetic.jpg")] {
            let document = try await repository.importDocument(data: bytes, originalFilename: filename,
                tripID: trip.id, travelerID: nil, title: "Synthetic image", kind: .other, expiryDate: nil)
            originals[document.id] = bytes
        }
        let backup = try await repository.exportBackup(documentIDs: nil)
        let destination = try DocumentRepository(rootURL: root())
        _ = try await destination.restoreBackup(backup)
        for (id, bytes) in originals {
            let restored = try await destination.documentData(id: id)
            XCTAssertEqual(restored, bytes)
        }
        let readiness = try await destination.verifyReadiness(tripID: trip.id)
        XCTAssertEqual(readiness.map(\.state), [.ready, .ready])
    }

    func testDeletingTripRemovesItsOriginalsAndFreesTheLibraryForANewTrip() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let deletedTrip = try await repository.createTrip(title: "Finished trip", departureDate: nil)
        let keptTrip = try await repository.createTrip(title: "Current trip", departureDate: nil)
        let traveler = try await repository.addTraveler(name: "Synthetic traveler")
        let deletedA = try await addDocument(to: repository, trip: deletedTrip, traveler: traveler)
        let deletedB = try await addDocument(to: repository, trip: deletedTrip, traveler: traveler)
        let kept = try await addDocument(to: repository, trip: keptTrip, traveler: traveler)

        try await repository.deleteTrip(id: deletedTrip.id)
        let library = try await repository.load()
        let keptBytes = try await repository.documentData(id: kept.id)
        XCTAssertEqual(library.trips, [keptTrip])
        XCTAssertEqual(library.travelers, [traveler])
        XCTAssertEqual(library.documents, [kept])
        XCTAssertEqual(keptBytes, pdf)
        let files = try XCTUnwrap(FileManager.default.enumerator(at: repositoryRoot,
            includingPropertiesForKeys: nil)?.allObjects as? [URL])
        XCTAssertFalse(files.contains { $0.lastPathComponent == deletedA.storedFilename })
        XCTAssertFalse(files.contains { $0.lastPathComponent == deletedB.storedFilename })
        XCTAssertEqual(files.filter { $0.pathExtension == "pdf" }.count, 1)

        try await repository.deleteTrip(id: keptTrip.id)
        let cleared = try await repository.load()
        XCTAssertTrue(cleared.trips.isEmpty)
        XCTAssertTrue(cleared.documents.isEmpty)
        XCTAssertEqual(cleared.travelers, [traveler])
        let nextTrip = try await repository.createTrip(title: "Next trip", departureDate: nil)
        let nextDocument = try await addDocument(to: repository, trip: nextTrip, traveler: traveler)
        let reused = try await repository.load()
        XCTAssertEqual(reused.trips, [nextTrip])
        XCTAssertEqual(reused.documents, [nextDocument])
    }

    func testDeletingTravelerUnlinksAcrossTripsAndPreservesAllOriginals() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let firstTrip = try await repository.createTrip(title: "First trip", departureDate: nil)
        let secondTrip = try await repository.createTrip(title: "Second trip", departureDate: nil)
        let deletedTraveler = try await repository.addTraveler(name: "Remove this person")
        let keptTraveler = try await repository.addTraveler(name: "Keep this person")
        var first = try await addDocument(to: repository, trip: firstTrip, traveler: deletedTraveler)
        var second = try await addDocument(to: repository, trip: secondTrip, traveler: deletedTraveler)
        let third = try await addDocument(to: repository, trip: secondTrip, traveler: keptTraveler)

        try await repository.deleteTraveler(id: deletedTraveler.id)
        first.travelerID = nil
        second.travelerID = nil
        let library = try await repository.load()
        XCTAssertEqual(library.travelers, [keptTraveler])
        XCTAssertEqual(library.documents, [first, second, third])
        for document in library.documents {
            let bytes = try await repository.documentData(id: document.id)
            XCTAssertEqual(bytes, pdf)
        }
        for trip in library.trips {
            let readiness = try await repository.verifyReadiness(tripID: trip.id)
            XCTAssertTrue(readiness.allSatisfy { $0.state == .ready })
        }
        let backup = try await repository.exportBackup(documentIDs: nil)
        let restored = try DocumentRepository(rootURL: root())
        let restoredLibrary = try await restored.restoreBackup(backup)
        XCTAssertEqual(restoredLibrary, library)
    }

    func testMetadataUpdatesPreserveOriginalIdentityBytesAndRecoverability() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Initial trip", departureDate: nil)
        let traveler = try await repository.addTraveler(name: "Initial person")
        let replacementTraveler = try await repository.addTraveler(name: "Another person")
        let document = try await addDocument(to: repository, trip: trip, traveler: traveler)
        let departure = Date(timeIntervalSince1970: 2_100_000_000)
        let expiry = Date(timeIntervalSince1970: 2_200_000_000)

        let updatedTrip = try await repository.updateTrip(id: trip.id, title: "  Updated trip  ", departureDate: departure)
        let updatedTraveler = try await repository.updateTraveler(id: traveler.id, name: "  Updated person  ")
        let updatedDocument = try await repository.updateDocument(id: document.id, title: "  Confirmed insurance  ",
            travelerID: replacementTraveler.id, kind: .insurance, expiryDate: expiry)
        XCTAssertEqual(updatedTrip, Trip(id: trip.id, title: "Updated trip", departureDate: departure))
        XCTAssertEqual(updatedTraveler, Traveler(id: traveler.id, name: "Updated person"))
        var expectedDocument = document
        expectedDocument.title = "Confirmed insurance"
        expectedDocument.travelerID = replacementTraveler.id
        expectedDocument.kind = .insurance
        expectedDocument.expiryDate = expiry
        XCTAssertEqual(updatedDocument, expectedDocument)
        let bytes = try await repository.documentData(id: document.id)
        let readiness = try await repository.verifyReadiness(tripID: trip.id)
        XCTAssertEqual(bytes, pdf)
        XCTAssertEqual(readiness.map(\.state), [.ready])

        let clearedDocument = try await repository.updateDocument(id: document.id, title: updatedDocument.title,
            travelerID: nil, kind: .insurance, expiryDate: nil)
        let clearedTrip = try await repository.updateTrip(id: trip.id, title: updatedTrip.title, departureDate: nil)
        XCTAssertNil(clearedDocument.travelerID)
        XCTAssertNil(clearedDocument.expiryDate)
        XCTAssertNil(clearedTrip.departureDate)
        let snapshot = try await repository.load()
        let reopened = try DocumentRepository(rootURL: repositoryRoot)
        let persisted = try await reopened.load()
        XCTAssertEqual(persisted, snapshot)
        let backup = try await reopened.exportBackup(documentIDs: nil)
        let recovered = try DocumentRepository(rootURL: root())
        let recoveredLibrary = try await recovered.restoreBackup(backup)
        let recoveredBytes = try await recovered.documentData(id: document.id)
        XCTAssertEqual(recoveredLibrary, snapshot)
        XCTAssertEqual(recoveredBytes, pdf)
    }

    func testInvalidLifecycleEditsPreserveSnapshotAndCompleteOriginal() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let trip = try await repository.createTrip(title: "Existing trip", departureDate: nil)
        let traveler = try await repository.addTraveler(name: "Existing person")
        let document = try await addDocument(to: repository, trip: trip, traveler: traveler)
        let expected = try await repository.load()
        let invalidOperations: [(RepositoryError, () async throws -> Void)] = [
            (.invalidName, { _ = try await repository.updateTrip(id: trip.id, title: "   ", departureDate: nil) }),
            (.invalidName, { _ = try await repository.updateTrip(id: trip.id, title: "Existing trip",
                departureDate: Date(timeIntervalSince1970: .infinity)) }),
            (.invalidName, { _ = try await repository.updateTraveler(id: traveler.id, name: String(repeating: "x", count: 201)) }),
            (.invalidName, { _ = try await repository.updateDocument(id: document.id, title: "",
                travelerID: traveler.id, kind: .passport, expiryDate: nil) }),
            (.missingReference, { _ = try await repository.updateDocument(id: document.id, title: "Updated title",
                travelerID: UUID(), kind: .passport, expiryDate: nil) }),
            (.tripNotFound, { try await repository.deleteTrip(id: UUID()) }),
            (.travelerNotFound, { try await repository.deleteTraveler(id: UUID()) }),
            (.tripNotFound, { _ = try await repository.updateTrip(id: UUID(), title: "Missing trip", departureDate: nil) }),
            (.travelerNotFound, { _ = try await repository.updateTraveler(id: UUID(), name: "Missing person") }),
            (.documentNotFound, { _ = try await repository.updateDocument(id: UUID(), title: "Missing document",
                travelerID: nil, kind: .other, expiryDate: nil) })
        ]
        for (expectedError, operation) in invalidOperations {
            do {
                try await operation()
                XCTFail("Invalid edits must not publish partial changes")
            } catch { XCTAssertEqual(error as? RepositoryError, expectedError) }
            let snapshot = try await repository.load()
            let bytes = try await repository.documentData(id: document.id)
            XCTAssertEqual(snapshot, expected)
            XCTAssertEqual(bytes, pdf)
        }
    }

    func testImportReviewValidationRequiresSupportedCompleteOriginalWithinLimit() throws {
        for data in [pdf, imageData(type: "public.png"), imageData(type: "public.jpeg")] {
            XCTAssertNoThrow(try DocumentRepository.validateImportData(data))
        }
        let invalid: [(Data, RepositoryError)] = [
            (Data("unsupported".utf8), .unsupportedFileType),
            (Data("%PDF-1.4\n%%EOF".utf8), .invalidFile),
            (Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]), .invalidFile),
            (Data(count: DocumentRepository.maximumDocumentBytes + 1), .documentTooLarge)
        ]
        for (data, expected) in invalid {
            XCTAssertThrowsError(try DocumentRepository.validateImportData(data)) {
                XCTAssertEqual($0 as? RepositoryError, expected)
            }
        }
    }

    func testBatchKeepsInputOrderMetadataAndCompleteOriginalsAcrossPortableRestore() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let trip = try await repository.createTrip(title: "Synthetic batch trip", departureDate: nil)
        let traveler = try await repository.addTraveler(name: "Example Person")
        let existing = try await addDocument(to: repository, trip: trip)
        let expiry = Date(timeIntervalSince1970: 2_000_000_000)
        let inputs = [
            DocumentImportInput(data: imageData(type: "public.png"), originalFilename: "first.png",
                travelerID: traveler.id, title: "  Passport  ", kind: .passport, expiryDate: expiry),
            DocumentImportInput(data: pdf, originalFilename: "second.pdf", title: "Ticket", kind: .ticket),
            DocumentImportInput(data: imageData(type: "public.jpeg"), originalFilename: "third.jpg",
                travelerID: traveler.id, title: "Insurance", kind: .insurance)
        ]
        let imported = try await repository.importDocuments(inputs, tripID: trip.id)
        XCTAssertEqual(imported.map(\.title), ["Passport", "Ticket", "Insurance"])
        XCTAssertEqual(imported.map(\.originalFilename), inputs.map(\.originalFilename))
        XCTAssertEqual(imported.map(\.kind), inputs.map(\.kind))
        XCTAssertEqual(imported.map(\.travelerID), inputs.map(\.travelerID))
        XCTAssertEqual(imported.map(\.expiryDate), inputs.map(\.expiryDate))
        XCTAssertEqual(Set(imported.map(\.id)).count, inputs.count)
        XCTAssertTrue(imported.allSatisfy { $0.tripID == trip.id })
        let expected = try await repository.load()
        XCTAssertEqual(expected.documents, [existing] + imported)

        let backup = try await repository.exportBackup(documentIDs: nil)
        let destination = try DocumentRepository(rootURL: root())
        let restored = try await destination.restoreBackup(backup)
        XCTAssertEqual(restored, expected)
        let existingBytes = try await destination.documentData(id: existing.id)
        XCTAssertEqual(existingBytes, pdf)
        for (document, input) in zip(imported, inputs) {
            let bytes = try await destination.documentData(id: document.id)
            XCTAssertEqual(bytes, input.data)
            XCTAssertEqual(document.byteCount, input.data.count)
        }
        let readiness = try await destination.verifyReadiness(tripID: trip.id)
        XCTAssertEqual(readiness.map(\.state), Array(repeating: .ready, count: 4))

        let selection = try await repository.exportBackup(documentIDs: [imported[0].id, imported[2].id])
        let selectedDestination = try DocumentRepository(rootURL: root())
        let selected = try await selectedDestination.restoreBackup(selection)
        XCTAssertEqual(selected.documents, [imported[0], imported[2]])
        XCTAssertEqual(selected.travelers, [traveler])
        for index in [0, 2] {
            let bytes = try await selectedDestination.documentData(id: imported[index].id)
            XCTAssertEqual(bytes, inputs[index].data)
        }
    }

    func testBatchValidatesEveryItemBeforeWritingAnyPrefix() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Existing trip", departureDate: nil)
        let existing = try await addDocument(to: repository, trip: trip)
        let before = try await repository.load()
        let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        // Any attempted staging write fails. Each invalid final row must be
        // diagnosed before the valid first row reaches this writer.
        let writeForbidden = try DocumentRepository(rootURL: repositoryRoot) { _, _ in
            throw CocoaError(.fileWriteOutOfSpace)
        }
        let valid = DocumentImportInput(data: pdf, originalFilename: "valid.pdf", title: "Valid first", kind: .ticket)
        let invalidRows: [(DocumentImportInput, RepositoryError)] = [
            (DocumentImportInput(data: Data("not a PDF".utf8), originalFilename: "invalid.pdf",
                title: "Bad signature", kind: .other), .unsupportedFileType),
            (DocumentImportInput(data: Data("%PDF-1.4\n%%EOF".utf8), originalFilename: "truncated.pdf",
                title: "Truncated PDF", kind: .other), .invalidFile),
            (DocumentImportInput(data: pdf, originalFilename: "blank.pdf", title: "  ", kind: .other), .invalidName),
            (DocumentImportInput(data: pdf, originalFilename: "../outside.pdf", title: "Path", kind: .other), .invalidName),
            (DocumentImportInput(data: pdf, originalFilename: "person.pdf", travelerID: UUID(),
                title: "Unknown person", kind: .other), .missingReference),
            (DocumentImportInput(data: pdf, originalFilename: "date.pdf", title: "Invalid date", kind: .other,
                expiryDate: Date(timeIntervalSince1970: .infinity)), .invalidName),
            (DocumentImportInput(data: Data(count: DocumentRepository.maximumDocumentBytes + 1),
                originalFilename: "large.pdf", title: "Oversized", kind: .other), .documentTooLarge)
        ]
        for (invalid, expectedError) in invalidRows {
            do {
                _ = try await writeForbidden.importDocuments([valid, invalid], tripID: trip.id)
                XCTFail("An invalid final row must reject the complete selection")
            } catch { XCTAssertEqual(error as? RepositoryError, expectedError) }
            try await assertBatchFailurePreserved(before, pointer: pointer,
                originals: [existing.id: pdf], root: repositoryRoot)
        }
    }

    func testBatchRejectsEmptyElevenAndUnknownTripButAcceptsTen() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Count bounds", departureDate: nil)
        let before = try await repository.load()
        let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        let input = DocumentImportInput(data: pdf, originalFilename: "same-name.pdf", title: "Synthetic", kind: .other)
        for count in [0, 11] {
            do {
                _ = try await repository.importDocuments(Array(repeating: input, count: count), tripID: trip.id)
                XCTFail("A selection must contain between one and ten files")
            } catch { XCTAssertEqual(error as? RepositoryError, .invalidImportCount) }
        }
        do {
            _ = try await repository.importDocuments([input], tripID: UUID())
            XCTFail("The shared destination trip must exist")
        } catch { XCTAssertEqual(error as? RepositoryError, .missingReference) }
        try await assertBatchFailurePreserved(before, pointer: pointer, originals: [:], root: repositoryRoot)
        let imported = try await repository.importDocuments(Array(repeating: input, count: 10), tripID: trip.id)
        XCTAssertEqual(imported.count, 10)
        XCTAssertEqual(Set(imported.map(\.storedFilename)).count, 10)
        let after = try await repository.load()
        XCTAssertEqual(after.documents, imported)
    }

    func testBatchAggregateLimitIncludesExistingBytesAndRejectsWithoutPartialImport() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Aggregate limit", departureDate: nil)
        let bytes = paddedPDF(byteCount: 13 * 1_024 * 1_024)
        let input = DocumentImportInput(data: bytes, originalFilename: "large-valid.pdf", title: "Synthetic large", kind: .other)
        let existing = try await repository.importDocuments(Array(repeating: input, count: 4), tripID: trip.id)
        let before = try await repository.load()
        XCTAssertEqual(before.documents.reduce(0) { $0 + $1.byteCount }, 52 * 1_024 * 1_024)
        let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        let small = DocumentImportInput(data: pdf, originalFilename: "fits-alone.pdf", title: "Fits alone", kind: .ticket)
        do {
            _ = try await repository.importDocuments([small, input], tripID: trip.id)
            XCTFail("Existing and incoming originals together exceed 64 MiB")
        } catch { XCTAssertEqual(error as? RepositoryError, .libraryTooLarge) }
        try await assertBatchFailurePreserved(before, pointer: pointer,
            originals: Dictionary(uniqueKeysWithValues: existing.map { ($0.id, bytes) }), root: repositoryRoot)
    }

    func testBatchWriteFailureAfterEarlierOriginalsRollsBackWholeSelection() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Disk full batch", departureDate: nil)
        let existing = try await addDocument(to: repository, trip: trip)
        let before = try await repository.load()
        let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        let failing = try DocumentRepository(rootURL: repositoryRoot) { data, url in
            if url.pathExtension == "png" { throw CocoaError(.fileWriteOutOfSpace) }
            try data.write(to: url, options: .atomic)
        }
        let inputs = [
            DocumentImportInput(data: pdf, originalFilename: "first.pdf", title: "First staged", kind: .ticket),
            DocumentImportInput(data: imageData(type: "public.png"), originalFilename: "second.png",
                title: "Second fails", kind: .passport)
        ]
        do {
            _ = try await failing.importDocuments(inputs, tripID: trip.id)
            XCTFail("Disk-full on a later original must roll back all new documents")
        } catch { XCTAssertEqual(error as? RepositoryError, .saveFailed) }
        try await assertBatchFailurePreserved(before, pointer: pointer, originals: [existing.id: pdf], root: repositoryRoot)
    }

    func testBatchCancellationDuringStagingAndBeforePublicationPreservesExistingOriginals() async throws {
        for cancelAtPointer in [false, true] {
            let repositoryRoot = try root()
            let repository = try DocumentRepository(rootURL: repositoryRoot)
            let trip = try await repository.createTrip(title: "Cancelled batch", departureDate: nil)
            let existing = try await addDocument(to: repository, trip: trip)
            let before = try await repository.load()
            let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
            let cancelling = try DocumentRepository(rootURL: repositoryRoot) { data, url in
                try data.write(to: url, options: .atomic)
                let target = cancelAtPointer ? url.lastPathComponent.hasPrefix(".pending-") : url.pathExtension == "png"
                if target { withUnsafeCurrentTask { $0?.cancel() } }
            }
            let inputs = [
                DocumentImportInput(data: imageData(type: "public.png"), originalFilename: "first.png",
                    title: "First staged", kind: .passport),
                DocumentImportInput(data: pdf, originalFilename: "second.pdf", title: "Second staged", kind: .ticket)
            ]
            let operation = Task { try await cancelling.importDocuments(inputs, tripID: trip.id) }
            do {
                _ = try await operation.value
                XCTFail("Cancellation before publication must not report an imported selection")
            } catch { XCTAssertTrue(error is CancellationError, "Preserve explicit cancellation instead of a storage error") }
            try await assertBatchFailurePreserved(before, pointer: pointer, originals: [existing.id: pdf], root: repositoryRoot)
        }
    }

    func testAlreadyCancelledBatchNeverPublishes() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Pre-cancelled batch", departureDate: nil)
        let before = try await repository.load()
        let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        let input = DocumentImportInput(data: pdf, originalFilename: "synthetic.pdf", title: "Cancelled", kind: .other)
        let operation = Task {
            withUnsafeCurrentTask { $0?.cancel() }
            return try await repository.importDocuments([input], tripID: trip.id)
        }
        do {
            _ = try await operation.value
            XCTFail("A request cancelled before entry must not publish")
        } catch { XCTAssertTrue(error is CancellationError) }
        try await assertBatchFailurePreserved(before, pointer: pointer, originals: [:], root: repositoryRoot)
    }

    func testBatchWriterCancellationRemainsCancellationAndCleansStaging() async throws {
        let repositoryRoot = try root()
        let repository = try DocumentRepository(rootURL: repositoryRoot)
        let trip = try await repository.createTrip(title: "Writer cancelled", departureDate: nil)
        let existing = try await addDocument(to: repository, trip: trip)
        let before = try await repository.load()
        let pointer = try Data(contentsOf: repositoryRoot.appendingPathComponent("active.json"))
        let cancelling = try DocumentRepository(rootURL: repositoryRoot) { data, url in
            if url.pathExtension == "png" { throw CancellationError() }
            try data.write(to: url, options: .atomic)
        }
        let input = DocumentImportInput(data: imageData(type: "public.png"), originalFilename: "cancelled.png",
            title: "Cancelled", kind: .other)
        do {
            _ = try await cancelling.importDocuments([input], tripID: trip.id)
            XCTFail("Cancellation from a staged write must propagate")
        } catch { XCTAssertTrue(error is CancellationError) }
        try await assertBatchFailurePreserved(before, pointer: pointer, originals: [existing.id: pdf], root: repositoryRoot)
    }

    private func assertBatchFailurePreserved(_ expected: LibrarySnapshot, pointer: Data,
                                             originals: [UUID: Data], root: URL,
                                             file: StaticString = #filePath, line: UInt = #line) async throws {
        XCTAssertEqual(try Data(contentsOf: root.appendingPathComponent("active.json")), pointer, file: file, line: line)
        let reopened = try DocumentRepository(rootURL: root)
        let actual = try await reopened.load()
        XCTAssertEqual(actual, expected, file: file, line: line)
        for (id, expectedBytes) in originals {
            let actualBytes = try await reopened.documentData(id: id)
            XCTAssertEqual(actualBytes, expectedBytes, file: file, line: line)
        }
        let children = try FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: nil)
        XCTAssertEqual(children.filter { UUID(uuidString: $0.lastPathComponent) != nil }.count, 1, file: file, line: line)
        XCTAssertFalse(children.contains { $0.lastPathComponent.hasPrefix(".pending-") }, file: file, line: line)
    }

    // A valid one-page PDF with exactly the requested full-original length.
    // Whitespace follows the objects, so only the xref table offset moves.
    private func paddedPDF(byteCount: Int) -> Data {
        var data = Data("%PDF-1.4\n".utf8)
        var offsets: [Int] = []
        for (index, object) in [
            "<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"
        ].enumerated() {
            offsets.append(data.count)
            data.append(Data("\(index + 1) 0 obj\n\(object)\nendobj\n".utf8))
        }
        let entries = offsets.map { String(format: "%010d 00000 n \n", $0) }.joined()
        let table = "xref\n0 4\n0000000000 65535 f \n" + entries + "trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n"
        // Reserve ten characters for the xref offset, a newline, and the EOF marker.
        let tailLength = table.utf8.count + 10 + "\n%%EOF\n".utf8.count
        let xrefOffset = byteCount - tailLength
        precondition(xrefOffset > data.count)
        data.append(Data(repeating: 0x20, count: xrefOffset - data.count - 1))
        data.append(0x0A)
        data.append(Data((table + String(format: "%010d", xrefOffset) + "\n%%EOF\n").utf8))
        precondition(data.count == byteCount)
        return data
    }

    func testDocumentLimitAndAggregateLimitAreEnforced() async throws {
        let repository = try DocumentRepository(rootURL: root())
        let trip = try await repository.createTrip(title: "Synthetic trip", departureDate: nil)
        var overLimit = Data("%PDF-1.4".utf8)
        overLimit.append(Data(count: DocumentRepository.maximumDocumentBytes))
        do {
            _ = try await repository.importDocument(data: overLimit, originalFilename: "large.pdf", tripID: trip.id,
                travelerID: nil, title: "Synthetic", kind: .other, expiryDate: nil)
            XCTFail("Oversized originals must be rejected")
        } catch { XCTAssertEqual(error as? RepositoryError, .documentTooLarge) }
        let document = try await addDocument(to: repository, trip: trip)
        let backup = try await repository.exportBackup(documentIDs: nil)
        let oversizedLibrary = try mutateArchive(backup) { json in
            var library = json["library"] as! [String: Any]
            let template = (library["documents"] as! [[String: Any]])[0]
            library["documents"] = (0..<5).map { _ -> [String: Any] in
                var doc = template
                let id = UUID()
                doc["id"] = id.uuidString
                doc["storedFilename"] = id.uuidString.lowercased() + ".pdf"
                doc["byteCount"] = DocumentRepository.maximumDocumentBytes
                return doc
            }
            json["library"] = library
        }
        do {
            _ = try await repository.restoreBackup(oversizedLibrary)
            XCTFail("Aggregate length is checked before original decoding is accepted")
        } catch { XCTAssertEqual(error as? RepositoryError, .libraryTooLarge) }
        let library = try await repository.load()
        XCTAssertEqual(library.documents, [document])
    }
}
