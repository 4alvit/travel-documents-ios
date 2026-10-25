import Foundation
import XCTest
import SwiftUI
import UIKit
@testable import Tripfolio

final class PrivacySupportTests: XCTestCase {
    @MainActor
    func testGuidanceRendersWithoutALibraryOrPurchaseEnvironment() async throws {
        var appeared = false
        var requestedURLs: [URL] = []
        let didAppear = XCTestExpectation(description: "Guidance host finished appearing")
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let window = UIWindow(windowScene: scene)
        let host = PrivacySupportHostingController(rootView:
            NavigationStack {
                PrivacySupportView().onAppear { appeared = true }
            }
            .environment(\.openURL, OpenURLAction { url in
                requestedURLs.append(url)
                return .discarded
            })
        )
        host.onDidAppear = { didAppear.fulfill() }
        window.rootViewController = host
        window.isHidden = false
        defer {
            window.isHidden = true
            window.rootViewController = nil
            host.onDidAppear = nil
        }

        // SwiftUI.onAppear can run before UIKit finishes the host transition.
        let appearance = await XCTWaiter.fulfillment(of: [didAppear], timeout: 5)
        XCTAssertEqual(appearance, .completed, "Guidance host must finish appearing")
        XCTAssertTrue(appeared, "Guidance must render without AppModel or a purchase environment")
        XCTAssertTrue(requestedURLs.isEmpty, "Rendering guidance must not open a website")
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
private final class PrivacySupportHostingController<Content: View>: UIHostingController<Content> {
    var onDidAppear: (@MainActor () -> Void)?

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        let completion = onDidAppear
        onDidAppear = nil
        completion?()
    }
}
