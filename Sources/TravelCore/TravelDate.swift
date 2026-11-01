import Foundation

/// Departure and expiry are civil days, not moments in time. The existing Date
/// wire field encodes Gregorian year/month/day at 12:00 UTC. Convert only at the
/// UI boundary; importedAt and readiness timestamps remain ordinary instants.
public enum TravelDate {
    public static func stored(from localDate: Date, calendar: Calendar = .current) -> Date {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = calendar.timeZone
        var components = local.dateComponents([.year, .month, .day], from: localDate)
        components.hour = 12
        return storageCalendar.date(from: components) ?? localDate
    }

    public static func local(from storedDate: Date, calendar: Calendar = .current) -> Date {
        var local = Calendar(identifier: .gregorian)
        local.timeZone = calendar.timeZone
        var components = storageCalendar.dateComponents([.year, .month, .day], from: storedDate)
        components.hour = 12
        return local.date(from: components) ?? storedDate
    }

    private static var storageCalendar: Calendar {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        return calendar
    }
}
