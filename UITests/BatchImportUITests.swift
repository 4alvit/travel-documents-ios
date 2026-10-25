import Foundation
import StoreKit
import StoreKitTest
import XCTest

/// Functional coverage at standard text size. The host seeds only the named
/// synthetic PDFs into this dedicated simulator's real Files provider. Nothing
/// is injected into the app library. The existing fixture flag bypasses device
/// authentication only; Pro must come from the actual local StoreKit purchase.
/// Run serially, with a runner maximum/default allowance of at least 300 seconds.
@MainActor
final class BatchImportUITests: XCTestCase {
    private let productID = "com.4alvit.tripfolio.pro"
    private var folder: String {
        ProcessInfo.processInfo.environment["TRIPDOCKET_BATCH_FOLDER"] ?? "TripDocket-Batch-QA"
    }
    private let filenames = ["synthetic-ticket.pdf", "synthetic-insurance.pdf"]

    func testRealFilesBatchRequiresEveryReviewAndPreservesOriginals() async throws {
        try XCTSkipUnless(ProcessInfo.processInfo.environment["TRIPDOCKET_BATCH_UI"] == "1",
                          "Opt in with TRIPDOCKET_BATCH_UI=1 on the dedicated, fixture-seeded simulator")
        guard !folder.isEmpty, !folder.contains("/"), !folder.contains("\\") else {
            throw BatchTestFailure(message: "TRIPDOCKET_BATCH_FOLDER must name a single nonempty Files folder")
        }
        executionTimeAllowance = 300
        continueAfterFailure = false
        let app = XCUIApplication()
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        app.terminate()
        let session = try await localStoreSession()
        defer {
            app.terminate()
            session.clearTransactions()
            session.resetToDefaultState()
        }
        app.launchArguments = ["--ui-testing-unlocked", "--ui-testing-reset", "--demo",
                               "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
        app.launch()
        try await openTrip(app)
        try await openBatchEntry(app)
        try await wait("Free batch entry must show Pro, not a file picker", app: app) {
            app.navigationBars["TripDocket Pro"].exists && !app.buttons["batch.chooseFiles"].exists
        }
        try await purchaseOnce(app, springboard: springboard, session: session)
        let done = app.navigationBars["TripDocket Pro"].buttons["Done"]
        try check(done.isHittable, app: app, "Pro Done is not reachable after purchase")
        done.tap()
        try await openBatchEntry(app)

        let choose = app.buttons["batch.chooseFiles"]
        try await wait("The purchased batch entry did not open", app: app) { choose.exists && choose.isEnabled }
        try await reveal(choose, app: app, navigation: "Import files")
        choose.tap()
        try await selectRealFiles(app)
        try await wait("Both real files were not prepared for individual review", app: app) {
            self.reviewRow(self.filenames[0], in: app).exists
                && self.reviewRow(self.filenames[1], in: app).exists
                && app.buttons["batch.save"].exists
        }
        try check(reviewRows(in: app).count == 2, app: app, "The draft must contain exactly the two selected files")
        try await assertReviews(0, saveEnabled: false, app: app)
        capture(app, "Two real Files originals; nothing reviewed")

        try await openReview(filenames[0], app: app)
        try await selectMetadata("Type", value: "Ticket", app: app)
        try await selectMetadata("Person", value: "Alex Example", app: app)
        let firstExpiry = app.switches["Add confirmed expiry date"]
        try await reveal(firstExpiry, app: app, navigation: "Review document")
        try check(firstExpiry.value as? String == "0", app: app, "A file must not acquire an inferred expiry date")
        try await replaceTitle("QA reviewed ticket", app: app)
        try await confirmCurrent(app)
        try await assertReviews(1, saveEnabled: false, app: app)
        capture(app, "First document confirmed; Save still disabled")

        try await openReview(filenames[1], app: app)
        try await selectMetadata("Type", value: "Insurance", app: app)
        try await selectMetadata("Person", value: "Everyone / unassigned", app: app)
        let secondExpiry = app.switches["Add confirmed expiry date"]
        try await reveal(secondExpiry, app: app, navigation: "Review document")
        try check(secondExpiry.value as? String == "0", app: app, "Second original has an unexpected inferred expiry")
        // The labelled Switch is the whole row; its centre is the text. Tap
        // the single native switch nested inside that exact row instead.
        let nativeSwitches = secondExpiry.switches
        try check(nativeSwitches.count == 1, app: app, "The expiry row must contain one native switch")
        let nativeExpiry = nativeSwitches.element(boundBy: 0)
        try check(nativeExpiry.isEnabled && nativeExpiry.isHittable, app: app,
                  "The native expiry switch is not reachable")
        nativeExpiry.tap()
        // The native DatePicker has no label. Its own cell carries the exact
        // Expiry date text and one DatePicker with a visible date-value button.
        let dateCells = app.cells.containing(.staticText, identifier: "Expiry date")
        try await wait("Explicit expiry opt-in did not reveal its date control", app: app) {
            guard secondExpiry.value as? String == "1", dateCells.count == 1 else { return false }
            let pickers = dateCells.element(boundBy: 0).datePickers
            guard pickers.count == 1 else { return false }
            let date = pickers.element(boundBy: 0).buttons["Date Picker"]
            return date.exists && date.isHittable
                && !(date.value as? String ?? "").trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
        // This fixture explicitly confirms the displayed current date; it does
        // not claim to test calendar navigation or OCR extraction of a date.
        capture(app, "Explicit expiry choice before confirmation")
        try await replaceTitle("QA reviewed insurance", app: app)
        try await confirmCurrent(app)
        try await assertReviews(2, saveEnabled: true, app: app)

        // A previously confirmed item's metadata cannot be changed silently.
        try await openReview(filenames[0], app: app)
        try await replaceTitle("QA corrected ticket", app: app)
        let reviewNavigation = app.navigationBars["Review document"]
        let back = [reviewNavigation.buttons["Import files"], reviewNavigation.buttons["Back"]]
            .first { $0.exists && $0.isHittable }
        try check(back != nil, app: app, "The review screen did not expose its Back control")
        back?.tap()
        try await assertReviews(1, saveEnabled: false, app: app)
        capture(app, "Editing a confirmed title requires review again")
        try await openReview(filenames[0], app: app)
        try await confirmCurrent(app)
        try await assertReviews(2, saveEnabled: true, app: app)
        let save = app.buttons["batch.save"]
        try await reveal(save, app: app, navigation: "Import files")
        capture(app, "Both documents individually confirmed; Save enabled")
        save.tap()
        try await wait("Batch save did not return to the trip", app: app) {
            !app.navigationBars["Import files"].exists
                && app.navigationBars["Coast weekend"].exists
                && self.documentRow("QA corrected ticket", in: app).exists
                && self.documentRow("QA reviewed insurance", in: app).exists
        }
        try await verifySavedLibrary(app)
        capture(app, "Two saved originals plus unchanged demo original")

        // Relaunch without reset: the successful result must be persistent.
        app.terminate()
        app.launchArguments = ["--ui-testing-unlocked",
                               "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryL"]
        app.launch()
        try await openTrip(app)
        try await verifySavedLibrary(app)
        for title in ["QA corrected ticket", "QA reviewed insurance"] {
            let row = documentRow(title, in: app)
            try await reveal(row, app: app, navigation: "Coast weekend")
            row.tap()
            try await wait("Saved original preview did not open: \(title)", app: app) {
                app.navigationBars["Original document"].exists
                    && app.otherElements["QLPreviewControllerView"].exists
            }
            // The renderer starts asynchronously. These captures require
            // independent pixel inspection; a container alone proves no PDF.
            try await Task.sleep(for: .seconds(5))
            capture(app, "Saved original after relaunch — \(title) — inspect PDF pixels")
            let previewDone = app.navigationBars["Original document"].buttons["Done"]
            try check(previewDone.isHittable, app: app, "Original preview Done is not reachable")
            previewDone.tap()
        }
    }

    private func localStoreSession() async throws -> SKTestSession {
        let configuration = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "Tripfolio", withExtension: "storekit"))
        let session = try SKTestSession(contentsOf: configuration)
        session.resetToDefaultState()
        session.clearTransactions()
        session.disableDialogs = true
        do {
            let transaction = try await session.buyProduct(identifier: productID, options: [])
            guard transaction.environment == .xcode, transaction.productID == productID else {
                throw BatchTestFailure(message: "StoreKit preflight did not return the expected Xcode test product; app was not launched")
            }
            session.clearTransactions()
            guard session.allTransactions().isEmpty else {
                throw BatchTestFailure(message: "StoreKit preflight transaction was not cleared")
            }
            session.disableDialogs = false
            return session
        } catch {
            session.clearTransactions()
            session.resetToDefaultState()
            throw error
        }
    }

    private func purchaseOnce(_ app: XCUIApplication, springboard: XCUIApplication, session: SKTestSession) async throws {
        let buy = app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", "Unlock Pro ·")).firstMatch
        try await wait("The local product did not load; no purchase retry is allowed", app: app) { buy.exists && buy.isEnabled }
        try await reveal(buy, app: app, navigation: "TripDocket Pro")
        buy.tap()
        try await wait("No positively identified Xcode payment sheet appeared", app: app, springboard: springboard) {
            self.xcodeMarker(app).exists || self.xcodeMarker(springboard).exists
        }
        let surface = xcodeMarker(app).exists ? app : springboard
        // The saved iOS 27 Xcode sheet labels its confirmation "Purchase".
        // Accept only these exact payment labels, under the same Xcode guard.
        let confirm = surface.buttons.matching(NSPredicate(
            format: "label ==[c] %@ OR label ==[c] %@", "Purchase", "Buy"
        )).firstMatch
        try await wait("Xcode payment sheet has no reachable Purchase or Buy control", app: app, springboard: springboard) {
            self.xcodeMarker(surface).exists && confirm.exists && confirm.isEnabled && confirm.isHittable
        }
        capture(app, "Xcode payment sheet before sole confirmation", springboard: springboard)
        try check(xcodeMarker(surface).exists, app: app, "Xcode marker disappeared before confirmation")
        confirm.tap()
        var successAlert: XCUIElement?
        try await wait("Local purchase neither completed nor showed its identified Xcode success alert",
                       app: app, springboard: springboard) {
            successAlert = self.localSuccessAlert(in: app) ?? self.localSuccessAlert(in: springboard)
            if let successAlert {
                let ok = successAlert.buttons["OK"]
                return ok.exists && ok.isEnabled && ok.isHittable
            }
            return app.staticTexts["Pro is unlocked"].exists
                && !self.xcodeMarker(app).exists && !self.xcodeMarker(springboard).exists
        }
        if let successAlert {
            capture(app, "Identified Xcode purchase success before OK", springboard: springboard)
            try check(isLocalSuccessAlert(successAlert), app: app,
                      "The identified Xcode success alert changed before dismissal")
            let ok = successAlert.buttons["OK"]
            try check(ok.isEnabled && ok.isHittable, app: app, "Xcode success OK became unavailable")
            ok.tap()
        }
        try await wait("Actual local purchase did not unlock Pro", app: app, springboard: springboard) {
            app.staticTexts["Pro is unlocked"].exists
                && !self.xcodeMarker(app).exists && !self.xcodeMarker(springboard).exists
        }
        try check(session.allTransactions().filter { $0.productIdentifier == productID }.count == 1,
                  app: app, "The app purchase did not produce exactly one expected local transaction")
        capture(app, "Actual local StoreKit Pro entitlement")
    }

    private func xcodeMarker(_ app: XCUIApplication) -> XCUIElement {
        app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", "Xcode")).firstMatch
    }

    private func localSuccessAlert(in app: XCUIApplication) -> XCUIElement? {
        app.alerts.allElementsBoundByIndex.first { isLocalSuccessAlert($0) }
    }

    private func isLocalSuccessAlert(_ alert: XCUIElement) -> Bool {
        // Both observed messages must belong to this same native alert. Never
        // dismiss a generic OK, account prompt, or failed-purchase alert.
        alert.exists
            && alert.staticTexts.matching(NSPredicate(
                format: "label CONTAINS %@", "Your purchase was successful."
            )).firstMatch.exists
            && alert.staticTexts.matching(NSPredicate(
                format: "label CONTAINS %@", "[Environment: Xcode]"
            )).firstMatch.exists
    }

    private func openTrip(_ app: XCUIApplication) async throws {
        let trip = app.staticTexts["Coast weekend"]
        try await wait("The synthetic trip did not load", app: app) { trip.exists && trip.isHittable }
        trip.tap()
        try await wait("Trip navigation did not open", app: app) { app.navigationBars["Coast weekend"].exists }
    }

    private func openBatchEntry(_ app: XCUIApplication) async throws {
        let actions = app.navigationBars["Coast weekend"].buttons["Trip actions"]
        try await wait("Trip actions is unavailable", app: app) { actions.exists && actions.isHittable }
        actions.tap()
        let batch = app.buttons["Import multiple files · Pro"]
        try await wait("Trip actions did not expose multiple-file import", app: app) { batch.isHittable }
        batch.tap()
    }

    private func selectRealFiles(_ app: XCUIApplication) async throws {
        let navigation = app.navigationBars["FullDocumentManagerViewControllerNavigationBar"].firstMatch
        try await wait("Files did not present its navigation", app: app) { navigation.exists }
        let picker = app.otherElements["Browse View (Picker)"].firstMatch
        try await wait("The real Files picker root is missing", app: app) { picker.exists }
        let directory = picker.cells.matching(identifier: folder + ", Folder").firstMatch
        // The captured native tab bar is a sibling of Browse View (Picker),
        // not its descendant. Its controls can appear after the root/navigation.
        let browse = app.tabBars["DOC.browsingModeTabBar"].buttons["Browse"].firstMatch
        let location = app.cells.matching(NSPredicate(
            format: "identifier == %@ OR identifier == %@", "DOC.sidebar.item.On My iPhone", "DOC.sidebar.item.On My iPad"
        )).firstMatch
        try await wait("Native Files navigation did not render its local browsing controls", app: app) {
            navigation.exists && picker.exists
                && ((directory.exists && directory.isHittable)
                    || (location.exists && location.isHittable)
                    || (browse.exists && browse.isHittable))
        }
        if !(directory.exists && directory.isHittable) {
            if !(location.exists && location.isHittable) {
                try check(browse.exists && browse.isHittable, app: app, "Native Files Browse is unavailable")
                browse.tap()
            }
            // Browse can restore On My iPhone directly instead of showing
            // the locations sidebar. Wait for either observed destination.
            try await wait("Files did not show the exact fixture folder or its local location", app: app) {
                (directory.exists && directory.isHittable) || (location.exists && location.isHittable)
            }
            if !(directory.exists && directory.isHittable) { location.tap() }
        }
        try await wait("The named synthetic Files folder is missing", app: app) { directory.exists && directory.isHittable }
        directory.tap()
        for filename in filenames {
            let basename = (filename as NSString).deletingPathExtension
            let file = picker.cells.matching(NSPredicate(format: "label BEGINSWITH %@", basename)).firstMatch
            try await wait("Missing selectable real Files original: \(filename)", app: app) { file.exists && file.isHittable }
            file.tap()
            try check(navigation.exists, app: app, "Files closed before both originals could be selected")
        }
        let open = picker.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", "Open", "Open (")).firstMatch
        try await wait("Files did not expose Open after selecting both originals", app: app) { open.exists && open.isEnabled && open.isHittable }
        capture(app, "Two synthetic originals selected in real Files")
        open.tap()
        try await wait("Files remained after opening the selection", app: app) { !navigation.exists }
    }

    private func reviewRows(in app: XCUIApplication) -> XCUIElementQuery {
        app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH %@", "batch.review."))
    }

    private func reviewRow(_ filename: String, in app: XCUIApplication) -> XCUIElement {
        reviewRows(in: app).matching(NSPredicate(format: "label CONTAINS %@", filename)).firstMatch
    }

    private func openReview(_ filename: String, app: XCUIApplication) async throws {
        let row = reviewRow(filename, in: app)
        try await reveal(row, app: app, navigation: "Import files")
        row.tap()
        try await wait("Individual review did not open for \(filename)", app: app) { app.navigationBars["Review document"].exists }
    }

    private func selectMetadata(_ title: String, value: String, app: XCUIApplication) async throws {
        let picker = app.buttons.matching(NSPredicate(format: "label == %@ OR label BEGINSWITH %@", title, title + ",")).firstMatch
        try await reveal(picker, app: app, navigation: "Review document")
        picker.tap()
        try await wait("\(title) choices did not open", app: app) { app.navigationBars[title].exists }
        // Navigation-link Picker rows are native buttons in the presented
        // choices collection, not StaticTexts (observed Type picker hierarchy).
        let choice = app.collectionViews.buttons.matching(NSPredicate(format: "label == %@", value)).firstMatch
        try await wait("Metadata choice is not reachable: \(value)", app: app) {
            app.navigationBars[title].exists && choice.exists && choice.isHittable
        }
        if choice.isSelected {
            // Selecting the current value leaves this native picker open.
            // Preserve the verified selection and return using its own Back.
            let back = app.navigationBars[title].buttons.matching(identifier: "BackButton").firstMatch
            try check(app.navigationBars[title].exists && back.exists && back.isHittable
                        && back.label == "Review document",
                      app: app, "Selected \(title) picker has no verified Back control")
            back.tap()
        } else {
            choice.tap()
        }
        try await wait("\(title) choice did not return to review", app: app) {
            !app.navigationBars[title].exists && app.navigationBars["Review document"].exists
        }
    }

    private func replaceTitle(_ value: String, app: XCUIApplication) async throws {
        let field = app.textFields["batch.title"].firstMatch
        try await reveal(field, app: app, navigation: "Review document")
        field.tap()
        // A native tap can place the caret at the beginning of this field.
        // Select the complete value through the iOS edit menu instead of
        // assuming where repeated Delete keystrokes will start.
        field.press(forDuration: 1.1)
        var selectAll: XCUIElement?
        try await wait("The title edit menu did not expose a reachable Select All", app: app) {
            selectAll = [app.menuItems["Select All"].firstMatch, app.buttons["Select All"].firstMatch]
                .first { $0.exists && $0.isEnabled && $0.isHittable }
            return selectAll != nil
        }
        capture(app, "Native title edit menu before Select All")
        try XCTUnwrap(selectAll).tap()
        field.typeText(value)
        try check(field.value as? String == value, app: app, "The document title was not edited exactly")
    }

    private func confirmCurrent(_ app: XCUIApplication) async throws {
        let confirm = app.buttons["batch.confirmItem"]
        try await reveal(confirm, app: app, navigation: "Review document")
        try check(confirm.isEnabled, app: app, "Valid document details could not be confirmed")
        confirm.tap()
        try await wait("Confirmation did not return to batch review", app: app) { !app.navigationBars["Review document"].exists }
    }

    private func assertReviews(_ count: Int, saveEnabled: Bool, app: XCUIApplication) async throws {
        let save = app.buttons["batch.save"]
        try await wait("Review count or Save availability is incorrect", app: app) {
            app.staticTexts["\(count) of 2 reviewed"].exists && save.exists && save.isEnabled == saveEnabled
        }
    }

    private func documentRow(_ title: String, in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH %@", title)).firstMatch
    }

    private func verifySavedLibrary(_ app: XCUIApplication) async throws {
        let ticket = documentRow("QA corrected ticket", in: app)
        let insurance = documentRow("QA reviewed insurance", in: app)
        try await wait("Saved document titles did not persist", app: app) { ticket.exists && insurance.exists }
        try check(ticket.label.contains("Ticket") && ticket.label.contains("Alex Example")
                    && !ticket.label.contains("Expires") && !ticket.label.contains("Expired"),
                  app: app, "Ticket metadata did not persist with its chosen person and no expiry")
        try check(insurance.label.contains("Insurance") && !insurance.label.contains("Alex Example")
                    && (insurance.label.contains("Expires") || insurance.label.contains("Expired")),
                  app: app, "Insurance metadata did not persist with the explicit date and unassigned person")
        let checkOriginals = app.buttons["Check all 3 originals"]
        try await reveal(checkOriginals, app: app, navigation: "Coast weekend")
        checkOriginals.tap()
        try await wait("The three complete originals did not verify", app: app) { app.staticTexts["3 of 3 originals verified"].exists }
    }

    private func reveal(_ element: XCUIElement, app: XCUIApplication, navigation: String) async throws {
        for _ in 0..<10 {
            let bar = app.navigationBars[navigation]
            try check(bar.exists, app: app, "Expected navigation is missing: \(navigation)")
            var viewport = app.frame.intersection(CGRect(x: bar.frame.minX, y: bar.frame.maxY,
                width: bar.frame.width, height: max(0, app.frame.maxY - bar.frame.maxY))).insetBy(dx: 6, dy: 8)
            for obstruction in app.tabBars.allElementsBoundByIndex + app.keyboards.allElementsBoundByIndex
                where obstruction.exists && obstruction.isHittable && obstruction.frame.minY > viewport.minY {
                viewport.size.height = max(0, min(viewport.maxY, obstruction.frame.minY - 8) - viewport.minY)
            }
            let frame = element.exists ? element.frame : .null
            if element.exists && element.isHittable && !frame.isEmpty && viewport.contains(frame) { return }
            let candidates = app.collectionViews.allElementsBoundByIndex + app.scrollViews.allElementsBoundByIndex
            let container = candidates.reversed().first {
                $0.exists && $0.isHittable && $0.frame.width <= bar.frame.width + 32
                    && $0.frame.intersection(viewport).height > 100
            }
            guard let container else { throw failure("No active scroll container for \(navigation)", app: app) }
            viewport = viewport.intersection(container.frame).insetBy(dx: 8, dy: 8)
            try check(viewport.height > 80, app: app, "No safe scroll viewport for \(navigation)")
            let upwards = frame.isNull || frame.midY > viewport.midY
            let distance = min(140, viewport.height * 0.45)
            let start = container.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: viewport.midX - container.frame.minX, dy: viewport.midY - container.frame.minY))
            start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 0, dy: upwards ? -distance : distance)),
                        withVelocity: .slow, thenHoldForDuration: 0.2)
            try await Task.sleep(for: .milliseconds(100))
        }
        throw failure("Required control did not become fully reachable in \(navigation): \(element.identifier)", app: app)
    }

    private func wait(_ message: String, app: XCUIApplication, springboard: XCUIApplication? = nil,
                      condition: @MainActor () -> Bool) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(15))
        repeat {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(100))
        } while ContinuousClock.now < deadline
        capture(app, message, springboard: springboard)
        throw BatchTestFailure(message: message)
    }

    private func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        if !condition { throw failure(message, app: app) }
    }

    private func failure(_ message: String, app: XCUIApplication) -> BatchTestFailure {
        capture(app, message)
        return BatchTestFailure(message: message)
    }

    private func capture(_ app: XCUIApplication, _ name: String, springboard: XCUIApplication? = nil) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let tree = XCTAttachment(string: app.debugDescription + (springboard.map { "\nSPRINGBOARD\n" + $0.debugDescription } ?? ""))
        tree.name = name + " — accessibility hierarchy"
        tree.lifetime = .keepAlways
        add(tree)
    }

    private struct BatchTestFailure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
