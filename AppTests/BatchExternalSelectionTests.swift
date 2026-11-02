import Foundation
import UIKit
import XCTest
import TravelCore
@testable import Tripfolio

/// Real local files exercise the production coordinator, semantic request and
/// coordinated model reader. Remote-provider delivery remains a native UI gate.
@MainActor
final class BatchExternalSelectionTests: XCTestCase {
    func testExternalSelectionPreservesURLValuesAndRejectsInvalidInputWithoutDeleting() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let relative = URL(fileURLWithPath: "one.pdf", relativeTo: fixture.originals)
        let original = try BatchExternalSelection([relative, fixture.urls[1]])
        XCTAssertEqual(original.urls[0].baseURL, relative.baseURL)
        XCTAssertEqual(original.urls[0].relativeString, relative.relativeString)
        XCTAssertEqual(original.urls, [relative, fixture.urls[1]])
        let repeated = try BatchExternalSelection([relative, relative])
        XCTAssertEqual(repeated.urls.count, 2, "Selection capture must not silently deduplicate")
        for invalid in [[], Array(repeating: relative, count: 11),
                        [relative, URL(string: "https://example.invalid/file.pdf")!],
                        [URL(string: "file://remote.invalid/file.pdf")!]] {
            XCTAssertThrowsError(try BatchExternalSelection(invalid))
        }
        BatchPickerSelection.external(original).dispose()
        fixture.assertOriginalsUnchanged()
    }

    func testTwoOriginalsAfterVisualDismantleArePreparedWithoutDeleting() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        delivery.presentation = nil
        BatchDocumentPicker.dismantleUIViewController(delivery.picker, coordinator: delivery.coordinator)
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        XCTAssertEqual(delivery.accepted, 1)
        try await waitUntil { delivery.finished == 1 }
        XCTAssertEqual(fixture.draft.phase, .reviewing)
        XCTAssertEqual(fixture.draft.items.map(\.filename), ["one.pdf", "two.pdf"])
        XCTAssertEqual(fixture.draft.items.map(\.originalData), fixture.bytes)
        XCTAssertFalse(fixture.draft.canSave)
        XCTAssertTrue(fixture.model.library.documents.isEmpty)
        fixture.assertOriginalsUnchanged()
        fixture.model.cancelBatchImport(draftID: fixture.draft.id)
        fixture.assertOriginalsUnchanged()
    }

    func testReadFailureRejectsWholeBatchAndPreservesOriginals() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        let absent = fixture.originals.appendingPathComponent("absent.pdf")
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: [fixture.urls[0], absent])
        try await waitUntil { delivery.finished == 1 }
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertEqual(fixture.draft.phase, .choosing)
        XCTAssertTrue(fixture.draft.items.isEmpty, "No prepared prefix may survive a failed read")
        XCTAssertNotNil(fixture.draft.errorMessage)
        XCTAssertFalse(FileManager.default.fileExists(atPath: absent.path))
        fixture.assertOriginalsUnchanged()
    }

    func testNativeCancelThenLateSelectionNeverReadsOrDeletesOriginals() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        delivery.coordinator.documentPickerWasCancelled(delivery.picker)
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertEqual(delivery.results, 0)
        XCTAssertEqual(delivery.finished, 0)
        XCTAssertTrue(fixture.draft.items.isEmpty)
        XCTAssertEqual(fixture.draft.phase, .choosing)
        XCTAssertNil(delivery.presentation)
        fixture.assertOriginalsUnchanged()
    }

    func testReplacedRequestRejectsOldURLsWithoutClearingNewPresentation() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        let replacement = BatchDocumentPicker.Session(draftID: fixture.draft.id)
        XCTAssertTrue(fixture.draft.beginPickerRequest(replacement.id))
        delivery.presentation = replacement
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        XCTAssertEqual(delivery.accepted, 0)
        XCTAssertEqual(delivery.finished, 0)
        XCTAssertTrue(delivery.presentation === replacement)
        XCTAssertTrue(fixture.draft.items.isEmpty)
        fixture.assertOriginalsUnchanged()
    }

    func testCancelledAndNewDraftRejectOldURLsWithoutDeleting() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        fixture.model.cancelBatchImport(draftID: fixture.draft.id)
        fixture.model.beginBatchImport(tripID: fixture.trip.id)
        let current = try XCTUnwrap(fixture.model.batchImportDraft)
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        XCTAssertEqual(delivery.accepted, 0)
        XCTAssertEqual(delivery.finished, 0)
        XCTAssertTrue(fixture.model.batchImportDraft === current)
        XCTAssertTrue(current.items.isEmpty)
        fixture.assertOriginalsUnchanged()
    }

    func testDuplicateCallbackAndCancelCannotRepeatPreparationOrDelete() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        delivery.coordinator.documentPickerWasCancelled(delivery.picker)
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertEqual(delivery.results, 1)
        fixture.assertOriginalsUnchanged()
        try await waitUntil { delivery.finished == 1 }
        XCTAssertEqual(fixture.draft.items.count, 2)
        fixture.assertOriginalsUnchanged()
    }

    func testModelRejectionReleasesBorrowedSelectionWithoutDeleting() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        fixture.model.isBusy = true
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertEqual(delivery.finished, 1)
        XCTAssertTrue(fixture.draft.items.isEmpty)
        fixture.assertOriginalsUnchanged()
        fixture.model.isBusy = false
    }

    func testCancelledPreparationFinishesWithoutDeletingOriginals() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = fixture.delivery()
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: fixture.urls)
        // Cancel before the newly scheduled preparation task gets its first turn.
        fixture.model.cancelBatchImport(draftID: fixture.draft.id)
        try await waitUntil { delivery.finished == 1 }
        XCTAssertNil(fixture.model.batchImportDraft)
        XCTAssertTrue(fixture.draft.items.isEmpty)
        fixture.assertOriginalsUnchanged()
    }

    private func waitUntil(_ predicate: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(10))
        while !predicate() {
            guard ContinuousClock.now < deadline else { throw WaitFailure.timedOut }
            try await Task.sleep(for: .milliseconds(5))
        }
    }
    private enum WaitFailure: Error { case timedOut }

    @MainActor
    private final class Delivery {
        let model: AppModel
        let session: BatchDocumentPicker.Session
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.pdf], asCopy: false)
        var presentation: BatchDocumentPicker.Session?
        var accepted = 0
        var results = 0
        var finished = 0
        lazy var coordinator = BatchDocumentPicker.Coordinator(session: session) { [unowned self] result in
            guard session.consumeRequest(from: model.batchImportDraft, clearing: &presentation) else {
                if case .success(let selection) = result { selection.dispose() }
                return
            }
            accepted += 1
            guard let result else { return }
            results += 1
            switch result {
            case .success(let selection):
                guard case .external = selection else { return XCTFail("Default picker must borrow originals") }
                model.prepareBatchImport(urls: selection.urls, draftID: session.draftID) { [self] in
                    selection.dispose()
                    finished += 1
                }
            case .failure(let error): XCTFail("Unexpected selection rejection: \(error)")
            }
        }
        init(model: AppModel, session: BatchDocumentPicker.Session) {
            self.model = model
            self.session = session
            presentation = session
        }
    }

    @MainActor
    private final class Fixture {
        let root: URL
        let originals: URL
        let urls: [URL]
        let bytes: [Data]
        let model: AppModel
        let trip: Trip
        let draft: BatchImportDraft
        init() async throws {
            let ownedRoot = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: ownedRoot, withIntermediateDirectories: true)
            do {
                let sourceRoot = ownedRoot.appendingPathComponent("originals", isDirectory: true)
                try FileManager.default.createDirectory(at: sourceRoot, withIntermediateDirectories: true)
                let data = ["FIRST SYNTHETIC", "SECOND SYNTHETIC"].map { text in
                    UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 100, height: 100)).pdfData { context in
                        context.beginPage()
                        (text as NSString).draw(at: CGPoint(x: 4, y: 4), withAttributes: nil)
                    }
                }
                let files = ["one.pdf", "two.pdf"].map { sourceRoot.appendingPathComponent($0) }
                for (url, content) in zip(files, data) { try content.write(to: url) }
                let library = ownedRoot.appendingPathComponent("library", isDirectory: true)
                let repository = try DocumentRepository(rootURL: library)
                let createdTrip = try await repository.createTrip(title: "Synthetic external originals", departureDate: nil)
                let createdModel = AppModel(rootURL: library, temporaryRootURL: ownedRoot.appendingPathComponent("exports"), proEntitlement: { true })
                await createdModel.refresh()
                createdModel.beginBatchImport(tripID: createdTrip.id)
                root = ownedRoot; originals = sourceRoot; urls = files; bytes = data
                model = createdModel; trip = createdTrip
                draft = try XCTUnwrap(createdModel.batchImportDraft)
            } catch {
                try? FileManager.default.removeItem(at: ownedRoot)
                throw error
            }
        }
        func delivery() -> Delivery {
            let session = BatchDocumentPicker.Session(draftID: draft.id)
            XCTAssertTrue(draft.beginPickerRequest(session.id))
            return Delivery(model: model, session: session)
        }
        func assertOriginalsUnchanged(file: StaticString = #filePath, line: UInt = #line) {
            for (url, content) in zip(urls, bytes) {
                XCTAssertEqual(try Data(contentsOf: url), content, file: file, line: line)
            }
        }
        func cleanup() {
            if let current = model.batchImportDraft { model.cancelBatchImport(draftID: current.id) }
            try? FileManager.default.removeItem(at: root)
        }
    }
}
