import Foundation

/// Bundle language controls wording and plural rules. Region controls formats.
/// iOS resolves its per-app language before the process starts; no preference is
/// written here, and no app-owned language setting overrides that resolution.
enum L10n {
    static let supportedLanguages = ["en", "ru"]

    static func language(preferences: [String]) -> String {
        Bundle.preferredLocalizations(from: supportedLanguages,
                                      forPreferences: preferences)
            .first(where: supportedLanguages.contains) ?? "en"
    }

    static func formattingLocale(locale: Locale = .current,
                                 bundle: Bundle = .main,
                                 preferredLanguages: [String]? = nil) -> Locale {
        let language = language(preferences: preferredLanguages ?? bundle.preferredLocalizations)
        var components = Locale.Components(languageCode: Locale.LanguageCode(language),
                                           languageRegion: locale.region)
        components.region = locale.region
        components.calendar = locale.calendar.identifier
        components.numberingSystem = locale.numberingSystem
        components.currency = locale.currency
        components.hourCycle = locale.hourCycle
        components.firstDayOfWeek = locale.firstDayOfWeek
        components.measurementSystem = locale.measurementSystem
        components.timeZone = locale.timeZone
        return Locale(components: components)
    }

    static func ui(_ key: StaticString, defaultValue: String.LocalizationValue,
                   locale: Locale = .current, bundle: Bundle = .main,
                   preferredLanguages: [String]? = nil) -> String {
        text(key, defaultValue: defaultValue, table: "UI", locale: locale,
             bundle: bundle, preferredLanguages: preferredLanguages)
    }

    static func service(_ key: StaticString, defaultValue: String.LocalizationValue,
                        locale: Locale = .current, bundle: Bundle = .main,
                        preferredLanguages: [String]? = nil) -> String {
        text(key, defaultValue: defaultValue, table: "Services", locale: locale,
             bundle: bundle, preferredLanguages: preferredLanguages)
    }

    private static func text(_ key: StaticString, defaultValue: String.LocalizationValue,
                             table: String, locale: Locale, bundle: Bundle,
                             preferredLanguages: [String]?) -> String {
        let language = language(preferences: preferredLanguages ?? bundle.preferredLocalizations)
        let resourceBundle = bundle.url(forResource: language, withExtension: "lproj")
            .flatMap(Bundle.init(url:)) ?? bundle
        let format = formattingLocale(locale: locale, bundle: bundle,
                                      preferredLanguages: [language])
        return String(localized: key, defaultValue: defaultValue, table: table,
                      bundle: resourceBundle, locale: format)
    }

    static func date(_ value: Date, date: Date.FormatStyle.DateStyle = .abbreviated,
                     time: Date.FormatStyle.TimeStyle = .omitted) -> String {
        value.formatted(Date.FormatStyle(date: date, time: time).locale(formattingLocale()))
    }

    static func byteCount(_ count: Int64, style: ByteCountFormatStyle.Style = .file) -> String {
        count.formatted(.byteCount(style: style).locale(formattingLocale()))
    }
}
