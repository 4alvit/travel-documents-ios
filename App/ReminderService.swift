import Foundation
import TravelCore
import UserNotifications

enum ReminderService {
    enum ReminderError: LocalizedError {
        case missingExpiry, expired, permissionDenied, dateUnavailable, proRequired, documentChanged

        var errorDescription: String? {
            switch self {
            case .missingExpiry:
                L10n.service("services.reminder.missingExpiry", defaultValue: "Confirm an expiry date before scheduling a reminder.")
            case .expired:
                L10n.service("services.reminder.expired", defaultValue: "This document expires too soon to schedule a reminder. Review its confirmed expiry date.")
            case .permissionDenied:
                L10n.service("services.reminder.permissionDenied", defaultValue: "Notifications are disabled. Enable TripDocket notifications in Settings, then try again.")
            case .dateUnavailable:
                L10n.service("services.reminder.dateUnavailable", defaultValue: "A reminder date could not be calculated. Check the expiry date and try again.")
            case .proRequired:
                L10n.service("services.reminder.proRequired", defaultValue: "TripDocket Pro is required to create a reminder. Your documents and existing reminders remain available.")
            case .documentChanged:
                L10n.service("services.reminder.documentChanged", defaultValue: "This document or reminder request changed. Open its current details and confirm the expiry date again.")
            }
        }
    }

    /// Called only after an explicit Schedule Reminder action. Entitlement is
    /// rechecked around permission prompts; a sheet opened before revocation
    /// must not keep the right to create new reminders. Stored expiry is a
    /// human-confirmed civil date, never raw OCR output.
    @MainActor
    static func schedule(
        document: TravelDocument,
        travelerName: String?,
        canSchedule: @escaping @MainActor () -> Bool,
        isCurrentDocument: @escaping @MainActor () -> Bool
    ) async throws {
        try await schedule(document: document, travelerName: travelerName,
                           canSchedule: canSchedule, isCurrentDocument: isCurrentDocument,
                           notifications: .system)
    }

    @MainActor
    static func schedule(
        document: TravelDocument,
        travelerName: String?,
        canSchedule: @escaping @MainActor () -> Bool,
        isCurrentDocument: @escaping @MainActor () -> Bool,
        notifications: NotificationClient,
        lifecycle: Lifecycle? = nil
    ) async throws {
        try Task.checkCancellation()
        guard canSchedule() else { throw ReminderError.proRequired }
        guard isCurrentDocument() else { throw ReminderError.documentChanged }
        guard let storedExpiry = document.expiryDate else { throw ReminderError.missingExpiry }
        let lifecycle = lifecycle ?? productionLifecycle
        let ticket = lifecycle.begin(document.id)
        defer { lifecycle.finish(document.id, ticket: ticket) }
        let isCurrent = {
            lifecycle.isCurrent(document.id, ticket: ticket) && isCurrentDocument()
        }
        let calendar = Calendar.current
        let expiry = TravelDate.local(from: storedExpiry, calendar: calendar)
        // Reject unusable expiry dates before asking for permission.
        _ = try notificationDate(for: expiry, calendar: calendar)
        let status = await notifications.authorizationStatus()
        try Task.checkCancellation()
        guard isCurrent() else { throw ReminderError.documentChanged }
        guard canSchedule() else { throw ReminderError.proRequired }
        switch status {
        case .notDetermined:
            let granted = try await notifications.requestAuthorization()
            try Task.checkCancellation()
            guard isCurrent() else { throw ReminderError.documentChanged }
            guard granted else {
                throw ReminderError.permissionDenied
            }
        case .authorized, .provisional, .ephemeral:
            break
        case .denied:
            throw ReminderError.permissionDenied
        @unknown default:
            throw ReminderError.permissionDenied
        }
        try Task.checkCancellation()
        guard isCurrent() else { throw ReminderError.documentChanged }
        guard canSchedule() else { throw ReminderError.proRequired }

        let operation = lifecycle.enqueue(document.id) {
            try Task.checkCancellation()
            guard isCurrent() else { throw ReminderError.documentChanged }
            guard canSchedule() else { throw ReminderError.proRequired }
            let content = UNMutableNotificationContent()
            content.title = NSString.localizedUserNotificationString(forKey: "reminder.title", arguments: nil)
            content.body = NSString.localizedUserNotificationString(forKey: "reminder.body", arguments: nil)
            content.sound = .default
            // Recompute after permission and queue waits. Keep all identifying
            // document/person details out of notification content.
            let fireDate = try notificationDate(for: expiry, calendar: calendar)
            let request = UNNotificationRequest(
                identifier: identifier(for: document.id), content: content,
                trigger: notificationTrigger(for: fireDate, calendar: calendar)
            )
            do {
                try await notifications.add(request)
            } catch {
                // A client may apply an add before returning an error. Stale or
                // cancelled work is removed while newer adds still wait behind us.
                if Task.isCancelled || !isCurrent() {
                    notifications.remove([request.identifier])
                }
                throw error
            }
            if Task.isCancelled || !isCurrent() {
                notifications.remove([request.identifier])
                try Task.checkCancellation()
                throw ReminderError.documentChanged
            }
            // Pro loss alone does not remove an already accepted reminder.
        }
        // The queue task is unstructured: explicitly forward its caller's
        // cancellation, including cancellation while waiting for a prior add.
        try await withTaskCancellationHandler {
            try await operation.value
        } onCancel: {
            operation.cancel()
        }
    }

    /// At 09:00 in the scheduling calendar's time zone, 30 days before expiry.
    /// When already within that window, use the next 09:00 strictly before the
    /// expiry day. The caller passes a local instant, not a stored civil date.
    static func notificationDate(
        for expiry: Date,
        now: Date = Date(),
        calendar: Calendar = .current
    ) throws -> Date {
        let expiryDay = calendar.startOfDay(for: expiry)
        guard expiryDay > now else { throw ReminderError.expired }
        guard let earlyDay = calendar.date(byAdding: .day, value: -30, to: expiryDay),
              let earlyTime = calendar.date(bySettingHour: 9, minute: 0, second: 0, of: earlyDay) else {
            throw ReminderError.dateUnavailable
        }
        if earlyTime > now { return earlyTime }
        guard let nextMorning = calendar.nextDate(
            after: now,
            matching: DateComponents(hour: 9, minute: 0, second: 0),
            matchingPolicy: .nextTime
        ), nextMorning < expiryDay else { throw ReminderError.expired }
        return nextMorning
    }

    /// Pin both calendar and time zone. Extracting a Buddhist year such as 2573
    /// and letting UNCalendarNotificationTrigger assume Gregorian would move a
    /// 2030 reminder by centuries. Travel does not automatically shift this
    /// reminder to the destination's 09:00; the scheduling zone remains in use.
    static func notificationTrigger(
        for fireDate: Date,
        calendar: Calendar = .current
    ) -> UNCalendarNotificationTrigger {
        var components = calendar.dateComponents([.era, .year, .month, .day, .hour, .minute, .second], from: fireDate)
        components.calendar = calendar
        components.timeZone = calendar.timeZone
        return UNCalendarNotificationTrigger(dateMatching: components, repeats: false)
    }

    /// Tests control asynchronous permission/add completion and observe cleanup
    /// through this boundary without presenting system UI.
    @MainActor
    struct NotificationClient {
        let authorizationStatus: @MainActor () async -> UNAuthorizationStatus
        let requestAuthorization: @MainActor () async throws -> Bool
        let add: @MainActor (UNNotificationRequest) async throws -> Void
        let remove: @MainActor ([String]) -> Void
        let removeAll: @MainActor () -> Void

        init(authorizationStatus: @escaping @MainActor () async -> UNAuthorizationStatus,
             requestAuthorization: @escaping @MainActor () async throws -> Bool,
             add: @escaping @MainActor (UNNotificationRequest) async throws -> Void,
             remove: @escaping @MainActor ([String]) -> Void = { _ in },
             removeAll: @escaping @MainActor () -> Void = {}) {
            self.authorizationStatus = authorizationStatus
            self.requestAuthorization = requestAuthorization
            self.add = add
            self.remove = remove
            self.removeAll = removeAll
        }

        static var system: Self {
            let center = UNUserNotificationCenter.current()
            return Self(
                authorizationStatus: { await center.notificationSettings().authorizationStatus },
                requestAuthorization: { try await center.requestAuthorization(options: [.alert, .sound]) },
                add: { try await center.add($0) },
                remove: {
                    center.removePendingNotificationRequests(withIdentifiers: $0)
                    center.removeDeliveredNotifications(withIdentifiers: $0)
                },
                removeAll: {
                    center.removeAllPendingNotificationRequests()
                    center.removeAllDeliveredNotifications()
                }
            )
        }
    }

    @MainActor @discardableResult
    static func cancel(documentID: UUID, notifications: NotificationClient = .system,
                       lifecycle: Lifecycle? = nil) -> Task<Void, Never> {
        let lifecycle = lifecycle ?? productionLifecycle
        lifecycle.invalidate(documentID)
        // Remove any already accepted reminder immediately. A replacement add
        // may still be suspended, so repeat cleanup in its serialized lane.
        notifications.remove([identifier(for: documentID)])
        let operation = lifecycle.enqueue(documentID) {
            notifications.remove([identifier(for: documentID)])
        }
        return Task { _ = try? await operation.value }
    }

    /// Use after a successful replacement restore to avoid stale reminders from
    /// the replaced library. Never call this merely because Pro rights changed.
    @MainActor @discardableResult
    static func cancelAll(notifications: NotificationClient = .system,
                          lifecycle: Lifecycle? = nil) -> Task<Void, Never> {
        (lifecycle ?? productionLifecycle).invalidateAll(removing: notifications.removeAll)
    }

    @MainActor private static let productionLifecycle = Lifecycle()

    /// One production instance; tests supply an independent instance. A lane
    /// serializes one document's adds/removals. The all-document barrier prevents
    /// a delayed restore cleanup from deleting a subsequently scheduled reminder.
    @MainActor final class Lifecycle {
        private struct Tail {
            let id: UUID
            let task: Task<Void, Never>
        }
        private var pending: [UUID: UUID] = [:]
        private var tails: [UUID: Tail] = [:]
        private var clear: Tail?

        func begin(_ documentID: UUID) -> UUID {
            let ticket = UUID()
            pending[documentID] = ticket
            return ticket
        }

        func isCurrent(_ documentID: UUID, ticket: UUID) -> Bool { pending[documentID] == ticket }
        // Internal observation allows tests to cancel only once work is queued.
        func queuedOperationID(for documentID: UUID) -> UUID? { tails[documentID]?.id }
        func invalidate(_ documentID: UUID) { pending[documentID] = nil }
        func finish(_ documentID: UUID, ticket: UUID) {
            if isCurrent(documentID, ticket: ticket) { invalidate(documentID) }
        }

        func enqueue(_ documentID: UUID,
                     operation: @escaping @MainActor () async throws -> Void) -> Task<Void, Error> {
            let previous = tails[documentID]?.task
            let barrier = clear?.task
            let id = UUID()
            let task = Task { @MainActor in
                await barrier?.value
                await previous?.value
                try await operation()
            }
            let tail = Task { @MainActor in
                _ = try? await task.value
                if self.tails[documentID]?.id == id { self.tails[documentID] = nil }
            }
            tails[documentID] = Tail(id: id, task: tail)
            return task
        }

        func invalidateAll(removing removeAll: @escaping @MainActor () -> Void) -> Task<Void, Never> {
            pending.removeAll()
            // Do not leave accepted reminders active while an old add is held.
            // The barrier repeats this after outstanding old adds complete.
            removeAll()
            let previous = clear?.task
            let existing = tails.values.map(\.task)
            let id = UUID()
            let task = Task { @MainActor in
                await previous?.value
                for tail in existing { await tail.value }
                removeAll()
                if self.clear?.id == id { self.clear = nil }
            }
            clear = Tail(id: id, task: task)
            return task
        }
    }

    private static func identifier(for documentID: UUID) -> String {
        "tripfolio.expiry.\(documentID.uuidString)"
    }
}
