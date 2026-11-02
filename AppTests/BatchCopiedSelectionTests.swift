import UIKit
import XCTest
import TravelCore
@testable import Tripfolio

/// The picker owns its copied files. The model releases that ownership only
/// after every read finishes, even when the visible draft has already closed.
@MainActor
final class BatchCopiedSelectionTests: XCTestCase {
    func testRejectedSelectionsFinishImmediatelyWithoutReading() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let entitlement = CopiedSelectionEntitlement()
        let (model, repository, trip) = try await fixture(root, reader, entitlement)
        let before = try await repository.load()
        let completion = CopiedSelectionCompletion()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        for urls in [[], (0...10).map { url("\($0).pdf") }] {
            model.prepareBatchImport(urls: urls, draftID: draft.id) { completion.count += 1 }
        }
        model.prepareBatchImport(urls: [url("stale.pdf")], draftID: UUID()) { completion.count += 1 }
        entitlement.isPro = false
        model.prepareBatchImport(urls: [url("free.pdf")], draftID: draft.id) { completion.count += 1 }
        model.isBusy = true
        model.prepareBatchImport(urls: [url("busy.pdf")], draftID: draft.id) { completion.count += 1 }
        XCTAssertEqual(completion.count, 5)
        let requests = await reader.requestCount
        XCTAssertEqual(requests, 0)
        XCTAssertTrue(draft.items.isEmpty)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testSuccessFinishesAfterAllReadsAndKeepsPreparedBytes() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let (model, repository, trip) = try await fixture(root, reader)
        let before = try await repository.load()
        let completion = CopiedSelectionCompletion()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("one.pdf"), url("two.pdf")], draftID: draft.id) {
            completion.count += 1
        }
        try await reader.waitForRequests(1)
        XCTAssertEqual(completion.count, 0)
        let bytes = pdf()
        await reader.release(0, result: .success(bytes))
        try await reader.waitForRequests(2)
        XCTAssertEqual(completion.count, 0)
        await reader.release(1, result: .success(bytes))
        try await waitUntil { completion.count == 1 }
        XCTAssertEqual(draft.phase, .reviewing)
        XCTAssertEqual(draft.items.map(\.originalData), [bytes, bytes])
        XCTAssertFalse(draft.canSave, "Cleanup must not bypass individual review")
        XCTAssertFalse(model.isBusy)
        model.cancelBatchImport(draftID: draft.id)
        XCTAssertEqual(completion.count, 1)
        let after = try await repository.load()
        XCTAssertEqual(after, before)
    }

    func testReadFailureFinishesOnceAndRejectsPreparedPrefix() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let (model, _, trip) = try await fixture(root, reader)
        let completion = CopiedSelectionCompletion()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("one.pdf"), url("failed.pdf")], draftID: draft.id) {
            completion.count += 1
        }
        try await reader.waitForRequests(1)
        await reader.release(0, result: .success(pdf()))
        try await reader.waitForRequests(2)
        XCTAssertEqual(completion.count, 0)
        await reader.release(1, result: .failure(CopiedSelectionFailure.read))
        try await waitUntil { completion.count == 1 }
        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertNotNil(draft.errorMessage)
        model.cancelBatchImport(draftID: draft.id)
        XCTAssertEqual(completion.count, 1)
    }

    func testInvalidReturnedDataFinishesOnceWithoutReview() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let (model, _, trip) = try await fixture(root, reader)
        let completion = CopiedSelectionCompletion()
        model.beginBatchImport(tripID: trip.id)
        let draft = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("invalid.pdf")], draftID: draft.id) { completion.count += 1 }
        try await reader.waitForRequests(1)
        await reader.release(0, result: .success(Data("not a document".utf8)))
        try await waitUntil { completion.count == 1 }
        XCTAssertEqual(draft.phase, .choosing)
        XCTAssertTrue(draft.items.isEmpty)
        XCTAssertNotNil(draft.errorMessage)
    }

    func testCancellationWaitsForOldReadAndDoesNotReleaseNewSelection() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let (model, _, trip) = try await fixture(root, reader)
        let oldCompletion = CopiedSelectionCompletion()
        let newCompletion = CopiedSelectionCompletion()
        model.beginBatchImport(tripID: trip.id)
        let oldID = try XCTUnwrap(model.batchImportDraft?.id)
        model.prepareBatchImport(urls: [url("old.pdf")], draftID: oldID) { oldCompletion.count += 1 }
        try await reader.waitForRequests(1)
        model.cancelBatchImport(draftID: oldID)
        XCTAssertEqual(oldCompletion.count, 0, "A canceled read may still hold the copied file open")
        model.beginBatchImport(tripID: trip.id)
        let current = try XCTUnwrap(model.batchImportDraft)
        model.prepareBatchImport(urls: [url("new.pdf")], draftID: current.id) { newCompletion.count += 1 }
        try await reader.waitForRequests(2)
        await reader.release(0, result: .success(pdf()))
        try await waitUntil { oldCompletion.count == 1 }
        XCTAssertEqual(newCompletion.count, 0)
        XCTAssertTrue(model.batchImportDraft === current)
        XCTAssertTrue(model.isBusy)
        XCTAssertTrue(current.items.isEmpty)
        await reader.release(1, result: .success(pdf()))
        try await waitUntil { newCompletion.count == 1 }
        XCTAssertEqual(oldCompletion.count, 1)
        XCTAssertEqual(current.items.map(\.filename), ["new.pdf"])
    }

    func testLibraryInvalidationWaitsForOutstandingRead() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let (model, _, trip) = try await fixture(root, reader)
        let completion = CopiedSelectionCompletion()
        model.beginBatchImport(tripID: trip.id)
        let id = try XCTUnwrap(model.batchImportDraft?.id)
        model.prepareBatchImport(urls: [url("stale.pdf")], draftID: id) { completion.count += 1 }
        try await reader.waitForRequests(1)
        model.library = .empty
        XCTAssertNil(model.batchImportDraft)
        XCTAssertEqual(completion.count, 0)
        await reader.release(0, result: .success(pdf()))
        try await waitUntil { completion.count == 1 }
        XCTAssertNil(model.batchImportDraft)
        XCTAssertFalse(model.isBusy)
    }

    func testModelReleasedBeforeTaskStartsStillFinishesSelection() async throws {
        let root = temporaryRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let reader = CopiedSelectionReader()
        let repository = try DocumentRepository(rootURL: root)
        let trip = try await repository.createTrip(title: "Synthetic copy lifetime", departureDate: nil)
        var model: AppModel? = AppModel(rootURL: root, temporaryRootURL: root.appendingPathComponent("exports"),
            proEntitlement: { true }, readExternal: { try await reader.read($0, maximum: $1) })
        await model?.refresh()
        model?.beginBatchImport(tripID: trip.id)
        let id = try XCTUnwrap(model?.batchImportDraft?.id)
        let completion = CopiedSelectionCompletion()
        weak var released = model
        model?.prepareBatchImport(urls: [url("unused.pdf")], draftID: id) { completion.count += 1 }
        model = nil // MainActor has not yielded to the newly created task.
        XCTAssertNil(released)
        try await waitUntil { completion.count == 1 }
        let requests = await reader.requestCount
        XCTAssertEqual(requests, 0)
    }

    private func fixture(_ root: URL, _ reader: CopiedSelectionReader,
                         _ entitlement: CopiedSelectionEntitlement? = nil)
        async throws -> (AppModel, DocumentRepository, Trip) {
        let entitlement = entitlement ?? CopiedSelectionEntitlement()
        let repository = try DocumentRepository(rootURL: root)
        let trip = try await repository.createTrip(title: "Synthetic copy lifetime", departureDate: nil)
        let model = AppModel(rootURL: root, temporaryRootURL: root.appendingPathComponent("exports"),
            proEntitlement: { entitlement.isPro }, readExternal: { try await reader.read($0, maximum: $1) })
        await model.refresh()
        return (model, repository, trip)
    }

    private func temporaryRoot() -> URL {
        FileManager.default.temporaryDirectory.appendingPathComponent("BatchCopiedSelectionTests-" + UUID().uuidString)
    }
    private func url(_ name: String) -> URL { URL(fileURLWithPath: "/synthetic-copied-files").appendingPathComponent(name) }
    private func pdf() -> Data {
        UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 200, height: 200)).pdfData { context in
            context.beginPage()
            NSString(string: "SYNTHETIC COPY").draw(at: CGPoint(x: 20, y: 20))
        }
    }
    private func waitUntil(_ predicate: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(5))
        while ContinuousClock.now < deadline {
            if predicate() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw CopiedSelectionFailure.timedOut
    }
}

@MainActor private final class CopiedSelectionCompletion { var count = 0 }
@MainActor private final class CopiedSelectionEntitlement { var isPro = true }
private enum CopiedSelectionFailure: Error { case read, timedOut }

/// Deliberately ignores caller cancellation until released: cleanup must wait
/// for that read, not merely for the visible draft to disappear.
private actor CopiedSelectionReader {
    private(set) var requestCount = 0
    private var continuations: [Int: CheckedContinuation<Data, any Error>] = [:]
    private var timeouts: [Int: Task<Void, Never>] = [:]
    func read(_ url: URL, maximum: Int) async throws -> Data {
        let index = requestCount
        requestCount += 1
        return try await withCheckedThrowingContinuation { continuation in
            continuations[index] = continuation
            timeouts[index] = Task { [weak self] in
                do { try await Task.sleep(for: .seconds(5)) } catch { return }
                await self?.release(index, result: .failure(CopiedSelectionFailure.timedOut))
            }
        }
    }
    func waitForRequests(_ count: Int) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while ContinuousClock.now < deadline {
            if requestCount >= count { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw CopiedSelectionFailure.timedOut
    }
    func release(_ index: Int, result: Result<Data, any Error>) {
        guard let continuation = continuations.removeValue(forKey: index) else { return }
        timeouts.removeValue(forKey: index)?.cancel()
        continuation.resume(with: result)
    }
}
