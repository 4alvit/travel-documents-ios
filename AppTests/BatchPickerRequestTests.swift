import Foundation
import UIKit
import XCTest
import TravelCore
@testable import Tripfolio

/// Exercises the production coordinator/request gate and model. Delegate inputs
/// are synthetic; the separate real Files UI test still validates native import.
@MainActor
final class BatchPickerRequestTests: XCTestCase {
    func testResultAfterPresentationDismantlePreparesCurrentDraft() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = try fixture.delivery()
        let copies = try fixture.copies()
        delivery.presentation = nil // UIKit/SwiftUI has already dismissed.
        BatchDocumentPicker.dismantleUIViewController(delivery.picker, coordinator: delivery.coordinator)
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: copies)
        XCTAssertFalse(delivery.session.active, "Coordinator consumes its terminal callback before the semantic gate")
        XCTAssertEqual(delivery.accepted, 1)
        try await waitUntil { fixture.draft.phase == .reviewing }
        XCTAssertEqual(fixture.draft.items.map(\.originalData), [fixture.pdf, fixture.pdf])
        XCTAssertFalse(fixture.draft.canSave, "Individual review remains required")
        XCTAssertTrue(copies.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
        XCTAssertTrue(fixture.model.library.documents.isEmpty)
    }

    func testReplacedRequestCannotClearNewPresentationOrPrepare() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let old = try fixture.delivery()
        let replacement = BatchDocumentPicker.Session(draftID: fixture.draft.id)
        XCTAssertTrue(fixture.draft.beginPickerRequest(replacement.id))
        old.presentation = replacement
        let copies = try fixture.copies()
        old.coordinator.documentPicker(old.picker, didPickDocumentsAt: copies)
        XCTAssertEqual(old.accepted, 0)
        XCTAssertTrue(old.presentation === replacement)
        XCTAssertTrue(fixture.draft.items.isEmpty)
        XCTAssertEqual(fixture.draft.phase, .choosing)
        XCTAssertTrue(copies.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
        XCTAssertTrue(replacement.consumeRequest(from: fixture.model.batchImportDraft, clearing: &old.presentation))
    }

    func testCancelledDraftRejectsLateResultAndDisposesCopies() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = try fixture.delivery()
        fixture.model.cancelBatchImport(draftID: fixture.draft.id)
        let copies = try fixture.copies()
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: copies)
        XCTAssertNil(fixture.model.batchImportDraft)
        XCTAssertEqual(delivery.accepted, 0)
        XCTAssertTrue(copies.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testNewDraftRejectsOldResultWithoutConsumingNewRequest() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let old = try fixture.delivery()
        fixture.model.cancelBatchImport(draftID: fixture.draft.id)
        fixture.model.beginBatchImport(tripID: fixture.trip.id)
        let current = try XCTUnwrap(fixture.model.batchImportDraft)
        let replacement = BatchDocumentPicker.Session(draftID: current.id)
        XCTAssertTrue(current.beginPickerRequest(replacement.id))
        old.presentation = replacement
        let copies = try fixture.copies()
        old.coordinator.documentPicker(old.picker, didPickDocumentsAt: copies)
        XCTAssertTrue(fixture.model.batchImportDraft === current)
        XCTAssertEqual(old.accepted, 0)
        XCTAssertTrue(old.presentation === replacement)
        XCTAssertTrue(current.items.isEmpty)
        XCTAssertTrue(replacement.consumeRequest(from: current, clearing: &old.presentation))
        XCTAssertTrue(copies.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testDuplicateResultCannotReacquireOrDeleteInUseLease() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = try fixture.delivery()
        let copies = try fixture.copies()
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: copies)
        // The scheduled model task has not run while this MainActor turn is held.
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: copies)
        delivery.coordinator.documentPickerWasCancelled(delivery.picker)
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertTrue(copies.allSatisfy { FileManager.default.fileExists(atPath: $0.path) })
        try await waitUntil { fixture.draft.phase == .reviewing }
        XCTAssertEqual(fixture.draft.items.count, 2)
        XCTAssertTrue(copies.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testNativeCancelConsumesRequestWithoutResultThenRejectsLateSelection() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = try fixture.delivery()
        delivery.coordinator.documentPickerWasCancelled(delivery.picker)
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertEqual(delivery.resultCount, 0)
        XCTAssertNil(delivery.presentation)
        XCTAssertFalse(delivery.session.consumeRequest(from: fixture.draft, clearing: &delivery.presentation))
        let copies = try fixture.copies()
        delivery.coordinator.documentPicker(delivery.picker, didPickDocumentsAt: copies)
        XCTAssertEqual(delivery.accepted, 1)
        XCTAssertTrue(fixture.draft.items.isEmpty)
        XCTAssertTrue(copies.allSatisfy { !FileManager.default.fileExists(atPath: $0.path) })
    }

    func testNonChoosingPhaseConsumesButRejectsRequestPermanently() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        let delivery = try fixture.delivery()
        fixture.draft.phase = .preparing
        XCTAssertFalse(delivery.session.consumeRequest(from: fixture.draft, clearing: &delivery.presentation))
        fixture.draft.phase = .choosing
        XCTAssertFalse(delivery.session.consumeRequest(from: fixture.draft, clearing: &delivery.presentation))
    }

    func testCannotBeginRequestOutsideChoosingPhase() async throws {
        let fixture = try await Fixture()
        defer { fixture.cleanup() }
        for phase: BatchImportDraft.Phase in [.preparing, .reviewing, .committing] {
            fixture.draft.phase = phase
            XCTAssertFalse(fixture.draft.beginPickerRequest(UUID()))
        }
    }

    private func waitUntil(_ condition: @MainActor () -> Bool) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(10))
        while !condition() {
            guard clock.now < deadline else { return XCTFail("Preparation did not finish") }
            try await Task.sleep(for: .milliseconds(5))
        }
    }

    @MainActor
    private final class Delivery {
        let model: AppModel
        let session: BatchDocumentPicker.Session
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.pdf], asCopy: true)
        var presentation: BatchDocumentPicker.Session?
        var accepted = 0
        var resultCount = 0
        lazy var coordinator = BatchDocumentPicker.Coordinator(session: session, capture: { .copied(try BatchDocumentSelection.capture($0)) }) { [unowned self] result in
            guard session.consumeRequest(from: model.batchImportDraft, clearing: &presentation) else {
                if case .success(let selection) = result { selection.dispose() }
                return
            }
            accepted += 1
            guard let result else { return }
            resultCount += 1
            switch result {
            case .success(let selection):
                model.prepareBatchImport(urls: selection.urls, draftID: session.draftID,
                                         onConsumptionFinished: { selection.dispose() })
            case .failure(let error):
                XCTFail("Unexpected selection failure: \(error)")
            }
        }
        init(model: AppModel, session: BatchDocumentPicker.Session) {
            self.model = model
            self.session = session
            self.presentation = session
        }
    }

    @MainActor
    private final class Fixture {
        let root: URL
        let model: AppModel
        let trip: Trip
        let draft: BatchImportDraft
        let pdf: Data
        init() async throws {
            let ownedRoot = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: ownedRoot, withIntermediateDirectories: true)
            do {
                let library = ownedRoot.appendingPathComponent("library", isDirectory: true)
                let repository = try DocumentRepository(rootURL: library)
                let createdTrip = try await repository.createTrip(title: "Synthetic picker lifecycle", departureDate: nil)
                let createdModel = AppModel(rootURL: library, temporaryRootURL: ownedRoot.appendingPathComponent("exports"), proEntitlement: { true })
                await createdModel.refresh()
                createdModel.beginBatchImport(tripID: createdTrip.id)
                let createdDraft = try XCTUnwrap(createdModel.batchImportDraft)
                let bytes = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 100, height: 100)).pdfData { context in
                    context.beginPage()
                    ("SYNTHETIC" as NSString).draw(at: CGPoint(x: 4, y: 4), withAttributes: nil)
                }
                root = ownedRoot
                model = createdModel
                trip = createdTrip
                draft = createdDraft
                pdf = bytes
            } catch {
                try? FileManager.default.removeItem(at: ownedRoot)
                throw error
            }
        }
        func delivery() throws -> Delivery {
            let session = BatchDocumentPicker.Session(draftID: draft.id)
            XCTAssertTrue(draft.beginPickerRequest(session.id))
            return Delivery(model: model, session: session)
        }
        func copies() throws -> [URL] {
            try ["one.pdf", "two.pdf"].map { name in
                let url = root.appendingPathComponent(name)
                try pdf.write(to: url)
                return url
            }
        }
        func cleanup() {
            if let current = model.batchImportDraft { model.cancelBatchImport(draftID: current.id) }
            try? FileManager.default.removeItem(at: root)
        }
    }
}
