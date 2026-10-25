import Foundation
import UserNotifications
import XCTest
@testable import Tripfolio

/// Exercises the actual framework callbacks without requesting permission.
/// Records callback completion without changing the runtime's authorization.
@MainActor
final class NotificationSystemTests: XCTestCase {
    func testSystemCallbacksCompleteAndCleanUpTheirOwnRequest() async throws {
        let center = UNUserNotificationCenter.current()
        let client = ReminderService.NotificationClient.system
        let authorization = await client.authorizationStatus()
        let identifier = "tripdocket.callback-test." + UUID().uuidString
        defer { client.remove([identifier]) }

        let content = UNMutableNotificationContent()
        content.title = "Callback integration test"
        let request = UNNotificationRequest(
            identifier: identifier,
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: 86_400, repeats: false)
        )
        let addCompletedWithoutError: Bool
        let outcome: String
        do {
            try await client.add(request)
            addCompletedWithoutError = true
            outcome = "callback completed without error"
        } catch {
            let failure = error as NSError
            // Unauthorized runtimes can return different framework error codes.
            // Any failure with a usable authorization remains unexpected.
            XCTAssertTrue(authorization == .notDetermined || authorization == .denied)
            XCTAssertEqual(failure.domain, UNErrorDomain)
            addCompletedWithoutError = false
            outcome = "error: \(failure.domain)/\(failure.code) — \(failure.localizedDescription)"
        }
        let maySchedule = authorization == .authorized || authorization == .provisional || authorization == .ephemeral
        var pendingAfterAdd = await containsRequest(identifier, center: center)
        if maySchedule {
            XCTAssertTrue(addCompletedWithoutError, "An authorized request must complete without error")
            for _ in 0..<100 where !pendingAfterAdd {
                try await Task.sleep(for: .milliseconds(50))
                pendingAfterAdd = await containsRequest(identifier, center: center)
            }
            XCTAssertTrue(pendingAfterAdd, "An authorized request must become pending")
        }
        // With no authorization, a nil error is only evidence that the callback
        // completed. Record queue visibility without claiming successful scheduling.

        client.remove([identifier])
        var remains = await containsRequest(identifier, center: center)
        for _ in 0..<100 where remains {
            try await Task.sleep(for: .milliseconds(50))
            remains = await containsRequest(identifier, center: center)
        }
        XCTAssertFalse(remains, "The test must clean up its own future request")

        let evidence = XCTAttachment(string: "Request: \(identifier); authorization raw value: \(authorization.rawValue); outcome: \(outcome); pending observed: \(pendingAfterAdd); scheduling validated: \(maySchedule && addCompletedWithoutError && pendingAfterAdd); cleanup complete: \(!remains)")
        evidence.name = "Actual UserNotifications callback outcome"
        evidence.lifetime = .keepAlways
        add(evidence)
    }

    private func containsRequest(_ identifier: String, center: UNUserNotificationCenter) async -> Bool {
        await withCheckedContinuation { continuation in
            center.getPendingNotificationRequests { @Sendable requests in
                continuation.resume(returning: requests.contains { $0.identifier == identifier })
            }
        }
    }
}
