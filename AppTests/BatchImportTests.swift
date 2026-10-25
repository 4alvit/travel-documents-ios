import UIKit
import XCTest
import TravelCore
@testable import Tripfolio

/// Real repository and original bytes; only entitlement input and external
/// reading are controlled. These tests do not establish StoreKit or UI behavior.
@MainActor
final class BatchImportTests: XCTestCase {
    func testSelectionLimitsRejectBeforeReadingOrWriting() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: [:])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        let filesBefore = try FileManager.default.subpathsOfDirectory(atPath: root.path).sorted()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)

        model.prepareBatchImport(urls: [], draftID: draft.id)
        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertNotNil(draft.errorMessage)
        model.prepareBatchImport(urls: (0...10).map { url("\($0).pdf") }, draftID: draft.id)
        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertFalse(model.isBusy)
        let requests = await reader.requests
        XCTAssertTrue(requests.isEmpty)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
        XCTAssertEqual(try FileManager.default.subpathsOfDirectory(atPath: root.path).sorted(), filesBefore)
    }

    func testBadFileRejectsWholePreparationWithoutPersistingValidPrefix() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: ["good.pdf": pdf(), "bad.pdf": Data("incomplete PDF".utf8)])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        let filesBefore = try FileManager.default.subpathsOfDirectory(atPath: root.path).sorted()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("good.pdf"), url("bad.pdf")], draftID: draft.id)
        try await waitUntil { !model.isBusy }

        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertNotNil(draft.errorMessage)
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertEqual(draft.preparedCount, 0)
        XCTAssertFalse(draft.canSave)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
        XCTAssertEqual(try FileManager.default.subpathsOfDirectory(atPath: root.path).sorted(), filesBefore)
    }

    func testReturnedBytesAreCheckedEvenWhenReaderIgnoresPerFileLimit() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let oversized = Data(repeating: 0x20, count: DocumentRepository.maximumDocumentBytes + 1)
        let reader = BatchScriptedReader(data: ["too-large.pdf": oversized])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("too-large.pdf")], draftID: draft.id)
        try await waitUntil { !model.isBusy }

        let requests = await reader.requests
        XCTAssertEqual(requests.map(\.maximum), [DocumentRepository.maximumDocumentBytes])
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertEqual(draft.errorMessage, RepositoryError.documentTooLarge.localizedDescription)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testAggregateLimitShrinksNextReadAndRejectsAllCopies() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let mib = 1_024 * 1_024
        let large = paddedPDF(bytes: 15 * mib)
        let tail = paddedPDF(bytes: 6 * mib)
        try DocumentRepository.validateImportData(large)
        try DocumentRepository.validateImportData(tail)
        let reader = BatchScriptedReader(data: ["large.pdf": large, "tail.pdf": tail])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: Array(repeating: url("large.pdf"), count: 4) + [url("tail.pdf")], draftID: draft.id)
        try await waitUntil { !model.isBusy }

        let requests = await reader.requests
        XCTAssertEqual(requests.map(\.maximum), [16, 16, 16, 16, 4].map { $0 * mib })
        XCTAssertEqual(draft.errorMessage, BatchImportError.noSpace.localizedDescription)
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertFalse(draft.canSave)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testCancellationClosesImmediatelyAndLateReadCannotTouchNewSession() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchHeldReader()
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        model.beginBatchImport(tripID: trip.id)
        let oldID = try XCTUnwrap(model.batchImportDraft?.id)
        let obsolete = WeakBatchDraft(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("old.pdf")], draftID: oldID)
        try await reader.waitForRequests(1)
        model.cancelBatchImport(draftID: oldID)
        XCTAssertNil(model.batchImportDraft)
        XCTAssertFalse(model.isBusy)

        model.beginBatchImport(tripID: trip.id)
        let current = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("new.pdf")], draftID: current.id)
        try await reader.waitForRequests(2)
        await reader.release(0, data: pdf("Old cancelled original"))
        // The old worker retains its local draft across the held read. Releasing
        // that reference proves it finished before checking the new busy owner.
        try await waitUntil { obsolete.value == nil }
        XCTAssertTrue(model.batchImportDraft === current)
        XCTAssertEqual(current.phase, .preparing)
        XCTAssertTrue(current.items.isEmpty)
        XCTAssertTrue(model.isBusy)
        await reader.release(1, data: pdf("New original"))
        try await waitUntil { current.phase == .reviewing && !model.isBusy }
        XCTAssertEqual(current.items.map(\.filename), ["new.pdf"])
        let after = try await repository.load()
        XCTAssertEqual(after, before)
        model.cancelBatchImport(draftID: current.id)
    }

    func testStalePickerSaveAndCancelActionsCannotChangeCurrentDraft() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: ["new.pdf": pdf()])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        model.beginBatchImport(tripID: trip.id)
        let oldID = try XCTUnwrap(model.batchImportDraft?.id)
        model.cancelBatchImport(draftID: oldID)
        model.beginBatchImport(tripID: trip.id)
        let current = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("stale.pdf")], draftID: oldID)
        model.cancelBatchImport(draftID: oldID)
        let staleSave = await model.commitBatchImport(draftID: oldID)
        XCTAssertFalse(staleSave)
        XCTAssertTrue(model.batchImportDraft === current)
        XCTAssertEqual(current.phase, .choosing)
        let requests = await reader.requests
        XCTAssertTrue(requests.isEmpty)

        model.prepareBatchImport(urls: [url("new.pdf")], draftID: current.id)
        try await waitUntil { current.phase == .reviewing && !model.isBusy }
        let item = try XCTUnwrap(current.items.first)
        model.confirmBatchItem(id: item.id)
        model.cancelBatchImport(draftID: oldID)
        let anotherStaleSave = await model.commitBatchImport(draftID: oldID)
        XCTAssertFalse(anotherStaleSave)
        XCTAssertTrue(model.batchImportDraft === current)
        XCTAssertTrue(current.canSave)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testProIsRequiredBeforeBeginningAndPreparing() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: [:])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        entitlement.isPro = false
        model.beginBatchImport(tripID: trip.id)
        XCTAssertNil(model.batchImportDraft)
        XCTAssertNotNil(model.errorMessage)
        entitlement.isPro = true
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        entitlement.isPro = false
        model.prepareBatchImport(urls: [url("not-read.pdf")], draftID: draft.id)
        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertEqual(draft.errorMessage, BatchImportError.proRequired.localizedDescription)
        let requests = await reader.requests
        XCTAssertTrue(requests.isEmpty)
        let persisted = try await repository.load()
        XCTAssertTrue(persisted.documents.isEmpty)
    }

    func testProLossDuringPreparationDiscardsWholePreparedPrefix() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchHeldReader()
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("one.pdf"), url("two.pdf")], draftID: draft.id)
        try await reader.waitForRequests(1)
        await reader.release(0, data: pdf())
        try await reader.waitForRequests(2)
        XCTAssertEqual(draft.preparedCount, 1)
        entitlement.isPro = false
        await reader.release(1, data: pdf())
        try await waitUntil { !model.isBusy }
        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertEqual(draft.preparedCount, 0)
        XCTAssertEqual(draft.errorMessage, BatchImportError.proRequired.localizedDescription)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testMetadataEditsInvalidateExplicitConfirmationAndRemovalUpdatesSaveEligibility() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: ["one.pdf": pdf(), "two.pdf": pdf()])
        let entitlement = BatchEntitlementState()
        let (model, _, trip, person) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let draft = try await prepare(model, trip: trip, filenames: ["one.pdf", "two.pdf"])
        let item = try XCTUnwrap(draft.items.first)
        XCTAssertFalse(item.isReviewed)
        XCTAssertFalse(draft.canSave)
        model.confirmBatchItem(id: item.id)
        XCTAssertTrue(item.isReviewed)
        let originalTitle = item.title
        item.title = "Edited title"
        XCTAssertFalse(item.isReviewed)
        item.title = originalTitle
        XCTAssertFalse(item.isReviewed, "Reverting an edit must still require fresh confirmation")
        model.confirmBatchItem(id: item.id)
        item.kind = .ticket
        XCTAssertFalse(item.isReviewed)
        model.confirmBatchItem(id: item.id)
        item.travelerID = person.id
        XCTAssertFalse(item.isReviewed)
        model.confirmBatchItem(id: item.id)
        item.hasExpiry = true
        XCTAssertFalse(item.isReviewed)
        model.confirmBatchItem(id: item.id)
        item.expiryDate = item.expiryDate.addingTimeInterval(86_400)
        XCTAssertFalse(item.isReviewed)
        item.title = "\n"
        model.confirmBatchItem(id: item.id)
        XCTAssertFalse(item.isReviewed)
        XCTAssertNotNil(draft.errorMessage)
        item.title = "Reviewed original"
        model.confirmBatchItem(id: item.id)
        XCTAssertFalse(draft.canSave, "The second item has not been confirmed")
        model.removeBatchItem(id: draft.items[1].id)
        XCTAssertTrue(draft.canSave)
    }

    func testProLossBeforeCommitBlocksWholeBatchAndKeepsReviewableDraft() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let original = pdf()
        let reader = BatchScriptedReader(data: ["one.pdf": original, "two.pdf": pdf()])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let before = try await repository.load()
        let draft = try await prepare(model, trip: trip, filenames: ["one.pdf", "two.pdf"])
        for item in draft.items { model.confirmBatchItem(id: item.id) }
        entitlement.isPro = false
        let saved = await model.commitBatchImport(draftID: draft.id)
        XCTAssertFalse(saved)
        XCTAssertTrue(model.batchImportDraft === draft)
        XCTAssertEqual(draft.phase, .reviewing)
        XCTAssertEqual(draft.items.count, 2)
        XCTAssertTrue(draft.items.allSatisfy(\.isReviewed))
        XCTAssertEqual(draft.errorMessage, BatchImportError.proRequired.localizedDescription)
        XCTAssertFalse(model.isBusy)
        let preview = try XCTUnwrap(model.batchPreviewURL(itemID: draft.items[0].id))
        XCTAssertEqual(try Data(contentsOf: preview), original)
        model.removeTemporary(preview)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testConfirmedBatchPublishesTogetherWithExactOriginalsAndPortableRecovery() async throws {
        let root = temporaryRoot(), recoveryRoot = temporaryRoot()
        defer {
            try? FileManager.default.removeItem(at: root)
            try? FileManager.default.removeItem(at: recoveryRoot)
        }
        let first = pdf("SYNTHETIC ticket"), second = pdf("SYNTHETIC insurance")
        let reader = BatchScriptedReader(data: ["ticket.pdf": first, "insurance.pdf": second])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, person) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let draft = try await prepare(model, trip: trip, filenames: ["ticket.pdf", "insurance.pdf"])
        let unreviewedSave = await model.commitBatchImport(draftID: draft.id)
        XCTAssertFalse(unreviewedSave)
        let stillEmpty = try await repository.load()
        XCTAssertTrue(stillEmpty.documents.isEmpty)
        let expiry = Date(timeIntervalSince1970: 1_900_000_000)
        draft.items[0].title = "Confirmed ticket"
        draft.items[0].kind = .ticket
        draft.items[0].travelerID = person.id
        draft.items[0].hasExpiry = true
        draft.items[0].expiryDate = expiry
        for item in draft.items { model.confirmBatchItem(id: item.id) }

        let saved = await model.commitBatchImport(draftID: draft.id)
        XCTAssertTrue(saved)
        XCTAssertNil(model.batchImportDraft)
        XCTAssertFalse(model.isBusy)
        let persisted = try await repository.load()
        XCTAssertEqual(persisted, model.library)
        XCTAssertEqual(persisted.documents.count, 2)
        let ticket = try XCTUnwrap(persisted.documents.first { $0.originalFilename == "ticket.pdf" })
        let insurance = try XCTUnwrap(persisted.documents.first { $0.originalFilename == "insurance.pdf" })
        XCTAssertEqual(ticket.title, "Confirmed ticket")
        XCTAssertEqual(ticket.kind, .ticket)
        XCTAssertEqual(ticket.travelerID, person.id)
        XCTAssertEqual(ticket.expiryDate, TravelDate.stored(from: expiry))
        XCTAssertNil(insurance.expiryDate)
        let ticketBytes = try await repository.documentData(id: ticket.id)
        let insuranceBytes = try await repository.documentData(id: insurance.id)
        XCTAssertEqual(ticketBytes, first)
        XCTAssertEqual(insuranceBytes, second)

        entitlement.isPro = false
        let exportResult = await model.makeBackup(documentIDs: nil)
        let backupURL = try XCTUnwrap(exportResult)
        defer { model.removeTemporary(backupURL) }
        let recovery = try DocumentRepository(rootURL: recoveryRoot)
        let restored = try await recovery.restoreBackup(Data(contentsOf: backupURL))
        XCTAssertEqual(restored, persisted)
        let restoredFirst = try await recovery.documentData(id: ticket.id)
        let restoredSecond = try await recovery.documentData(id: insurance.id)
        XCTAssertEqual(restoredFirst, first)
        XCTAssertEqual(restoredSecond, second)
    }

    func testRepositoryFailureKeepsConfirmedDraftForRetryWithoutPrefixWrites() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let original = pdf("Existing synthetic original")
        let reader = BatchScriptedReader(data: ["new.pdf": pdf("New synthetic original")])
        let entitlement = BatchEntitlementState()
        let (model, repository, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        await model.importData(original, filename: "existing.pdf", tripID: trip.id, travelerID: nil,
                               title: "Existing", kind: .booking, expiryDate: nil)
        let before = model.library
        let existing = try XCTUnwrap(before.documents.first)
        XCTAssertEqual(model.remainingLibraryBytes, DocumentRepository.maximumLibraryBytes - original.count)
        let draft = try await prepare(model, trip: trip, filenames: ["new.pdf"])
        let item = try XCTUnwrap(draft.items.first)
        model.confirmBatchItem(id: item.id)
        let contents = FileManager.default.enumerator(at: root, includingPropertiesForKeys: nil)?.allObjects ?? []
        let originalURL = try XCTUnwrap(contents.compactMap { $0 as? URL }.first { $0.lastPathComponent == existing.storedFilename })
        try FileManager.default.removeItem(at: originalURL)
        model.notice = nil

        let saved = await model.commitBatchImport(draftID: draft.id)
        XCTAssertFalse(saved)
        XCTAssertTrue(model.batchImportDraft === draft)
        XCTAssertEqual(draft.phase, .reviewing)
        XCTAssertTrue(item.isReviewed)
        XCTAssertTrue(draft.canSave)
        XCTAssertNotNil(draft.errorMessage)
        XCTAssertNil(model.notice)
        XCTAssertFalse(model.isBusy)
        XCTAssertEqual(model.library, before)
        let afterFailure = try await repository.load()
        XCTAssertEqual(afterFailure, before)

        // Repair only the test-induced missing original, then retry the same
        // confirmed draft. A failed attempt must not have added a hidden prefix.
        try original.write(to: originalURL, options: .atomic)
        let retried = await model.commitBatchImport(draftID: draft.id)
        XCTAssertTrue(retried)
        let afterRetry = try await repository.load()
        XCTAssertEqual(afterRetry.documents.count, 2)
        XCTAssertEqual(afterRetry.documents.filter { $0.originalFilename == "new.pdf" }.count, 1)
    }

    func testModelDraftSurvivesUnchangedRefreshAndIsInvalidatedByLibraryChanges() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: ["one.pdf": pdf()])
        let entitlement = BatchEntitlementState()
        let (model, _, trip, person) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        let draft = try await prepare(model, trip: trip, filenames: ["one.pdf"])
        let item = try XCTUnwrap(draft.items.first)
        item.title = "Unsaved title survives view recreation"
        item.travelerID = person.id
        model.confirmBatchItem(id: item.id)
        await model.refresh()
        XCTAssertTrue(model.batchImportDraft === draft)
        XCTAssertTrue(draft.items.first === item)
        XCTAssertEqual(item.title, "Unsaved title survives view recreation")
        XCTAssertTrue(item.isReviewed)
        // This asserts model lifetime only; normal-auth UI teardown is separate.
        await model.deleteTraveler(id: person.id)
        XCTAssertNil(model.batchImportDraft)
        XCTAssertTrue(draft.items.isEmpty)
        model.beginBatchImport(tripID: trip.id)
        XCTAssertNotNil(model.batchImportDraft)
        await model.deleteTrip(id: trip.id)
        XCTAssertNil(model.batchImportDraft)
    }

    func testDocumentEditAndBatchDraftCannotSilentlyReplaceEachOther() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = BatchScriptedReader(data: [:])
        let entitlement = BatchEntitlementState()
        let (model, _, trip, _) = try await fixture(root: root, entitlement: entitlement,
            read: { try await reader.read($0, maximum: $1) })
        await model.importData(pdf(), filename: "existing.pdf", tripID: trip.id, travelerID: nil,
                               title: "Existing", kind: .booking, expiryDate: nil)
        let document = try XCTUnwrap(model.library.documents.first)
        model.beginEditingDocument(document)
        let edit = try XCTUnwrap(model.documentEditDraft)
        edit.title = "Do not discard this edit"
        model.beginBatchImport(tripID: trip.id)
        XCTAssertNil(model.batchImportDraft)
        XCTAssertTrue(model.documentEditDraft === edit)
        XCTAssertEqual(edit.title, "Do not discard this edit")
        model.cancelDocumentEdit()
        model.beginBatchImport(tripID: trip.id)
        let batch = try XCTUnwrap(model.batchImportDraft)
        model.beginEditingDocument(document)
        XCTAssertNil(model.documentEditDraft)
        XCTAssertTrue(model.batchImportDraft === batch)
    }

    private func fixture(root: URL, entitlement: BatchEntitlementState,
                         read: @escaping @Sendable (URL, Int) async throws -> Data)
        async throws -> (AppModel, DocumentRepository, Trip, Traveler) {
        let repository = try DocumentRepository(rootURL: root)
        let trip = try await repository.createTrip(title: "Synthetic batch trip", departureDate: nil)
        let person = try await repository.addTraveler(name: "Synthetic traveler")
        let model = AppModel(rootURL: root, proEntitlement: { entitlement.isPro }, readExternal: read)
        await model.refresh()
        return (model, repository, trip, person)
    }

    private func prepare(_ model: AppModel, trip: Trip, filenames: [String]) async throws -> BatchImportDraft {
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: filenames.map(url), draftID: draft.id)
        try await waitUntil { !model.isBusy }
        XCTAssertEqual(draft.phase, .reviewing, draft.errorMessage ?? "No preparation error")
        XCTAssertEqual(draft.preparedCount, filenames.count)
        return draft
    }

    private func waitUntil(_ condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(5))
        while ContinuousClock.now < deadline {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw BatchTestError.timedOut
    }

    private func temporaryRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("BatchTests-" + UUID().uuidString)
    }

    private func url(_ filename: String) -> URL {
        URL(fileURLWithPath: "/synthetic-files").appendingPathComponent(filename)
    }

    private func pdf(_ title: String = "SYNTHETIC BATCH — NOT VALID FOR TRAVEL") -> Data {
        UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 400, height: 500)).pdfData { context in
            context.beginPage()
            NSString(string: title).draw(at: CGPoint(x: 30, y: 30), withAttributes: [.font: UIFont.systemFont(ofSize: 14)])
        }
    }

    private func paddedPDF(bytes: Int) -> Data {
        // Keep a valid xref and %%EOF at the end; appending padding after EOF
        // would test a malformed PDF instead of the aggregate byte limit.
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
        let tailLength = table.utf8.count + 10 + "\n%%EOF\n".utf8.count
        let xrefOffset = bytes - tailLength
        precondition(xrefOffset > data.count)
        data.append(Data(repeating: 0x20, count: xrefOffset - data.count - 1))
        data.append(0x0A)
        data.append(Data((table + String(format: "%010d", xrefOffset) + "\n%%EOF\n").utf8))
        precondition(data.count == bytes)
        return data
    }

}

private enum BatchTestError: Error { case timedOut, missingFixture }

@MainActor private final class BatchEntitlementState { var isPro = true }
@MainActor private final class WeakBatchDraft {
    weak var value: BatchImportDraft?
    init(_ value: BatchImportDraft?) { self.value = value }
}

private struct BatchReadRequest: Sendable {
    let url: URL
    let maximum: Int
}

private actor BatchScriptedReader {
    let data: [String: Data]
    private(set) var requests: [BatchReadRequest] = []
    init(data: [String: Data]) { self.data = data }

    func read(_ url: URL, maximum: Int) throws -> Data {
        requests.append(BatchReadRequest(url: url, maximum: maximum))
        guard let bytes = data[url.lastPathComponent] else { throw BatchTestError.missingFixture }
        return bytes
    }
}

/// Intentionally returns valid bytes even after the caller is cancelled, so
/// the test can prove that a late result cannot publish into another session.
private actor BatchHeldReader {
    private var requests: [BatchReadRequest] = []
    private var continuations: [Int: CheckedContinuation<Data, any Error>] = [:]
    private var timeouts: [Int: Task<Void, Never>] = [:]

    func read(_ url: URL, maximum: Int) async throws -> Data {
        let index = requests.count
        requests.append(BatchReadRequest(url: url, maximum: maximum))
        return try await withCheckedThrowingContinuation { continuation in
            continuations[index] = continuation
            timeouts[index] = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(5)) }
                catch { return }
                await self?.finish(index, result: .failure(BatchTestError.timedOut))
            }
        }
    }

    func waitForRequests(_ count: Int) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while ContinuousClock.now < deadline {
            if requests.count >= count { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw BatchTestError.timedOut
    }

    func release(_ index: Int, data: Data) { finish(index, result: .success(data)) }

    private func finish(_ index: Int, result: Result<Data, any Error>) {
        guard let continuation = continuations.removeValue(forKey: index) else { return }
        timeouts.removeValue(forKey: index)?.cancel()
        continuation.resume(with: result)
    }
}
