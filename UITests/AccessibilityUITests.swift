import XCTest

/// Layout/reachability checks only. The launch flags install synthetic fixtures
/// and bypass authentication; passing this suite is NOT evidence of privacy,
/// biometric behavior, payment routing, or physical-device accessibility.
@MainActor
final class AccessibilityUITests: XCTestCase {
    private let backupWarningText = "The backup includes every original document, person and trip in readable, unencrypted form. Anyone with a copy can access them. Keep it in a trusted location. Previously shared copies cannot be revoked."

    func testMaximumTypeFreeCardAndProDismissal() async throws {
        let app = try launchFixture()
        defer { app.terminate() }

        let localLibraryNotice = app.staticTexts[
            "Documents stay in your local library. Export a backup before changing devices."
        ]
        try await scrollTo(localLibraryNotice, in: app, navigationTitle: "TripDocket",
                           description: "Local library and backup notice", preferWholeFrame: true)
        attach(app, name: "Maximum type — readable local library and backup notice")

        let freeCard = app.buttons.matching(NSPredicate(
            format: "label CONTAINS %@", "Free: 1 trip"
        )).firstMatch
        try await scrollTo(freeCard, in: app, navigationTitle: "TripDocket",
                           description: "Free plan card", preferWholeFrame: true,
                           fallbackAnchor: localLibraryNotice)
        attach(app, name: "Maximum type — reachable Free card")
        freeCard.tap()

        let pro = app.navigationBars["TripDocket Pro"]
        try require(pro.waitForExistence(timeout: 5), app: app, "Pro sheet did not open from the Free card")
        let footer = app.staticTexts.matching(NSPredicate(
            format: "label BEGINSWITH %@", "Free includes one trip"
        )).firstMatch
        // The long footer may be taller than the viewport at maximum type.
        // Require a meaningful visible portion rather than an impossible full fit.
        try await scrollTo(footer, in: app, navigationTitle: "TripDocket Pro",
                           description: "Pro data-access footer", preferWholeFrame: false)
        attach(app, name: "Maximum type — Pro footer after scrolling")

        // Dismissal must work regardless of price/product availability. Never
        // press purchase or Restore purchases in this layout-only suite.
        let done = pro.buttons["Done"]
        try require(done.exists && done.isHittable, app: app, "Pro Done is not reachable after scrolling")
        done.tap()
        try require(pro.waitForNonExistence(timeout: 5), app: app, "Pro Done did not dismiss the sheet")
        try require(app.navigationBars["TripDocket"].exists, app: app, "Trips navigation did not return")
        attach(app, name: "Maximum type — returned from Pro")
    }

    func testMaximumTypeReadinessAndImportCancellation() async throws {
        let app = try launchFixture()
        defer { app.terminate() }

        let trip = app.staticTexts["Coast weekend"]
        try await scrollTo(trip, in: app, navigationTitle: "TripDocket",
                           description: "Synthetic trip", preferWholeFrame: true)
        trip.tap()
        let check = app.buttons["Check original"]
        try await scrollTo(check, in: app, navigationTitle: "Coast weekend",
                           description: "Original verification action", preferWholeFrame: true)
        check.tap()

        let result = app.staticTexts["1 of 1 original verified"]
        try require(result.waitForExistence(timeout: 5), app: app, "Original verification result did not appear")
        try await scrollTo(result, in: app, navigationTitle: "Coast weekend",
                           description: "Original verification result", preferWholeFrame: true)
        attach(app, name: "Maximum type — verification result")

        let add = app.navigationBars["Coast weekend"].buttons["Add document"]
        try require(add.exists && add.isHittable, app: app, "Add document toolbar action is not reachable")
        add.tap()
        let importBar = app.navigationBars["Add document"]
        try require(importBar.waitForExistence(timeout: 5), app: app, "Import sheet did not open")
        let files = app.buttons["Import from Files"]
        try await scrollTo(files, in: app, navigationTitle: "Add document",
                           description: "Import from Files action", preferWholeFrame: true)
        try require(importBar.buttons["Save"].exists && !importBar.buttons["Save"].isEnabled,
                    app: app, "Import Save should be disabled without a selected original")
        attach(app, name: "Maximum type — import entry")
        files.tap()
        try await cancelFilePicker(in: app, presentingAction: files, name: "Import Files picker")

        let cancelImport = importBar.buttons["Cancel"]
        try require(cancelImport.exists && cancelImport.isHittable,
                    app: app, "Import sheet Cancel is not reachable after closing Files")
        cancelImport.tap()
        try require(importBar.waitForNonExistence(timeout: 5), app: app, "Import sheet did not close")
        try require(app.navigationBars["Coast weekend"].exists,
                    app: app, "Trip navigation did not return after cancelling import")
        attach(app, name: "Maximum type — cancelled import returned to trip")
    }

    func testMaximumTypeCompleteBackupWarningAndCancellation() async throws {
        executionTimeAllowance = 180
        let app = try launchFixture()
        defer { app.terminate() }
        try selectTab("Settings", in: app)

        let backup = app.buttons["Export full backup"]
        try await scrollTo(backup, in: app, navigationTitle: "Settings",
                           description: "Full backup action", preferWholeFrame: true)
        backup.tap()
        let choose = app.buttons["Export…"]
        try require(choose.waitForExistence(timeout: 5) && choose.isHittable,
                    app: app, "Backup warning action is not reachable")
        try verifyCompleteBackupExportAction(in: app, checkpoint: "before reading")
        try await verifyCompleteBackupWarning(in: app)
        try verifyCompleteBackupExportAction(in: app, checkpoint: "after reading")
        try dismissConfirmation(in: app)
        try require(choose.waitForNonExistence(timeout: 5), app: app, "Backup warning did not dismiss")
        try require(app.sheets["Export an unencrypted backup?"].waitForNonExistence(timeout: 5),
                    app: app, "Backup warning remained after cancellation")
        try require(backup.exists && backup.isHittable,
                    app: app, "Settings backup action did not return after cancelling the warning")
        attach(app, name: "Maximum type — complete backup warning cancelled; no export")
    }

    func testMaximumTypeRestoreEntryAndTabNavigation() async throws {
        let app = try launchFixture()
        defer { app.terminate() }
        try selectTab("Settings", in: app)

        let restore = app.buttons["Restore from backup"]
        try await scrollTo(restore, in: app, navigationTitle: "Settings",
                           description: "Restore from backup action", preferWholeFrame: true)
        restore.tap()
        try await cancelFilePicker(in: app, presentingAction: restore, name: "Restore Files picker")
        try require(app.navigationBars["Settings"].exists, app: app, "Settings did not return after cancelling restore")

        try selectTab("People", in: app)
        try require(app.navigationBars["People"].waitForExistence(timeout: 5), app: app, "People tab did not open")
        attach(app, name: "Maximum type — People tab")
        try selectTab("Trips", in: app)
        try require(app.navigationBars["TripDocket"].waitForExistence(timeout: 5), app: app, "Trips tab did not return")
        attach(app, name: "Maximum type — Trips tab")
    }

    private func launchFixture() throws -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.launchArguments = [
            "--ui-testing-unlocked", "--ui-testing-reset", "--demo",
            "-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"
        ]
        app.launch()
        try require(app.navigationBars["TripDocket"].waitForExistence(timeout: 15),
                    app: app, "Synthetic fixture did not open its Trips navigation")
        return app
    }

    private func selectTab(_ title: String, in app: XCUIApplication) throws {
        // iPad's adaptive tabs can be exposed as buttons without a tabBars node.
        let tab = app.buttons[title].firstMatch
        try require(tab.waitForExistence(timeout: 5) && tab.isHittable,
                    app: app, "\(title) tab is not reachable")
        tab.tap()
    }

    private func scrollTo(
        _ target: XCUIElement, in app: XCUIApplication, navigationTitle: String,
        description: String, preferWholeFrame: Bool, fallbackAnchor: XCUIElement? = nil
    ) async throws {
        var previousFrame: CGRect?
        var usedFallback = false
        var lastDragWasFallback = false
        for attempt in 0...10 {
            if target.exists && target.isHittable && visiblePortion(
                of: target, in: app, navigationTitle: navigationTitle,
                preferWholeFrame: preferWholeFrame
            ) { return }
            guard attempt < 10 else { break }
            guard let container = activeScrollContainer(in: app, navigationTitle: navigationTitle) else {
                attach(app, name: "No active scroll container — \(description)")
                throw LayoutFailure(message: "No hittable app scrollView/collectionView for \(description)")
            }
            // Keep both endpoints inside the visible List/Form. Full swipes
            // overshot partly visible rows and oscillated across the viewport.
            let viewport = visibleViewport(in: app, navigationTitle: navigationTitle)
                .intersection(container.frame).insetBy(dx: 12, dy: 12)
            guard !viewport.isNull, viewport.width > 24, viewport.height > 80 else {
                attach(app, name: "No safe drag viewport — \(description)")
                throw LayoutFailure(message: "No safe scroll viewport for \(description)")
            }
            let frame = target.exists ? target.frame : .null
            let hasFrame = !frame.isNull && !frame.isEmpty
                && frame.minY.isFinite && frame.maxY.isFinite
            let unchanged = hasFrame && (previousFrame.map {
                abs(frame.minX - $0.minX) <= 1 && abs(frame.minY - $0.minY) <= 1
                    && abs(frame.width - $0.width) <= 1 && abs(frame.height - $0.height) <= 1
            } ?? false)
            if lastDragWasFallback && (!hasFrame || unchanged) {
                attach(app, name: "No movement after anchored drag — \(description)")
                throw LayoutFailure(message: "\(description) did not move after its single anchored fallback")
            }
            lastDragWasFallback = false
            let isNear = hasFrame && frame.intersects(viewport)
            let maximumStep = isNear ? min(160, viewport.height * 0.25)
                : min(320, viewport.height * 0.45)
            var correction = -maximumStep // Search downward for an unloaded row.
            if hasFrame {
                if frame.minY < viewport.minY {
                    correction = viewport.minY - frame.minY + 12
                } else if frame.maxY > viewport.maxY {
                    correction = viewport.maxY - frame.maxY - 12
                } else {
                    correction = viewport.midY - frame.midY
                }
            }
            let distance = min(maximumStep, max(24, abs(correction)))
            var translation = correction > 0 ? distance : -distance
            let origin = container.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            var start = origin.withOffset(CGVector(
                dx: viewport.midX - container.frame.minX,
                dy: viewport.midY - container.frame.minY
            ))
            if let fallbackAnchor, unchanged, !usedFallback {
                // The iPad wrapper can miss a pan begun on the interactive trip
                // row. Retry once from the already verified inert notice.
                guard fallbackAnchor.exists, fallbackAnchor.isHittable,
                      visiblePortion(of: fallbackAnchor, in: app,
                                     navigationTitle: navigationTitle, preferWholeFrame: true) else {
                    attach(app, name: "Unavailable fallback anchor — \(description)")
                    throw LayoutFailure(message: "\(description) has no visible, hittable fallback anchor")
                }
                let anchorFrame = fallbackAnchor.frame
                let anchorPoint = CGPoint(x: anchorFrame.midX, y: anchorFrame.midY)
                let availableDistance = (correction > 0
                    ? viewport.maxY - anchorPoint.y : anchorPoint.y - viewport.minY) - 1
                guard viewport.contains(anchorPoint), availableDistance >= 120 else {
                    attach(app, name: "No safe anchored drag — \(description)")
                    throw LayoutFailure(message: "\(description) has no safe 120-point anchored drag")
                }
                let fallbackDistance = min(160, availableDistance)
                translation = correction > 0 ? fallbackDistance : -fallbackDistance
                start = fallbackAnchor.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
                usedFallback = true
                lastDragWasFallback = true
                print("LAYOUT_SCROLL_FALLBACK \(description): anchor=\(anchorFrame), dy=\(translation)")
            }
            let end = start.withOffset(CGVector(dx: 0, dy: translation))
            print("LAYOUT_SCROLL \(description): target=\(frame), viewport=\(viewport), dy=\(translation)")
            previousFrame = hasFrame ? frame : nil
            start.press(forDuration: 0.05, thenDragTo: end,
                        withVelocity: .slow, thenHoldForDuration: 0.2)
            try await Task.sleep(for: .milliseconds(100))
        }
        attach(app, name: "Unreachable at maximum type — \(description)")
        throw LayoutFailure(message: "\(description) did not become safely hittable after bounded scrolling")
    }

    private func activeScrollContainer(in app: XCUIApplication, navigationTitle: String) -> XCUIElement? {
        let navigation = app.navigationBars[navigationTitle]
        let navigationFrame = navigation.exists ? navigation.frame : app.frame
        let viewport = visibleViewport(in: app, navigationTitle: navigationTitle)
        let candidates = app.scrollViews.allElementsBoundByIndex + app.collectionViews.allElementsBoundByIndex
        return candidates.filter { element in
            guard element.exists, !element.frame.isEmpty else { return false }
            let frame = element.frame
            // A modal's navigation width excludes the larger presenting iPad List.
            guard frame.width <= navigationFrame.width + 32,
                  abs(frame.midX - navigationFrame.midX) < max(32, navigationFrame.width / 4),
                  frame.intersects(viewport) else { return false }
            if element.isHittable { return true }
            // On iPad the visible List wrapper can report non-hittable while
            // its actual rows are usable. Require visible descendant evidence
            // before using that wrapper's geometry for the bounded drag.
            let descendants = element.buttons.allElementsBoundByIndex
                + element.staticTexts.allElementsBoundByIndex
            return descendants.contains { child in
                guard child.exists, child.isHittable, !child.frame.isEmpty else { return false }
                let visible = child.frame.intersection(frame).intersection(viewport)
                return !visible.isNull && visible.width >= min(44, child.frame.width)
                    && visible.height >= min(44, child.frame.height)
            }
        }.max { left, right in
            left.frame.width * left.frame.height < right.frame.width * right.frame.height
        }
    }

    private func visibleViewport(in app: XCUIApplication, navigationTitle: String?) -> CGRect {
        var viewport = app.windows.firstMatch.exists ? app.windows.firstMatch.frame : app.frame
        viewport = viewport.insetBy(dx: 2, dy: 2)
        if let navigationTitle {
            let navigation = app.navigationBars[navigationTitle]
            if navigation.exists, navigation.isHittable {
                let top = max(viewport.minY, navigation.frame.maxY)
                viewport = CGRect(x: max(viewport.minX, navigation.frame.minX), y: top,
                                  width: min(viewport.width, navigation.frame.width),
                                  height: max(0, viewport.maxY - top))
            }
        }
        // Floating bottom tabs can overlap a List row that still reports exists.
        // Top-mounted iPad tabs should not remove the bottom half of the viewport.
        for bar in app.tabBars.allElementsBoundByIndex where bar.exists && bar.isHittable {
            if bar.frame.minY > viewport.midY {
                viewport.size.height = max(0, min(viewport.maxY, bar.frame.minY) - viewport.minY)
            }
        }
        return viewport
    }

    private func visiblePortion(
        of element: XCUIElement, in app: XCUIApplication, navigationTitle: String?,
        preferWholeFrame: Bool = false
    ) -> Bool {
        let viewport = visibleViewport(in: app, navigationTitle: navigationTitle)
        let frame = element.frame
        guard !frame.isEmpty, !viewport.isEmpty else { return false }
        if preferWholeFrame, frame.height <= viewport.height, frame.width <= viewport.width {
            return viewport.insetBy(dx: -1, dy: -1).contains(frame)
        }
        let intersection = frame.intersection(viewport)
        return !intersection.isNull
            && intersection.width >= min(44, frame.width)
            && intersection.height >= min(44, frame.height)
    }

    private func verifyCompleteBackupExportAction(in app: XCUIApplication, checkpoint: String) throws {
        let dialog = app.sheets["Export an unencrypted backup?"].firstMatch
        try require(dialog.exists, app: app, "Backup warning is missing \(checkpoint)")
        let exportPredicate = NSPredicate(format: "label == %@", "Export…")
        let warningPredicate = NSPredicate(format: "label == %@", backupWarningText)
        let panes = dialog.scrollViews
        var candidates: [XCUIElement] = []
        for index in 0..<panes.count {
            let pane = panes.element(boundBy: index)
            if pane.buttons.matching(exportPredicate).count == 1
                && pane.staticTexts.matching(warningPredicate).count == 0 {
                candidates.append(pane)
            }
        }
        try require(candidates.count == 1, app: app,
                    "Backup export action pane is missing or ambiguous \(checkpoint)")
        let actions = candidates[0]
        let button = actions.buttons.matching(exportPredicate).firstMatch
        try require(button.exists && button.isEnabled && button.isHittable,
                    app: app, "Backup export action is unavailable \(checkpoint)")
        let window = app.windows.firstMatch.exists ? app.windows.firstMatch.frame : app.frame
        let viewport = actions.frame.intersection(dialog.frame).intersection(window)
        let frame = button.frame
        try require(!viewport.isNull && !viewport.isEmpty && !frame.isEmpty
                    && frame.minX.isFinite && frame.minY.isFinite
                    && frame.width.isFinite && frame.height.isFinite,
                    app: app, "Backup export action has invalid visible bounds \(checkpoint)")
        print("WARNING_ACTION \(checkpoint) button=\(frame) viewport=\(viewport) fullyContained=\(viewport.contains(frame))")
        // Hittability alone passed with 46 points of the old button clipped on
        // iPad. The whole button must fit in its own action pane and the window.
        try require(viewport.contains(frame), app: app,
                    "Backup export action is partly clipped \(checkpoint)")
        attach(app, name: "Maximum type — entire backup export action \(checkpoint); no export")
    }

    private func verifyCompleteBackupWarning(in app: XCUIApplication) async throws {
        let dialog = app.sheets["Export an unencrypted backup?"].firstMatch
        let text = backupWarningText
        try require(dialog.waitForExistence(timeout: 5), app: app, "Native backup warning sheet is missing")

        // The native dialog has separate text and action scroll views. Only
        // the pane containing the complete warning can establish text coverage.
        // Avoid the identifier-subscript path for this long label: the observed
        // XCTest runtime aborted while building its type/identifier predicate.
        // Exact label predicates retain the same body/action distinction.
        let warningPredicate = NSPredicate(format: "label == %@", text)
        let exportPredicate = NSPredicate(format: "label == %@", "Export…")
        let panes = dialog.scrollViews
        var candidates: [XCUIElement] = []
        for index in 0..<panes.count {
            let pane = panes.element(boundBy: index)
            let warnings = pane.staticTexts.matching(warningPredicate)
            let exportActions = pane.buttons.matching(exportPredicate)
            if warnings.count == 1 && exportActions.count == 0 {
                candidates.append(pane)
            }
        }
        try require(candidates.count == 1, app: app, "Backup warning text pane is missing or ambiguous")
        let body = candidates[0]
        let warning = body.staticTexts.matching(warningPredicate).firstMatch
        var originalSize: CGSize?
        var slices: [ClosedRange<CGFloat>] = []

        for attempt in 0...18 {
            try require(dialog.exists && body.exists && warning.exists,
                        app: app, "Backup warning disappeared while reading")
            let window = app.windows.firstMatch.exists ? app.windows.firstMatch.frame : app.frame
            let viewport = body.frame.intersection(dialog.frame).intersection(window).insetBy(dx: 2, dy: 2)
            let frame = warning.frame
            try require(!viewport.isNull && viewport.width > 44 && viewport.height > 80
                        && !frame.isEmpty && frame.minX.isFinite && frame.minY.isFinite
                        && frame.width.isFinite && frame.height.isFinite,
                        app: app, "Backup warning has no valid text viewport")
            try require(frame.minX >= viewport.minX - 1 && frame.maxX <= viewport.maxX + 1,
                        app: app, "Backup warning text is clipped horizontally")
            if let originalSize {
                try require(abs(frame.width - originalSize.width) <= 1
                            && abs(frame.height - originalSize.height) <= 1,
                            app: app, "Backup warning reflowed; prior text slices cannot prove coverage")
            } else {
                originalSize = frame.size
            }

            let visible = frame.intersection(viewport)
            if !visible.isNull && !visible.isEmpty {
                let lower = max(0, visible.minY - frame.minY)
                let upper = min(frame.height, visible.maxY - frame.minY)
                slices.append(lower...upper)
            }
            // Merge all captured label-relative intervals. Seeing only the
            // first and final lines must not pass if a middle region is missing.
            var coveredThrough: CGFloat = 0
            for slice in slices.sorted(by: { $0.lowerBound < $1.lowerBound }) {
                if slice.lowerBound > coveredThrough + 1 { break }
                coveredThrough = max(coveredThrough, slice.upperBound)
            }
            print("WARNING_COVERAGE attempt=\(attempt) text=\(frame) viewport=\(viewport) slices=\(slices) contiguous=\(coveredThrough)/\(frame.height)")
            // Keep every overlapping portion for independent pixel inspection;
            // geometric coverage alone is not a claim about VoiceOver behavior.
            attach(app, name: "Maximum type — backup warning text slice \(attempt); no export")
            if coveredThrough >= frame.height - 1 { return }
            guard attempt < 18 else { break }

            // Bring the first uncovered region toward the top, retaining an
            // overlap. Both endpoints stay in the text pane, above the actions.
            let overlap = min(48, viewport.height * 0.25)
            let correction = viewport.minY + overlap - (frame.minY + coveredThrough)
            let distance = min(160, min(viewport.height * 0.4, max(24, abs(correction))))
            let translation = correction > 0 ? distance : -distance
            let start = body.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
                .withOffset(CGVector(dx: viewport.midX - body.frame.minX,
                                     dy: viewport.midY - body.frame.minY))
            let end = start.withOffset(CGVector(dx: 0, dy: translation))
            print("WARNING_DRAG attempt=\(attempt) dy=\(translation)")
            start.press(forDuration: 0.05, thenDragTo: end,
                        withVelocity: .slow, thenHoldForDuration: 0.2)
            try await Task.sleep(for: .milliseconds(150))
        }
        throw LayoutFailure(message: "Complete backup warning text was not reachable after bounded in-pane scrolling")
    }

    private func cancelFilePicker(
        in app: XCUIApplication, presentingAction: XCUIElement, name: String
    ) async throws {
        // Observed in the real Files picker hierarchy. The presenting SwiftUI
        // action can still report hittable while Files is on top of it.
        let filesNavigation = app.navigationBars["FullDocumentManagerViewControllerNavigationBar"].firstMatch
        let sidebarNavigation = app.navigationBars["DOCSidebarView"].firstMatch
        // A captured cold presentation took almost eight seconds to expose its
        // navigation bar. Give that presentation its own bounded wait before
        // measuring Cancel readiness; a one-point Other labelled Cancel is not
        // evidence of a usable button and must not be tapped as a fallback.
        try require(filesNavigation.waitForExistence(timeout: 15),
                    app: app, "\(name) did not present its Files navigation")
        var cancel: XCUIElement?
        let deadline = Date().addingTimeInterval(8)
        repeat {
            if filesNavigation.exists {
                // iPhone exposes Cancel in the main navigation; the observed
                // iPad split picker places it in the Files sidebar navigation.
                cancel = [filesNavigation.buttons["Cancel"].firstMatch,
                          sidebarNavigation.buttons["Cancel"].firstMatch]
                    .first { $0.exists && $0.isHittable }
            }
            if cancel != nil { break }
            try await Task.sleep(for: .milliseconds(100))
        } while Date() < deadline
        guard let cancel else {
            attach(app, name: "Missing Files Cancel — \(name)")
            throw LayoutFailure(message: "\(name) did not expose a hittable Cancel in either Files navigation")
        }
        try require(filesNavigation.exists && cancel.isHittable,
                    app: app, "\(name) disappeared before its Cancel could be tapped")
        attach(app, name: "Maximum type — \(name)")
        cancel.tap()
        try require(filesNavigation.waitForNonExistence(timeout: 5),
                    app: app, "\(name) navigation remained after cancellation")
        let returnDeadline = Date().addingTimeInterval(5)
        while !presentingAction.isHittable && Date() < returnDeadline {
            try await Task.sleep(for: .milliseconds(100))
        }
        try require(presentingAction.exists && presentingAction.isHittable,
                    app: app, "\(name) did not return to its presenting action")
    }

    private func dismissConfirmation(in app: XCUIApplication) throws {
        if let cancel = app.buttons.matching(identifier: "Cancel").allElementsBoundByIndex
            .last(where: { $0.exists && $0.isHittable }) {
            cancel.tap()
        } else {
            // iPad confirmation popovers can omit a visible Cancel action.
            let outside = app.otherElements["PopoverDismissRegion"]
            try require(outside.waitForExistence(timeout: 3) && outside.isHittable,
                        app: app, "Confirmation has no reachable Cancel or popover dismiss region")
            outside.tap()
        }
    }

    private func require(_ condition: Bool, app: XCUIApplication, _ message: String) throws {
        guard condition else {
            attach(app, name: message)
            throw LayoutFailure(message: message)
        }
    }

    private func attach(_ app: XCUIApplication, name: String) {
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "\(name) — accessibility hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }

    private struct LayoutFailure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
