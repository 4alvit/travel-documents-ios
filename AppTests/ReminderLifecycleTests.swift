import Foundation
import TravelCore
import UserNotifications
import XCTest
@testable import Tripfolio

/// Service lifecycle tests with isolated state and a controlled notification
/// client. No StoreKit, system permission UI or delivery timing is exercised.
@MainActor
final class ReminderLifecycleTests: XCTestCase {
    func testDeletedDocumentWhileReadingAuthorizationCannotSchedule() async throws {
        let context = Context(), gate = Gate()
        context.statusGate = gate
        let task = context.schedule()
        try await arrived(gate)
        context.current = nil
        gate.open()
        await expectChanged(task)
        XCTAssertEqual(context.permissionCalls, 0)
        XCTAssertEqual(context.addCalls, 0)
    }

    func testEditedExpiryWhilePermissionIsSuspendedCannotScheduleOldDate() async throws {
        let context = Context(), gate = Gate()
        context.status = .notDetermined
        context.permissionGate = gate
        let task = context.schedule()
        try await arrived(gate)
        context.current?.expiryDate?.addTimeInterval(86_400)
        gate.open()
        await expectChanged(task)
        XCTAssertEqual(context.addCalls, 0)
    }

    func testCallerCancellationDuringPermissionPreventsAdd() async throws {
        let context = Context(), gate = Gate()
        context.status = .notDetermined
        context.permissionGate = gate
        let task = context.schedule()
        try await arrived(gate)
        task.cancel()
        gate.open()
        await expectCancelled(task)
        XCTAssertEqual(context.addCalls, 0)
    }

    func testExplicitCancelInvalidatesUnchangedDocumentDuringPermission() async throws {
        let context = Context(), gate = Gate()
        context.status = .notDetermined
        context.permissionGate = gate
        let task = context.schedule()
        try await arrived(gate)
        await ReminderService.cancel(documentID: context.current!.id,
            notifications: context.client, lifecycle: context.lifecycle).value
        gate.open()
        await expectChanged(task)
        XCTAssertEqual(context.addCalls, 0)
        XCTAssertTrue(context.pending.isEmpty)
    }

    func testRestoreInvalidatesIdenticalDocumentDuringPermission() async throws {
        let context = Context(), gate = Gate()
        context.status = .notDetermined
        context.permissionGate = gate
        let task = context.schedule()
        try await arrived(gate)
        await ReminderService.cancelAll(notifications: context.client, lifecycle: context.lifecycle).value
        gate.open()
        await expectChanged(task)
        XCTAssertEqual(context.addCalls, 0)
    }

    func testNewIntentWaitsForOldAddAndSurvivesItsCleanup() async throws {
        let context = Context(), gate = Gate()
        context.addGates = [0: gate]
        let old = context.schedule()
        try await arrived(gate)
        context.current?.expiryDate?.addTimeInterval(86_400 * 7)
        let newer = context.schedule()
        try await waitUntil { context.statusCalls == 2 }
        XCTAssertEqual(context.addCalls, 1, "The second add must wait for the first lane")
        gate.open()
        await expectChanged(old)
        try await newer.value
        XCTAssertEqual(context.events, ["add:0", "remove", "add:1"])
        try assertCurrentRequest(context)
    }

    func testCancelWhileAddIsSuspendedRemovesLateOriginal() async throws {
        let context = Context(), gate = Gate()
        context.addGates = [0: gate]
        let task = context.schedule()
        try await arrived(gate)
        let cancellation = ReminderService.cancel(documentID: context.current!.id,
            notifications: context.client, lifecycle: context.lifecycle)
        gate.open()
        await expectChanged(task)
        await cancellation.value
        XCTAssertTrue(context.pending.isEmpty)
    }

    func testCallerCancellationWhileAddIsSuspendedRemovesLateOriginal() async throws {
        let context = Context(), gate = Gate()
        context.addGates = [0: gate]
        let task = context.schedule()
        try await arrived(gate)
        task.cancel()
        gate.open()
        await expectCancelled(task)
        XCTAssertTrue(context.pending.isEmpty)
    }

    func testCancelImmediatelyRemovesAcceptedReminderWhileReplacementAddIsSuspended() async throws {
        let context = Context(), gate = Gate()
        try await context.schedule().value
        XCTAssertEqual(context.pending.count, 1)
        context.addGates = [1: gate]
        let replacement = context.schedule()
        try await arrived(gate)
        let cancellation = ReminderService.cancel(documentID: context.current!.id,
            notifications: context.client, lifecycle: context.lifecycle)
        XCTAssertTrue(context.pending.isEmpty, "An accepted reminder must be removed before the held add returns")
        gate.open()
        await expectChanged(replacement)
        await cancellation.value
        XCTAssertTrue(context.pending.isEmpty, "A late replacement add must also be removed")
    }

    func testRestoreImmediatelyRemovesAcceptedReminderWhileReplacementAddIsSuspended() async throws {
        let context = Context(), gate = Gate()
        try await context.schedule().value
        XCTAssertEqual(context.pending.count, 1)
        context.addGates = [1: gate]
        let replacement = context.schedule()
        try await arrived(gate)
        let clearing = ReminderService.cancelAll(notifications: context.client, lifecycle: context.lifecycle)
        XCTAssertTrue(context.pending.isEmpty, "Restore must remove accepted reminders before the held add returns")
        gate.open()
        await expectChanged(replacement)
        await clearing.value
        XCTAssertTrue(context.pending.isEmpty, "Restore must also remove late old-library adds")
    }

    func testCancellationWhileQueuedIsForwardedToQueueTask() async throws {
        let context = Context(), firstGate = Gate()
        context.addGates = [0: firstGate]
        let first = context.schedule()
        try await arrived(firstGate)
        let documentID = try XCTUnwrap(context.current?.id)
        let firstOperation = try XCTUnwrap(context.lifecycle.queuedOperationID(for: documentID))
        let queued = context.schedule()
        try await waitUntil {
            let operation = context.lifecycle.queuedOperationID(for: documentID)
            return operation != nil && operation != firstOperation
        }
        queued.cancel()
        firstGate.open()
        await expectChanged(first)
        await expectCancelled(queued)
        XCTAssertEqual(context.addCalls, 1)
        XCTAssertTrue(context.pending.isEmpty)
    }

    func testRestoreBarrierCannotDeleteNewDocumentReminder() async throws {
        let context = Context(), gate = Gate()
        context.addGates = [0: gate]
        let old = context.schedule()
        try await arrived(gate)
        let clearing = ReminderService.cancelAll(notifications: context.client, lifecycle: context.lifecycle)
        context.current = Context.document()
        let newer = context.schedule()
        try await waitUntil { context.statusCalls == 2 }
        XCTAssertEqual(context.addCalls, 1)
        gate.open()
        await expectChanged(old)
        await clearing.value
        try await newer.value
        XCTAssertEqual(context.events, ["removeAll", "add:0", "remove", "removeAll", "add:1"])
        try assertCurrentRequest(context)
    }

    func testProLossDuringPermissionPreservesPreviouslyAcceptedReminder() async throws {
        let context = Context()
        try await context.schedule().value
        let previous = context.pending
        let gate = Gate()
        context.status = .notDetermined
        context.permissionGate = gate
        let second = context.schedule()
        try await arrived(gate)
        context.isPro = false
        gate.open()
        do {
            try await second.value
            XCTFail("Lost Pro must prevent a new add")
        } catch ReminderService.ReminderError.proRequired {}
        XCTAssertEqual(context.addCalls, 1)
        XCTAssertEqual(context.pending, previous)
        XCTAssertEqual(context.events, ["add:0"])
    }

    func testProLossAloneAfterAcceptedAddDoesNotRemoveReminder() async throws {
        let context = Context(), gate = Gate()
        context.addGates = [0: gate]
        let task = context.schedule()
        try await arrived(gate)
        context.isPro = false
        gate.open()
        try await task.value
        XCTAssertEqual(context.events, ["add:0"])
        try assertCurrentRequest(context)
    }

    func testPartiallyAppliedFailedAddIsCleanedWhenCallerWasCancelled() async throws {
        let context = Context(), gate = Gate()
        context.addGates = [0: gate]
        context.failAfterApplying = [0]
        let task = context.schedule()
        try await arrived(gate)
        task.cancel()
        gate.open()
        do {
            try await task.value
            XCTFail("The injected add must fail")
        } catch Context.Failure.addFailed {}
        XCTAssertEqual(context.events, ["add:0", "remove"])
        XCTAssertTrue(context.pending.isEmpty)
    }

    func testOldPermissionCompletionCannotOverwriteNewIntent() async throws {
        let context = Context(), gate = Gate()
        context.status = .notDetermined
        context.permissionGate = gate
        let old = context.schedule()
        try await arrived(gate)
        context.status = .authorized
        context.permissionGate = nil
        let newer = context.schedule()
        try await newer.value
        gate.open()
        await expectChanged(old)
        XCTAssertEqual(context.addCalls, 1)
        XCTAssertEqual(context.events, ["add:0"])
        try assertCurrentRequest(context)
    }

    private func arrived(_ gate: Gate) async throws {
        try await waitUntil { gate.arrived }
        XCTAssertFalse(gate.timedOut)
    }

    private func waitUntil(_ predicate: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(3))
        while !predicate() {
            guard ContinuousClock.now < deadline else { throw Context.Failure.timeout }
            try await Task.sleep(for: .milliseconds(10))
        }
    }

    private func expectChanged(_ task: Task<Void, Error>) async {
        do {
            try await task.value
            XCTFail("A stale document or superseded intent must not succeed")
        } catch ReminderService.ReminderError.documentChanged {
        } catch { XCTFail("Expected documentChanged, got \(error)") }
    }

    private func expectCancelled(_ task: Task<Void, Error>) async {
        do {
            try await task.value
            XCTFail("Cancelled work must not succeed")
        } catch is CancellationError {
        } catch { XCTFail("Expected cancellation, got \(error)") }
    }

    private func assertCurrentRequest(_ context: Context) throws {
        let document = try XCTUnwrap(context.current)
        XCTAssertEqual(context.pending.count, 1)
        let request = try XCTUnwrap(context.pending.values.first)
        XCTAssertTrue(request.identifier.hasSuffix(document.id.uuidString))
        let trigger = try XCTUnwrap(request.trigger as? UNCalendarNotificationTrigger)
        let expiry = TravelDate.local(from: try XCTUnwrap(document.expiryDate))
        XCTAssertEqual(trigger.nextTriggerDate(), try ReminderService.notificationDate(for: expiry))
    }

    @MainActor private final class Gate {
        private var continuation: CheckedContinuation<Void, Never>?
        private var watchdog: Task<Void, Never>?
        private(set) var arrived = false
        private(set) var timedOut = false

        func wait() async {
            await withCheckedContinuation { continuation in
                self.continuation = continuation
                self.arrived = true
                self.watchdog = Task { @MainActor in
                    do { try await Task.sleep(for: .seconds(5)) } catch { return }
                    self.timedOut = true
                    XCTFail("A controlled notification gate was not released within five seconds")
                    self.open()
                }
            }
        }

        func open() {
            watchdog?.cancel()
            watchdog = nil
            let continuation = continuation
            self.continuation = nil
            continuation?.resume()
        }
    }

    @MainActor private final class Context {
        enum Failure: Error { case addFailed, timeout }
        let lifecycle = ReminderService.Lifecycle()
        var current: TravelDocument? = document()
        var isPro = true
        var status: UNAuthorizationStatus = .authorized
        var statusGate: Gate?
        var permissionGate: Gate?
        var addGates: [Int: Gate] = [:]
        var failAfterApplying: Set<Int> = []
        var statusCalls = 0
        var permissionCalls = 0
        var addCalls = 0
        var pending: [String: UNNotificationRequest] = [:]
        var events: [String] = []

        var client: ReminderService.NotificationClient {
            ReminderService.NotificationClient(
                authorizationStatus: {
                    self.statusCalls += 1
                    await self.statusGate?.wait()
                    return self.status
                },
                requestAuthorization: {
                    self.permissionCalls += 1
                    await self.permissionGate?.wait()
                    return true
                },
                add: { request in
                    let index = self.addCalls
                    self.addCalls += 1
                    await self.addGates[index]?.wait()
                    self.pending[request.identifier] = request
                    self.events.append("add:\(index)")
                    if self.failAfterApplying.contains(index) { throw Failure.addFailed }
                },
                remove: { identifiers in
                    self.events.append("remove")
                    for identifier in identifiers { self.pending[identifier] = nil }
                },
                removeAll: {
                    self.events.append("removeAll")
                    self.pending.removeAll()
                }
            )
        }

        func schedule() -> Task<Void, Error> {
            let snapshot = current!
            return Task { @MainActor in
                try await ReminderService.schedule(document: snapshot, travelerName: nil,
                    canSchedule: { self.isPro }, isCurrentDocument: { self.current == snapshot },
                    notifications: self.client, lifecycle: self.lifecycle)
            }
        }

        static func document() -> TravelDocument {
            let expiry = TravelDate.stored(from: Date().addingTimeInterval(86_400 * 90))
            return TravelDocument(tripID: UUID(), title: "Synthetic reminder fixture", kind: .passport,
                expiryDate: expiry, originalFilename: "synthetic.pdf", storedFilename: UUID().uuidString + ".pdf",
                byteCount: 1, sha256: String(repeating: "0", count: 64))
        }
    }
}
