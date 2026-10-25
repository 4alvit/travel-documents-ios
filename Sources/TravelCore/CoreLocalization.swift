import Foundation

/// String lookup stays separate from regional formatting and persisted model values.
/// Explicit preferences support deterministic tests without changing process settings.
enum CoreLocalization {
    static let resourceBundle = Bundle.module

    static func text(_ key: StaticString, defaultValue: String.LocalizationValue,
                     preferredLanguages: [String]? = nil) -> String {
        let preferences = preferredLanguages ?? applicationLanguages
        let language = Bundle.preferredLocalizations(
            from: resourceBundle.localizations.filter { $0 != "Base" },
            forPreferences: preferences + ["en"]
        ).first ?? "en"
        let bundle = resourceBundle.url(forResource: language, withExtension: "lproj")
            .flatMap { Bundle(url: $0) } ?? resourceBundle
        return String(localized: key, defaultValue: defaultValue,
                      table: "Core", bundle: bundle)
    }

    private static var applicationLanguages: [String] {
        // Respect the host application's language choice (including per-app language).
        // A standalone SwiftPM executable has no localized main bundle of its own.
        if Bundle.main.localizations.contains(where: { $0 != "Base" }) {
            return Bundle.main.preferredLocalizations
        }
        return Locale.preferredLanguages
    }
}
