import XCTest
import UIKit

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

    private enum PhoneTimingError: Error { case invalidProfile }

    private func useHostedPhoneTiming() throws -> Bool {
        guard let profile = ProcessInfo.processInfo.environment["TRIPDOCKET_PHONE_TIMING"] else {
            return false
        }
        guard profile == "hosted-intel-phone-v1" else { throw PhoneTimingError.invalidProfile }
        #if DEBUG && arch(x86_64) && targetEnvironment(simulator)
        guard UIDevice.current.userInterfaceIdiom == .phone else { throw PhoneTimingError.invalidProfile }
        return true
        #else
        throw PhoneTimingError.invalidProfile
        #endif
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
        // Hosted Intel Phone needs time for all four confirmations and captures.
        // Other runs retain their allowances; the dedicated iPad cap remains 480s.
        let hostedPhone = try useHostedPhoneTiming()
        executionTimeAllowance = russian && maximumType ? 600 : (hostedPhone ? 720 : 480)
        continueAfterFailure = false
        let copy = Copy(russian: russian)
        let app = XCUIApplication()
        app.launchEnvironment = [:]
        app.launchArguments = [
            "--ui-testing-unlocked", "--ui-testing-reset", "--ui-testing-guidance-diagnostics",
            "-AppleLanguages", russian ? "(ru-RU)" : "(en-US)",
            "-AppleLocale", russian ? "ru_RU" : "en_US",
            "-UIPreferredContentSizeCategoryName", maximumType
                ? "UICTContentSizeCategoryAccessibilityXXXL" : "UICTContentSizeCategoryL"
        ]
        app.launch()
        defer { app.terminate() }
        try require(app.navigationBars["TripDocket"].waitForExistence(timeout: 15),
                    app: app, "Fresh library did not open")
        try await selectTab(copy.settings, navigationTitle: copy.settings,
                            failure: "Settings did not open", in: app)
        // Resetting library data does not reset StoreKit entitlements. Fail this
        // precondition explicitly rather than revoking or fabricating an entitlement.
        let free = app.staticTexts[copy.freeTitle]
        try require(free.waitForExistence(timeout: 5) && free.isHittable,
                    app: app, "Requires an unentitled Free fixture; do not reset StoreKit automatically")
        attach(app, name: "Free Settings before guidance")
        let entry = app.buttons["privacySupport.entry"].firstMatch
        try await scrollTo(entry, in: app, navigationTitle: copy.settings,
                           description: "Privacy and support entry", preferWholeFrame: true,
                           snapshotMatch: SnapshotMatch(type: .button, key: "privacySupport.entry"))
        entry.tap()
        try require(app.navigationBars[copy.title].waitForExistence(timeout: 5),
                    app: app, "Bundled guidance did not open from Free Settings")
        var guidanceContainer = try requireActiveScrollContainer(
            in: app, navigationTitle: copy.title, description: "Bundled guidance"
        )

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
            try await readWholeText(body, in: app, title: copy.title, name: id,
                                    scrollContainer: guidanceContainer,
                                    snapshotMatch: SnapshotMatch(type: .staticText, key: id))
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
        for (index, linkDestination) in destinations.enumerated() {
            let (kind, expectedURL) = linkDestination
            if index > 0 {
                // The previous confirmation was dismissed. Select this page's
                // live List again rather than retaining a handle across it.
                guidanceContainer = try requireActiveScrollContainer(
                    in: app, navigationTitle: copy.title, description: kind + " guidance entry"
                )
            }
            let link = app.buttons["privacySupport.link." + kind].firstMatch
            try await scrollTo(link, in: app, navigationTitle: copy.title,
                               description: "Website confirmation entry " + kind, preferWholeFrame: true,
                               searchDown: kind != "supportIssue", scrollContainer: guidanceContainer,
                               snapshotMatch: SnapshotMatch(type: .button, key: "privacySupport.link." + kind))
            link.tap()
            let sheet = app.navigationBars[copy.externalTitle]
            try require(sheet.waitForExistence(timeout: 5), app: app, "Missing confirmation for " + kind)
            let confirmationContainer = try requireActiveScrollContainer(
                in: app, navigationTitle: copy.externalTitle, description: kind + " confirmation"
            )
            // Use an exact label predicate rather than a very long identifier query.
            let explanation = app.staticTexts.matching(NSPredicate(format: "label == %@", copy.externalBody)).firstMatch
            try await readWholeText(explanation, in: app, title: copy.externalTitle,
                                    name: kind + " external explanation", scrollContainer: confirmationContainer,
                                    snapshotMatch: SnapshotMatch(type: .staticText, label: copy.externalBody))
            let warning = app.staticTexts["privacySupport.external.warning"].firstMatch
            if kind == "supportIssue" {
                try await readWholeText(warning, in: app, title: copy.externalTitle,
                                        name: "Public support warning", scrollContainer: confirmationContainer,
                                        snapshotMatch: SnapshotMatch(type: .staticText, key: "privacySupport.external.warning"))
                try require(warning.label == copy.warning, app: app, "Incorrect warning in public-support confirmation")
            } else {
                try require(!warning.exists, app: app, "Unexpected public-issue warning for " + kind)
            }
            let destination = app.staticTexts["privacySupport.external.destination"].firstMatch
            try await readWholeText(destination, in: app, title: copy.externalTitle,
                                    name: kind + " exact destination", scrollContainer: confirmationContainer,
                                    snapshotMatch: SnapshotMatch(type: .staticText, key: "privacySupport.external.destination"))
            try require(destination.label == expectedURL, app: app, "Unexpected destination for " + kind)
            let open = app.buttons["privacySupport.external.open"].firstMatch
            let acceptedOpen = try await scrollTo(open, in: app, navigationTitle: copy.externalTitle,
                                                  description: "Explicit website action " + kind, preferWholeFrame: true,
                                                  scrollContainer: confirmationContainer,
                                                  snapshotMatch: SnapshotMatch(type: .button, key: "privacySupport.external.open"))
            try require(open.label == copy.open && open.isEnabled,
                        app: app, "Open action has incorrect language or is disabled")
            let freshOpenFrame = open.frame
            let openBounds = freshOpenFrame == acceptedOpen.targetFrame
                ? acceptedOpen.visibleBounds
                : visibleViewport(in: app, navigationTitle: copy.externalTitle)
                    .intersection(confirmationContainer.element.frame)
            let verifiedOpenFrame = freshOpenFrame == acceptedOpen.targetFrame ? freshOpenFrame : open.frame
            try require(openBounds.insetBy(dx: -1, dy: -1).contains(verifiedOpenFrame),
                        app: app, "Open action is clipped")
            let cancelCandidates = sheet.buttons.matching(identifier: "privacySupport.external.cancel").allElementsBoundByIndex
            try require(cancelCandidates.count == 1, app: app, "Cancel is missing or ambiguous in the current confirmation toolbar for " + kind)
            let cancel = cancelCandidates[0]
            try require(cancel.exists && cancel.isEnabled && cancel.isHittable && cancel.label == copy.cancel,
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
                           description: "Free state after guidance", preferWholeFrame: true, searchDown: false,
                           snapshotMatch: SnapshotMatch(type: .staticText, key: copy.freeTitle))
        try require(free.exists && free.isHittable, app: app, "Free state changed during guidance")
        try await selectTab(copy.trips, navigationTitle: "TripDocket",
                            failure: "Trips did not return after guidance", in: app)
        attach(app, name: "Guidance completed and returned to Trips")
    }

    /// Cover every vertical point of a Text's stable frame, including paragraphs
    /// taller than one screen. A label existing in AX alone is insufficient.
    private func readWholeText(_ text: XCUIElement, in app: XCUIApplication,
                               title: String, name: String,
                               scrollContainer: ScrollContainer? = nil,
                               snapshotMatch: SnapshotMatch) async throws {
        guard let container = scrollContainer ?? identifiedScrollContainer(in: app, navigationTitle: title) else {
            attach(app, name: "No active text container — " + name)
            throw LayoutFailure(message: "No active text container for " + name)
        }
        // A caller may share the selected List within one continuous page or
        // confirmation. Geometry remains live after every scroll.
        let accepted = try await scrollTo(text, in: app, navigationTitle: title,
                                          description: name, preferWholeFrame: true,
                                          scrollContainer: container, readingPrefix: true, snapshotMatch: snapshotMatch)
        try require(!text.label.isEmpty, app: app, "Empty accessible text: " + name)
        let size = accepted.targetFrame.size
        var covered: CGFloat = 0
        var previous: CGRect?
        for slice in 0..<20 {
            let containerFrame: CGRect
            let viewport: CGRect
            let frame: CGRect
            // No gesture separates acceptance from the first slice. Reuse its
            // geometry only while a fresh text frame confirms it has not moved.
            // Every later slice, or a changed first frame, gets fresh bounds.
            let firstFrame = slice == 0 ? text.frame : nil
            if let firstFrame, firstFrame == accepted.targetFrame {
                containerFrame = accepted.containerFrame
                viewport = textReadingViewport(accepted.visibleBounds)
                frame = firstFrame
            } else if let observation = snapshotGeometry(
                in: app, navigationTitle: title, target: snapshotMatch, container: container.match
            ), let targetFrame = observation.targetFrame, let observedContainer = observation.containerFrame {
                containerFrame = observedContainer
                viewport = textReadingViewport(observation.viewport.bounds.intersection(observedContainer))
                frame = targetFrame
            } else {
                containerFrame = container.element.frame
                viewport = textReadingViewport(legacyViewportObservation(in: app, navigationTitle: title).bounds
                    .intersection(containerFrame))
                frame = text.frame
            }
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
            try await dragWithinViewport(translation, container: container.element,
                                         containerFrame: containerFrame,
                                         viewport: viewport.insetBy(dx: 12, dy: 12),
                                         app: app, name: name)
        }
        attach(app, name: "Incomplete text coverage — " + name)
        throw LayoutFailure(message: "Did not expose the entire text after 20 bounded slices: " + name)
    }

    private func selectTab(
        _ title: String, navigationTitle: String, failure: String, in app: XCUIApplication
    ) async throws {
        let clock = ContinuousClock()
        func observation(until deadline: ContinuousClock.Instant)
            throws -> (element: XCUIElement, selected: Bool, navigationVisible: Bool)? {
            // One AX snapshot supplies all hierarchy/geometry facts. Repeated
            // exists/count calls previously spent the five-second readiness
            // budget before the unique visible iPad action could be tapped.
            guard clock.now < deadline else { return nil }
            let root = try app.snapshot()
            guard clock.now < deadline else { return nil }
            var visited = 0
            var matches = 0
            var leaves: [(node: XCUIElementSnapshot, parent: XCUIElementSnapshot?)] = []
            var navigationFrames: [CGRect] = []
            func visit(_ node: XCUIElementSnapshot, parent: XCUIElementSnapshot?, depth: Int) -> Bool? {
                guard clock.now < deadline, depth <= 40, visited < 1_000 else {
                    return nil
                }
                visited += 1
                if node.elementType == .navigationBar,
                   node.identifier == navigationTitle || node.label == navigationTitle {
                    navigationFrames.append(node.frame)
                }
                let matching = node.elementType == .button && node.label == title
                if matching { matches += 1 }
                var descendantMatches = false
                for child in node.children {
                    guard let found = visit(child, parent: node, depth: depth + 1) else { return nil }
                    if found { descendantMatches = true }
                }
                if matching && !descendantMatches { leaves.append((node, parent)) }
                return matching || descendantMatches
            }
            guard visit(root, parent: nil, depth: 0) != nil else { return nil }
            guard clock.now < deadline, leaves.count == 1, let leaf = leaves.first else { return nil }
            let frame = leaf.node.frame
            guard !frame.isNull, !frame.isInfinite, frame.width > 0, frame.height > 0,
                  root.frame.contains(frame), leaf.node.isEnabled else { return nil }
            // Native tabs can acquire their symbol identifier after the
            // readiness snapshot. An empty identifier is not stable identity;
            // the exact label and .element still require a unique live action.
            let exactAction = leaf.node.identifier.isEmpty
                ? NSPredicate(format: "label == %@", title)
                : NSPredicate(format: "label == %@ AND identifier == %@", title, leaf.node.identifier)
            let buttons = app.buttons.matching(exactAction)
            let action: XCUIElementQuery
            if matches == 1 {
                action = buttons
            } else if matches == 2, let parent = leaf.parent,
                      parent.elementType == .button, parent.label == title,
                      parent.identifier == leaf.node.identifier, parent.frame == frame {
                // The observed iPad representation is one exact parent/child
                // pair, not two independent actions. Any other shape fails.
                action = buttons.children(matching: .button).matching(exactAction)
            } else {
                return nil
            }
            guard clock.now < deadline else { return nil }
            let navigationVisible = navigationFrames.count == 1 && navigationFrames.allSatisfy {
                !$0.isNull && !$0.isInfinite && $0.width > 0 && $0.height > 0 && root.frame.contains($0)
            }
            // .element preserves the query's unique-match requirement; no
            // index, firstMatch or coordinate substitutes for the actual action.
            return (action.element, leaf.node.isSelected, navigationVisible)
        }
        // The bounded snapshot already verifies the exact leaf is enabled.
        // Resolve the same unique live action for hittability without another enabled RPC.
        let readinessDeadline = clock.now.advanced(by: .seconds(5))
        var target: XCUIElement?
        while clock.now < readinessDeadline {
            if let current = try observation(until: readinessDeadline),
               clock.now < readinessDeadline && current.element.isHittable,
               clock.now < readinessDeadline {
                target = current.element
                break
            }
            let remaining = clock.now.duration(to: readinessDeadline)
            if remaining > .zero { try await Task.sleep(for: min(.milliseconds(100), remaining)) }
        }
        guard let target, clock.now < readinessDeadline else {
            try require(false, app: app, title + " tab is not uniquely reachable")
            return
        }
        target.tap() // One real action; never retry an ignored tap or use coordinates.
        let transitionDeadline = clock.now.advanced(by: .seconds(5))
        while clock.now < transitionDeadline {
            if let current = try observation(until: transitionDeadline), current.selected,
               current.navigationVisible,
               clock.now < transitionDeadline {
                return
            }
            let remaining = clock.now.duration(to: transitionDeadline)
            if remaining > .zero { try await Task.sleep(for: min(.milliseconds(100), remaining)) }
        }
        try require(false, app: app, failure)
    }

    private struct ScrollObservation {
        let targetFrame: CGRect
        let containerFrame: CGRect
        let visibleBounds: CGRect
    }

    @discardableResult
    private func scrollTo(
        _ target: XCUIElement, in app: XCUIApplication, navigationTitle: String,
        description: String, preferWholeFrame: Bool, searchDown: Bool = true,
        scrollContainer: ScrollContainer? = nil, readingPrefix: Bool = false,
        snapshotMatch: SnapshotMatch
    ) async throws -> ScrollObservation {
        guard let container = scrollContainer
            ?? identifiedScrollContainer(in: app, navigationTitle: navigationTitle) else {
            attach(app, name: "No active scroll container — \(description)")
            throw LayoutFailure(message: "No hittable app scrollView/collectionView for \(description)")
        }
        for attempt in 0...10 {
            let exists: Bool
            let frame: CGRect
            let containerFrame: CGRect
            let visibleBounds: CGRect
            // One fresh hierarchy observation keeps target, List and chrome
            // geometry coherent. Ambiguous shapes use the original live queries.
            if let observation = snapshotGeometry(
                in: app, navigationTitle: navigationTitle, target: snapshotMatch, container: container.match
            ), let observedContainer = observation.containerFrame {
                exists = observation.targetFrame != nil
                frame = observation.targetFrame ?? .null
                containerFrame = observedContainer
                visibleBounds = observation.viewport.bounds.intersection(observedContainer)
            } else {
                exists = target.exists
                frame = exists ? target.frame : .null
                containerFrame = container.element.frame
                visibleBounds = legacyViewportObservation(in: app, navigationTitle: navigationTitle).bounds
                    .intersection(containerFrame)
            }
            let tallReadingText = readingPrefix && frame.height > textReadingViewport(visibleBounds).height
            // Use the reader's exact inset for short text as well as tall-text
            // prefixes. An expanded hit-test tolerance can leave a short final
            // strip unreadable without enough height for an overlapping step.
            let readingStartVisible = readingStartIsVisible(of: frame, in: visibleBounds)
            if exists && target.isHittable && visiblePortion(
                of: frame, in: visibleBounds, preferWholeFrame: preferWholeFrame
            ) && (!readingPrefix || readingStartVisible) {
                return ScrollObservation(targetFrame: frame, containerFrame: containerFrame,
                                         visibleBounds: visibleBounds)
            }
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
            if tallReadingText && hasFrame && !readingStartVisible {
                let correction = visibleBounds.minY + 24 - frame.minY
                let distance = max(24, abs(correction))
                try await dragWithinViewport(correction > 0 ? distance : -distance,
                                             container: container.element, containerFrame: containerFrame,
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
            let origin = container.element.coordinate(withNormalizedOffset: CGVector(dx: 0, dy: 0))
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

    private func requireActiveScrollContainer(
        in app: XCUIApplication, navigationTitle: String, description: String
    ) throws -> ScrollContainer {
        guard let container = identifiedScrollContainer(in: app, navigationTitle: navigationTitle) else {
            attach(app, name: "No active scroll container — " + description)
            throw LayoutFailure(message: "No hittable app scrollView/collectionView for " + description)
        }
        return container
    }

    private struct ScrollContainer {
        let element: XCUIElement
        let match: SnapshotMatch?
    }

    private func identifiedScrollContainer(in app: XCUIApplication, navigationTitle: String) -> ScrollContainer? {
        guard let element = activeScrollContainer(in: app, navigationTitle: navigationTitle) else { return nil }
        let identity = (try? element.snapshot()).map {
            SnapshotMatch(type: $0.elementType, identifier: $0.identifier, label: $0.label)
        }
        return ScrollContainer(element: element, match: identity)
    }

    private func activeScrollContainer(in app: XCUIApplication, navigationTitle: String) -> XCUIElement? {
        let observation = viewportObservation(in: app, navigationTitle: navigationTitle)
        let navigationFrame = observation.navigationFrame ?? app.frame
        let viewport = observation.bounds
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
        viewportObservation(in: app, navigationTitle: navigationTitle).bounds
    }

    private struct ViewportObservation {
        let bounds: CGRect
        let navigationFrame: CGRect?
    }

    private struct SnapshotMatch {
        let type: XCUIElement.ElementType
        var key: String? = nil
        var identifier: String? = nil
        var label: String? = nil

        @MainActor
        func matches(_ node: XCUIElementSnapshot) -> Bool {
            node.elementType == type
                && (key == nil || node.identifier == key || node.label == key)
                && (identifier == nil || node.identifier == identifier)
                && (label == nil || node.label == label)
        }
    }

    private struct SnapshotGeometry {
        let viewport: ViewportObservation
        let targetFrame: CGRect?
        let containerFrame: CGRect?
    }

    private func snapshotGeometry(
        in app: XCUIApplication, navigationTitle: String?,
        target: SnapshotMatch? = nil, container: SnapshotMatch? = nil
    ) -> SnapshotGeometry? {
        guard let root = try? app.snapshot() else { return nil }
        var nodes: [XCUIElementSnapshot] = []
        func visit(_ node: XCUIElementSnapshot, depth: Int) -> Bool {
            guard depth <= 40, nodes.count < 2_000 else { return false }
            nodes.append(node)
            return node.children.allSatisfy { visit($0, depth: depth + 1) }
        }
        guard visit(root, depth: 0) else { return nil }
        let windows = nodes.filter { $0.elementType == .window }
        let bars = nodes.filter { $0.elementType == .tabBar }
        let navigation = navigationTitle.map { title in
            nodes.filter { SnapshotMatch(type: .navigationBar, key: title).matches($0) }
        } ?? []
        let targets = target.map { match in nodes.filter { match.matches($0) } } ?? []
        let containers = container.map { match in nodes.filter { match.matches($0) } } ?? []
        // No index-to-tree-order assumptions. In particular, an empty List ID
        // is usable only when its complete typed identity is unique in the app.
        guard windows.count == 1, bars.count <= 1,
              navigationTitle == nil || navigation.count == 1,
              targets.count <= 1, container == nil || containers.count == 1 else { return nil }
        func finiteFrame(_ frame: CGRect) -> Bool {
            !frame.isNull && !frame.isInfinite && !frame.isEmpty
                && frame.origin.x.isFinite && frame.origin.y.isFinite
                && frame.width.isFinite && frame.height.isFinite
        }
        guard finiteFrame(windows[0].frame),
              (navigation + bars + targets + containers).allSatisfy({ finiteFrame($0.frame) }) else { return nil }
        var bounds = windows[0].frame.insetBy(dx: 2, dy: 2)
        let navigationFrame = navigation.first?.frame
        // Snapshot geometry never substitutes for live action/hit-test checks.
        if let title = navigationTitle, let frame = navigationFrame,
           app.navigationBars[title].isHittable {
            let top = max(bounds.minY, frame.maxY)
            bounds = CGRect(x: max(bounds.minX, frame.minX), y: top,
                            width: min(bounds.width, frame.width), height: max(0, bounds.maxY - top))
        }
        if let frame = bars.first?.frame, app.tabBars.element.isHittable, frame.minY > bounds.midY {
            bounds.size.height = max(0, min(bounds.maxY, frame.minY) - bounds.minY)
        }
        return SnapshotGeometry(viewport: ViewportObservation(bounds: bounds, navigationFrame: navigationFrame),
                                targetFrame: targets.first?.frame, containerFrame: containers.first?.frame)
    }

    private func viewportObservation(in app: XCUIApplication, navigationTitle: String?) -> ViewportObservation {
        snapshotGeometry(in: app, navigationTitle: navigationTitle)?.viewport
            ?? legacyViewportObservation(in: app, navigationTitle: navigationTitle)
    }

    private func legacyViewportObservation(in app: XCUIApplication, navigationTitle: String?) -> ViewportObservation {
        let window = app.windows.firstMatch
        var viewport = window.exists ? window.frame : app.frame
        viewport = viewport.insetBy(dx: 2, dy: 2)
        var navigationFrame: CGRect?
        if let navigationTitle {
            let navigation = app.navigationBars[navigationTitle]
            if navigation.exists {
                let isHittable = navigation.isHittable
                let frame = navigation.frame
                navigationFrame = frame
                if isHittable {
                    let top = max(viewport.minY, frame.maxY)
                    viewport = CGRect(x: max(viewport.minX, frame.minX), y: top,
                                      width: min(viewport.width, frame.width),
                                      height: max(0, viewport.maxY - top))
                }
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
        return ViewportObservation(bounds: viewport, navigationFrame: navigationFrame)
    }

    private func textReadingViewport(_ visibleBounds: CGRect) -> CGRect {
        visibleBounds.insetBy(dx: 1, dy: 1)
    }

    private func readingStartIsVisible(of frame: CGRect, in visibleBounds: CGRect) -> Bool {
        let viewport = textReadingViewport(visibleBounds)
        guard !frame.isEmpty, !viewport.isEmpty else { return false }
        if frame.height <= viewport.height {
            return viewport.contains(frame)
        }
        // Same 1...48 pt prefix alignment relative to the original bounds.
        return frame.minY >= viewport.minY && frame.minY <= viewport.minY + 47
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
        // debugDescription truncates accessibility values. Read only the two
        // known diagnostic elements and retain their strictly bounded schema
        // before a screenshot request can interrupt the remaining capture.
        let content = guidanceDiagnosticValue(
            app.collectionViews.matching(identifier: "privacySupport.content")
        )
        let cancel = guidanceDiagnosticValue(
            app.buttons.matching(identifier: "privacySupport.external.cancel")
        )
        let diagnostics = XCTAttachment(string: "version=1\ncontent=\(content)\ncancel=\(cancel)")
        diagnostics.name = "\(name) — guidance diagnostics"
        diagnostics.lifetime = .keepAlways
        add(diagnostics)
        let screenshot = XCTAttachment(screenshot: app.screenshot())
        screenshot.name = name
        screenshot.lifetime = .keepAlways
        add(screenshot)
        let hierarchy = XCTAttachment(string: app.debugDescription)
        hierarchy.name = "\(name) — accessibility hierarchy"
        hierarchy.lifetime = .keepAlways
        add(hierarchy)
    }

    private func guidanceDiagnosticValue(_ query: XCUIElementQuery) -> String {
        guard query.count == 1,
              let value = query.element(boundBy: 0).value as? String,
              value.utf8.count <= 512 else { return "unavailable" }
        let link = "(?:none|supportIssue|privacyPreview|supportPreview|developer)"
        let selectionAfterCancel = "(?:notObserved|none|supportIssue|privacyPreview|supportPreview|developer)"
        let pattern = #"\Aguidance-diagnostic presentations=[0-9]{1,10} lastPresented="# + link
            + #" cancellations=[0-9]{1,10} lastCancelled="# + link
            + " selectionAfterCancel=" + selectionAfterCancel + " selection=" + link
            + #" dismissals=[0-9]{1,10} scene=(?:active|inactive|background|unknown)\z"#
        guard value.range(of: pattern, options: .regularExpression) != nil else { return "unavailable" }
        return value
    }

    private struct LayoutFailure: LocalizedError {
        let message: String
        var errorDescription: String? { message }
    }
}
