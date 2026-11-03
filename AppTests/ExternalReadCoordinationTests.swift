import Foundation
import XCTest
@testable import Tripfolio

/// Uses Foundation's real coordinator/presenter protocol and synthetic files.
/// No production coordinator injection, simulator mutation or external provider.
@MainActor
final class ExternalReadCoordinationTests: XCTestCase {
    func testWaitsForPresenterAndReadsCompleteAtomicReplacement() async throws {
        executionTimeAllowance = 30
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let original = Data("old".utf8)
        let replacement = Data(repeating: 0x6B, count: 1_048_576 + 37)
        try original.write(to: fixture.file)
        let presenter = SavingPresenter(url: fixture.file)
        NSFileCoordinator.addFilePresenter(presenter)
        defer { presenter.release(); NSFileCoordinator.removeFilePresenter(presenter) }

        let read = startRead(fixture.file, maximum: replacement.count)
        await fulfillment(of: [presenter.saveRequested], timeout: 5)
        XCTAssertNil(read.outcome.value, "The read must wait for the presenter's pending write")
        // Saving pending presenter changes is itself part of coordinated access.
        // Atomic replacement changes the inode at the same logical URL.
        presenter.release(replacement: replacement)
        await fulfillment(of: [read.finished], timeout: 5)
        await read.task.value
        XCTAssertEqual(try XCTUnwrap(read.outcome.value).get(), replacement)
        XCTAssertEqual(try Data(contentsOf: fixture.file), replacement)
    }

    func testCancellationReleasesPendingPresenterWaitBeforeWriterCompletes() async throws {
        executionTimeAllowance = 30
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let original = Data("unchanged".utf8)
        try original.write(to: fixture.file)
        let presenter = SavingPresenter(url: fixture.file)
        NSFileCoordinator.addFilePresenter(presenter)
        defer { presenter.release(); NSFileCoordinator.removeFilePresenter(presenter) }

        let read = startRead(fixture.file, maximum: 1024)
        await fulfillment(of: [presenter.saveRequested], timeout: 5)
        XCTAssertNil(read.outcome.value)
        read.task.cancel()
        await fulfillment(of: [read.finished], timeout: 5)
        let finishedBeforeRelease = read.outcome.value
        // Always release the presenter's completion, including on assertion
        // failure, so the fixture cannot leave a coordination request pending.
        presenter.release()
        await read.task.value
        guard case .failure(let error) = finishedBeforeRelease else {
            return XCTFail("Cancellation did not finish while the presenter was held")
        }
        XCTAssertTrue(error is CancellationError)
        XCTAssertEqual(try Data(contentsOf: fixture.file), original)
    }

    func testRealCoordinatorCancelledBeforeCoordinateNeverEntersAccessor() async throws {
        executionTimeAllowance = 30
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try Data("synthetic".utf8).write(to: fixture.file)
        let url = fixture.file
        let result = await Task.detached {
            // This directly checks the real Foundation contract needed by the
            // tiny cancellation race between publication and coordinate().
            let coordinator = NSFileCoordinator(filePresenter: nil)
            coordinator.cancel()
            var error: NSError?
            var entered = false
            coordinator.coordinate(readingItemAt: url, options: [], error: &error) { _ in entered = true }
            return (entered, error?.domain, error?.code)
        }.value
        XCTAssertFalse(result.0)
        XCTAssertEqual(result.1, NSCocoaErrorDomain)
        XCTAssertEqual(result.2, NSUserCancelledError)
    }

    func testReplacementLargerThanLimitIsRejectedAfterCoordination() async throws {
        executionTimeAllowance = 30
        let fixture = try Fixture()
        defer { fixture.dispose() }
        try Data([1]).write(to: fixture.file)
        let replacement = Data(repeating: 0x42, count: 4097)
        let presenter = SavingPresenter(url: fixture.file)
        NSFileCoordinator.addFilePresenter(presenter)
        defer { presenter.release(); NSFileCoordinator.removeFilePresenter(presenter) }

        let read = startRead(fixture.file, maximum: 4096)
        await fulfillment(of: [presenter.saveRequested], timeout: 5)
        presenter.release(replacement: replacement)
        await fulfillment(of: [read.finished], timeout: 5)
        await read.task.value
        guard case .failure(let error) = read.outcome.value else {
            return XCTFail("The size limit must apply to the replacement, not stale pre-coordination metadata")
        }
        XCTAssertFalse(error is CancellationError)
        XCTAssertEqual(try Data(contentsOf: fixture.file), replacement)
    }

    func testExactBoundEmptyAndMissingFilesWithRealCoordinator() async throws {
        executionTimeAllowance = 30
        let fixture = try Fixture()
        defer { fixture.dispose() }
        let data = Data(repeating: 0x3A, count: 1_048_576 + 17)
        try data.write(to: fixture.file)
        let exact = try await AppModel.readExternal(fixture.file, maximum: data.count)
        XCTAssertEqual(exact, data)
        do {
            _ = try await AppModel.readExternal(fixture.file, maximum: data.count - 1)
            XCTFail("A one-byte excess must fail")
        } catch { XCTAssertFalse(error is CancellationError) }
        try Data().write(to: fixture.file)
        do {
            _ = try await AppModel.readExternal(fixture.file, maximum: 1024)
            XCTFail("An empty file must fail")
        } catch { XCTAssertFalse(error is CancellationError) }
        try FileManager.default.removeItem(at: fixture.file)
        do {
            _ = try await AppModel.readExternal(fixture.file, maximum: 1024)
            XCTFail("A missing file must not become an empty success")
        } catch { XCTAssertFalse(error is CancellationError) }
    }

    private func startRead(_ url: URL, maximum: Int) -> Read {
        let outcome = Outcome()
        let finished = expectation(description: "read finished")
        let task = Task.detached {
            do { outcome.set(.success(try await AppModel.readExternal(url, maximum: maximum))) }
            catch { outcome.set(.failure(error)) }
            finished.fulfill()
        }
        return Read(task: task, outcome: outcome, finished: finished)
    }

    private struct Read {
        let task: Task<Void, Never>
        let outcome: Outcome
        let finished: XCTestExpectation
    }

    private final class Outcome: @unchecked Sendable {
        private let lock = NSLock()
        private var result: Result<Data, Error>?
        var value: Result<Data, Error>? {
            lock.lock(); defer { lock.unlock() }
            return result
        }
        func set(_ result: Result<Data, Error>) {
            lock.lock(); defer { lock.unlock() }
            self.result = result
        }
    }

    private final class SavingPresenter: NSObject, NSFilePresenter, @unchecked Sendable {
        let presentedItemURL: URL?
        let presentedItemOperationQueue: OperationQueue = {
            let queue = OperationQueue()
            queue.maxConcurrentOperationCount = 1
            return queue
        }()
        let saveRequested = XCTestExpectation(description: "real presenter asked to save pending changes")
        private let lock = NSLock()
        private var pending: (@Sendable (Error?) -> Void)?
        private var released = false

        init(url: URL) { presentedItemURL = url }

        func savePresentedItemChanges(completionHandler: @escaping @Sendable (Error?) -> Void) {
            lock.lock()
            if released {
                lock.unlock()
                completionHandler(nil)
                return
            }
            let duplicate = pending != nil
            if !duplicate { pending = completionHandler }
            lock.unlock()
            if duplicate { completionHandler(CocoaError(.userCancelled)); return }
            saveRequested.fulfill()
        }

        func release(replacement: Data? = nil) {
            lock.lock()
            released = true
            let completion = pending
            pending = nil
            lock.unlock()
            guard let completion else { return }
            do {
                if let replacement, let url = presentedItemURL { try replacement.write(to: url, options: .atomic) }
                completion(nil)
            } catch { completion(error) }
        }
    }

    private struct Fixture {
        let directory: URL
        var file: URL { directory.appendingPathComponent("synthetic.bin") }
        init() throws {
            directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: false)
        }
        func dispose() { try? FileManager.default.removeItem(at: directory) }
    }
}
