import Darwin
import Foundation
import XCTest

/// Requires the host biometric bridge and an enrolled, dedicated simulator.
/// These tests never bypass LocalAuthentication. The bridge emits a real
/// simulator Face ID event only after a flushed request from an observed prompt.
/// Screenshots need visual review: AX assertions do not prove absence of pixels
/// in the system app switcher, nor do simulated events validate physical Face ID.
@MainActor
final class PrivacyTransitionUITests: XCTestCase {
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    private let draftSuffix = " PRIVACY DRAFT"

    func testFailedAndCancelledAuthenticationKeepDocumentsPrivate() async throws {
        let app = try await launchLocked()
        defer { app.terminate() }
        try await unlockInitialFixture(app)

        let settings = app.buttons["Settings"].firstMatch
        try await require("Settings is not reachable", app: app) { settings.exists && settings.isHittable }
        settings.tap()
        let lock = app.buttons["Lock now"]
        try await reveal(lock, in: app)
        lock.tap()
        try await requireLocked(app, checkpoint: "Explicit lock before failed authentication")
        try await startAuthentication(app)
        try await requestBiometric("nomatch", in: app)
        try await require("Face ID failure did not expose a failure/retry or ended locked state", app: app) {
            self.hasAuthenticationFailure(in: app) || self.unlockButton(in: app).isHittable
        }
        try assertPrivate(app, checkpoint: "After nonmatching Face ID")
        try await attachSettled(app, name: "Nonmatching Face ID — documents private")

        // If the failed attempt already ended, begin a separate real prompt.
        // Cancellation is only claimed after tapping its observed system control.
        if unlockButton(in: app).isHittable && !hasAuthenticationUI(in: app) {
            try await startAuthentication(app)
        }
        try await cancelAuthentication(app)
        try await requireLocked(app, checkpoint: "After cancelling real authentication")
        try await require("Cancelled authentication left Unlock unavailable", app: app) {
            self.unlockButton(in: app).isHittable
        }
        try await startAuthentication(app)
        try await requestBiometric("match", in: app)
        try await requireUnlocked(app)
        try await attachSettled(app, name: "Successful authentication after failure and cancellation")
    }

    func testOriginalPreviewIsPrivateAcrossBackgroundAndReturn() async throws {
        let app = try await launchLocked()
        defer { app.terminate() }
        try await unlockInitialFixture(app)
        try await openTrip(app)
        let original = documentRow(in: app)
        try await reveal(original, in: app)
        original.tap()
        try await require("Original preview did not expose its Quick Look view and usable Done action", app: app) {
            app.navigationBars["Original document"].buttons["Done"].isHittable
                && app.otherElements["QLPreviewControllerView"].exists
        }
        // The observed Quick Look container is present before its PDF finishes
        // drawing. Allow a bounded render interval, then visually review the
        // actual PDF pixels in this attachment before accepting the evidence.
        try await attachSettled(app, name: "Original preview before background", delay: .seconds(5))
        try await backgroundAndReturnLocked(app, checkpoint: "Original preview")
        try await requestBiometric("match", in: app)
        try await requireUnlocked(app)
        try await attachSettled(app, name: "Original preview session after real authentication")
    }

    func testExportShareIsPrivateAcrossBackgroundAndReturn() async throws {
        let app = try await launchLocked()
        defer { app.terminate() }
        try await unlockInitialFixture(app)
        try await openTrip(app)
        let export = app.buttons["Export trip packet"]
        try await reveal(export, in: app)
        export.tap()
        let choose = app.buttons["Export…"]
        try await require("Explicit export warning did not appear", app: app) { choose.isHittable }
        let warning = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "readable, unencrypted form")).firstMatch
        try check(warning.exists, app: app, "Export did not present its plaintext warning")
        choose.tap()
        try await require("System share sheet did not expose a file action", app: app) {
            self.hasShareSheet(in: app)
        }
        try await attachSettled(app, name: "Export share sheet before background — no recipient selected")
        try await backgroundAndReturnLocked(app, checkpoint: "Export share sheet")
        try await requestBiometric("match", in: app)
        try await requireUnlocked(app)
        try await attachSettled(app, name: "Export session after real authentication — no file sent")
    }

    func testEditDraftIsPrivateAcrossBackgroundAndReturn() async throws {
        let app = try await launchLocked()
        defer { app.terminate() }
        try await unlockInitialFixture(app)
        _ = try await openDraft(app)
        try await backgroundAndReturnLocked(app, checkpoint: "Unsaved document draft")
        try await requestBiometric("match", in: app)
        try await requireUnlocked(app)
        // Privacy and availability are asserted here. Exact draft retention is
        // a separate test below, so a lost draft cannot be reported as a leak.
        try await attachSettled(app, name: "Editor session after real authentication")
    }

    func testUnsavedDocumentDraftSurvivesBackgroundAfterAuthentication() async throws {
        let app = try await launchLocked()
        defer { app.terminate() }
        try await unlockInitialFixture(app)
        let expected = try await openDraft(app)
        try await backgroundAndReturnLocked(app, checkpoint: "Draft preservation")
        try await requestBiometric("match", in: app)
        try await requireUnlocked(app)
        let title = app.textFields["Document title"]
        try await require("Privacy passed, but the unsaved document editor was discarded on background", app: app) {
            title.exists && title.value as? String == expected
        }
        try await attachSettled(app, name: "Unsaved draft retained after real authentication")
        let cancel = app.navigationBars["Edit document"].buttons["Cancel"]
        try check(cancel.isHittable, app: app, "Retained draft cannot be cancelled")
        cancel.tap()
    }

    func testMaximumTypeUnlockIsReachablePortraitAndLandscapeWithoutAuthenticationSuccess() async throws {
        let app = try await launchLocked(maximumType: true)
        defer {
            app.terminate()
            XCUIDevice.shared.orientation = .portrait
        }
        // Reject then cancel the real prompt; never emit a matching event in
        // this test. This also exercises the longer post-failure lock message.
        try await requestBiometric("nomatch", in: app)
        try await require("Maximum type Face ID attempt did not report failure", app: app) {
            self.hasAuthenticationFailure(in: app) || self.unlockButton(in: app).isHittable
        }
        if unlockButton(in: app).isHittable && !hasAuthenticationUI(in: app) {
            try await startAuthentication(app)
        }
        // At maximum type, Unlock may correctly be below the fold after this
        // cancellation. Wait for the locked state, then prove it is reachable
        // by scrolling, rather than requiring it to be immediately visible.
        var cancel: XCUIElement?
        try await require("Maximum type Face ID prompt has no reachable cancellation control", app: app) {
            cancel = self.authenticationCancel(in: app)
            return cancel != nil
        }
        try check(hasAuthenticationUI(in: app), app: app,
                  "Maximum type authentication disappeared before cancellation")
        try XCTUnwrap(cancel).tap()
        try await require("Maximum type cancellation did not return to the locked screen", app: app) {
            self.lockTitle(in: app).exists && !self.hasAuthenticationUI(in: app)
        }
        try await assertUnlockReachable(app, orientation: "portrait")
        XCUIDevice.shared.orientation = .landscapeLeft
        try await require("App did not enter landscape", app: app) { app.frame.width > app.frame.height }
        try await assertUnlockReachable(app, orientation: "landscape")
        // Prove the visible control actually starts a real authentication UI.
        try await startAuthentication(app)
        try assertPrivate(app, checkpoint: "Maximum type landscape authentication prompt")
        try await attachSettled(app, name: "Maximum type landscape — real authentication reached without success")
    }

    private func launchLocked(maximumType: Bool = false) async throws -> XCUIApplication {
        guard ProcessInfo.processInfo.environment["TRIPDOCKET_BIOMETRIC_DRIVER"] == "1" else {
            throw XCTSkip("Requires TRIPDOCKET_BIOMETRIC_DRIVER=1 and the host Face ID bridge on an enrolled, dedicated simulator. No authentication bypass is used.")
        }
        continueAfterFailure = false
        XCUIDevice.shared.orientation = .portrait
        let app = XCUIApplication()
        app.terminate()
        app.launchArguments = ["--demo"]
        if maximumType {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launchEnvironment = [:]
        app.launch()
        try await requireLocked(app, checkpoint: "Process launch before any biometric success")
        try await waitForAuthenticationUI(app)
        return app
    }

    private func unlockInitialFixture(_ app: XCUIApplication) async throws {
        try await requestBiometric("match", in: app)
        try await require("The dedicated simulator did not load the synthetic Coast weekend fixture after real authentication", app: app) {
            app.staticTexts["Coast weekend"].exists && !self.lockTitle(in: app).exists
        }
        try await attachSettled(app, name: "Synthetic fixture unlocked by real simulated Face ID")
    }

    private func openTrip(_ app: XCUIApplication) async throws {
        let trip = app.staticTexts["Coast weekend"]
        try await reveal(trip, in: app)
        trip.tap()
        try await require("Synthetic trip did not open", app: app) { app.buttons["Check original"].exists }
    }

    private func openDraft(_ app: XCUIApplication) async throws -> String {
        try await openTrip(app)
        let document = documentRow(in: app)
        try await reveal(document, in: app)
        document.press(forDuration: 1)
        let edit = app.buttons["Edit details"]
        try await require("Document context menu did not expose Edit details", app: app) { edit.isHittable }
        edit.tap()
        let title = app.textFields["Document title"]
        try await require("Document editor did not open", app: app) { title.isHittable }
        let expected = "Weekend reservation" + draftSuffix
        // Set only a transient editor value. Do not save or alter the fixture.
        title.tap()
        title.typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: (title.value as? String ?? "").count) + expected)
        try check(title.value as? String == expected, app: app, "Unable to establish the unsaved synthetic draft")
        try await attachSettled(app, name: "Unsaved synthetic document draft before background")
        return expected
    }

    private func backgroundAndReturnLocked(_ app: XCUIApplication, checkpoint: String) async throws {
        // This supported gesture attempts to expose the system's saved card.
        // Do not infer app-switcher entry from the gesture or AX alone: inspect
        // the attachment visually before claiming snapshot privacy coverage.
        let origin = app.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
        let start = origin.withOffset(CGVector(dx: app.frame.width / 2, dy: app.frame.height - 2))
        let end = origin.withOffset(CGVector(dx: app.frame.width / 2, dy: app.frame.height * 0.45))
        start.press(forDuration: 0.05, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 1)
        try await attachSettled(app, name: "\(checkpoint) — App-switcher gesture — requires visual review")
        // Home supplies the actual background transition even if the attempt
        // above did not enter the switcher on this device or system version.
        XCUIDevice.shared.press(.home)
        try await Task.sleep(for: .milliseconds(700))
        if app.state == .runningForeground {
            // Observed on iOS 27: Home from the switcher can return to the
            // selected app. Send one additional Home only in that known state.
            XCUIDevice.shared.press(.home)
        }
        try await require("App did not remain running in background", app: app) {
            app.state == .runningBackground || app.state == .runningBackgroundSuspended
        }
        app.activate()
        try await requireLocked(app, checkpoint: "\(checkpoint) — return before biometric success")
        try await waitForAuthenticationUI(app)
    }

    private func requireLocked(_ app: XCUIApplication, checkpoint: String) async throws {
        try await require("Privacy lock is absent: \(checkpoint)", app: app) { self.lockTitle(in: app).exists }
        try assertPrivate(app, checkpoint: checkpoint)
        try await attachSettled(app, name: checkpoint)
    }

    private func assertPrivate(_ app: XCUIApplication, checkpoint: String) throws {
        let secrets = ["Coast weekend", "Weekend reservation", "Alex Example", "ABC-000",
                       "SYNTHETIC DEMO", "sample-reservation.pdf", "PRIVACY DRAFT"]
        var predicates = secrets.map { secret in
            NSPredicate(
                format: "label CONTAINS[c] %@ OR value CONTAINS[c] %@", secret, secret
            )
        }
        predicates.append(NSPredicate(format: "label IN %@", ["Document title", "Original document", "Export trip packet", "Settings"]))
        // One AX query avoids delaying a live system authentication prompt with
        // a separate cross-process snapshot for every synthetic secret.
        let exposed = app.descendants(matching: .any).matching(
            NSCompoundPredicate(orPredicateWithSubpredicates: predicates)
        ).firstMatch
        try check(!exposed.exists, app: app, "Sensitive content or document controls remain in the locked accessibility tree: \(checkpoint)")
    }

    private func requireUnlocked(_ app: XCUIApplication) async throws {
        try await require("Successful Face ID did not restore a usable document interface", app: app) {
            !self.lockTitle(in: app).exists && !self.hasAuthenticationUI(in: app) && (
                app.staticTexts["Coast weekend"].isHittable
                || app.navigationBars["Coast weekend"].buttons["Add document"].isHittable
                || app.navigationBars["Original document"].buttons["Done"].isHittable
                || app.textFields["Document title"].isHittable
                || app.buttons["Settings"].firstMatch.isHittable || self.hasShareSheet(in: app)
            )
        }
    }

    private func startAuthentication(_ app: XCUIApplication) async throws {
        try await require("Unlock is not reachable before authentication", app: app) {
            self.unlockButton(in: app).isHittable
        }
        unlockButton(in: app).tap()
        try await waitForAuthenticationUI(app)
    }

    private func waitForAuthenticationUI(_ app: XCUIApplication) async throws {
        try await require("No real system Face ID UI observed; bridge request withheld", app: app) {
            // First-use permission is distinct from an authentication prompt.
            // Only accept its observed app-specific Face ID permission alert.
            for surface in [app, self.springboard] {
                for alert in surface.alerts.allElementsBoundByIndex where
                    alert.label.contains("TripDocket") && alert.label.contains("Face ID") {
                    let allow = alert.buttons.matching(NSPredicate(format: "label == %@ OR label == %@", "OK", "Allow")).firstMatch
                    if allow.isHittable { allow.tap(); return false }
                }
            }
            return self.hasBiometricScanUI(in: app)
        }
    }

    private func hasAuthenticationUI(in app: XCUIApplication) -> Bool {
        hasBiometricScanUI(in: app) || [app, springboard].contains { surface in
            surface.alerts["com.apple.localauthentication.ax.authentication.alert"].exists
        }
    }

    private func hasBiometricScanUI(in app: XCUIApplication) -> Bool {
        // A failed scan has its own observed LocalAuthentication alert. It is
        // still an authentication UI, but cannot consume a new biometric event
        // until the user explicitly retries. Do not signal the bridge there.
        guard ![app, springboard].contains(where: { surface in
            surface.alerts["com.apple.localauthentication.ax.authentication.alert"].exists
        }) else { return false }
        return [app, springboard].contains { surface in
            surface.descendants(matching: .any).matching(NSPredicate(
                format: "label == %@ OR label CONTAINS %@", "Face ID", "Unlock your private travel documents."
            )).firstMatch.exists
        }
    }

    private func requestBiometric(_ result: String, in app: XCUIApplication) async throws {
        try await waitForAuthenticationUI(app)
        try assertPrivate(app, checkpoint: "Before requesting Face ID \(result)")
        print("TRIPDOCKET_BIOMETRIC_REQUEST \(result)")
        fflush(nil)
    }

    private func hasAuthenticationFailure(in app: XCUIApplication) -> Bool {
        [app, springboard].contains { surface in
            surface.descendants(matching: .any).matching(NSPredicate(
                format: "label CONTAINS[c] %@ OR label CONTAINS[c] %@ OR label == %@ OR label CONTAINS[c] %@",
                "not recognized", "try Face ID again", "Try Again", "documents remain locked"
            )).firstMatch.exists
        }
    }

    private func authenticationCancel(in app: XCUIApplication) -> XCUIElement? {
        guard hasAuthenticationUI(in: app) else { return nil }
        for surface in [springboard, app] {
            let alert = surface.alerts["com.apple.localauthentication.ax.authentication.alert"]
            guard alert.exists else { continue }
            let cancel = alert.buttons.matching(identifier: "com.apple.localauthentication.ax.authentication.button.cancel")
                .allElementsBoundByIndex.first { $0.exists && $0.isHittable }
            if let cancel { return cancel }
        }
        // Prefer the app's explicit LAContext cancel title on either system
        // surface. A generic Close could belong to a document/share sheet.
        for label in ["Keep Locked", "Cancel"] {
            for surface in [springboard, app] {
                let cancel = surface.buttons.matching(NSPredicate(format: "label == %@", label))
                    .allElementsBoundByIndex.first { $0.exists && $0.isHittable }
                if let cancel { return cancel }
            }
        }
        return nil
    }

    private func cancelAuthentication(_ app: XCUIApplication) async throws {
        var cancel: XCUIElement?
        try await require("Observed Face ID prompt has no reachable system cancellation control", app: app) {
            cancel = self.authenticationCancel(in: app)
            return cancel != nil
        }
        try check(hasAuthenticationUI(in: app), app: app,
                  "System authentication disappeared before cancellation; refusing to tap an unrelated control")
        try XCTUnwrap(cancel).tap()
        try await require("System cancellation did not return to the locked screen", app: app) {
            self.unlockButton(in: app).isHittable && !self.hasAuthenticationUI(in: app)
        }
        try assertPrivate(app, checkpoint: "System authentication cancelled")
    }

    private func assertUnlockReachable(_ app: XCUIApplication, orientation: String) async throws {
        try await requireLocked(app, checkpoint: "Maximum type \(orientation) after failed authentication")
        var activeScroll: XCUIElement?
        try await require("Maximum type \(orientation) has no reachable privacy scroll view", app: app) {
            activeScroll = app.scrollViews.matching(identifier: "privacy.lock.scroll")
                .allElementsBoundByIndex.first { $0.exists && $0.isHittable }
            return activeScroll != nil
        }
        let scroll = try XCTUnwrap(activeScroll)
        let title = scroll.staticTexts["TripDocket is locked"].firstMatch
        // Rotation can retain the preceding orientation's scroll offset. Go
        // back to the heading so the first image documents wrapped text too.
        for attempt in 0...8 {
            let viewport = scroll.frame.intersection(app.frame).insetBy(dx: 2, dy: 2)
            if title.exists && title.isHittable && !title.frame.isEmpty && viewport.contains(title.frame) { break }
            try check(attempt < 8, app: app, "Maximum type \(orientation) lock heading is clipped after bounded scrolling")
            scroll.swipeDown()
            try await Task.sleep(for: .milliseconds(100))
        }
        try await attachSettled(app, name: "Maximum type \(orientation) — wrapped lock text at top")

        let unlock = scroll.buttons["privacy.unlock"].firstMatch
        for attempt in 0...8 {
            let viewport = scroll.frame.intersection(app.frame).insetBy(dx: 2, dy: 2)
            if unlock.exists && unlock.isHittable && !unlock.frame.isEmpty && viewport.contains(unlock.frame) {
                try assertPrivate(app, checkpoint: "Maximum type \(orientation) after scrolling")
                try await attachSettled(app, name: "Maximum type \(orientation) — Unlock fully reachable after scrolling")
                return
            }
            try check(attempt < 8, app: app, "Maximum type \(orientation) clips or disables Unlock after bounded scrolling")
            if unlock.exists && unlock.frame.minY < viewport.minY {
                scroll.swipeDown()
            } else {
                scroll.swipeUp()
            }
            try await Task.sleep(for: .milliseconds(100))
        }
    }

    private func lockTitle(in app: XCUIApplication) -> XCUIElement { app.staticTexts["TripDocket is locked"].firstMatch }
    private func unlockButton(in app: XCUIApplication) -> XCUIElement {
        // The opaque shield and root lock screen expose the same identifier in
        // separate windows. Only the frontmost candidate can receive a tap.
        let candidates = app.buttons.matching(identifier: "privacy.unlock")
        return candidates.allElementsBoundByIndex.first { $0.exists && $0.isHittable }
            ?? candidates.firstMatch
    }
    private func documentRow(in app: XCUIApplication) -> XCUIElement {
        app.buttons.matching(NSPredicate(format: "label CONTAINS %@", "Weekend reservation")).firstMatch
    }
    private func hasShareSheet(in app: XCUIApplication) -> Bool {
        // Observed iOS 27 share actions are Cells in ActivityListView, not
        // Buttons. Require that actual sheet and a reachable file action, but
        // never tap an action or select a recipient.
        guard app.otherElements["ActivityListView"].exists else { return false }
        return app.cells.matching(NSPredicate(format: "label == %@ OR label == %@", "Save to Files", "Copy"))
            .allElementsBoundByIndex.contains { $0.exists && $0.isHittable }
    }

    private func reveal(_ target: XCUIElement, in app: XCUIApplication) async throws {
        for _ in 0..<5 {
            if target.exists && target.isHittable { return }
            app.swipeUp()
            try await Task.sleep(for: .milliseconds(100))
        }
        try check(target.exists && target.isHittable, app: app, "Synthetic fixture control is not reachable: \(target.identifier)")
    }

    private func require(_ message: String, app: XCUIApplication, condition: @MainActor () -> Bool) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: .seconds(15))
        repeat {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(100))
        } while clock.now < deadline
        try check(false, app: app, message)
    }

    private func check(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        guard condition else {
            attach(app, name: message)
            throw PrivacyTestError(message: message)
        }
    }

    private func attach(_ app: XCUIApplication, name: String) {
        let screenshot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCTAttachment(string: "APP\n\(app.debugDescription)\nSPRINGBOARD\n\(springboard.debugDescription)")
        hierarchy.name = "\(name) — accessibility hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }

    private func attachSettled(
        _ app: XCUIApplication, name: String, delay: Duration = .milliseconds(700)
    ) async throws {
        // Existence and hittability can become true before a system sheet or
        // Home zoom animation finishes. Yield rather than blocking XCTest.
        try await Task.sleep(for: delay)
        attach(app, name: name)
    }

    private struct PrivacyTestError: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
