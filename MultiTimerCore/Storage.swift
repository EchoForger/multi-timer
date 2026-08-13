import Foundation

public enum MultiTimerPaths {
    private static var baseDirectory: URL {
        #if os(macOS)
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".config/multitimer")
        #else
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MultiTimer")
        #endif
    }

    public static var stateURL: URL {
        if let override = ProcessInfo.processInfo.environment["MULTITIMER_STATE_PATH"], !override.isEmpty {
            return URL(fileURLWithPath: override)
        }
        return baseDirectory.appendingPathComponent("state.json")
    }

    public static var statsURL: URL {
        if let override = ProcessInfo.processInfo.environment["MULTITIMER_STATS_PATH"], !override.isEmpty {
            return URL(fileURLWithPath: override)
        }
        return baseDirectory.appendingPathComponent("pomodoro-stats.json")
    }

    public static var socketURL: URL {
        if let override = ProcessInfo.processInfo.environment["MULTITIMER_SOCKET_PATH"], !override.isEmpty {
            return URL(fileURLWithPath: override)
        }
        return baseDirectory.appendingPathComponent("control.sock")
    }
}

public enum AtomicJSON {
    public static func load<T: Decodable>(_ type: T.Type, from url: URL, fallback: @autoclosure () -> T) -> T {
        guard let data = try? Data(contentsOf: url) else { return fallback() }
        return (try? JSONDecoder().decode(type, from: data)) ?? fallback()
    }

    public static func save<T: Encodable>(_ value: T, to url: URL) throws {
        let manager = FileManager.default
        try manager.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let data = try encoder.encode(value)
        let temporary = url.deletingLastPathComponent()
            .appendingPathComponent(".\(url.lastPathComponent).\(UUID().uuidString).tmp")
        try data.write(to: temporary, options: .atomic)
        if manager.fileExists(atPath: url.path) {
            _ = try manager.replaceItemAt(url, withItemAt: temporary)
        } else {
            try manager.moveItem(at: temporary, to: url)
        }
    }
}

public final class StateStore: @unchecked Sendable {
    public let url: URL

    public init(url: URL = MultiTimerPaths.stateURL) {
        self.url = url
    }

    public func load() -> StateDocument {
        AtomicJSON.load(StateDocument.self, from: url, fallback: StateDocument())
    }

    public func save(_ document: StateDocument) throws {
        try AtomicJSON.save(document, to: url)
    }
}

public final class StatsStore: @unchecked Sendable {
    public let url: URL

    public init(url: URL = MultiTimerPaths.statsURL) {
        self.url = url
    }

    public func load() -> PomodoroStats {
        AtomicJSON.load(PomodoroStats.self, from: url, fallback: PomodoroStats())
    }

    public func save(_ stats: PomodoroStats) throws {
        try AtomicJSON.save(stats, to: url)
    }

    public func sessions(
        in day: Date,
        from stats: PomodoroStats? = nil,
        calendar: Calendar = .current
    ) -> [FocusSession] {
        let stats = stats ?? load()
        let selectedKey = FocusAnalytics.dayKey(for: day, timeZone: calendar.timeZone)
        return stats.sessions.filter { session in
            let timeZone = TimeZone(identifier: session.timeZoneIdentifier) ?? calendar.timeZone
            var sessionCalendar = Calendar(identifier: .gregorian)
            sessionCalendar.timeZone = timeZone
            guard let localDay = FocusAnalytics.date(for: selectedKey, timeZone: timeZone),
                  let nextDay = sessionCalendar.date(byAdding: .day, value: 1, to: localDay) else { return false }
            let dayStart = localDay.timeIntervalSince1970
            let dayEnd = nextDay.timeIntervalSince1970
            return session.focusIntervals.contains { $0.startedAt < dayEnd && $0.endedAt > dayStart }
                || (session.startedAt >= dayStart && session.startedAt < dayEnd)
                || session.endedAt.map { $0 >= dayStart && $0 < dayEnd } == true
        }
    }

    public func focusedSeconds(
        in day: Date,
        from stats: PomodoroStats? = nil,
        calendar: Calendar = .current
    ) -> TimeInterval {
        let stats = stats ?? load()
        let key = FocusAnalytics.dayKey(for: day, timeZone: calendar.timeZone)
        return FocusAnalytics.dailySummaries(from: stats)[key]?.focusedSeconds ?? 0
    }
}
