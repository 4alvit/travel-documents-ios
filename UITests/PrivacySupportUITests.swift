import XCTest

/// Feature navigation/layout only. DEBUG authentication bypass is intentional.
/// This suite does not establish real authentication, denied-network behavior,
/// VoiceOver speech order, purchase behavior, or external-browser behavior.
@MainActor
final class PrivacySupportUITests: XCTestCase {
    func testEnglishFreeGuidanceAndCancelledLinks() async throws {
        try await verifyGuidance(russian: false, maximumType: false)
    }

    func testRussianMaximumTypeFreeGuidanceAndCancelledLinks() async throws {
        try await verifyGuidance(russian: true, maximumType: true)
    }

    private struct Copy {
        let russian: Bool
        var title: String { russian ? "Данные и помощь" : "Privacy & support" }
        var settings: String { russian ? "Настройки" : "Settings" }
        var trips: String { russian ? "Поездки" : "Trips" }
        var freeTitle: String { russian ? "Место для каждой поездки" : "Make room for every trip" }
        var offline: String { russian ? "Эта страница доступна без интернета и без Pro. Для перехода по веб-ссылкам нужна сеть." : "This page is available offline and without Pro. Website links need an internet connection." }
        var externalTitle: String { russian ? "Открыть веб-сайт?" : "Open a website?" }
        var externalBody: String { russian ? "Ссылка откроет GitHub вне TripDocket; для этого нужен интернет. Посещение сайта регулируется правилами GitHub. TripDocket не прикрепляет ваши документы к этой ссылке." : "This opens GitHub outside TripDocket and needs an internet connection. GitHub handles the web visit under its own policies. TripDocket does not attach your documents to this link." }
        var warning: String { russian ? "Не публикуйте документы, чеки о покупках, пароли, коды доступа и другие данные для входа или личные резервные копии. Перед публикацией проверьте снимки экрана на личные сведения." : "Do not post documents, purchase receipts, credentials or personal backups. Check screenshots for private information before posting." }
        var open: String { russian ? "Открыть сайт" : "Open website" }
        var cancel: String { russian ? "Отмена" : "Cancel" }
    }

    private func verifyGuidance(russian: Bool, maximumType: Bool) async throws {
        executionTimeAllowance = 360
        continueAfterFailure = false
        let copy = Copy(russian: russian)
        let app = XCUIApplication()
        app.launchEnvironment = [:]
        app.launchArguments = [
            "--ui-testing-unlocked", "--ui-testing-reset",
            "-AppleLanguages", russian ? "(ru-RU)" : "(en-US)",
            "-AppleLocale", russian ? "ru_RU" : "en_US",
            "-UIPreferredContentSizeCategoryName", maximumType
                ? "UICTContentSizeCategoryAccessibilityXXXL" : "UICTContentSizeCategoryL"
        ]
        app.launch()
        defer { app.terminate() }
        try require(app.navigationBars["TripDocket"].waitForExistence(timeout: 15),
                    app: app, "Fresh library did not open")
        try selectTab(copy.settings, in: app)
        try require(app.navigationBars[copy.settings].waitForExistence(timeout: 5),
                    app: app, "Settings did not open")
        // Resetting library data does not reset StoreKit entitlements. Fail this
        // precondition explicitly rather than revoking or fabricating an entitlement.
        let free = app.staticTexts[copy.freeTitle]
        try require(free.waitForExistence(timeout: 5) && free.isHittable,
                    app: app, "Requires an unentitled Free fixture; do not reset StoreKit automatically")
        attach(app, name: "Free Settings before guidance")
        let entry = app.buttons["privacySupport.entry"].firstMatch
        try await scrollTo(entry, in: app, navigationTitle: copy.settings,
                           description: "Privacy and support entry", preferWholeFrame: true)
        entry.tap()
        try require(app.navigationBars[copy.title].waitForExistence(timeout: 5),
                    app: app, "Bundled guidance did not open from Free Settings")

        let bodies = [
            "privacySupport.offline", "privacySupport.local.body", "privacySupport.access.body",
            "privacySupport.deletion.body", "privacySupport.deletion.temporary",
            "privacySupport.export.body", "privacySupport.export.restore",
            "privacySupport.apple.purchases", "privacySupport.apple.backup",
            "privacySupport.limits.body", "privacySupport.help.body",
            "privacySupport.support.body", "privacySupport.support.warning",
            "privacySupport.web.preview", "privacySupport.developer.name"
        ]
        for id in bodies {
            let body = app.staticTexts[id].firstMatch
            try await readWholeText(body, in: app, title: copy.title, name: id)
            if id == "privacySupport.offline" {
                try require(body.label == copy.offline, app: app, "Offline/Free introduction is incomplete or has wrong language")
            } else if id == "privacySupport.support.warning" {
                try require(body.label == copy.warning, app: app, "Public-support warning is incomplete or has wrong language")
            } else if id != "privacySupport.developer.name" {
                let containsRussian = body.label.range(of: "[А-Яа-яЁё]", options: .regularExpression) != nil
                try require(containsRussian == russian, app: app, "Unexpected language in \(id)")
            }
        }

        let base = "https://github.com/4alvit/travel-documents-ios"
        let docs = base + "/blob/1391b30776cd6ea48eab97cd92d4b098ff8f9474/docs/app-store/drafts/"
        let suffix = russian ? "ru.md" : "en-US.md"
        let destinations = [
            ("supportIssue", base + "/issues"),
            ("privacyPreview", docs + "privacy-" + suffix),
            ("supportPreview", docs + "support-" + suffix),
            ("developer", "https://github.com/4alvit")
        ]
        for (kind, expectedURL) in destinations {
            let link = app.buttons["privacySupport.link." + kind].firstMatch
            try await scrollTo(link, in: app, navigationTitle: copy.title,
                               description: "Website confirmation entry " + kind, preferWholeFrame: true,
                               searchDown: kind != "supportIssue")
            link.tap()
            let sheet = app.navigationBars[copy.externalTitle]
            try require(sheet.waitForExistence(timeout: 5), app: app, "Missing confirmation for " + kind)
            // Use an exact label predicate rather than a very long identifier query.
            let explanation = app.staticTexts.matching(NSPredicate(format: "label == %@", copy.externalBody)).firstMatch
            try await readWholeText(explanation, in: app, title: copy.externalTitle, name: kind + " external explanation")
            let warning = app.staticTexts["privacySupport.external.warning"].firstMatch
            if kind == "supportIssue" {
                try await readWholeText(warning, in: app, title: copy.externalTitle, name: "Public support warning")
                try require(warning.label == copy.warning, app: app, "Incorrect warning in public-support confirmation")
            } else {
                try require(!warning.exists, app: app, "Unexpected public-issue warning for " + kind)
            }
            let destination = app.staticTexts["privacySupport.external.destination"].firstMatch
            try await readWholeText(destination, in: app, title: copy.externalTitle, name: kind + " exact destination")
            try require(destination.label == expectedURL, app: app, "Unexpected destination for " + kind)
            let open = app.buttons["privacySupport.external.open"].firstMatch
            try await scrollTo(open, in: app, navigationTitle: copy.externalTitle,
                               description: "Explicit website action " + kind, preferWholeFrame: true)
            try require(open.label == copy.open && open.isEnabled,
                        app: app, "Open action has incorrect language or is disabled")
            try require(visibleViewport(in: app, navigationTitle: copy.externalTitle)
                .intersection(activeScrollContainer(in: app, navigationTitle: copy.externalTitle)?.frame ?? .zero)
                .insetBy(dx: -1, dy: -1).contains(open.frame), app: app, "Open action is clipped")
            let cancel = app.buttons["privacySupport.external.cancel"].firstMatch
            try require(cancel.exists && cancel.isHittable && cancel.label == copy.cancel,
                        app: app, "Localized Cancel is unavailable for " + kind)
            try require(sheet.frame.insetBy(dx: -1, dy: -1).contains(cancel.frame),
                        app: app, "Cancel is clipped outside the confirmation toolbar")
            attach(app, name: kind + " confirmation actions — Open intentionally not tapped")
            cancel.tap()
            try require(sheet.waitForNonExistence(timeout: 5), app: app, "Cancel did not dismiss " + kind)
            try require(!destination.exists && app.state == .runningForeground,
                        app: app, "Confirmation remained or app left foreground after Cancel")
            try require(app.navigationBars[copy.title].exists,
                        app: app, "Guidance did not return after " + kind + " cancellation")
            attach(app, name: kind + " cancelled, guidance retained")
        }

        let navigation = app.navigationBars[copy.title]
        let namedBack = navigation.buttons[copy.settings].firstMatch
        let back = namedBack.exists ? namedBack : navigation.buttons["BackButton"].firstMatch
        try require(back.exists && back.isHittable, app: app, "Back to Settings is not reachable")
        back.tap()
        try require(app.navigationBars[copy.settings].waitForExistence(timeout: 5),
                    app: app, "Settings did not return from guidance")
        try await scrollTo(free, in: app, navigationTitle: copy.settings,
                           description: "Free state after guidance", preferWholeFrame: true, searchDown: false)
        try require(free.exists && free.isHittable, app: app, "Free state changed during guidance")
        try selectTab(copy.trips, in: app)
        try require(app.navigationBars["TripDocket"].waitForExistence(timeout: 5),
                    app: app, "Trips did not return after guidance")
        attach(app, name: "Guidance completed and returned to Trips")
    }

    /// Cover every vertical point of a Text's stable frame, including paragraphs
    /// taller than one screen. A label existing in AX alone is insufficient.
    private func readWholeText(_ text: XCUIElement, in app: XCUIApplication,
                               title: String, name: String) async throws {
        guard let container = activeScrollContainer(in: app, navigationTitle: title) else {
            attach(app, name: "No active text container — " + name)
            throw LayoutFailure(message: "No active text container for " + name)
        }
        // This invocation cannot navigate or replace its List. Reuse its selected
        // container while still reading live geometry after every scroll.
        try await scrollTo(text, in: app, navigationTitle: title,
                           description: name, preferWholeFrame: true, scrollContainer: container,
                           readingPrefix: true)
        try require(!text.label.isEmpty, app: app, "Empty accessible text: " + name)
        let size = text.frame.size
        var covered: CGFloat = 0
        var previous: CGRect?
        for slice in 0..<20 {
            let containerFrame = container.frame
            let viewport = visibleViewport(in: app, navigationTitle: title)
                .intersection(containerFrame).insetBy(dx: 1, dy: 1)
            let frame = text.frame
            try require(text.exists && abs(frame.width - size.width) <= 1 && abs(frame.height - size.height) <= 1,
                        app: app, "Text geometry changed during reading: " + name)
            try require(frame.minX >= viewport.minX - 2 && frame.maxX <= viewport.maxX + 2,
                        app: app, "Text is horizontally clipped: " + name)
            let visible = frame.intersection(viewport)
            try require(!visible.isNull && visible.height > 0, app: app, "Text left viewport: " + name)
            let first = max(0, visible.minY - frame.minY)
            let last = min(frame.height, visible.maxY - frame.minY)
            // A later slice extends coverage only when it overlaps the already
            // read region by at least 48 pt. Overshoot is repaired, never skipped.
            let latestStart = covered > 0 ? max(0, covered - 48) : 1
            print("TEXT_READ \(name): slice=\(slice + 1), frame=\(frame), viewport=\(viewport), first=\(first), last=\(last), covered=\(covered)")
            if first <= latestStart, last > covered {
                covered = last
                attach(app, name: name + " readable slice " + String(slice + 1))
            }
            if covered >= frame.height - 1 { return }
            if let previous {
                try require(abs(frame.minY - previous.minY) > 1,
                            app: app, "Reading drag made no progress: " + name)
            }
            // Aim for 64 pt overlap, leaving margin for the measured 48 pt
            // requirement. The next observation still verifies the actual overlap.
            let allowedStart = covered > 0 ? max(0, covered - 48) : 1
            let translation: CGFloat
            if first > allowedStart {
                translation = max(24, first - max(0, covered - 64) + 12)
            } else {
                try require(visible.height > 64, app: app,
                            "Insufficient visible text for an overlapping step: " + name)
                translation = -(visible.height - 64)
            }
            previous = frame
            try await dragWithinViewport(translation, container: container,
                                         containerFrame: containerFrame,
                                         viewport: viewport.insetBy(dx: 12, dy: 12),
                                         app: app, name: name)
        }
        attach(app, name: "Incomplete text coverage — " + name)
        throw LayoutFailure(message: "Did not expose the entire text after 20 bounded slices: " + name)
    }

    private func selectTab(_ title: String, in app: XCUIApplication) throws {
        let tab = app.buttons[title].firstMatch
        try require(tab.waitForExistence(timeout: 5) && tab.isHittable,
                    app: app, title + " tab is not reachable")
        tab.tap()
    }

    private func scrollTo(
        _ target: XCUIElement, in app: XCUIApplication, navigationTitle: String,
        description: String, preferWholeFrame: Bool, searchDown: Bool = true,
        scrollContainer: XCUIElement? = nil, readingPrefix: Bool = false
    ) async throws {
        guard let container = scrollContainer
            ?? activeScrollContainer(in: app, navigationTitle: navigationTitle) else {
            attach(app, name: "No active scroll container — \(description)")
            throw LayoutFailure(message: "No hittable app scrollView/collectionView for \(description)")
        }
        for attempt in 0...10 {
            let exists = target.exists
            let frame = exists ? target.frame : .null
            // Settings has a collapsing large title. Keep the bounds live, but
            // share this one geometry read between acceptance and the next drag.
            let containerFrame = container.frame
            let visibleBounds = visibleViewport(in: app, navigationTitle: navigationTitle)
                .intersection(containerFrame)
            let tallReadingText = readingPrefix && frame.height > visibleBounds.height
            // Start tall text near the top with its whole prefix visible, not a
            // 44 pt sliver at the bottom. Short text keeps full-frame acceptance.
            let prefixAligned = frame.minY >= visibleBounds.minY + 1
                && frame.minY <= visibleBounds.minY + 48
            if exists && target.isHittable && visiblePortion(
                of: frame, in: visibleBounds, preferWholeFrame: preferWholeFrame
            ) && (!tallReadingText || prefixAligned) { return }
            guard attempt < 10 else { break }
            // Keep both endpoints inside the visible List/Form. Full swipes
            // overshot partly visible rows and oscillated across the viewport.
            let viewport = visibleBounds.insetBy(dx: 12, dy: 12)
            guard !viewport.isNull, viewport.width > 24, viewport.height > 80 else {
                attach(app, name: "No safe drag viewport — \(description)")
                throw LayoutFailure(message: "No safe scroll viewport for \(description)")
            }
            let hasFrame = !frame.isNull && !frame.isEmpty
                && frame.minY.isFinite && frame.maxY.isFinite
            if tallReadingText && hasFrame && !prefixAligned {
                let correction = visibleBounds.minY + 24 - frame.minY
                let distance = max(24, abs(correction))
                try await dragWithinViewport(correction > 0 ? distance : -distance,
                                             container: container, containerFrame: containerFrame,
                                             viewport: viewport, app: app,
                                             name: "Align text prefix — " + description)
                continue
            }
            let isNear = hasFrame && frame.intersects(viewport)
            let maximumStep = isNear ? min(160, viewport.height * 0.25)
                : min(320, viewport.height * 0.45)
            var correction = searchDown ? -maximumStep : maximumStep // Known direction for an unloaded row.
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
            let translation = correction > 0 ? distance : -distance
            let origin = container.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            let start = origin.withOffset(CGVector(
                dx: viewport.midX - containerFrame.minX,
                dy: viewport.midY - containerFrame.minY
            ))
            let end = start.withOffset(CGVector(dx: 0, dy: translation))
            print("LAYOUT_SCROLL \(description): target=\(frame), viewport=\(viewport), dy=\(translation)")
            start.press(forDuration: 0.05, thenDragTo: end,
                        withVelocity: .slow, thenHoldForDuration: 0.2)
            try await Task.sleep(for: .milliseconds(100))
        }
        attach(app, name: "Unreachable at maximum type — \(description)")
        throw LayoutFailure(message: "\(description) did not become safely hittable after bounded scrolling")
    }

    /// Long moves start near the corresponding edge, keeping both endpoints
    /// within the live safe List viewport instead of dragging from its center.
    private func dragWithinViewport(
        _ requestedTranslation: CGFloat, container: XCUIElement,
        containerFrame: CGRect, viewport: CGRect, app: XCUIApplication, name: String
    ) async throws {
        try require(!viewport.isNull && viewport.width > 24 && viewport.height > 80,
                    app: app, "No safe text-drag viewport: " + name)
        let distance = min(abs(requestedTranslation), viewport.height - 2)
        let translation = requestedTranslation > 0 ? distance : -distance
        let startPoint = CGPoint(x: viewport.midX,
                                 y: translation > 0 ? viewport.minY + 1 : viewport.maxY - 1)
        let endPoint = CGPoint(x: startPoint.x, y: startPoint.y + translation)
        try require(distance > 0 && viewport.contains(startPoint) && viewport.contains(endPoint),
                    app: app, "Text-drag endpoints leave the safe viewport: " + name)
        let start = container.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
            .withOffset(CGVector(dx: startPoint.x - containerFrame.minX,
                                 dy: startPoint.y - containerFrame.minY))
        print("TEXT_READ_SCROLL \(name): viewport=\(viewport), dy=\(translation)")
        start.press(forDuration: 0.05,
                    thenDragTo: start.withOffset(CGVector(dx: 0, dy: translation)),
                    withVelocity: .slow, thenHoldForDuration: 0.2)
        try await Task.sleep(for: .milliseconds(100))
    }

    private func activeScrollContainer(in app: XCUIApplication, navigationTitle: String) -> XCUIElement? {
        let navigation = app.navigationBars[navigationTitle]
        let navigationFrame = navigation.exists ? navigation.frame : app.frame
        let viewport = visibleViewport(in: app, navigationTitle: navigationTitle)
        let candidates = app.scrollViews.allElementsBoundByIndex + app.collectionViews.allElementsBoundByIndex
        // Apply the same geometry filters before either accessibility pass.
        let geometric: [(element: XCUIElement, frame: CGRect)] = candidates.compactMap { element in
            guard element.exists else { return nil }
            let frame = element.frame
            // A modal's navigation width excludes the larger presenting iPad List.
            guard !frame.isEmpty, frame.width <= navigationFrame.width + 32,
                  abs(frame.midX - navigationFrame.midX) < max(32, navigationFrame.width / 4),
                  frame.intersects(viewport) else { return nil }
            return (element, frame)
        }
        // A directly hittable List is stronger evidence than a wrapper. Return
        // before enumerating descendants of an obscured presenting screen.
        let directlyHittable = geometric.filter { $0.element.isHittable }
        if let direct = directlyHittable.max(by: { left, right in
            left.frame.width * left.frame.height < right.frame.width * right.frame.height
        }) {
            return direct.element
        }
        // Only when no List is directly hittable, retain the iPad wrapper
        // fallback requiring a visible, hittable descendant in the safe bounds.
        let usable = geometric.filter { candidate in
            let descendants = candidate.element.buttons.allElementsBoundByIndex
                + candidate.element.staticTexts.allElementsBoundByIndex
            return descendants.contains { child in
                guard child.exists, child.isHittable else { return false }
                let childFrame = child.frame
                guard !childFrame.isEmpty else { return false }
                let visible = childFrame.intersection(candidate.frame).intersection(viewport)
                return !visible.isNull && visible.width >= min(44, childFrame.width)
                    && visible.height >= min(44, childFrame.height)
            }
        }
        return usable.max { left, right in
            left.frame.width * left.frame.height < right.frame.width * right.frame.height
        }?.element
    }

    private func visibleViewport(in app: XCUIApplication, navigationTitle: String?) -> CGRect {
        let window = app.windows.firstMatch
        var viewport = window.exists ? window.frame : app.frame
        viewport = viewport.insetBy(dx: 2, dy: 2)
        if let navigationTitle {
            let navigation = app.navigationBars[navigationTitle]
            if navigation.exists, navigation.isHittable {
                let frame = navigation.frame
                let top = max(viewport.minY, frame.maxY)
                viewport = CGRect(x: max(viewport.minX, frame.minX), y: top,
                                  width: min(viewport.width, frame.width),
                                  height: max(0, viewport.maxY - top))
            }
        }
        // Floating bottom tabs can overlap a List row that still reports exists.
        // Top-mounted iPad tabs should not remove the bottom half of the viewport.
        for bar in app.tabBars.allElementsBoundByIndex where bar.exists && bar.isHittable {
            let frame = bar.frame
            if frame.minY > viewport.midY {
                viewport.size.height = max(0, min(viewport.maxY, frame.minY) - viewport.minY)
            }
        }
        return viewport
    }

    private func visiblePortion(
        of frame: CGRect, in viewport: CGRect, preferWholeFrame: Bool = false
    ) -> Bool {
        guard !frame.isEmpty, !viewport.isEmpty else { return false }
        if preferWholeFrame, frame.height <= viewport.height, frame.width <= viewport.width {
            return viewport.insetBy(dx: -1, dy: -1).contains(frame)
        }
        let intersection = frame.intersection(viewport)
        return !intersection.isNull
            && intersection.width >= min(44, frame.width)
            && intersection.height >= min(44, frame.height)
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
