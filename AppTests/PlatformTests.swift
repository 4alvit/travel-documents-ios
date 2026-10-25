import Foundation
import StoreKit
import StoreKitTest
import TravelCore
import UserNotifications
import XCTest
@testable import Tripfolio

/// Run serially: SKTestSession controls the StoreKit environment for this app.
/// The .storekit file is copied into this test bundle's resources. That alone
/// does not prove application API routing. Preflight rejects a missing local
/// entitlement stream; see the cold-runtime limitation in release-evidence.md.
@MainActor
final class PlatformTests: XCTestCase {
    func testReminderUsesThirtyDaysBeforeExpiryAtNine() throws {
        let calendar = losAngelesCalendar
        let actual = try ReminderService.notificationDate(
            for: date(2026, 12, 20), now: date(2026, 10, 20), calendar: calendar
        )
        XCTAssertEqual(actual, date(2026, 11, 20, 9))
    }

    func testReminderWithinThirtyDaysUsesNextNineAM() throws {
        XCTAssertEqual(
            try ReminderService.notificationDate(for: date(2026, 11, 1), now: date(2026, 10, 20, 8), calendar: losAngelesCalendar),
            date(2026, 10, 20, 9)
        )
        XCTAssertEqual(
            try ReminderService.notificationDate(for: date(2026, 11, 1), now: date(2026, 10, 20, 10), calendar: losAngelesCalendar),
            date(2026, 10, 21, 9)
        )
    }

    func testReminderKeepsWallClockTimeAcrossDaylightSavingChanges() throws {
        XCTAssertEqual(
            try ReminderService.notificationDate(for: date(2026, 4, 7), now: date(2026, 3, 1), calendar: losAngelesCalendar),
            date(2026, 3, 8, 9)
        )
        XCTAssertEqual(
            try ReminderService.notificationDate(for: date(2026, 11, 10), now: date(2026, 10, 31, 10), calendar: losAngelesCalendar),
            date(2026, 11, 1, 9)
        )
    }

    func testReminderRejectsExpiredOrTooSoonDates() {
        for (expiry, now) in [
            (date(2026, 10, 20), date(2026, 10, 20, 8)),
            (date(2026, 10, 21), date(2026, 10, 20, 10))
        ] {
            XCTAssertThrowsError(try ReminderService.notificationDate(for: expiry, now: now, calendar: losAngelesCalendar)) { error in
                guard case ReminderService.ReminderError.expired = error else {
                    return XCTFail("Expected the too-soon expiry error, got \(error)")
                }
            }
        }
    }

    func testReminderTriggerKeepsTheBuddhistCalendarAndSchedulingZone() throws {
        let futureYear = losAngelesCalendar.component(.year, from: Date()) + 4
        let intended = date(futureYear, 6, 1, 9)
        var buddhist = Calendar(identifier: .buddhist)
        buddhist.timeZone = losAngelesCalendar.timeZone
        let trigger = ReminderService.notificationTrigger(for: intended, calendar: buddhist)
        XCTAssertEqual(trigger.dateComponents.year, futureYear + 543)
        XCTAssertEqual(trigger.dateComponents.calendar?.identifier, .buddhist)
        XCTAssertEqual(trigger.dateComponents.timeZone, buddhist.timeZone)
        // Inspect the system's actual interpretation, not just our components.
        XCTAssertEqual(try XCTUnwrap(trigger.nextTriggerDate()), intended)
        XCTAssertFalse(trigger.repeats)
    }

    func testReminderTriggerKeepsExplicitZoneAcrossTheDateLine() throws {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Pacific/Kiritimati")!
        let futureYear = calendar.component(.year, from: Date()) + 4
        let intended = try XCTUnwrap(calendar.date(from: DateComponents(year: futureYear, month: 6, day: 1, hour: 9)))
        let trigger = ReminderService.notificationTrigger(for: intended, calendar: calendar)
        XCTAssertEqual(try XCTUnwrap(trigger.nextTriggerDate()), intended)
    }

    func testReminderRejectsFreeUserBeforeReadingPermission() async throws {
        var permissionReads = 0
        var permissionRequests = 0
        var additions = 0
        let notifications = ReminderService.NotificationClient(
            authorizationStatus: { permissionReads += 1; return .notDetermined },
            requestAuthorization: { permissionRequests += 1; return true },
            add: { _ in additions += 1 }
        )
        do {
            try await ReminderService.schedule(document: futureDocument(), travelerName: nil,
                                               canSchedule: { false }, isCurrentDocument: { true }, notifications: notifications)
            XCTFail("A free user cannot schedule a new reminder")
        } catch ReminderService.ReminderError.proRequired {}
        XCTAssertEqual(permissionReads, 0)
        XCTAssertEqual(permissionRequests, 0)
        XCTAssertEqual(additions, 0)
    }

    func testReminderRechecksEntitlementBeforeAskingPermission() async throws {
        var entitled = true
        var permissionRequests = 0
        var additions = 0
        let notifications = ReminderService.NotificationClient(
            authorizationStatus: { entitled = false; return .notDetermined },
            requestAuthorization: { permissionRequests += 1; return true },
            add: { _ in additions += 1 }
        )
        do {
            try await ReminderService.schedule(document: futureDocument(), travelerName: nil,
                                               canSchedule: { entitled }, isCurrentDocument: { true }, notifications: notifications)
            XCTFail("A revoked entitlement cannot ask permission for a new reminder")
        } catch ReminderService.ReminderError.proRequired {}
        XCTAssertEqual(permissionRequests, 0)
        XCTAssertEqual(additions, 0)
    }

    func testReminderRechecksEntitlementAfterPermissionReturns() async throws {
        var entitled = true
        var permissionRequests = 0
        var additions = 0
        let notifications = ReminderService.NotificationClient(
            authorizationStatus: { .notDetermined },
            requestAuthorization: { permissionRequests += 1; entitled = false; return true },
            add: { _ in additions += 1 }
        )
        do {
            try await ReminderService.schedule(document: futureDocument(), travelerName: nil,
                                               canSchedule: { entitled }, isCurrentDocument: { true }, notifications: notifications)
            XCTFail("A revoked entitlement cannot add after an asynchronous permission prompt")
        } catch ReminderService.ReminderError.proRequired {}
        XCTAssertEqual(permissionRequests, 1)
        XCTAssertEqual(additions, 0)
    }

    func testReminderUsesConfirmedCivilDateAndGenericNotificationContent() async throws {
        let document = futureDocument()
        var captured: UNNotificationRequest?
        let notifications = ReminderService.NotificationClient(
            authorizationStatus: { .authorized },
            requestAuthorization: { XCTFail("Already authorized"); return false },
            add: { captured = $0 }
        )
        try await ReminderService.schedule(document: document, travelerName: "Synthetic private traveler",
                                           canSchedule: { true }, isCurrentDocument: { true }, notifications: notifications)
        let request = try XCTUnwrap(captured)
        XCTAssertFalse(request.content.title.contains(document.title))
        XCTAssertFalse(request.content.body.contains(document.title))
        XCTAssertFalse(request.content.body.contains("Synthetic private traveler"))
        XCTAssertTrue(request.content.userInfo.isEmpty)
        let localExpiry = TravelDate.local(from: try XCTUnwrap(document.expiryDate))
        let expected = try ReminderService.notificationDate(for: localExpiry)
        let trigger = try XCTUnwrap(request.trigger as? UNCalendarNotificationTrigger)
        XCTAssertEqual(try XCTUnwrap(trigger.nextTriggerDate()), expected)
    }

    func testVerifiedPurchaseAndRestoreFromLocalHistory() async throws {
        try await withStoreSession { session in
            let manager = PurchaseManager()
            await manager.load()
            XCTAssertFalse(manager.isPro)
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            await manager.purchase()
            let purchased = try await eventually { manager.isPro }
            XCTAssertTrue(purchased, diagnostics(manager))
            XCTAssertFalse(manager.isBusy)

            // A new manager has no app-owned boolean cache to rely on.
            let restored = PurchaseManager()
            await restored.load()
            XCTAssertTrue(restored.isPro, "Verified local StoreKit history must restore access on launch. \(diagnostics(restored))")
            try await waitForLocalEntitlement(present: true)
            await restored.restore()
            XCTAssertTrue(restored.isPro, diagnostics(restored))
            XCTAssertFalse(restored.isBusy)
        }
    }

    func testRefundRevokesProThroughTransactionUpdates() async throws {
        try await withStoreSession { session in
            let manager = PurchaseManager()
            await manager.load()
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            await manager.purchase()
            let purchased = try await eventually { manager.isPro }
            XCTAssertTrue(purchased, diagnostics(manager))
            let transaction = try XCTUnwrap(session.allTransactions().first(where: {
                $0.productIdentifier == PurchaseManager.productID
            }), diagnostics(manager))
            try session.refundTransaction(identifier: transaction.identifier)
            // Do not call load(): this must be delivered by the live listener.
            let revoked = try await eventually { !manager.isPro }
            XCTAssertTrue(revoked, "A refund must revoke access without relaunching. \(diagnostics(manager))")
            let relaunched = PurchaseManager()
            await relaunched.load()
            XCTAssertFalse(relaunched.isPro)
        }
    }

    func testAskToBuyStaysFreeUntilApproved() async throws {
        try await withStoreSession { session in
            session.askToBuyEnabled = true
            let manager = PurchaseManager()
            await manager.load()
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            await manager.purchase()
            XCTAssertFalse(manager.isPro)
            XCTAssertFalse(manager.isBusy)
            XCTAssertTrue(manager.statusMessage?.contains("awaiting approval") == true, diagnostics(manager))
            let pending = try XCTUnwrap(session.allTransactions().first(where: \.pendingAskToBuyConfirmation), diagnostics(manager))
            let approvalStarted = Date()
            try session.approveAskToBuyTransaction(identifier: pending.identifier)
            let approvalReturned = Date()
            let approved = try await eventually { manager.isPro }
            XCTAssertTrue(approved, "Approval must unlock through transaction updates. \(diagnostics(manager))")
            await attachStoreSnapshot(session, manager: manager, phase:
                "Ask to Buy: pendingID=\(pending.identifier), approvalStarted=\(approvalStarted.timeIntervalSince1970), approvalReturned=\(approvalReturned.timeIntervalSince1970), checkpoint=\(Date().timeIntervalSince1970), observedApproved=\(approved)")
        }
    }

    func testDeclinedAskToBuyDoesNotGrantAccess() async throws {
        try await withStoreSession { session in
            session.askToBuyEnabled = true
            let manager = PurchaseManager()
            await manager.load()
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            await manager.purchase()
            let pending = try XCTUnwrap(session.allTransactions().first(where: \.pendingAskToBuyConfirmation), diagnostics(manager))
            try session.declineAskToBuyTransaction(identifier: pending.identifier)
            await manager.load()
            XCTAssertFalse(manager.isPro)
        }
    }

    func testPurchaseNetworkFailureReturnsToIdleWithoutGrantingPro() async throws {
        try await withStoreSession { session in
            let manager = PurchaseManager()
            await manager.load()
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            // Exercise an API failure here. Actual user cancellation is covered by
            // PurchaseUITests through the system payment sheet.
            try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .purchase)
            await manager.purchase()
            XCTAssertFalse(manager.isPro)
            XCTAssertFalse(manager.isBusy)
            XCTAssertTrue(manager.statusMessage?.contains("purchase could not be completed") == true, diagnostics(manager))
        }
    }

    func testUnverifiedPurchaseDoesNotGrantPro() async throws {
        try await withStoreSession { session in
            let manager = PurchaseManager()
            await manager.load()
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            try await session.setSimulatedError(.verification(.invalidSignature), forAPI: .verification)
            await manager.purchase()
            XCTAssertFalse(manager.isPro)
            XCTAssertFalse(manager.isBusy)
            XCTAssertTrue(manager.statusMessage?.localizedCaseInsensitiveContains("verif") == true, diagnostics(manager))
        }
    }

    func testPriceAndSyncNetworkErrorsDoNotEraseVerifiedEntitlement() async throws {
        try await withStoreSession { session in
            let manager = PurchaseManager()
            await manager.load()
            _ = try XCTUnwrap(manager.displayPrice, diagnostics(manager))
            await manager.purchase()
            let purchased = try await eventually { manager.isPro }
            XCTAssertTrue(purchased, diagnostics(manager))

            // This simulates the API failures, not physical airplane mode.
            try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .loadProducts)
            let relaunched = PurchaseManager()
            await relaunched.load()
            XCTAssertTrue(relaunched.isPro, "Price fetch failure cannot revoke a verified cached transaction. \(diagnostics(relaunched))")
            XCTAssertNil(relaunched.displayPrice, "Never invent a fallback price")
            try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .appStoreSync)
            try await waitForLocalEntitlement(present: true)
            await relaunched.restore()
            XCTAssertTrue(relaunched.isPro, diagnostics(relaunched))
            XCTAssertFalse(relaunched.isBusy)
        }
    }

    private func makeStoreSession() async throws -> SKTestSession {
        let configuration = try XCTUnwrap(
            Bundle(for: PlatformTests.self).url(forResource: "Tripfolio", withExtension: "storekit"),
            "Add App/Tripfolio.storekit to TripfolioTests Copy Bundle Resources"
        )
        let session = try SKTestSession(contentsOf: configuration)
        do {
            try await reset(session)
            session.disableDialogs = true
            // Exercise the real local StoreKit server before the app under test.
            // SKTestSession construction alone does not prove that the host's
            // StoreKit APIs are connected to that same environment.
            let transaction = try await session.buyProduct(identifier: PurchaseManager.productID, options: [])
            guard transaction.productID == PurchaseManager.productID,
                  transaction.productType == .nonConsumable,
                  transaction.environment == .xcode else {
                throw LocalStoreKitEnvironmentError(detail:
                    "Synthetic purchase returned product \(transaction.productID) in \(transaction.environment.rawValue), expected the configured non-consumable in Xcode.")
            }
            try await waitForLocalEntitlement(present: true, transactionID: transaction.id)
            await transaction.finish()
            session.clearTransactions()
            try await waitForLocalEntitlement(present: false)
            return session
        } catch {
            do { try await reset(session) }
            catch { XCTFail("StoreKit preflight cleanup failed: \(error)") }
            if let environmentError = error as? LocalStoreKitEnvironmentError { throw environmentError }
            throw LocalStoreKitEnvironmentError(detail: "Synthetic StoreKit purchase failed: \(error)")
        }
    }

    /// Also called immediately before restore: never invoke AppStore.sync from
    /// these automated tests without current, verified evidence of local StoreKit.
    private func waitForLocalEntitlement(present: Bool, transactionID: UInt64? = nil) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(5))
        repeat {
            var found = false
            for await result in StoreKit.Transaction.currentEntitlements {
                let transaction: StoreKit.Transaction
                switch result {
                case .verified(let verified):
                    transaction = verified
                case .unverified(let unverified, let error):
                    guard unverified.productID == PurchaseManager.productID else { continue }
                    throw LocalStoreKitEnvironmentError(detail:
                        "The entitlement stream returned unverified transaction \(unverified.id), expected \(transactionID.map(String.init) ?? "any"), in \(unverified.environment.rawValue): \(error)")
                }
                guard transaction.productID == PurchaseManager.productID else { continue }
                guard transaction.environment == .xcode else {
                    throw LocalStoreKitEnvironmentError(detail:
                        "The entitlement stream is using \(transaction.environment.rawValue), expected Xcode. AppStore.sync was not called.")
                }
                if transaction.productType == .nonConsumable,
                   transaction.revocationDate == nil,
                   !transaction.isUpgraded,
                   transactionID == nil || transaction.id == transactionID {
                    found = true
                }
            }
            if found == present { return }
            if clock.now >= deadline { break }
            try await Task.sleep(for: .milliseconds(50))
        } while clock.now < deadline
        throw LocalStoreKitEnvironmentError(detail: present
            ? "No verified Xcode entitlement appeared within five seconds. AppStore.sync was not called."
            : "The synthetic Xcode entitlement remained after clearTransactions for five seconds.")
    }

    private struct LocalStoreKitEnvironmentError: LocalizedError, CustomStringConvertible {
        let detail: String
        var description: String {
            "Local StoreKit routing is not ready: \(detail) See docs/release-evidence.md for the cold-runtime limitation. Configuration-file presence does not prove application API routing."
        }
        var errorDescription: String? { description }
    }

    private func diagnostics(_ manager: PurchaseManager) -> String {
        "isPro=\(manager.isPro), isBusy=\(manager.isBusy), displayPrice=\(manager.displayPrice ?? "nil"), statusMessage=\(manager.statusMessage ?? "nil")"
    }

    /// Observe synthetic test state after the acceptance checkpoint; never refresh
    /// the manager or grant access to make a failed live-update assertion pass.
    private func attachStoreSnapshot(_ session: SKTestSession, manager: PurchaseManager, phase: String) async {
        var lines = [phase, "manager at checkpoint: \(diagnostics(manager))"]
        for transaction in session.allTransactions() where transaction.productIdentifier == PurchaseManager.productID {
            lines.append("session: id=\(transaction.identifier), pending=\(transaction.pendingAskToBuyConfirmation)")
        }
        var count = 0
        for await result in StoreKit.Transaction.currentEntitlements {
            let transaction: StoreKit.Transaction
            let verification: String
            switch result {
            case .verified(let value):
                transaction = value
                verification = "verified"
            case .unverified(let value, let error):
                transaction = value
                verification = "unverified: \(error)"
            }
            guard transaction.productID == PurchaseManager.productID else { continue }
            count += 1
            lines.append("entitlement: id=\(transaction.id), environment=\(transaction.environment.rawValue), verification=\(verification), revoked=\(transaction.revocationDate != nil)")
        }
        lines.append("matching entitlement count: \(count)")
        lines.append("injected verification: \(String(describing: await session.simulatedError(forAPI: .verification)))")
        lines.append("injected purchase: \(String(describing: await session.simulatedError(forAPI: .purchase)))")
        lines.append("injected loadProducts: \(String(describing: await session.simulatedError(forAPI: .loadProducts)))")
        lines.append("injected appStoreSync: \(String(describing: await session.simulatedError(forAPI: .appStoreSync)))")
        lines.append("snapshot finished: \(Date().timeIntervalSince1970); manager: \(diagnostics(manager))")
        let attachment = XCTAttachment(string: lines.joined(separator: "\n"))
        attachment.name = "Synthetic StoreKit state after acceptance checkpoint"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func withStoreSession(_ body: @MainActor (SKTestSession) async throws -> Void) async throws {
        let session = try await makeStoreSession()
        do {
            try await body(session)
        } catch {
            do { try await reset(session) }
            catch { XCTFail("StoreKit scenario cleanup failed: \(error)") }
            throw error
        }
        try await reset(session)
    }

    private func reset(_ session: SKTestSession) async throws {
        session.resetToDefaultState()
        // Error injection is asynchronous and must not leak into the next case.
        try await session.setSimulatedError(nil, forAPI: .verification)
        try await session.setSimulatedError(nil, forAPI: .purchase)
        try await session.setSimulatedError(nil, forAPI: .loadProducts)
        try await session.setSimulatedError(nil, forAPI: .appStoreSync)
        let flagsBeforeFinalReset = storeSessionFlags(session)
        // Make the checked-in configuration the final setup mutation, after
        // the asynchronous fault cleanup. Nil readback alone did not prevent
        // ordinary purchases being cancelled by the hosted Xcode test server.
        session.resetToDefaultState()
        let verificationError = await session.simulatedError(forAPI: .verification)
        let purchaseError = await session.simulatedError(forAPI: .purchase)
        let productError = await session.simulatedError(forAPI: .loadProducts)
        let syncError = await session.simulatedError(forAPI: .appStoreSync)
        let attachment = XCTAttachment(string: [
            "Before final configuration reset: \(flagsBeforeFinalReset)",
            "After final configuration reset: \(storeSessionFlags(session))",
            "verification: \(String(describing: verificationError))",
            "purchase: \(String(describing: purchaseError))",
            "loadProducts: \(String(describing: productError))",
            "appStoreSync: \(String(describing: syncError))",
            "Legacy failTransactionsEnabled is deprecated and is not authoritative for modern API fault state."
        ].joined(separator: "\n"))
        attachment.name = "Synthetic StoreKit configuration reset"
        attachment.lifetime = .keepAlways
        add(attachment)
        guard verificationError == nil, purchaseError == nil, productError == nil, syncError == nil else {
            throw LocalStoreKitEnvironmentError(detail: "Simulated API errors remained after explicit reset.")
        }
        session.clearTransactions()
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(5))
        repeat {
            var hasEntitlementRecord = false
            for await result in StoreKit.Transaction.currentEntitlements {
                // An unverified record is still stale state to remove, never a grant.
                switch result {
                case .verified(let transaction), .unverified(let transaction, _):
                    if transaction.productID == PurchaseManager.productID { hasEntitlementRecord = true }
                }
            }
            if session.allTransactions().isEmpty && !hasEntitlementRecord { return }
            if clock.now >= deadline { break }
            try await Task.sleep(for: .milliseconds(50))
        } while clock.now < deadline
        throw LocalStoreKitEnvironmentError(detail: "StoreKit history or entitlement records remained after explicit cleanup.")
    }

    private func storeSessionFlags(_ session: SKTestSession) -> String {
        "askToBuy=\(session.askToBuyEnabled), interruptedPurchases=\(session.interruptedPurchasesEnabled), legacyFailTransactions=\(session.failTransactionsEnabled)"
    }

    private func eventually(_ condition: @MainActor () -> Bool) async throws -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(5))
        while clock.now < deadline {
            if condition() { return true }
            try await Task.sleep(for: .milliseconds(50))
        }
        return condition()
    }

    private var losAngelesCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "America/Los_Angeles")!
        return calendar
    }

    private func date(_ year: Int, _ month: Int, _ day: Int, _ hour: Int = 0) -> Date {
        losAngelesCalendar.date(from: DateComponents(year: year, month: month, day: day, hour: hour))!
    }

    private func futureDocument() -> TravelDocument {
        let localExpiry = Calendar.current.date(byAdding: .day, value: 120, to: Date())!
        return TravelDocument(
            tripID: UUID(), title: "Synthetic private document", kind: .passport,
            expiryDate: TravelDate.stored(from: localExpiry), originalFilename: "synthetic.pdf",
            storedFilename: "synthetic.pdf", byteCount: 1, sha256: String(repeating: "0", count: 64)
        )
    }
}
