import Foundation
import XCTest

/// Run this class on both an iPhone and an iPad destination. Language and content
/// size overrides belong only to each launched app process; no system settings
/// are changed. The ordinary-launch test never bypasses or completes auth.
/// The two fixture tests use synthetic data and bypass auth for UI checks only.
/// No test taps purchase, Restore, Files, or the confirmed export action.
/// Screenshots require visual review; sampled AX checks do not prove absence of
/// every transient pixel, physical-device privacy, or VoiceOver behavior.
@MainActor
final class LocalizationUITests: XCTestCase {
    private let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
    private let backupWarningText = "Резервная копия содержит все оригиналы документов, сведения о путешественниках и поездках в открытом, незашифрованном виде. Любой, у кого есть копия, может получить к ним доступ. Храните её в надёжном месте. Ранее переданные копии нельзя отозвать."
    private let backupWarningTitle = "Экспортировать копию без шифрования?"
    private let exportActionTitle = "Экспорт"
    private let cancelTitle = "Отмена"

    func testOrdinaryLaunchUsesFirstSupportedLanguageAndRemainsLocked() async throws {
        continueAfterFailure = false
        executionTimeAllowance = 180
        let cases: [(languages: String, russian: Bool)] = [
            ("(ru-RU,en-US)", true),
            ("(en-GB,ru-RU)", false),
            ("(fr-FR,ru-RU,en-US)", true),
            ("(fr-FR)", false)
        ]
        for item in cases {
            try await verifyOrdinaryLockedLaunch(languages: item.languages, russian: item.russian)
        }
    }

    func testRussianDemoReadinessImportCancellationAndProDismissal() async throws {
        executionTimeAllowance = 120
        let app = try launchFixture()
        defer { app.terminate() }

        for title in ["Поездки", "Люди", "Настройки"] {
            try require(app.buttons[title].firstMatch.exists, app: app,
                        "Russian tab label is missing: \(title)")
        }
        let trip = app.staticTexts["Coast weekend"]
        try await scrollTo(trip, in: app, navigationTitle: "TripDocket",
                           description: "Untranslated synthetic trip title", preferWholeFrame: true)
        attach(app, name: "ru-US — synthetic trip and Russian tabs")
        trip.tap()

        let check = app.buttons["Проверить оригинал"]
        try await scrollTo(check, in: app, navigationTitle: "Coast weekend",
                           description: "Russian original verification action", preferWholeFrame: true)
        try require(check.isEnabled, app: app, "Original verification action is disabled")
        check.tap()
        let result = app.staticTexts["Проверено 1 из 1 оригинала"]
        try require(result.waitForExistence(timeout: 5), app: app,
                    "Russian readiness summary is missing or has incorrect plural wording")
        try await scrollTo(result, in: app, navigationTitle: "Coast weekend",
                           description: "Russian verification result", preferWholeFrame: true)
        attach(app, name: "ru-US — original verified with Russian plural")

        let add = app.navigationBars["Coast weekend"].buttons["Добавить документ"]
        try require(add.exists && add.isHittable, app: app, "Russian Add document is not reachable")
        add.tap()
        let importBar = app.navigationBars["Документ"]
        try require(importBar.waitForExistence(timeout: 5), app: app, "Russian import sheet did not open")
        let files = app.buttons["Импортировать из «Файлов»"]
        try await scrollTo(files, in: app, navigationTitle: "Документ",
                           description: "Russian Files entry; do not open", preferWholeFrame: true)
        let save = importBar.buttons["Сохранить"]
        try require(save.exists && !save.isEnabled, app: app,
                    "Russian import Save must exist and be disabled without an original")
        let cancel = importBar.buttons[cancelTitle]
        try require(cancel.exists && cancel.isHittable, app: app, "Russian import Cancel is not reachable")
        attach(app, name: "ru-US — import entry, disabled Save and Cancel; Files unopened")
        cancel.tap()
        try require(importBar.waitForNonExistence(timeout: 5), app: app, "Import Cancel did not dismiss the sheet")
        try require(app.navigationBars["Coast weekend"].exists, app: app,
                    "Synthetic trip did not return after import cancellation")

        try selectTab("Настройки", in: app)
        try require(app.navigationBars["Настройки"].waitForExistence(timeout: 5), app: app,
                    "Russian Settings navigation did not open")
        // Works with either existing entitlement state. No StoreKit state is
        // changed, and neither the buy nor the restore control is selected.
        let proCard = app.buttons.matching(NSPredicate(
            format: "label CONTAINS %@ OR label BEGINSWITH %@",
            "Место для каждой поездки", "TripDocket Pro"
        )).firstMatch
        try await scrollTo(proCard, in: app, navigationTitle: "Настройки",
                           description: "Settings Pro information card", preferWholeFrame: true)
        attach(app, name: "ru-US — Settings before opening Pro information")
        proCard.tap()
        let pro = app.navigationBars["TripDocket Pro"]
        try require(pro.waitForExistence(timeout: 5), app: app, "Pro information sheet did not open")
        let intro = app.staticTexts["Разовая покупка для ваших поездок и тех, с кем вы путешествуете."]
        try require(intro.waitForExistence(timeout: 5), app: app, "Pro introduction is not in Russian")
        let done = pro.buttons["Готово"]
        try require(done.exists && done.isHittable, app: app, "Russian Pro Done is not reachable")
        attach(app, name: "ru-US — Russian Pro information and Done; no transaction")
        done.tap()
        try require(pro.waitForNonExistence(timeout: 5), app: app, "Russian Pro Done did not dismiss the sheet")
        try require(app.navigationBars["Настройки"].exists, app: app, "Settings did not return from Pro")
        attach(app, name: "ru-US — returned to Settings after Pro Done")
    }

    func testRussianMaximumTypeCompleteBackupWarningAndCancellation() async throws {
        executionTimeAllowance = 120
        let app = try launchFixture(maximumType: true)
        defer { app.terminate() }
        try selectTab("Настройки", in: app)
        let backup = app.buttons["Экспортировать полную резервную копию"]
        try await scrollTo(backup, in: app, navigationTitle: "Настройки",
                           description: "Russian full backup action", preferWholeFrame: true)
        backup.tap()
        let choose = app.buttons[exportActionTitle]
        try require(choose.waitForExistence(timeout: 5) && choose.isHittable,
                    app: app, "Russian backup warning action is not reachable")
        try verifyCompleteBackupExportAction(in: app, checkpoint: "before reading")
        try await verifyCompleteBackupWarning(in: app)
        try verifyCompleteBackupExportAction(in: app, checkpoint: "after reading")
        try dismissConfirmation(in: app)
        try require(choose.waitForNonExistence(timeout: 5), app: app, "Russian backup warning did not dismiss")
        try require(app.sheets[backupWarningTitle].waitForNonExistence(timeout: 5),
                    app: app, "Russian backup warning remained after cancellation")
        try require(backup.exists && backup.isHittable,
                    app: app, "Settings backup action did not return after cancellation")
        attach(app, name: "ru-US maximum type — complete warning cancelled; no export")
    }

    private func verifyOrdinaryLockedLaunch(languages: String, russian: Bool) async throws {
        let app = XCUIApplication()
        app.terminate()
        // Replace, rather than append to, test-plan launch arguments so that
        // its default --ui-testing-unlocked cannot enter these launches.
        app.launchArguments = ["-AppleLanguages", languages, "-AppleLocale", "en_US"]
        app.launchEnvironment = [:]
        app.launch()
        defer { app.terminate() }
        let expectedTitle = russian ? "TripDocket закрыт" : "TripDocket is locked"
        let otherTitle = russian ? "TripDocket is locked" : "TripDocket закрыт"
        let explanation = russian ? "Ваши документы для поездок скрыты, пока вы не откроете к ним доступ." : "Your travel documents stay private until you unlock."
        let expectedUnlock = russian ? "Открыть доступ" : "Unlock"
        let title = app.staticTexts[expectedTitle].firstMatch
        try require(title.waitForExistence(timeout: 15), app: app,
                    "Ordinary launch \(languages) did not show expected lock title: \(expectedTitle)")
        // A native auth prompt may be present. Never accept it or request a
        // biometric event. Capture Springboard with the app for that case.
        for sample in 0..<5 {
            try require(title.exists, app: app, "Ordinary launch left its lock screen: \(languages), sample \(sample)")
            try require(!app.staticTexts[otherTitle].firstMatch.exists, app: app,
                        "Ordinary launch mixed Russian and English lock titles: \(languages)")
            try require(app.staticTexts[explanation].firstMatch.exists, app: app,
                        "Lock explanation does not match first supported language: \(languages)")
            let unlock = app.buttons["privacy.unlock"].firstMatch
            if unlock.exists {
                try require(unlock.label == expectedUnlock, app: app,
                            "Unlock action does not match first supported language: \(languages)")
            }
            try assertNoUnderlyingContent(app, checkpoint: "\(languages), sample \(sample)")
            if sample == 0 || sample == 4 {
                attach(app, name: "Ordinary \(languages), en_US — locked sample \(sample)")
            }
            if sample < 4 { try await Task.sleep(for: .milliseconds(250)) }
        }
    }

    private func assertNoUnderlyingContent(_ app: XCUIApplication, checkpoint: String) throws {
        let fixtureValues = ["Coast weekend", "Weekend reservation", "Alex Example", "ABC-000",
                             "SYNTHETIC DEMO", "sample-reservation.pdf", "PRIVACY DRAFT"]
        var predicates = fixtureValues.map { value in
            NSPredicate(format: "label CONTAINS[c] %@ OR value CONTAINS[c] %@", value, value)
        }
        // Check both supported languages, even if there is no synthetic fixture
        // in ordinary app storage. Content navigation itself must stay hidden.
        predicates.append(NSPredicate(format: "label IN %@", [
            "Trips", "People", "Settings", "Поездки", "Люди", "Настройки",
            "Document title", "Original document", "Export trip packet", "Create trip", "Add document",
            "Название документа", "Оригинал документа", "Экспортировать документы поездки", "Создать поездку", "Добавить документ"
        ]))
        let exposed = app.descendants(matching: .any).matching(
            NSCompoundPredicate(orPredicateWithSubpredicates: predicates)
        ).firstMatch
        try require(!exposed.exists, app: app,
                    "Underlying document data or navigation leaked into locked AX tree: \(checkpoint)")
        try require(app.navigationBars.count == 0 && app.tabBars.count == 0, app: app,
                    "Underlying navigation or tabs remain while locked: \(checkpoint)")
    }

    private func launchFixture(maximumType: Bool = false) throws -> XCUIApplication {
        continueAfterFailure = false
        let app = XCUIApplication()
        app.terminate()
        app.launchArguments = [
            "--ui-testing-unlocked", "--ui-testing-reset", "--demo",
            "-AppleLanguages", "(ru-RU,en-US)", "-AppleLocale", "en_US"
        ]
        if maximumType {
            app.launchArguments += ["-UIPreferredContentSizeCategoryName", "UICTContentSizeCategoryAccessibilityXXXL"]
        }
        app.launchEnvironment = [:]
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
                throw LocalizationFailure(message: "No hittable app scrollView/collectionView for \(description)")
            }
            // Keep both endpoints inside the visible List/Form. Full swipes
            // overshot partly visible rows and oscillated across the viewport.
            let viewport = visibleViewport(in: app, navigationTitle: navigationTitle)
                .intersection(container.frame).insetBy(dx: 12, dy: 12)
            guard !viewport.isNull, viewport.width > 24, viewport.height > 80 else {
                attach(app, name: "No safe drag viewport — \(description)")
                throw LocalizationFailure(message: "No safe scroll viewport for \(description)")
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
                throw LocalizationFailure(message: "\(description) did not move after its single anchored fallback")
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
                    throw LocalizationFailure(message: "\(description) has no visible, hittable fallback anchor")
                }
                let anchorFrame = fallbackAnchor.frame
                let anchorPoint = CGPoint(x: anchorFrame.midX, y: anchorFrame.midY)
                let availableDistance = (correction > 0
                    ? viewport.maxY - anchorPoint.y : anchorPoint.y - viewport.minY) - 1
                guard viewport.contains(anchorPoint), availableDistance >= 120 else {
                    attach(app, name: "No safe anchored drag — \(description)")
                    throw LocalizationFailure(message: "\(description) has no safe 120-point anchored drag")
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
        throw LocalizationFailure(message: "\(description) did not become safely hittable after bounded scrolling")
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
        let dialog = app.sheets[backupWarningTitle].firstMatch
        try require(dialog.exists, app: app, "Backup warning is missing \(checkpoint)")
        let exportPredicate = NSPredicate(format: "label == %@", exportActionTitle)
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
        let dialog = app.sheets[backupWarningTitle].firstMatch
        let text = backupWarningText
        try require(dialog.waitForExistence(timeout: 5), app: app, "Native backup warning sheet is missing")

        // The native dialog has separate text and action scroll views. Only
        // the pane containing the complete warning can establish text coverage.
        // Avoid the identifier-subscript path for this long label: the observed
        // XCTest runtime aborted while building its type/identifier predicate.
        // Exact label predicates retain the same body/action distinction.
        let warningPredicate = NSPredicate(format: "label == %@", text)
        let exportPredicate = NSPredicate(format: "label == %@", exportActionTitle)
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
        throw LocalizationFailure(message: "Complete backup warning text was not reachable after bounded in-pane scrolling")
    }

    private func dismissConfirmation(in app: XCUIApplication) throws {
        if let cancel = app.buttons.matching(identifier: cancelTitle).allElementsBoundByIndex
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
            throw LocalizationFailure(message: message)
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

    private struct LocalizationFailure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
