import SwiftUI

@main
struct TripfolioApp: App {
    // Keep one model shared by this app's scenes, while allowing the injected
    // unit-test bundle to configure StoreKit before constructing any model.
    @State private var model: AppModel? = AppLaunch.isHostedUnitTest() ? nil : AppModel()

    var body: some Scene {
        WindowGroup {
            if let model {
                TripfolioRoot(model: model)
            } else {
                // The injected test bundle initializes local StoreKit before
                // any test creates an AppModel or PurchaseManager.
                Color.clear
            }
        }
    }
}

enum AppLaunch {
    static func isHostedUnitTest(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        #if DEBUG
        guard let path = environment["XCTestBundlePath"] else { return false }
        return URL(fileURLWithPath: path).lastPathComponent == "TripfolioTests.xctest"
        #else
        return false
        #endif
    }
}

private struct TripfolioRoot: View {
    let model: AppModel

    var body: some View {
        PrivacyLockView {
            RootView()
                .environment(model)
                .tint(Color(red: 0.04, green: 0.40, blue: 0.38))
                .task {
                    await model.refresh()
                    #if DEBUG
                    if ProcessInfo.processInfo.arguments.contains("--demo") {
                        await model.installSyntheticDemoIfEmpty()
                    }
                    #endif
                }
                .task { await model.purchases.load() }
        }
        .environment(\.locale, L10n.formattingLocale())
    }
}
