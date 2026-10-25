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

        app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset", "--demo", "--ui-testing-purchase-diagnostics"]
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

    func testPurchaseFailureAlertInEnglishWithDiagnostics() async throws {
        try await verifyPurchaseFailureAlert(russian: false, diagnostics: true)
    }

    func testPurchaseFailureAlertInRussianWithDiagnostics() async throws {
        try await verifyPurchaseFailureAlert(russian: true, diagnostics: true)
    }

    func testPurchaseFailureAlertWithoutDiagnosticFlag() async throws {
        try await verifyPurchaseFailureAlert(russian: false, diagnostics: false)
    }

    private func verifyPurchaseFailureAlert(russian: Bool, diagnostics: Bool) async throws {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        let session = try await makeLocalStoreSession()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        addTeardownBlock { @MainActor in
            app.terminate()
            try await self.clearPurchaseFailure(session)
        }
        // The existing local preflight must pass before any simulated API error.
        session.disableDialogs = true
        do {
            app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset", "--demo",
                                   "-AppleLanguages", russian ? "(ru-RU,en-US)" : "(en-US)",
                                   "-AppleLocale", "en_US"]
            if diagnostics { app.launchArguments.append("--ui-testing-purchase-diagnostics") }
            app.launch()
            let settings = app.buttons[russian ? "Настройки" : "Settings"].firstMatch
            try await require("Localized Settings did not load", app: app, springboard: springboard) {
                settings.exists && settings.isHittable
            }
            settings.tap()
            let upgrade = app.staticTexts[russian ? "Место для каждой поездки" : "Make room for every trip"]
            try await require("The free plan is not available", app: app, springboard: springboard) {
                upgrade.exists && upgrade.isHittable
            }
            upgrade.tap()
            let buy = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@",
                russian ? "Открыть Pro ·" : "Unlock Pro ·")).firstMatch
            let title = russian ? "Не удалось завершить покупку" : "Purchase not completed"
            let message = russian
                ? "Не удалось завершить покупку. Проверьте подключение к интернету и учётную запись App Store, затем повторите попытку."
                : "The purchase could not be completed. Check your connection and App Store account, then try again."
            let alert = app.alerts[title]
            let ok = alert.buttons[russian ? "ОК" : "OK"]
            var completedAttempts = 0
            for attempt in 1...ExpectedFailureHistory.requiredAttempts {
                try await require("Purchase is not ready for failure attempt \(attempt)", app: app, springboard: springboard) {
                    buy.exists && buy.isEnabled && buy.isHittable && app.alerts.count == 0
                }
                try await session.setSimulatedError(.generic(.networkError(URLError(.notConnectedToInternet))), forAPI: .purchase)
                guard await session.simulatedError(forAPI: .purchase) != nil else {
                    throw PurchaseTestError(message: "The purchase failure was not installed")
                }
                buy.tap()
                // No scrolling: a matching status below the paywall or in the
                // underlying Settings must not satisfy this alert assertion.
                let body = alert.staticTexts.matching(NSPredicate(format: "label BEGINSWITH %@", message)).firstMatch
                try await require("Purchase failure is not immediately accessible on the paywall", app: app, springboard: springboard) {
                    app.alerts.count == 1 && alert.exists && body.exists && body.isHittable
                        && ok.exists && ok.isEnabled && ok.isHittable
                }
                try await require("Unexpected purchase diagnostic visibility", app: app, springboard: springboard) {
                    diagnostics
                        ? body.label == message + "\n\npurchase-diagnostic phase=purchase category=network domain=NSURLErrorDomain code=-1009"
                        : body.label == message && !app.debugDescription.contains("purchase-diagnostic")
                }
                try await require("An app error must not imitate the system payment sheet", app: app, springboard: springboard) {
                    !self.xcodeMarker(in: app).exists && !self.xcodeMarker(in: springboard).exists
                }
                attachDiagnostics(app: app, springboard: springboard,
                                  name: "Purchase failure \(russian ? "ru" : "en") diagnostics=\(diagnostics) attempt=\(attempt)")
                ok.tap()
                try await require("Acknowledging the failure did not restore an idle paywall", app: app, springboard: springboard) {
                    app.alerts.count == 0 && buy.exists && buy.isEnabled && buy.isHittable
                }
                try await session.setSimulatedError(nil, forAPI: .purchase)
                guard await session.simulatedError(forAPI: .purchase) == nil else {
                    throw PurchaseTestError(message: "The previous purchase failure was not cleared")
                }
                // Count only a fully checked alert/idle cycle and verified fault removal.
                completedAttempts += 1
            }
            app.buttons[russian ? "Готово" : "Done"].tap()
            try await require("Paywall did not dismiss", app: app, springboard: springboard) {
                upgrade.exists && upgrade.isHittable
            }
            upgrade.tap()
            try await require("Reopening the paywall replayed an old failure", app: app, springboard: springboard) {
                buy.exists && buy.isEnabled && buy.isHittable && app.alerts.count == 0
            }
            try await requirePurchasePostcondition(app: app, springboard: springboard, session: session,
                                                   buy: buy, russian: russian, diagnostics: diagnostics,
                                                   completedAttempts: completedAttempts)
            // Keep postcondition failures immediate. Navigation can trigger the
            // existing ProView load(), so quota is a later, success-only check.
            try await verifyFailedPurchaseFreeQuota(app: app, springboard: springboard, russian: russian)
        } catch {
            attachDiagnostics(app: app, springboard: springboard, name: "Purchase failure regression cleanup")
            throw error
        }
    }

    private func requirePurchasePostcondition(
        app: XCUIApplication, springboard: XCUIApplication, session: SKTestSession,
        buy: XCUIElement, russian: Bool, diagnostics: Bool, completedAttempts: Int
    ) async throws {
        var lastObservation = "observation=unavailable"
        var completion = "interrupted"
        var knownProObserved = false
        defer {
            recordPurchaseObservation("purchase-postcondition completion=\(completion)\n\(lastObservation)\nquota=notAttemptedBeforeExpectedFailurePostconditionCompletion",
                                      name: "Purchase postcondition before cleanup")
        }
        do {
            // Retain the 15-second wait and raw empty-history observation.
            // Acceptance classifies the full array, never the diagnostic prefix.
            try await require("Failed purchases did not preserve Free access or expected failure history", app: app, springboard: springboard) {
                let proLabel = russian ? "Pro доступен" : "Pro is unlocked"
                let proSelector = app.staticTexts[proLabel]
                let proExists = proSelector.exists
                let transactions = session.allTransactions()
                let historyEmpty = transactions.isEmpty
                let decision = ExpectedFailureHistory.evaluate(transactions.map {
                    ExpectedFailureHistory.Record(stateRawValue: $0.state.rawValue,
                        productIdentifier: $0.productIdentifier,
                        pendingAskToBuyConfirmation: $0.pendingAskToBuyConfirmation)
                }, completedAttempts: completedAttempts, productID: self.productID)
                let history = self.purchaseHistoryObservation(transactions)
                let buyExists = buy.exists
                let buyEnabled = buyExists ? String(buy.isEnabled) : "unknown"
                let buyHittable = buyExists ? String(buy.isHittable) : "unknown"
                let appState = self.purchaseAppState(app, diagnostics: diagnostics)
                // A later poll or navigation must not conceal a known Pro observation.
                knownProObserved = knownProObserved || appState.knownIsPro == true
                // AX queries are sequential, not an atomic entitlement snapshot.
                lastObservation = "noPro=\(!proExists) historyEmpty=\(historyEmpty) proMatches=\(app.staticTexts.matching(identifier: proLabel).count)\n"
                    + "buyExists=\(buyExists) buyEnabled=\(buyEnabled) buyHittable=\(buyHittable)\n"
                    + "appState=\(appState.diagnostic)\n"
                    + "expectedFailureHistory accepted=\(decision.accepted) completedAttempts=\(completedAttempts) requiredAttempts=\(ExpectedFailureHistory.requiredAttempts) attemptsComplete=\(decision.attemptsComplete) withinAttemptBound=\(decision.withinAttemptBound) allRecordsExpectedFailures=\(decision.allRecordsExpectedFailures) knownProObserved=\(knownProObserved)\n"
                    + history
                return decision.allowsPostcondition(noPro: !proExists, knownProObserved: knownProObserved)
            }
            completion = "passed"
        } catch let error as PurchaseTestError {
            completion = "conditionNotMet"
            throw error
        }
    }

    private func purchaseAppState(_ app: XCUIApplication, diagnostics: Bool) -> PurchaseAppState {
        guard diagnostics else { return .unknownDisabled }
        let elements = app.buttons.matching(identifier: "purchase.state")
        guard elements.count == 1 else { return .unknownMissingOrAmbiguous }
        // Never copy arbitrary AX values into the bounded record.
        switch elements.element(boundBy: 0).value as? String {
        case "purchase-state isPro=false isBusy=false": return .known(isPro: false, isBusy: false)
        case "purchase-state isPro=false isBusy=true": return .known(isPro: false, isBusy: true)
        case "purchase-state isPro=true isBusy=false": return .known(isPro: true, isBusy: false)
        case "purchase-state isPro=true isBusy=true": return .known(isPro: true, isBusy: true)
        default: return .unknownUnrecognized
        }
    }

    private func purchaseHistoryObservation(_ transactions: [SKTestTransaction]) -> String {
        let limit = 64
        let states = ["purchasing", "purchased", "failed", "restored", "deferred", "unknown"]
        var counts = Array(repeating: Array(repeating: 0, count: 4), count: states.count)
        for transaction in transactions.prefix(limit) {
            let state: Int
            switch transaction.state {
            case .purchasing: state = 0
            case .purchased: state = 1
            case .failed: state = 2
            case .restored: state = 3
            case .deferred: state = 4
            @unknown default: state = 5
            }
            let productMatches = transaction.productIdentifier == productID
            let pending = transaction.pendingAskToBuyConfirmation
            counts[state][(productMatches ? 2 : 0) + (pending ? 1 : 0)] += 1
        }
        var lines = ["history total=\(transactions.count) inspected=\(min(transactions.count, limit)) truncated=\(transactions.count > limit)",
                     "history columns=unmatchedNotPending,unmatchedPending,matchedNotPending,matchedPending"]
        for (index, state) in states.enumerated() {
            lines.append("history state=\(state) counts=\(counts[index].map(String.init).joined(separator: ","))")
        }
        return lines.joined(separator: "\n")
    }

    private func verifyFailedPurchaseFreeQuota(
        app: XCUIApplication, springboard: XCUIApplication, russian: Bool
    ) async throws {
        var completion = "interrupted-or-failed"
        defer {
            recordPurchaseObservation("purchase-free-quota completion=\(completion) afterExpectedFailurePostconditionPassed=true",
                                      name: "Purchase failure Free quota")
        }
        app.buttons[russian ? "Готово" : "Done"].tap()
        let trips = app.buttons[russian ? "Поездки" : "Trips"].firstMatch
        try await require("Trips did not become available for the Free quota check", app: app, springboard: springboard) {
            trips.exists && trips.isHittable
        }
        trips.tap()
        let create = app.buttons[russian ? "Создать поездку" : "Create trip"]
        try await require("The existing demo trip is not available after failed purchases", app: app, springboard: springboard) {
            app.staticTexts["Coast weekend"].exists && create.exists && create.isHittable
        }
        create.tap()
        try await require("Failed purchases unexpectedly removed the free trip limit", app: app, springboard: springboard) {
            app.navigationBars["TripDocket Pro"].exists
                && !app.textFields[russian ? "Название поездки" : "Trip name"].exists
        }
        attachDiagnostics(app: app, springboard: springboard, name: "Failed purchases preserve Free trip quota")
        completion = "passed"
    }

    private func recordPurchaseObservation(_ value: String, name: String) {
        // Fixed vocabulary, booleans and counts only; no identifiers or error payloads.
        print(value)
        let attachment = XCTAttachment(string: value)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func clearPurchaseFailure(_ session: SKTestSession) async throws {
        // Await fault removal before restoring the local configuration. A failed
        // cleanup is a test failure and cannot be silently carried to another test.
        do {
            try await session.setSimulatedError(nil, forAPI: .purchase)
        } catch {
            session.clearTransactions()
            session.resetToDefaultState()
            throw error
        }
        session.clearTransactions()
        session.resetToDefaultState()
        guard await session.simulatedError(forAPI: .purchase) == nil,
              session.allTransactions().isEmpty else {
            throw PurchaseTestError(message: "Purchase failure regression left local StoreKit state behind")
        }
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

    func testExpectedFailureHistoryAcceptsEmptyOneAndTwoFailures() {
        for count in 0...2 {
            let result = expectedHistory(Array(repeating: historyRecord(), count: count))
            XCTAssertTrue(result.attemptsComplete)
            XCTAssertTrue(result.withinAttemptBound)
            XCTAssertTrue(result.allRecordsExpectedFailures)
            XCTAssertTrue(result.accepted)
        }
    }

    func testExpectedFailureHistoryRejectsUnsafeAndUnknownStates() {
        let unsafe = [SKPaymentTransactionState.purchasing.rawValue,
                      SKPaymentTransactionState.purchased.rawValue,
                      SKPaymentTransactionState.restored.rawValue,
                      SKPaymentTransactionState.deferred.rawValue, Int.max]
        for state in unsafe {
            let result = expectedHistory([historyRecord(stateRawValue: state)])
            XCTAssertFalse(result.allRecordsExpectedFailures, "state=\(state)")
            XCTAssertFalse(result.accepted)
        }
    }

    func testExpectedFailureHistoryRejectsForeignOrEmptyProduct() {
        for product in ["", "com.example.other.pro", productID.uppercased()] {
            let result = expectedHistory([historyRecord(product: product)])
            XCTAssertFalse(result.allRecordsExpectedFailures)
            XCTAssertFalse(result.accepted)
        }
    }

    func testExpectedFailureHistoryRejectsPendingConfirmation() {
        let result = expectedHistory([historyRecord(pending: true)])
        XCTAssertFalse(result.allRecordsExpectedFailures)
        XCTAssertFalse(result.accepted)
    }

    func testExpectedFailureHistoryRejectsMixedRecordsInEitherOrder() {
        let unsafe = [historyRecord(stateRawValue: SKPaymentTransactionState.purchased.rawValue),
                      historyRecord(stateRawValue: Int.max), historyRecord(product: "other"),
                      historyRecord(pending: true)]
        for record in unsafe {
            for records in [[historyRecord(), record], [record, historyRecord()]] {
                let result = expectedHistory(records)
                XCTAssertFalse(result.allRecordsExpectedFailures)
                XCTAssertFalse(result.accepted)
            }
        }
    }

    func testExpectedFailureHistoryRejectsOverflow() {
        let result = expectedHistory(Array(repeating: historyRecord(), count: 3))
        XCTAssertTrue(result.attemptsComplete)
        XCTAssertTrue(result.allRecordsExpectedFailures)
        XCTAssertFalse(result.withinAttemptBound)
        XCTAssertFalse(result.accepted)
    }

    func testExpectedFailureHistoryRejectsIncompleteAndInvalidAttemptCounts() {
        for completed in [-1, 0, 1, 3, Int.max] {
            for count in [0, 2] {
                let result = expectedHistory(Array(repeating: historyRecord(), count: count),
                                             completedAttempts: completed)
                XCTAssertFalse(result.attemptsComplete, "completed=\(completed)")
                XCTAssertFalse(result.accepted)
            }
        }
    }

    func testExpectedFailureHistoryInspectsSuffixBeyondDiagnosticPrefix() {
        let prefix = Array(repeating: historyRecord(), count: 64)
        let allFailed = expectedHistory(prefix + [historyRecord()])
        XCTAssertTrue(allFailed.allRecordsExpectedFailures)
        XCTAssertFalse(allFailed.accepted) // Still exceeds the two-attempt bound.
        let unsafeSuffix = expectedHistory(prefix + [
            historyRecord(stateRawValue: SKPaymentTransactionState.purchased.rawValue)
        ])
        // Inspect this independent result: accepted=false alone could pass
        // solely because of the count bound, hiding a prefix-only classifier.
        XCTAssertFalse(unsafeSuffix.allRecordsExpectedFailures)
        XCTAssertFalse(unsafeSuffix.accepted)
    }

    func testPurchasePostconditionRejectsKnownProAndPreservesUnknownState() {
        let valid = expectedHistory([])
        for busy in [false, true] {
            let pro = PurchaseAppState.known(isPro: true, isBusy: busy)
            XCTAssertEqual(pro.knownIsPro, true)
            XCTAssertFalse(valid.allowsPostcondition(noPro: true, knownProObserved: pro.knownIsPro == true))
            let free = PurchaseAppState.known(isPro: false, isBusy: busy)
            XCTAssertEqual(free.knownIsPro, false)
            XCTAssertTrue(valid.allowsPostcondition(noPro: true, knownProObserved: free.knownIsPro == true))
        }
        let unknowns: [PurchaseAppState] = [.unknownDisabled, .unknownMissingOrAmbiguous, .unknownUnrecognized]
        for state in unknowns {
            XCTAssertNil(state.knownIsPro)
            XCTAssertTrue(state.diagnostic.hasPrefix("unknown-"))
            XCTAssertTrue(valid.allowsPostcondition(noPro: true, knownProObserved: state.knownIsPro == true))
            // A previously observed Pro value remains a failure even when
            // the latest observation is unknown or the Pro label is absent.
            XCTAssertFalse(valid.allowsPostcondition(noPro: true, knownProObserved: true))
        }
        XCTAssertFalse(valid.allowsPostcondition(noPro: false, knownProObserved: false))
        XCTAssertFalse(expectedHistory([historyRecord(pending: true)])
            .allowsPostcondition(noPro: true, knownProObserved: false))
    }

    private func historyRecord(
        stateRawValue: Int = SKPaymentTransactionState.failed.rawValue,
        product: String? = nil, pending: Bool = false
    ) -> ExpectedFailureHistory.Record {
        .init(stateRawValue: stateRawValue, productIdentifier: product ?? productID,
              pendingAskToBuyConfirmation: pending)
    }

    private func expectedHistory(
        _ records: [ExpectedFailureHistory.Record], completedAttempts: Int = 2
    ) -> ExpectedFailureHistory.Decision {
        ExpectedFailureHistory.evaluate(records, completedAttempts: completedAttempts, productID: productID)
    }

    private enum ExpectedFailureHistory {
        static let requiredAttempts = 2

        struct Record {
            let stateRawValue: Int
            let productIdentifier: String
            let pendingAskToBuyConfirmation: Bool
        }

        struct Decision {
            let attemptsComplete: Bool
            let withinAttemptBound: Bool
            let allRecordsExpectedFailures: Bool
            var accepted: Bool { attemptsComplete && withinAttemptBound && allRecordsExpectedFailures }

            func allowsPostcondition(noPro: Bool, knownProObserved: Bool) -> Bool {
                noPro && accepted && !knownProObserved
            }
        }

        static func evaluate(_ records: [Record], completedAttempts: Int, productID: String) -> Decision {
            // Independent full-array classification lets the suffix regression
            // detect a prefix-only scan even when the count bound also rejects.
            let allExpected = records.allSatisfy {
                $0.stateRawValue == SKPaymentTransactionState.failed.rawValue
                    && $0.productIdentifier == productID && !$0.pendingAskToBuyConfirmation
            }
            return Decision(attemptsComplete: completedAttempts == requiredAttempts,
                            withinAttemptBound: completedAttempts >= 0 && records.count <= completedAttempts,
                            allRecordsExpectedFailures: allExpected)
        }
    }

    private enum PurchaseAppState {
        case known(isPro: Bool, isBusy: Bool)
        case unknownDisabled, unknownMissingOrAmbiguous, unknownUnrecognized

        var knownIsPro: Bool? {
            if case .known(let isPro, _) = self { return isPro }
            return nil
        }

        var diagnostic: String {
            switch self {
            case .known(let isPro, let isBusy): return "known isPro=\(isPro) isBusy=\(isBusy)"
            case .unknownDisabled: return "unknown-disabled"
            case .unknownMissingOrAmbiguous: return "unknown-missing-or-ambiguous"
            case .unknownUnrecognized: return "unknown-unrecognized"
            }
        }
    }

    private struct PurchaseTestError: LocalizedError, CustomStringConvertible {
        let message: String
        var description: String { message }
        var errorDescription: String? { message }
    }
}
