import Foundation
import UIKit
import UniformTypeIdentifiers
import XCTest
@testable import Tripfolio

@MainActor
final class BatchDocumentPickerTests: XCTestCase {
    func testOwnedCopyCleanupIsExactAndIdempotent() throws {
        try fixture { root in
            let copy = try file("copy.pdf", root: root)
            let other = try file("other.pdf", root: root)
            let selection = try BatchDocumentSelection.capture([copy], temporaryDirectory: root)
            XCTAssertEqual(selection.urls.map(\.lastPathComponent), ["copy.pdf"])
            selection.dispose()
            selection.dispose()
            XCTAssertFalse(exists(copy))
            XCTAssertTrue(exists(other))
            XCTAssertTrue(exists(root))
        }
    }

    func testPartialRejectionDisposesKnownCopyAndLeavesUnknownPath() throws {
        try fixture { root in
            let allowed = root.appendingPathComponent("allowed", isDirectory: true)
            try FileManager.default.createDirectory(at: allowed, withIntermediateDirectories: true)
            let copy = try file("copy.pdf", root: allowed)
            let external = try file("original.pdf", root: root)
            XCTAssertThrowsError(try BatchDocumentSelection.capture([copy, external], temporaryDirectory: allowed))
            XCTAssertFalse(exists(copy))
            XCTAssertTrue(exists(external))
        }
    }

    func testRejectsFileAndParentSymlinksWithoutDeletingTheirTargets() throws {
        try fixture { root in
            let original = try file("original.pdf", root: root)
            let link = root.appendingPathComponent("link.pdf")
            try FileManager.default.createSymbolicLink(at: link, withDestinationURL: original)
            XCTAssertThrowsError(try BatchDocumentSelection.capture([link], temporaryDirectory: root))
            XCTAssertTrue(exists(original))
            XCTAssertTrue(exists(link))
            let nested = root.appendingPathComponent("nested", isDirectory: true)
            try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
            let nestedCopy = try file("copy.pdf", root: nested)
            let directoryLink = root.appendingPathComponent("alias", isDirectory: true)
            try FileManager.default.createSymbolicLink(at: directoryLink, withDestinationURL: nested)
            XCTAssertThrowsError(try BatchDocumentSelection.capture([directoryLink.appendingPathComponent("copy.pdf")], temporaryDirectory: root))
            XCTAssertTrue(exists(nestedCopy))
        }
    }

    func testRejectsHardlinksAndDirectories() throws {
        try fixture { root in
            let original = try file("original.pdf", root: root)
            let link = root.appendingPathComponent("hardlink.pdf")
            try FileManager.default.linkItem(at: original, to: link)
            XCTAssertThrowsError(try BatchDocumentSelection.capture([link], temporaryDirectory: root))
            XCTAssertThrowsError(try BatchDocumentSelection.capture([root], temporaryDirectory: root))
            XCTAssertTrue(exists(original))
            XCTAssertTrue(exists(link))
        }
    }

    func testReplacementFileIsNotDeleted() throws {
        try fixture { root in
            let copy = try file("copy.pdf", root: root)
            let selection = try BatchDocumentSelection.capture([copy], temporaryDirectory: root)
            let moved = root.appendingPathComponent("moved.pdf")
            try FileManager.default.moveItem(at: copy, to: moved)
            _ = try file("copy.pdf", root: root)
            selection.dispose()
            XCTAssertTrue(exists(copy))
            XCTAssertTrue(exists(moved))
        }
    }

    func testReplacementDirectoryIsNotTraversed() throws {
        try fixture { root in
            let nested = root.appendingPathComponent("nested", isDirectory: true)
            try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
            let copy = try file("copy.pdf", root: nested)
            let selection = try BatchDocumentSelection.capture([copy], temporaryDirectory: root)
            let moved = root.appendingPathComponent("moved", isDirectory: true)
            try FileManager.default.moveItem(at: nested, to: moved)
            try FileManager.default.createDirectory(at: nested, withIntermediateDirectories: true)
            _ = try file("copy.pdf", root: nested)
            selection.dispose()
            XCTAssertTrue(exists(copy))
            XCTAssertTrue(exists(moved.appendingPathComponent("copy.pdf")))
        }
    }

    func testOversizedSelectionDisposesEveryValidatedCopy() throws {
        try fixture { root in
            let copies = try (0..<11).map { try file("copy-\($0).pdf", root: root) }
            XCTAssertThrowsError(try BatchDocumentSelection.capture(copies, temporaryDirectory: root))
            XCTAssertTrue(copies.allSatisfy { !exists($0) })
        }
    }

    func testUnconsumedLeaseDisposesAtEndOfLifetime() throws {
        try fixture { root in
            let copy = try file("copy.pdf", root: root)
            do {
                let selection = try BatchDocumentSelection.capture([copy], temporaryDirectory: root)
                XCTAssertEqual(selection.urls.count, 1)
                withExtendedLifetime(selection) { XCTAssertTrue(exists(copy)) }
            }
            XCTAssertFalse(exists(copy))
        }
    }

    func testDuplicateCallbackCannotDeleteInUseCopiesOrCompleteTwice() throws {
        try fixture { root in
            let copy = try file("copy.pdf", root: root)
            let session = BatchDocumentPicker.Session(draftID: UUID())
            var delivered: BatchDocumentSelection?
            var completions = 0
            let coordinator = BatchDocumentPicker.Coordinator(session: session, capture: {
                try BatchDocumentSelection.capture($0, temporaryDirectory: root)
            }) { result in
                completions += 1
                XCTAssertFalse(session.active)
                if case .success(let selection) = result { delivered = selection }
            }
            let picker = controller()
            coordinator.documentPicker(picker, didPickDocumentsAt: [copy])
            coordinator.documentPicker(picker, didPickDocumentsAt: [copy])
            coordinator.documentPickerWasCancelled(picker)
            XCTAssertEqual(completions, 1)
            XCTAssertTrue(exists(copy))
            delivered?.dispose()
            XCTAssertFalse(exists(copy))
        }
    }

    func testCancelThenLateSelectionDisposesWithoutAnotherCompletion() throws {
        try fixture { root in
            let copy = try file("copy.pdf", root: root)
            let session = BatchDocumentPicker.Session(draftID: UUID())
            var completions = 0
            let coordinator = BatchDocumentPicker.Coordinator(session: session, capture: {
                try BatchDocumentSelection.capture($0, temporaryDirectory: root)
            }) { result in
                completions += 1
                XCTAssertNil(result)
            }
            let picker = controller()
            coordinator.documentPickerWasCancelled(picker)
            coordinator.documentPicker(picker, didPickDocumentsAt: [copy])
            XCTAssertEqual(completions, 1)
            XCTAssertFalse(exists(copy))
        }
    }

    func testExplicitInvalidationThenLateSelectionDisposesWithoutPublishing() throws {
        try fixture { root in
            let copy = try file("copy.pdf", root: root)
            let session = BatchDocumentPicker.Session(draftID: UUID())
            let coordinator = BatchDocumentPicker.Coordinator(session: session, capture: {
                try BatchDocumentSelection.capture($0, temporaryDirectory: root)
            }) { _ in XCTFail("An explicitly invalidated picker must not publish") }
            let picker = controller()
            session.invalidate()
            coordinator.documentPicker(picker, didPickDocumentsAt: [copy])
            coordinator.documentPickerWasCancelled(picker)
            XCTAssertFalse(exists(copy))
        }
    }

    func testValidationFailureIsOneTerminalResult() throws {
        let session = BatchDocumentPicker.Session(draftID: UUID())
        var completions = 0
        let coordinator = BatchDocumentPicker.Coordinator(session: session, capture: { _ in
            throw CocoaError(.fileReadNoPermission)
        }) { result in
            completions += 1
            guard case .failure = result else { return XCTFail("Expected validation failure") }
        }
        let picker = controller()
        coordinator.documentPicker(picker, didPickDocumentsAt: [])
        coordinator.documentPicker(picker, didPickDocumentsAt: [])
        coordinator.documentPickerWasCancelled(picker)
        XCTAssertEqual(completions, 1)
    }

    private func controller() -> UIDocumentPickerViewController {
        UIDocumentPickerViewController(forOpeningContentTypes: [.pdf], asCopy: true)
    }

    private func fixture(_ body: (URL) throws -> Void) throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        try body(root)
    }

    private func file(_ name: String, root: URL) throws -> URL {
        let url = root.appendingPathComponent(name)
        try Data("synthetic-copy".utf8).write(to: url)
        return url
    }

    private func exists(_ url: URL) -> Bool { FileManager.default.fileExists(atPath: url.path) }
}
