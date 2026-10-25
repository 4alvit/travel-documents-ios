import Foundation
import StoreKit
import StoreKitTest
import XCTest

/// Keep this suite serial with the other StoreKit tests: SKTestSession changes
/// the shared local StoreKit environment, including payment-sheet presentation.
@MainActor
final class PurchaseUITests: XCTestCase {
    private let productID = "com.4alvit.tripfolio.pro"

    func testCancellingSystemPurchaseSheetKeepsFreeAccess() async throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        let session = try await makeLocalStoreSession()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        defer {
            app.terminate()
            session.clearTransactions()
            session.resetToDefaultState()
        }

        app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset", "--demo"]
        app.launch()
        try await require("The synthetic demo trip did not load", app: app, springboard: springboard) {
            app.staticTexts["Coast weekend"].exists
        }
        let settings = app.buttons["Settings"].firstMatch
        try await require("The app did not show Settings", app: app, springboard: springboard) {
            settings.exists && settings.isHittable
        }
        settings.tap()
        let upgrade = app.staticTexts["Make room for every trip"]
        try await require("The fresh local session is not showing the free plan", app: app, springboard: springboard) {
            upgrade.exists && upgrade.isHittable
        }
        upgrade.tap()

        let buy = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Unlock Pro ·")).firstMatch
        try await require("The local StoreKit product did not load", app: app, springboard: springboard) {
            buy.exists && buy.isEnabled && buy.isHittable
        }
        buy.tap()

        // Require positive evidence of Xcode's payment UI. Never interact with
        // an Apple Account login or a Sandbox/production payment sheet.
        try await require("No Xcode payment sheet appeared", app: app, springboard: springboard) {
            self.xcodeMarker(in: app).exists || self.xcodeMarker(in: springboard).exists
        }
        let paymentSurface = xcodeMarker(in: app).exists ? app : springboard
        var cancel: XCUIElement?
        try await require("The Xcode payment sheet has no accessible Cancel or Close button", app: app, springboard: springboard) {
            cancel = paymentSurface.buttons.matching(NSPredicate(
                format: "label ==[c] %@ OR label ==[c] %@", "Cancel", "Close"
            )).allElementsBoundByIndex.first(where: { $0.exists && $0.isHittable })
            return cancel != nil
        }
        try XCTUnwrap(cancel).tap()

        let cancelled = app.staticTexts.matching(NSPredicate(
            format: "label BEGINSWITH %@", "Purchase cancelled"
        )).firstMatch
        try await require("Cancelling the system sheet did not return the app to an idle, free state", app: app, springboard: springboard) {
            cancelled.exists && buy.exists && buy.isEnabled
                && !self.xcodeMarker(in: app).exists && !self.xcodeMarker(in: springboard).exists
        }
        XCTAssertFalse(app.staticTexts["Pro is unlocked"].exists)
        XCTAssertTrue(session.allTransactions().isEmpty, "Cancel must not create a local purchase")
        attachDiagnostics(app: app, springboard: springboard, name: "System purchase cancelled")

        // The synthetic demo already uses the one free trip. A cancelled
        // purchase must leave the real trip-creation quota enforced.
        app.buttons["Done"].tap()
        app.buttons["Trips"].firstMatch.tap()
        let create = app.buttons["Create trip"]
        try await require("The existing demo trip is not available after cancellation", app: app, springboard: springboard) {
            create.exists && create.isHittable
        }
        create.tap()
        try await require("Cancellation unexpectedly removed the free trip limit", app: app, springboard: springboard) {
            app.navigationBars["TripDocket Pro"].exists
        }
        XCTAssertFalse(app.textFields["Trip name"].exists)
    }

    private func makeLocalStoreSession() async throws -> SKTestSession {
        let configuration = try XCTUnwrap(
            Bundle(for: PurchaseUITests.self).url(forResource: "Tripfolio", withExtension: "storekit"),
            "Add App/Tripfolio.storekit to TripfolioUITests Copy Bundle Resources"
        )
        let session = try SKTestSession(contentsOf: configuration)
        session.resetToDefaultState()
        session.clearTransactions()
        session.disableDialogs = true
        do {
            // This is a synthetic server-side purchase, completed and cleared
            // before the app launches or any payment UI is presented.
            let transaction = try await session.buyProduct(identifier: productID, options: [])
            guard transaction.environment == .xcode, transaction.productID == productID else {
                throw PurchaseTestError(message:
                    "Expected local Xcode StoreKit, got \(transaction.environment.rawValue). The app was not launched.")
            }
            // The UI runner is a different bundle from the configured app.
            // Remove this synthetic preflight purchase through SKTestSession;
            // finishing it from the runner can target the runner's own store.
            session.clearTransactions()
            guard try await waitUntil({ session.allTransactions().isEmpty }, timeout: .seconds(5)) else {
                throw PurchaseTestError(message: "The synthetic preflight transaction was not cleared.")
            }
            session.disableDialogs = false
            return session
        } catch {
            session.clearTransactions()
            session.resetToDefaultState()
            throw PurchaseTestError(message: "Local StoreKit UI preflight failed: \(error)")
        }
    }

    private func xcodeMarker(in app: XCUIApplication) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "Xcode")).firstMatch
    }

    private func require(
        _ message: String, app: XCUIApplication, springboard: XCUIApplication,
        condition: @MainActor () -> Bool
    ) async throws {
        guard try await waitUntil(condition, timeout: .seconds(15)) else {
            attachDiagnostics(app: app, springboard: springboard, name: message)
            throw PurchaseTestError(message: message)
        }
    }

    private func waitUntil(_ condition: @MainActor () -> Bool, timeout: Duration) async throws -> Bool {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        repeat {
            if condition() { return true }
            try await Task.sleep(for: .milliseconds(100))
        } while clock.now < deadline
        return condition()
    }

    private func attachDiagnostics(app: XCUIApplication, springboard: XCUIApplication, name: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCTAttachment(string: "APP\n\(app.debugDescription)\nSPRINGBOARD\n\(springboard.debugDescription)")
        hierarchy.name = "\(name) — accessibility"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }

    private struct PurchaseTestError: LocalizedError, CustomStringConvertible {
        let message: String
        var description: String { message }
        var errorDescription: String? { message }
    }
}
