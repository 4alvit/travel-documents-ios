import SwiftUI

@main
struct TripfolioApp: App {
    @State private var model = AppModel()

    var body: some Scene {
        WindowGroup {
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
}
