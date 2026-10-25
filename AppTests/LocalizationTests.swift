import Foundation
import XCTest
import UIKit
@testable import Tripfolio

final class LocalizationTests: XCTestCase {
    func testPreferredSupportedLanguageAndEnglishFallback() {
        XCTAssertEqual(L10n.language(preferences: ["ru-RU", "en-US"]), "ru")
        XCTAssertEqual(L10n.language(preferences: ["fr-FR", "ru-RU", "en-US"]), "ru")
        XCTAssertEqual(L10n.language(preferences: ["en-GB", "ru-RU"]), "en")
        XCTAssertEqual(L10n.language(preferences: ["fr-FR"]), "en")
        XCTAssertEqual(L10n.ui("nav.trips", defaultValue: "Trips",
                              preferredLanguages: ["ja-JP"]), "Trips")
    }

    func testRussianPluralGrammarWithAmericanRegion() {
        let expected = [0: "0 документов", 1: "1 документ", 2: "2 документа",
                        5: "5 документов", 21: "21 документ"]
        for count in [0, 1, 2, 5, 21] {
            XCTAssertEqual(L10n.ui("count.documents", defaultValue: "\(count) documents",
                                  locale: Locale(identifier: "en_US"),
                                  preferredLanguages: ["ru"]), expected[count])
        }
        let count = 12_345
        XCTAssertEqual(L10n.ui("count.documents", defaultValue: "\(count) documents",
                              locale: Locale(identifier: "en_US"),
                              preferredLanguages: ["ru"]), "12,345 документов")
    }

    func testEnglishPluralGrammarWithRussianRegion() {
        for count in [0, 1, 2, 5, 21] {
            let noun = count == 1 ? "document" : "documents"
            XCTAssertEqual(L10n.ui("count.documents", defaultValue: "\(count) documents",
                                  locale: Locale(identifier: "ru_RU"),
                                  preferredLanguages: ["en"]), "\(count) \(noun)")
        }
    }

    func testMultipleArgumentsSelectPluralUsingTotalAndPreserveUserText() {
        let name = "Поездка ABC-21"
        for total in [0, 1, 2, 5, 21] {
            let ready = total == 1 ? 0 : 1
            let noun = total == 1 || total == 21 ? "оригинала" : "оригиналов"
            let text = L10n.ui("readiness.summary", defaultValue: "\(ready) of \(total) originals verified",
                               locale: Locale(identifier: "en_US"), preferredLanguages: ["ru"])
            XCTAssertEqual(text, "Проверено \(ready) из \(total) \(noun)")
            let notice = L10n.service("services.model.readiness.verified",
                                      defaultValue: "\(ready) of \(total) originals verified on this device.",
                                      locale: Locale(identifier: "en_US"), preferredLanguages: ["ru"])
            XCTAssertTrue(notice.hasPrefix("На этом устройстве проверено \(ready) из \(total) \(noun)."), notice)
            let deleted = L10n.ui("trip.deleteBody", defaultValue: "\(name) and \(total) original documents",
                                  locale: Locale(identifier: "en_US"), preferredLanguages: ["ru"])
            let form = total == 1 || total == 21 ? "оригинал документа" : total == 2 ? "оригинала документов" : "оригиналов документов"
            XCTAssertTrue(deleted.hasPrefix("«\(name)» и \(total) \(form)"), deleted)
        }
    }

    func testDeferredNotificationKeysHaveGenericTranslationsInTheMainBundle() throws {
        for language in ["en", "ru"] {
            let url = try XCTUnwrap(Bundle.main.url(forResource: language, withExtension: "lproj"))
            let bundle = try XCTUnwrap(Bundle(url: url))
            for key in ["reminder.title", "reminder.body"] {
                let value = bundle.localizedString(forKey: key, value: "__MISSING__", table: "Localizable")
                XCTAssertNotEqual(value, "__MISSING__")
                XCTAssertNotEqual(value, key)
                XCTAssertFalse(value.contains("%@"))
            }
        }
    }

    func testLanguageAndRegionRemainIndependent() {
        let american = Locale(identifier: "en_US")
        let russian = Locale(identifier: "ru_RU")
        let mixed = L10n.formattingLocale(locale: american, preferredLanguages: ["ru"])
        XCTAssertEqual(mixed.language.languageCode?.identifier, "ru")
        XCTAssertEqual(mixed.region?.identifier, "US")
        XCTAssertEqual(12_345.5.formatted(.number.locale(mixed)),
                       12_345.5.formatted(.number.locale(american)))
        XCTAssertNotEqual(12_345.5.formatted(.number.locale(mixed)),
                          12_345.5.formatted(.number.locale(russian)))
        let original = Locale(identifier: "en_US@calendar=buddhist;numbers=thai")
        let preserved = L10n.formattingLocale(locale: original, preferredLanguages: ["ru"])
        XCTAssertEqual(preserved.calendar.identifier, original.calendar.identifier)
        XCTAssertEqual(preserved.numberingSystem, original.numberingSystem)
        XCTAssertEqual(preserved.hourCycle, original.hourCycle)
    }

    func testNumericDateUsesRegion() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let date = calendar.date(from: DateComponents(year: 2026, month: 10, day: 20, hour: 12))!
        func numeric(_ locale: Locale) -> String {
            let formatter = DateFormatter()
            formatter.locale = locale
            formatter.calendar = calendar
            formatter.timeZone = calendar.timeZone
            formatter.dateStyle = .short
            return formatter.string(from: date)
        }
        let mixed = L10n.formattingLocale(locale: Locale(identifier: "en_US"),
                                         preferredLanguages: ["ru"])
        XCTAssertEqual(numeric(mixed), numeric(Locale(identifier: "en_US")))
        XCTAssertNotEqual(numeric(mixed), numeric(Locale(identifier: "ru_RU")))
    }

    func testLocalizedPermissionResourcesAreInTheAppBundle() throws {
        for language in ["en", "ru"] {
            let url = try XCTUnwrap(Bundle.main.url(forResource: language, withExtension: "lproj"))
            let bundle = try XCTUnwrap(Bundle(url: url))
            for key in ["NSCameraUsageDescription", "NSFaceIDUsageDescription", "TripDocket document backup"] {
                let value = bundle.localizedString(forKey: key, value: nil, table: "InfoPlist")
                XCTAssertFalse(value.isEmpty)
                if language == "ru" || key != "TripDocket document backup" {
                    XCTAssertNotEqual(value, key, "\(language):\(key)")
                }
            }
            XCTAssertEqual(bundle.localizedString(forKey: "CFBundleDisplayName", value: nil,
                                                  table: "InfoPlist"), "TripDocket")
        }
    }

    func testMissingKeyUsesItsEnglishDefaultWithoutTranslatingUserContent() {
        let title = "Анна / Passport ABC-123.pdf"
        XCTAssertEqual(L10n.ui("test.missing.key", defaultValue: "Original: \(title)",
                              preferredLanguages: ["ru"]), "Original: \(title)")
    }

    @MainActor
    func testOCRRecognizesRussianAndEnglishWithoutUsingTheInterfaceLanguage() async throws {
        let renderer = UIGraphicsImageRenderer(size: CGSize(width: 900, height: 220))
        let data = renderer.pngData { context in
            UIColor.white.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 900, height: 220))
            let attributes: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: 46, weight: .medium),
                .foregroundColor: UIColor.black
            ]
            ("TRAVEL DOCUMENT 2026" as NSString).draw(at: CGPoint(x: 30, y: 25), withAttributes: attributes)
            ("ПОЕЗДКА 2026" as NSString).draw(at: CGPoint(x: 30, y: 115), withAttributes: attributes)
        }
        let text = try await OCRService.recognizeText(in: data)
        XCTAssertTrue(text.contains("TRAVEL DOCUMENT"), text)
        XCTAssertTrue(text.contains("ПОЕЗДКА"), text)
    }
}
