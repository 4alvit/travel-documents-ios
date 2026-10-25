import Foundation
import XCTest
@testable import TravelCore

final class TravelDateTests: XCTestCase {
    func testSelectedDayStaysTheSameAcrossTravelAndDateLine() throws {
        for origin in ["America/Los_Angeles", "Asia/Tokyo", "Pacific/Kiritimati", "Pacific/Honolulu"] {
            let source = calendar(zone: origin)
            let chosen = try XCTUnwrap(source.date(from: DateComponents(year: 2027, month: 6, day: 1, hour: 18)))
            let stored = TravelDate.stored(from: chosen, calendar: source)
            for destination in ["Asia/Tokyo", "America/Los_Angeles", "Pacific/Kiritimati", "Pacific/Honolulu"] {
                let target = calendar(zone: destination)
                let local = TravelDate.local(from: stored, calendar: target)
                let parts = target.dateComponents([.year, .month, .day], from: local)
                XCTAssertEqual(parts.year, 2027)
                XCTAssertEqual(parts.month, 6)
                XCTAssertEqual(parts.day, 1)
                XCTAssertEqual(TravelDate.stored(from: local, calendar: target), stored)
            }
        }
    }

    func testNonGregorianUserCalendarDoesNotChangeStoredCivilDay() throws {
        var buddhist = Calendar(identifier: .buddhist)
        buddhist.timeZone = TimeZone(identifier: "Asia/Bangkok")!
        let chosen = try XCTUnwrap(buddhist.date(from: DateComponents(year: 2573, month: 1, day: 1, hour: 9)))
        let stored = TravelDate.stored(from: chosen, calendar: buddhist)
        let western = calendar(zone: "America/Los_Angeles")
        let parts = western.dateComponents([.year, .month, .day], from: TravelDate.local(from: stored, calendar: western))
        XCTAssertEqual(parts.year, 2030)
        XCTAssertEqual(parts.month, 1)
        XCTAssertEqual(parts.day, 1)
    }

    func testDSTBoundaryDatesRoundTrip() throws {
        let local = calendar(zone: "America/Los_Angeles")
        for (month, day) in [(3, 8), (11, 1)] {
            let chosen = try XCTUnwrap(local.date(from: DateComponents(year: 2026, month: month, day: day)))
            let result = TravelDate.local(from: TravelDate.stored(from: chosen, calendar: local), calendar: local)
            XCTAssertEqual(local.component(.month, from: result), month)
            XCTAssertEqual(local.component(.day, from: result), day)
        }
    }

    private func calendar(zone: String) -> Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: zone)!
        return calendar
    }
}
