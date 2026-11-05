import Foundation
import XCTest
import SwiftUI
import UIKit
@testable import Tripfolio

final class PrivacySupportTests: XCTestCase {
    @MainActor
    func testGuidanceRendersWithoutALibraryOrPurchaseEnvironment() async throws {
        let trace = GuidanceAppearanceTrace()
        trace.record(.testStarted)
        defer { add(trace.attachment()) }
        let appearanceAllowance = try guidanceAppearanceAllowance()
        var appeared = false
        var requestedURLs: [URL] = []
        let didAppear = XCTestExpectation(description: "Guidance host finished appearing")
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        trace.sceneActivationState = scene.activationState.rawValue
        let window = UIWindow(windowScene: scene)
        let host = PrivacySupportHostingController(rootView:
            NavigationStack {
                PrivacySupportView().onAppear {
                    appeared = true
                    trace.record(.swiftUIOnAppear)
                }
            }
            .environment(\.openURL, OpenURLAction { url in
                requestedURLs.append(url)
                return .discarded
            })
        )
        host.onDidAppear = {
            trace.record(.uiKitViewDidAppear)
            didAppear.fulfill()
        }
        window.rootViewController = host
        trace.record(.beforeWindowVisibility)
        window.isHidden = false
        trace.record(.afterWindowVisibility)
        defer {
            window.isHidden = true
            window.rootViewController = nil
            host.onDidAppear = nil
        }

        // SwiftUI.onAppear can run before UIKit finishes the host transition.
        trace.record(.waiterStarted)
        let appearance = await XCTWaiter.fulfillment(of: [didAppear], timeout: appearanceAllowance)
        trace.record(.waiterReturned)
        trace.waiterResult = appearance.rawValue
        XCTAssertEqual(appearance, .completed, "Guidance host must finish appearing")
        XCTAssertTrue(appeared, "Guidance must render without AppModel or a purchase environment")
        XCTAssertTrue(requestedURLs.isEmpty, "Rendering guidance must not open a website")
    }

    private enum CoreTimingError: Error { case invalidProfile }

    @MainActor
    private func guidanceAppearanceAllowance() throws -> TimeInterval {
        let environment = ProcessInfo.processInfo.environment
        guard let profile = environment["TRIPDOCKET_CORE_TIMING"] else { return 5 }
        guard profile == "hosted-intel-core-v1",
              environment["TRIPDOCKET_PHONE_TIMING"] == nil,
              environment["TRIPDOCKET_IPAD_TIMING"] == nil else {
            throw CoreTimingError.invalidProfile
        }
        #if DEBUG && arch(x86_64) && targetEnvironment(simulator)
        guard UIDevice.current.userInterfaceIdiom == .phone else {
            throw CoreTimingError.invalidProfile
        }
        return 30
        #else
        throw CoreTimingError.invalidProfile
        #endif
    }

    func testOfflineGuidanceIsPresentInBothShippedLanguageBundles() throws {
        let required = [
            "privacySupport.offline", "privacySupport.local.body", "privacySupport.access.body",
            "privacySupport.deletion.body", "privacySupport.deletion.temporary",
            "privacySupport.export.body", "privacySupport.export.restore",
            "privacySupport.apple.purchases", "privacySupport.apple.backup",
            "privacySupport.limits.body", "privacySupport.help.body",
            "privacySupport.support.body", "privacySupport.support.warning",
            "privacySupport.web.preview", "privacySupport.external.body"
        ]
        for language in ["en", "ru"] {
            let url = try XCTUnwrap(Bundle.main.url(forResource: language, withExtension: "lproj"))
            let bundle = try XCTUnwrap(Bundle(url: url))
            for key in required {
                let value = bundle.localizedString(forKey: key, value: "__MISSING__", table: "UI")
                XCTAssertNotEqual(value, "__MISSING__", "\(language): \(key)")
                XCTAssertNotEqual(value, key)
                XCTAssertFalse(value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                XCTAssertFalse(value.contains("https://"), "Offline paragraphs must not depend on a web document")
            }
        }
    }

    func testPublicLinksHaveNoUserDataAndUseTheFirstSupportedLanguage() {
        for preferences in [["ru-RU", "en-US"], ["fr-FR", "ru-RU"], ["en-US", "ru-RU"], ["ja-JP"]] {
            let russian = preferences.first != "en-US" && preferences.contains("ru-RU")
            for link in PrivacySupportLink.allCases {
                let url = link.url(preferredLanguages: preferences)
                XCTAssertEqual(url.scheme, "https")
                XCTAssertEqual(url.host, "github.com")
                XCTAssertNil(url.user)
                XCTAssertNil(url.password)
                XCTAssertNil(url.query)
                XCTAssertNil(url.fragment)
                switch link {
                case .supportIssue: XCTAssertEqual(url.path, "/4alvit/travel-documents-ios/issues")
                case .developer: XCTAssertEqual(url.path, "/4alvit")
                case .privacyPreview, .supportPreview:
                    XCTAssertTrue(url.path.hasPrefix("/4alvit/travel-documents-ios/blob/1391b30776cd6ea48eab97cd92d4b098ff8f9474/docs/app-store/drafts/"))
                    let document = link == .privacyPreview ? "privacy" : "support"
                    XCTAssertEqual(url.lastPathComponent, "\(document)-\(russian ? "ru" : "en-US").md")
                }
            }
        }
    }
}

@MainActor
private final class GuidanceAppearanceTrace {
    enum Event: String {
        case testStarted, beforeWindowVisibility, afterWindowVisibility
        case waiterStarted, waiterReturned, swiftUIOnAppear, uiKitViewDidAppear
    }

    private let started = ProcessInfo.processInfo.systemUptime
    private var events: [(Event, TimeInterval)] = []
    private var truncated = false
    var sceneActivationState: Int?
    var waiterResult: Int?

    func record(_ event: Event) {
        guard events.count < 16 else {
            truncated = true
            return
        }
        events.append((event, ProcessInfo.processInfo.systemUptime - started))
    }

    func attachment() -> XCTAttachment {
        // Fixed event names and relative times only; no scene identifiers or URLs.
        let text = (["version=1", "truncated=\(truncated)",
                     "scene_activation_state=\(sceneActivationState.map(String.init) ?? "unobserved")",
                     "waiter_result=\(waiterResult.map(String.init) ?? "unobserved")"]
                    + events.map { "event=\($0.0.rawValue) elapsed_seconds=\($0.1)" })
            .joined(separator: "\n")
        let attachment = XCTAttachment(string: text)
        attachment.name = "Guidance host appearance timing"
        attachment.lifetime = .keepAlways
        return attachment
    }
}

@MainActor
private final class PrivacySupportHostingController<Content: View>: UIHostingController<Content> {
    var onDidAppear: (@MainActor () -> Void)?

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        let completion = onDidAppear
        onDidAppear = nil
        completion?()
    }
}
