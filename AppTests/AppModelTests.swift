import UIKit
import XCTest
import TravelCore
@testable import Tripfolio

@MainActor
final class AppModelTests: XCTestCase {
    func testSingleImportDraftRetainsSourceAndEditsAcrossRefresh() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic trip", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        model.beginDocumentImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.documentImportDraft)
        let source = root.appendingPathComponent("Synthetic ticket.pdf")
        model.selectImportFile(source, draftID: draft.id)
        draft.title = "Билет домой"
        draft.kind = .ticket
        draft.hasExpiry = true
        draft.expiryDate = Date(timeIntervalSince1970: 2_000_000_000)
        draft.recognizedText = "Editable suggestion"

        // RootView is reconstructed and refreshes after the privacy lock.
        await model.refresh()
        XCTAssertTrue(model.documentImportDraft === draft)
        XCTAssertEqual(draft.fileURL, source)
        XCTAssertEqual(draft.title, "Билет домой")
        XCTAssertEqual(draft.kind, .ticket)
        XCTAssertTrue(draft.hasExpiry)
        XCTAssertEqual(draft.expiryDate, Date(timeIntervalSince1970: 2_000_000_000))
        XCTAssertEqual(draft.recognizedText, "Editable suggestion")
        XCTAssertTrue(model.library.documents.isEmpty, "An unsaved draft must not publish a document")

        let relaunched = AppModel(rootURL: root)
        await relaunched.refresh()
        XCTAssertNil(relaunched.documentImportDraft, "Unsaved import details are RAM-only")
        XCTAssertTrue(relaunched.library.documents.isEmpty)
    }

    func testCancelledImportCallbacksCannotChangeReplacementDraft() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic trip", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        model.beginDocumentImport(tripID: trip.id)
        let old = try XCTUnwrap(model.documentImportDraft)
        model.cancelDocumentImport(draftID: old.id)
        XCTAssertNil(model.documentImportDraft)
        model.beginDocumentImport(tripID: trip.id)
        let current = try XCTUnwrap(model.documentImportDraft)
        current.title = "Keep this draft"
        model.selectImportFile(root.appendingPathComponent("late.pdf"), draftID: old.id)
        model.selectImportScan(samplePDF(), draftID: old.id)
        model.cancelDocumentImport(draftID: old.id)
        await model.saveDocumentImport(draftID: old.id)
        XCTAssertTrue(model.documentImportDraft === current)
        XCTAssertFalse(current.hasSource)
        XCTAssertEqual(current.title, "Keep this draft")
        XCTAssertTrue(model.library.documents.isEmpty)
    }

    func testSingleImportFailureKeepsDraftAndSuccessPublishesOnce() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic trip", departureDate: nil)
        model.beginDocumentImport(tripID: try XCTUnwrap(model.library.trips.first?.id))
        let draft = try XCTUnwrap(model.documentImportDraft)
        model.selectImportScan(Data("Not a PDF".utf8), draftID: draft.id)
        await model.saveDocumentImport(draftID: draft.id)
        XCTAssertNotNil(model.errorMessage)
        XCTAssertTrue(model.documentImportDraft === draft)
        XCTAssertTrue(model.library.documents.isEmpty)

        model.errorMessage = nil
        let original = samplePDF()
        model.selectImportScan(original, draftID: draft.id)
        draft.title = "Confirmed synthetic ticket"
        draft.kind = .ticket
        await model.saveDocumentImport(draftID: draft.id)
        XCTAssertNil(model.errorMessage)
        XCTAssertNil(model.documentImportDraft)
        let document = try XCTUnwrap(model.library.documents.first)
        XCTAssertEqual(document.title, "Confirmed synthetic ticket")
        XCTAssertEqual(document.kind, .ticket)
        let repository = try DocumentRepository(rootURL: root)
        let saved = try await repository.documentData(id: document.id)
        XCTAssertEqual(saved, original)
        await model.saveDocumentImport(draftID: draft.id)
        XCTAssertEqual(model.library.documents.count, 1)
    }

    func testSingleImportRemainsBusyAndKeepsItsDraftDuringProviderRead() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let barrier = ExternalReadBarrier()
        let model = AppModel(rootURL: root, readExternal: { url, maximum in
            try await barrier.read(url, maximum: maximum)
        })
        await model.createTrip(title: "Synthetic trip", departureDate: nil)
        model.beginDocumentImport(tripID: try XCTUnwrap(model.library.trips.first?.id))
        let draft = try XCTUnwrap(model.documentImportDraft)
        let source = root.appendingPathComponent("Synthetic ticket.pdf")
        model.selectImportFile(source, draftID: draft.id)
        draft.title = "Confirmed ticket"
        draft.kind = .ticket
        let operation = Task { await model.saveDocumentImport(draftID: draft.id) }
        defer { operation.cancel(); Task { await barrier.cancel() } }
        let request = try await barrier.waitForRequest()

        XCTAssertEqual(request.url, source)
        XCTAssertTrue(model.isBusy, "The import form must stay disabled while a provider read is pending")
        XCTAssertTrue(model.documentImportDraft === draft)
        XCTAssertTrue(model.library.documents.isEmpty)
        model.cancelDocumentImport(draftID: draft.id)
        model.selectImportFile(root.appendingPathComponent("Late replacement.pdf"), draftID: draft.id)
        XCTAssertTrue(model.documentImportDraft === draft)
        XCTAssertEqual(draft.fileURL, source)

        await barrier.release(samplePDF())
        await operation.value
        XCTAssertFalse(model.isBusy)
        XCTAssertNil(model.documentImportDraft)
        XCTAssertEqual(model.library.documents.count, 1)
        XCTAssertEqual(model.library.documents.first?.title, "Confirmed ticket")
        XCTAssertEqual(model.library.documents.first?.kind, .ticket)
    }

    func testLibraryReplacementInvalidatesImportEvenWithIdenticalContent() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic trip", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        let repository = try DocumentRepository(rootURL: root)
        let backup = root.appendingPathComponent("Synthetic.tripbackup")
        try await repository.exportBackup(documentIDs: nil).write(to: backup)
        model.beginDocumentImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.documentImportDraft)
        model.selectImportFile(root.appendingPathComponent("unsaved.pdf"), draftID: draft.id)
        await model.restoreBackup(url: backup)
        XCTAssertNil(model.errorMessage)
        XCTAssertNil(model.documentImportDraft)
        await model.saveDocumentImport(draftID: draft.id)
        XCTAssertTrue(model.library.documents.isEmpty)
    }

    func testImportDraftDoesNotOverlapExistingEditorOrBatch() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, document, _) = try await editableDocument(at: root)
        model.beginDocumentImport(tripID: document.tripID)
        let draft = try XCTUnwrap(model.documentImportDraft)
        model.beginEditingDocument(document)
        model.beginBatchImport(tripID: document.tripID)
        XCTAssertTrue(model.documentImportDraft === draft)
        XCTAssertNil(model.documentEditDraft)
        XCTAssertNil(model.batchImportDraft)
        model.cancelDocumentImport(draftID: draft.id)
        model.beginEditingDocument(document)
        model.beginDocumentImport(tripID: document.tripID)
        XCTAssertNotNil(model.documentEditDraft)
        XCTAssertNil(model.documentImportDraft)
    }

    func testDeletingImportTripInvalidatesDraftAndLateSelection() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic trip", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        model.beginDocumentImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.documentImportDraft)
        model.selectImportScan(samplePDF(), draftID: draft.id)
        await model.deleteTrip(id: trip.id)
        XCTAssertNil(model.documentImportDraft)
        model.selectImportFile(root.appendingPathComponent("late.pdf"), draftID: draft.id)
        await model.saveDocumentImport(draftID: draft.id)
        XCTAssertNil(model.documentImportDraft)
        XCTAssertTrue(model.library.trips.isEmpty)
        XCTAssertTrue(model.library.documents.isEmpty)
    }

    func testSelectAllSearchResultsNeverAddsHiddenOriginals() {
        let visible = UUID(), hidden = UUID()
        XCTAssertEqual(DocumentSelection.togglingAll(selected: [], visible: [visible]), [visible])
        XCTAssertEqual(DocumentSelection.togglingAll(selected: [hidden], visible: [visible]), [visible])
        XCTAssertEqual(DocumentSelection.togglingAll(selected: [visible, hidden], visible: [visible]), [])
        XCTAssertEqual(DocumentSelection.togglingAll(selected: [hidden], visible: []), [])
        XCTAssertEqual(DocumentSelection.togglingAll(selected: [], visible: [visible, hidden]), [visible, hidden])
    }

    func testDeniedCacheCleanupPreservesExistingLibraryAndRecovery() async throws {
        let fm = FileManager.default
        let workspace = temporaryRoot()
        let root = workspace.appendingPathComponent("Library", isDirectory: true)
        let cache = workspace.appendingPathComponent("PresentationCache", isDirectory: true)
        defer {
            // Restore permission only on this test's private directory.
            try? fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: cache.path)
            try? fm.removeItem(at: workspace)
        }
        let original = samplePDF()
        let (repository, before) = try await seedPolicyDocuments(count: 1, at: root, original: original)
        let trip = try XCTUnwrap(before.trips.first)
        let document = try XCTUnwrap(before.documents.first)
        let archive = try await repository.exportBackup(documentIDs: nil)
        let backup = workspace.appendingPathComponent("Synthetic.tripbackup")
        try archive.write(to: backup)
        try fm.createDirectory(at: cache, withIntermediateDirectories: true)
        let abandonedCopy = cache.appendingPathComponent("Abandoned.txt")
        try Data("Synthetic abandoned presentation copy".utf8).write(to: abandonedCopy)
        try fm.setAttributes([.posixPermissions: 0o500], ofItemAtPath: cache.path)

        // Prove the real filesystem fault exists before exercising initialization;
        // a privileged environment that can remove it must fail this precondition.
        XCTAssertThrowsError(try fm.removeItem(at: cache))
        XCTAssertTrue(fm.fileExists(atPath: abandonedCopy.path))
        let model = AppModel(rootURL: root, temporaryRootURL: cache)
        XCTAssertNil(model.errorMessage, "Disposable-cache cleanup must not report that the library failed to open")
        await model.refresh()
        XCTAssertEqual(model.library, before)
        await model.checkReadiness(tripID: trip.id)
        XCTAssertEqual(model.readiness[document.id]?.state, .ready)
        XCTAssertFalse(model.purchases.isPro)

        // Opening the repository does not make the still-denied cache writable.
        // Presentation/export failures must remain honest and nondestructive.
        let deniedPreview = await model.previewURL(documentID: document.id)
        XCTAssertNil(deniedPreview)
        XCTAssertNotNil(model.errorMessage)
        model.errorMessage = nil
        let deniedExport = await model.makeBackup(documentIDs: nil)
        XCTAssertNil(deniedExport)
        XCTAssertNotNil(model.errorMessage)
        XCTAssertEqual(model.library, before)

        // Recovery operates on the persistent library even while cleanup fails.
        model.errorMessage = nil
        await model.restoreBackup(url: backup)
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.library, before)
        XCTAssertTrue(fm.fileExists(atPath: abandonedCopy.path))
        let restoredOriginal = try await repository.documentData(id: document.id)
        XCTAssertEqual(restoredOriginal, original)

        // Once the transient cache fault is repaired, the SAME model must be able
        // to preview and export; it must not retain a nil repository from launch.
        try fm.setAttributes([.posixPermissions: 0o700], ofItemAtPath: cache.path)
        let previewResult = await model.previewURL(documentID: document.id)
        let preview = try XCTUnwrap(previewResult)
        XCTAssertEqual(try Data(contentsOf: preview), original)
        let exportResult = await model.makeBackup(documentIDs: nil)
        let exported = try XCTUnwrap(exportResult)
        XCTAssertNil(model.errorMessage)
        let recovered = try DocumentRepository(rootURL: workspace.appendingPathComponent("Recovered"))
        let recoveredLibrary = try await recovered.restoreBackup(Data(contentsOf: exported))
        XCTAssertEqual(recoveredLibrary, before)
        let recoveredOriginal = try await recovered.documentData(id: document.id)
        XCTAssertEqual(recoveredOriginal, original)
    }

    func testFreeQuotaSurvivesRelaunchAndDeletingTripAllowsReplacement() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "First trip", departureDate: nil)
        await model.createTrip(title: "Over quota", departureDate: nil)
        XCTAssertEqual(model.library.trips.count, 1)
        XCTAssertNotNil(model.errorMessage)
        let relaunched = AppModel(rootURL: root)
        await relaunched.refresh()
        XCTAssertFalse(relaunched.canAddTrip)
        await relaunched.deleteTrip(id: try XCTUnwrap(relaunched.library.trips.first?.id))
        XCTAssertTrue(relaunched.canAddTrip)
        await relaunched.createTrip(title: "Next trip", departureDate: nil)
        XCTAssertEqual(relaunched.library.trips.map(\.title), ["Next trip"])
    }

    func testFreeRecoveryAboveQuotaPreservesViewingExportAndDeletion() async throws {
        let root = temporaryRoot(), sourceRoot = temporaryRoot()
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: sourceRoot)
        }
        let source = try DocumentRepository(rootURL: sourceRoot)
        let first = try await source.createTrip(title: "First", departureDate: nil)
        _ = try await source.createTrip(title: "Second", departureDate: nil)
        let original = samplePDF()
        for number in 1...9 {
            _ = try await source.importDocument(data: original, originalFilename: "sample.pdf", tripID: first.id,
                travelerID: nil, title: "Sample \(number)", kind: .booking, expiryDate: nil)
        }
        let backup = try await source.exportBackup(documentIDs: nil)
        let file = sourceRoot.appendingPathComponent("synthetic.tripbackup")
        try backup.write(to: file)
        let model = AppModel(rootURL: root)
        await model.restoreBackup(url: file)
        XCTAssertNil(model.errorMessage)
        XCTAssertFalse(model.purchases.isPro)
        XCTAssertEqual(model.library.documents.count, 9)
        XCTAssertFalse(model.canAddDocument)
        let document = try XCTUnwrap(model.library.documents.first)
        let preview = await model.previewURL(documentID: document.id)
        XCTAssertEqual(try Data(contentsOf: XCTUnwrap(preview)), original)
        let exported = await model.makeBackup(documentIDs: [document.id])
        XCTAssertNotNil(exported)
        await model.deleteDocument(id: document.id)
        XCTAssertEqual(model.library.documents.count, 8)
    }

    func testInvalidRestoreLeavesLibraryAndOriginalUnchanged() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Keep me", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        await model.importData(samplePDF(), filename: "sample.pdf", tripID: trip.id, travelerID: nil,
            title: "Keep original", kind: .booking, expiryDate: nil)
        let before = model.library
        let broken = root.appendingPathComponent("broken.tripbackup")
        try Data("{\"formatVersion\":1}".utf8).write(to: broken)
        await model.restoreBackup(url: broken)
        XCTAssertNotNil(model.errorMessage)
        XCTAssertEqual(model.library, before)
        await model.checkReadiness(tripID: trip.id)
        XCTAssertEqual(model.readiness[try XCTUnwrap(before.documents.first?.id)]?.state, .ready)
    }

    func testConcurrentCreatesCannotBypassFreeLimit() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        async let first: Void = model.createTrip(title: "First", departureDate: nil)
        async let second: Void = model.createTrip(title: "Second", departureDate: nil)
        _ = await (first, second)
        XCTAssertEqual(model.library.trips.count, 1)
    }

    func testTemporaryCopiesAreReplacedAndExplicitlyRemoved() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        await model.importData(samplePDF(), filename: "sample.pdf", tripID: trip.id, travelerID: nil,
            title: "Sample", kind: .booking, expiryDate: nil)
        let document = try XCTUnwrap(model.library.documents.first)
        let firstResult = await model.previewURL(documentID: document.id)
        let first = try XCTUnwrap(firstResult)
        let secondResult = await model.previewURL(documentID: document.id)
        let second = try XCTUnwrap(secondResult)
        XCTAssertFalse(FileManager.default.fileExists(atPath: first.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: second.path))
        model.removeTemporary(second)
        XCTAssertFalse(FileManager.default.fileExists(atPath: second.path))
        // A forged cleanup URL cannot remove unrelated files or the library.
        model.removeTemporary(root.appendingPathComponent("active.json"))
        XCTAssertTrue(FileManager.default.fileExists(atPath: root.appendingPathComponent("active.json").path))
    }

    func testFileImportCopiesOriginalAndSurvivesSourceRemoval() async throws {
        let root = temporaryRoot(), source = temporaryRoot().appendingPathExtension("pdf")
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: source)
        }
        let original = samplePDF()
        try original.write(to: source)
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Offline fixture", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        await model.importFile(url: source, tripID: trip.id, travelerID: nil,
            title: "Copied original", kind: .ticket, expiryDate: nil)
        XCTAssertNil(model.errorMessage)
        let document = try XCTUnwrap(model.library.documents.first)
        try FileManager.default.removeItem(at: source)
        let relaunched = AppModel(rootURL: root)
        await relaunched.refresh()
        await relaunched.checkReadiness(tripID: trip.id)
        XCTAssertEqual(relaunched.readiness[document.id]?.state, .ready)
        let previewResult = await relaunched.previewURL(documentID: document.id)
        let preview = try XCTUnwrap(previewResult)
        XCTAssertEqual(try Data(contentsOf: preview), original)
        relaunched.removeTemporary(preview)
    }

    // These exercise the actual AppModel quota policy with controlled dependency
    // inputs. They do not simulate, verify, or claim a StoreKit transaction.
    func testPolicyEntitlementLossDuringFileReadRejectsNinthDocumentAndPreservesAccess() async throws {
        let root = temporaryRoot(), recoveredRoot = temporaryRoot()
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: recoveredRoot)
        }
        let original = samplePDF()
        let (repository, before) = try await seedPolicyDocuments(count: 8, at: root, original: original)
        let trip = try XCTUnwrap(before.trips.first)
        let barrier = ExternalReadBarrier()
        let entitlement = PolicyEntitlementState()
        let model = AppModel(rootURL: root, proEntitlement: { entitlement.isPro }, readExternal: { url, maximum in
            try await barrier.read(url, maximum: maximum)
        })
        await model.refresh()
        XCTAssertEqual(model.library, before)
        XCTAssertTrue(model.canAddDocument)
        let source = root.appendingPathComponent("ninth-document.pdf")
        let operation = Task {
            await model.importFile(url: source, tripID: trip.id, travelerID: nil,
                                   title: "Must not become the ninth document", kind: .ticket, expiryDate: nil)
        }
        defer { operation.cancel(); Task { await barrier.cancel() } }
        let request = try await barrier.waitForRequest()
        XCTAssertEqual(request.url, source)
        XCTAssertEqual(request.maximum, 16 * 1_024 * 1_024)
        XCTAssertTrue(model.isBusy)
        entitlement.isPro = false
        XCTAssertFalse(model.canAddDocument)
        await barrier.release(original)
        await operation.value

        XCTAssertFalse(model.isBusy)
        XCTAssertEqual(model.library, before)
        XCTAssertTrue(model.errorMessage?.contains("eight documents") == true, model.errorMessage ?? "No quota error")
        let persisted = try await repository.load()
        XCTAssertEqual(persisted, before, "The rejected addition must not reach persistent storage")
        for document in before.documents {
            let bytes = try await repository.documentData(id: document.id)
            XCTAssertEqual(bytes, original)
        }

        // Loss of the addition right must not block existing-document operations.
        model.errorMessage = nil
        let document = try XCTUnwrap(before.documents.first)
        let previewResult = await model.previewURL(documentID: document.id)
        let preview = try XCTUnwrap(previewResult)
        XCTAssertEqual(try Data(contentsOf: preview), original)
        model.removeTemporary(preview)
        let edited = await model.updateDocument(id: document.id, title: "Still editable without Pro",
                                                travelerID: document.travelerID, kind: .insurance, expiryDate: nil)
        XCTAssertTrue(edited)
        XCTAssertNil(model.errorMessage)
        let editedBytes = try await repository.documentData(id: document.id)
        XCTAssertEqual(editedBytes, original)
        let exportResult = await model.makeBackup(documentIDs: nil)
        let exported = try XCTUnwrap(exportResult)
        defer { model.removeTemporary(exported) }
        let recovered = try DocumentRepository(rootURL: recoveredRoot)
        let recoveredLibrary = try await recovered.restoreBackup(Data(contentsOf: exported))
        XCTAssertEqual(recoveredLibrary, model.library)
        XCTAssertEqual(recoveredLibrary.documents.count, 8)
        for document in recoveredLibrary.documents {
            let bytes = try await recovered.documentData(id: document.id)
            XCTAssertEqual(bytes, original)
        }
    }

    func testPolicyEntitlementLossDuringFileReadStillAllowsEighthDocument() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let original = samplePDF()
        let (repository, before) = try await seedPolicyDocuments(count: 7, at: root, original: original)
        let trip = try XCTUnwrap(before.trips.first)
        let barrier = ExternalReadBarrier()
        let entitlement = PolicyEntitlementState()
        let model = AppModel(rootURL: root, proEntitlement: { entitlement.isPro }, readExternal: { url, maximum in
            try await barrier.read(url, maximum: maximum)
        })
        await model.refresh()
        let source = root.appendingPathComponent("eighth-document.pdf")
        let operation = Task {
            await model.importFile(url: source, tripID: trip.id, travelerID: nil,
                                   title: "Eighth after entitlement loss", kind: .ticket, expiryDate: nil)
        }
        defer { operation.cancel(); Task { await barrier.cancel() } }
        let request = try await barrier.waitForRequest()
        XCTAssertEqual(request.url, source)
        XCTAssertEqual(request.maximum, 16 * 1_024 * 1_024)
        XCTAssertTrue(model.isBusy)
        entitlement.isPro = false
        XCTAssertTrue(model.canAddDocument, "Free capacity remains available after entitlement loss")
        await barrier.release(original)
        await operation.value

        XCTAssertFalse(model.isBusy)
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.library.documents.count, 8)
        XCTAssertEqual(Array(model.library.documents.prefix(7)), before.documents)
        XCTAssertFalse(model.canAddDocument)
        let persisted = try await repository.load()
        XCTAssertEqual(persisted, model.library)
        let added = try XCTUnwrap(persisted.documents.first { $0.title == "Eighth after entitlement loss" })
        let storedBytes = try await repository.documentData(id: added.id)
        XCTAssertEqual(storedBytes, original)
    }

    func testPolicyEntitlementLossDuringRestoreAllowsRecoveryButBlocksNewAddition() async throws {
        let root = temporaryRoot(), sourceRoot = temporaryRoot()
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: sourceRoot)
        }
        let original = samplePDF()
        let (sourceRepository, sourceLibrary) = try await seedPolicyDocuments(count: 9, at: sourceRoot, original: original)
        let backup = try await sourceRepository.exportBackup(documentIDs: nil)
        let (repository, before) = try await seedPolicyDocuments(count: 1, at: root, original: original)
        let barrier = ExternalReadBarrier()
        let entitlement = PolicyEntitlementState()
        let model = AppModel(rootURL: root, proEntitlement: { entitlement.isPro }, readExternal: { url, maximum in
            try await barrier.read(url, maximum: maximum)
        })
        await model.refresh()
        let source = sourceRoot.appendingPathComponent("existing-library.tripbackup")
        let operation = Task { await model.restoreBackup(url: source) }
        defer { operation.cancel(); Task { await barrier.cancel() } }
        let request = try await barrier.waitForRequest()
        XCTAssertEqual(request.url, source)
        XCTAssertEqual(request.maximum, 96 * 1_024 * 1_024)
        XCTAssertTrue(model.isBusy)
        XCTAssertEqual(model.library, before)
        entitlement.isPro = false
        await barrier.release(backup)
        await operation.value

        XCTAssertFalse(model.isBusy)
        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.library, sourceLibrary)
        XCTAssertFalse(model.canAddDocument)
        let restored = try await repository.load()
        XCTAssertEqual(restored, sourceLibrary)
        for document in restored.documents {
            let bytes = try await repository.documentData(id: document.id)
            XCTAssertEqual(bytes, original)
        }
        let trip = try XCTUnwrap(restored.trips.first)
        await model.importData(original, filename: "blocked.pdf", tripID: trip.id, travelerID: nil,
                               title: "Must not become the tenth document", kind: .ticket, expiryDate: nil)
        XCTAssertTrue(model.errorMessage?.contains("eight documents") == true, model.errorMessage ?? "No quota error")
        XCTAssertFalse(model.isBusy)
        XCTAssertEqual(model.library, sourceLibrary)
        let afterRejectedAddition = try await repository.load()
        XCTAssertEqual(afterRejectedAddition, sourceLibrary)
    }

    func testAlreadyCancelledExternalReadDoesNotOpenSource() async {
        let missing = temporaryRoot().appendingPathComponent("not-created.pdf")
        let read = Task { try await AppModel.readExternal(missing, maximum: 16 * 1_024 * 1_024) }
        read.cancel()
        do {
            _ = try await read.value
            XCTFail("An already cancelled read must not return data")
        } catch is CancellationError {
            // Opening the missing source instead would produce a file error.
        } catch {
            XCTFail("Expected cancellation before file access, got \(error)")
        }
    }

    func testCancellingImportDuringExternalReadDoesNotAddDocument() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let original = samplePDF()
        let (repository, before) = try await seedPolicyDocuments(count: 1, at: root, original: original)
        let trip = try XCTUnwrap(before.trips.first)
        let barrier = ExternalReadBarrier()
        let model = AppModel(rootURL: root, readExternal: { url, maximum in
            try await barrier.read(url, maximum: maximum)
        })
        await model.refresh()
        model.notice = nil
        let source = root.appendingPathComponent("cancelled-import.pdf")
        let operation = Task {
            await model.importFile(url: source, tripID: trip.id, travelerID: nil,
                                   title: "Cancelled addition", kind: .ticket, expiryDate: nil)
        }
        defer { operation.cancel(); Task { await barrier.cancel() } }
        let request = try await barrier.waitForRequest()
        XCTAssertEqual(request.url, source)
        XCTAssertTrue(model.isBusy)

        // The provider still returns valid bytes after caller cancellation.
        // Cancellation must be checked before a storage transaction is submitted.
        operation.cancel()
        await barrier.release(original)
        await operation.value

        XCTAssertFalse(model.isBusy)
        XCTAssertEqual(model.library, before)
        XCTAssertNil(model.notice, "A cancelled import must not report a saved original")
        let persisted = try await repository.load()
        XCTAssertEqual(persisted, before)
        for document in before.documents {
            let bytes = try await repository.documentData(id: document.id)
            XCTAssertEqual(bytes, original)
        }
    }

    func testCancellingRestoreDuringExternalReadPreservesLibraryReadinessAndDraft() async throws {
        let root = temporaryRoot(), sourceRoot = temporaryRoot()
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: sourceRoot)
        }
        let original = samplePDF()
        let (sourceRepository, sourceLibrary) = try await seedPolicyDocuments(count: 9, at: sourceRoot, original: original)
        let backup = try await sourceRepository.exportBackup(documentIDs: nil)
        XCTAssertEqual(sourceLibrary.documents.count, 9, "The supplied backup is valid and exceeds the free quota")
        let (repository, before) = try await seedPolicyDocuments(count: 1, at: root, original: original)
        let document = try XCTUnwrap(before.documents.first)
        let barrier = ExternalReadBarrier()
        let model = AppModel(rootURL: root, readExternal: { url, maximum in
            try await barrier.read(url, maximum: maximum)
        })
        await model.refresh()
        await model.checkReadiness(tripID: document.tripID)
        let readinessBefore = model.readiness
        XCTAssertEqual(readinessBefore[document.id]?.state, .ready)
        model.beginEditingDocument(document)
        let draft = try XCTUnwrap(model.documentEditDraft)
        let expiry = Date(timeIntervalSince1970: 1_900_000_000)
        draft.title = "Keep my unsaved title"
        draft.kind = .passport
        draft.travelerID = nil
        draft.hasExpiry = true
        draft.expiryDate = expiry
        model.notice = nil
        let source = sourceRoot.appendingPathComponent("cancelled-restore.tripbackup")
        let operation = Task { await model.restoreBackup(url: source) }
        defer { operation.cancel(); Task { await barrier.cancel() } }
        let request = try await barrier.waitForRequest()
        XCTAssertEqual(request.url, source)
        XCTAssertTrue(model.isBusy)

        operation.cancel()
        await barrier.release(backup)
        await operation.value

        XCTAssertFalse(model.isBusy)
        XCTAssertEqual(model.library, before)
        XCTAssertEqual(model.readiness, readinessBefore)
        XCTAssertTrue(model.documentEditDraft === draft)
        XCTAssertEqual(draft.title, "Keep my unsaved title")
        XCTAssertEqual(draft.kind, .passport)
        XCTAssertNil(draft.travelerID)
        XCTAssertTrue(draft.hasExpiry)
        XCTAssertEqual(draft.expiryDate, expiry)
        XCTAssertNil(model.notice, "A cancelled restore must not report a replaced library")
        let persisted = try await repository.load()
        XCTAssertEqual(persisted, before)
        for retained in before.documents {
            let bytes = try await repository.documentData(id: retained.id)
            XCTAssertEqual(bytes, original)
        }
    }

    func testDocumentEditSavesFieldsAndClearsDraftWithoutChangingOriginal() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, original) = try await editableDocument(at: root)
        await model.addTraveler(name: "Synthetic traveler")
        let traveler = try XCTUnwrap(model.library.travelers.first)
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        let expiry = Date(timeIntervalSince1970: 1_900_000_000)
        draft.title = "Updated boarding pass"
        draft.kind = .ticket
        draft.travelerID = traveler.id
        draft.hasExpiry = true
        draft.expiryDate = expiry

        await model.saveDocumentEdit()

        XCTAssertNil(model.errorMessage)
        XCTAssertNil(model.documentEditDraft)
        var expected = source
        expected.title = "Updated boarding pass"
        expected.kind = .ticket
        expected.travelerID = traveler.id
        expected.expiryDate = TravelDate.stored(from: expiry)
        XCTAssertEqual(model.library.documents, [expected])
        let repository = try DocumentRepository(rootURL: root)
        let persisted = try await repository.load()
        let storedOriginal = try await repository.documentData(id: source.id)
        XCTAssertEqual(persisted.documents, [expected])
        XCTAssertEqual(storedOriginal, original)

        // Turning these controls off must remove their saved values, even
        // though the date picker still holds its previous nonoptional date.
        model.beginEditingDocument(expected)
        let cleared = try XCTUnwrap(model.documentEditDraft)
        cleared.hasExpiry = false
        cleared.travelerID = nil
        await model.saveDocumentEdit()
        XCTAssertNil(model.documentEditDraft)
        let finalDocument = try XCTUnwrap(model.library.documents.first)
        XCTAssertNil(finalDocument.expiryDate)
        XCTAssertNil(finalDocument.travelerID)
        XCTAssertEqual(finalDocument.id, source.id)
    }

    func testInvalidDocumentEditRetainsSameDraftAndPreservesSavedLibrary() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, original) = try await editableDocument(at: root)
        let before = model.library
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.title = " \n "
        draft.kind = .passport
        draft.hasExpiry = true
        let expiry = Date(timeIntervalSince1970: 1_900_000_000)
        draft.expiryDate = expiry

        await model.saveDocumentEdit()

        XCTAssertNotNil(model.errorMessage)
        XCTAssertTrue(model.documentEditDraft === draft)
        XCTAssertEqual(draft.title, " \n ")
        XCTAssertEqual(draft.kind, .passport)
        XCTAssertTrue(draft.hasExpiry)
        XCTAssertEqual(draft.expiryDate, expiry)
        XCTAssertEqual(model.library, before)
        XCTAssertFalse(model.isBusy)
        let repository = try DocumentRepository(rootURL: root)
        let persisted = try await repository.load()
        let storedOriginal = try await repository.documentData(id: source.id)
        XCTAssertEqual(persisted, before)
        XCTAssertEqual(storedOriginal, original)
    }

    func testUnchangedRefreshKeepsDraftUntilExplicitCancel() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, _) = try await editableDocument(at: root)
        let before = model.library
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.title = "Unsaved private draft"
        draft.kind = .insurance

        await model.refresh()
        model.beginEditingDocument(source)

        XCTAssertTrue(model.documentEditDraft === draft)
        XCTAssertEqual(draft.title, "Unsaved private draft")
        XCTAssertEqual(draft.kind, .insurance)
        XCTAssertEqual(model.library, before)
        model.cancelDocumentEdit()
        XCTAssertNil(model.documentEditDraft)
        XCTAssertEqual(model.library, before)
        model.beginEditingDocument(source)
        let reopened = try XCTUnwrap(model.documentEditDraft)
        XCTAssertFalse(reopened === draft)
        XCTAssertEqual(reopened.title, source.title)
        XCTAssertEqual(reopened.kind, source.kind)
    }

    func testDeletingEditedDocumentInvalidatesDraftAndCannotResurrectIt() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, _) = try await editableDocument(at: root)
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.title = "Must not resurrect"

        await model.deleteDocument(id: source.id)

        XCTAssertNil(model.documentEditDraft)
        XCTAssertTrue(model.library.documents.isEmpty)
        await model.saveDocumentEdit()
        XCTAssertTrue(model.library.documents.isEmpty)
        let persisted = try await DocumentRepository(rootURL: root).load()
        XCTAssertTrue(persisted.documents.isEmpty)
    }

    func testChangedSourceInvalidatesDraftRatherThanOverwritingNewerDetails() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, _) = try await editableDocument(at: root)
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.title = "Stale edit"

        await model.updateDocument(id: source.id, title: "Newer saved details", travelerID: nil,
                                   kind: .insurance, expiryDate: nil)

        XCTAssertNil(model.documentEditDraft)
        let updated = try XCTUnwrap(model.library.documents.first)
        XCTAssertEqual(updated.title, "Newer saved details")
        XCTAssertEqual(updated.kind, .insurance)
        await model.saveDocumentEdit()
        XCTAssertEqual(model.library.documents, [updated])
    }

    func testDeletingDraftSelectedTravelerInvalidatesEvenWhenSourceIsUnchanged() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, _) = try await editableDocument(at: root)
        await model.addTraveler(name: "Draft selection only")
        let traveler = try XCTUnwrap(model.library.travelers.first)
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.travelerID = traveler.id
        draft.title = "Unsaved assignment"

        await model.deleteTraveler(id: traveler.id)

        XCTAssertNil(model.documentEditDraft)
        XCTAssertEqual(model.library.documents, [source])
        XCTAssertTrue(model.library.travelers.isEmpty)
    }

    func testSuccessfulRestoreClearsDraftEvenWhenRestoredSourceIsIdentical() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, _) = try await editableDocument(at: root)
        let before = model.library
        let backupResult = await model.makeBackup(documentIDs: nil)
        let backup = try XCTUnwrap(backupResult)
        defer { model.removeTemporary(backup) }
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.title = "Discarded by explicit restore"

        await model.restoreBackup(url: backup)

        XCTAssertNil(model.errorMessage)
        XCTAssertEqual(model.library, before)
        XCTAssertNil(model.documentEditDraft)
    }

    func testFailedRestoreRetainsDraftAndItsUnsavedFields() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let (model, source, _) = try await editableDocument(at: root)
        let before = model.library
        model.beginEditingDocument(source)
        let draft = try XCTUnwrap(model.documentEditDraft)
        draft.title = "Keep my unsaved edit"
        draft.kind = .passport
        let broken = root.appendingPathComponent("broken-draft-restore.tripbackup")
        try Data("{\"formatVersion\":1}".utf8).write(to: broken)

        await model.restoreBackup(url: broken)

        XCTAssertNotNil(model.errorMessage)
        XCTAssertEqual(model.library, before)
        XCTAssertTrue(model.documentEditDraft === draft)
        XCTAssertEqual(draft.title, "Keep my unsaved edit")
        XCTAssertEqual(draft.kind, .passport)
    }

    private func seedPolicyDocuments(count: Int, at root: URL, original: Data) async throws -> (DocumentRepository, LibrarySnapshot) {
        let repository = try DocumentRepository(rootURL: root)
        let trip = try await repository.createTrip(title: "Synthetic policy fixture", departureDate: nil)
        let traveler = try await repository.addTraveler(name: "Synthetic traveler")
        for number in 1...count {
            _ = try await repository.importDocument(data: original, originalFilename: "sample.pdf", tripID: trip.id,
                travelerID: traveler.id, title: "Existing document \(number)", kind: .booking, expiryDate: nil)
        }
        return (repository, try await repository.load())
    }

    private func editableDocument(at root: URL) async throws -> (AppModel, TravelDocument, Data) {
        let model = AppModel(rootURL: root)
        await model.createTrip(title: "Synthetic edit fixture", departureDate: nil)
        let trip = try XCTUnwrap(model.library.trips.first)
        let original = samplePDF()
        await model.importData(original, filename: "editable-sample.pdf", tripID: trip.id, travelerID: nil,
                               title: "Saved original title", kind: .booking, expiryDate: nil)
        XCTAssertNil(model.errorMessage)
        return (model, try XCTUnwrap(model.library.documents.first), original)
    }

    private func temporaryRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("TripfolioTests-" + UUID().uuidString)
    }

    private func samplePDF() -> Data {
        UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 595, height: 842)).pdfData { context in
            context.beginPage()
            NSString(string: "SYNTHETIC FIXTURE — NOT VALID FOR TRAVEL").draw(at: CGPoint(x: 40, y: 40),
                withAttributes: [.font: UIFont.systemFont(ofSize: 14)])
        }
    }
}

@MainActor
private final class PolicyEntitlementState {
    var isPro = true
}

/// Suspends only the external-read dependency. The test controls the returned
/// bytes, while AppModel and DocumentRepository perform their real policy/writes.
/// Both waiting for entry and a forgotten release fail within bounded time.
private actor ExternalReadBarrier {
    struct Request: Sendable {
        let url: URL
        let maximum: Int
    }

    private enum BarrierError: Error {
        case duplicateRead, readNotStarted, releaseTimedOut
    }

    private var request: Request?
    private var continuation: CheckedContinuation<Data, any Error>?
    private var timeout: Task<Void, Never>?

    func read(_ url: URL, maximum: Int) async throws -> Data {
        guard request == nil else { throw BarrierError.duplicateRead }
        try Task.checkCancellation()
        request = Request(url: url, maximum: maximum)
        return try await withCheckedThrowingContinuation { continuation in
            self.continuation = continuation
            timeout = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(5)) }
                catch { return }
                await self?.expire()
            }
        }
    }

    func waitForRequest() async throws -> Request {
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while ContinuousClock.now < deadline {
            if let request { return request }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw BarrierError.readNotStarted
    }

    func release(_ data: Data) {
        finish(.success(data))
    }

    func cancel() {
        finish(.failure(CancellationError()))
    }

    private func expire() {
        finish(.failure(BarrierError.releaseTimedOut))
    }

    private func finish(_ result: Result<Data, any Error>) {
        guard let continuation else { return }
        self.continuation = nil
        timeout?.cancel()
        timeout = nil
        continuation.resume(with: result)
    }
}
