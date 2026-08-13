import Foundation

public struct DailyFocusSummary: Equatable, Sendable, Identifiable {
    public let day: String
    public var focusedSeconds: TimeInterval
    public var completedPomodoros: Int
    public var focusSessions: Int
    public var containsEstimate: Bool

    public var id: String { day }

    public init(
        day: String,
        focusedSeconds: TimeInterval = 0,
        completedPomodoros: Int = 0,
        focusSessions: Int = 0,
        containsEstimate: Bool = false
    ) {
        self.day = day
        self.focusedSeconds = focusedSeconds
        self.completedPomodoros = completedPomodoros
        self.focusSessions = focusSessions
        self.containsEstimate = containsEstimate
    }
}

public enum FocusReviewPeriod: String, CaseIterable, Sendable {
    case week
    case month
}

public struct FocusPeriodSummary: Equatable, Sendable {
    public let days: [DailyFocusSummary]
    public let previousFocusedSeconds: TimeInterval
    public let previousCompletedPomodoros: Int

    public var focusedSeconds: TimeInterval { days.reduce(0) { $0 + $1.focusedSeconds } }
    public var completedPomodoros: Int { days.reduce(0) { $0 + $1.completedPomodoros } }
}

public enum FocusAnalytics {
    public static let badgeHours = [10, 25, 50, 100, 250, 500, 1_000]

    public static func dayKey(for date: Date, timeZone: TimeZone = .current) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let components = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", components.year ?? 0, components.month ?? 0, components.day ?? 0)
    }

    public static func date(for dayKey: String, timeZone: TimeZone = .current) -> Date? {
        let parts = dayKey.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3 else { return nil }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        return calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: parts[2]))
    }

    public static func dailySummaries(from stats: PomodoroStats) -> [String: DailyFocusSummary] {
        var result: [String: DailyFocusSummary] = [:]
        for session in stats.sessions {
            let timeZone = TimeZone(identifier: session.timeZoneIdentifier) ?? .current
            let sessionDay = dayKey(for: Date(timeIntervalSince1970: session.startedAt), timeZone: timeZone)
            var startSummary = result[sessionDay] ?? DailyFocusSummary(day: sessionDay)
            startSummary.focusSessions += 1
            startSummary.containsEstimate = startSummary.containsEstimate || session.legacyEstimated
            result[sessionDay] = startSummary

            if session.completed, let endedAt = session.endedAt {
                let completionDay = dayKey(for: Date(timeIntervalSince1970: endedAt), timeZone: timeZone)
                var completionSummary = result[completionDay] ?? DailyFocusSummary(day: completionDay)
                completionSummary.completedPomodoros += 1
                completionSummary.containsEstimate = completionSummary.containsEstimate || session.legacyEstimated
                result[completionDay] = completionSummary
            }

            let intervals = session.focusIntervals.isEmpty
                ? session.endedAt.map { [FocusInterval(startedAt: session.startedAt, endedAt: $0)] } ?? []
                : session.focusIntervals
            let intervalTotal = intervals.reduce(0) { $0 + $1.duration }
            let scale = intervalTotal > 0 ? session.focusedSeconds / intervalTotal : 0
            for interval in intervals {
                split(interval: interval, timeZone: timeZone) { day, wallSeconds in
                    var summary = result[day] ?? DailyFocusSummary(day: day)
                    summary.focusedSeconds += wallSeconds * scale
                    summary.containsEstimate = summary.containsEstimate || session.legacyEstimated
                    result[day] = summary
                }
            }
        }
        return result
    }

    public static func targetMinutes(on day: String, goals: [DailyFocusGoal]) -> Int? {
        goals
            .filter { $0.effectiveDay <= day }
            .sorted { $0.effectiveDay < $1.effectiveDay }
            .last?
            .targetMinutes
    }

    public static func currentStreak(
        stats: PomodoroStats,
        goals: [DailyFocusGoal],
        now: Date = Date(),
        timeZone: TimeZone = .current
    ) -> Int {
        guard !goals.isEmpty else { return 0 }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        let summaries = dailySummaries(from: stats)
        var cursor = calendar.startOfDay(for: now)
        var streak = 0
        while true {
            let key = dayKey(for: cursor, timeZone: timeZone)
            guard let target = targetMinutes(on: key, goals: goals) else { break }
            let focused = summaries[key]?.focusedSeconds ?? 0
            guard focused >= TimeInterval(target * 60) else { break }
            streak += 1
            guard let previous = calendar.date(byAdding: .day, value: -1, to: cursor) else { break }
            cursor = previous
        }
        return streak
    }

    public static func periodSummary(
        stats: PomodoroStats,
        period: FocusReviewPeriod,
        containing anchor: Date,
        now: Date = Date(),
        timeZone: TimeZone = .current
    ) -> FocusPeriodSummary {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        calendar.firstWeekday = Calendar.current.firstWeekday
        let interval = periodInterval(period, containing: anchor, calendar: calendar)
        let visibleEnd = min(interval.end, now.addingTimeInterval(1))
        let summaries = dailySummaries(from: stats)
        let days = daySequence(from: interval.start, to: visibleEnd, calendar: calendar).map { date in
            let key = dayKey(for: date, timeZone: timeZone)
            return summaries[key] ?? DailyFocusSummary(day: key)
        }

        let elapsed = max(0, visibleEnd.timeIntervalSince(interval.start))
        let previousInterval = periodInterval(period, containing: interval.start.addingTimeInterval(-1), calendar: calendar)
        let previousEnd = min(previousInterval.end, previousInterval.start.addingTimeInterval(elapsed))
        let previousDays = daySequence(from: previousInterval.start, to: previousEnd, calendar: calendar).map {
            summaries[dayKey(for: $0, timeZone: timeZone)] ?? DailyFocusSummary(day: dayKey(for: $0, timeZone: timeZone))
        }
        return FocusPeriodSummary(
            days: days,
            previousFocusedSeconds: previousDays.reduce(0) { $0 + $1.focusedSeconds },
            previousCompletedPomodoros: previousDays.reduce(0) { $0 + $1.completedPomodoros }
        )
    }

    public static func periodInterval(
        _ period: FocusReviewPeriod,
        containing date: Date,
        calendar: Calendar
    ) -> DateInterval {
        switch period {
        case .week:
            return calendar.dateInterval(of: .weekOfYear, for: date)!
        case .month:
            return calendar.dateInterval(of: .month, for: date)!
        }
    }

    private static func split(
        interval: FocusInterval,
        timeZone: TimeZone,
        consume: (String, TimeInterval) -> Void
    ) {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        var cursor = Date(timeIntervalSince1970: interval.startedAt)
        let end = Date(timeIntervalSince1970: interval.endedAt)
        while cursor < end {
            let nextDay = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: cursor)) ?? end
            let segmentEnd = min(nextDay, end)
            consume(dayKey(for: cursor, timeZone: timeZone), segmentEnd.timeIntervalSince(cursor))
            cursor = segmentEnd
        }
    }

    private static func daySequence(from start: Date, to end: Date, calendar: Calendar) -> [Date] {
        guard end > start else { return [] }
        var result: [Date] = []
        var cursor = calendar.startOfDay(for: start)
        while cursor < end {
            result.append(cursor)
            guard let next = calendar.date(byAdding: .day, value: 1, to: cursor) else { break }
            cursor = next
        }
        return result
    }
}
