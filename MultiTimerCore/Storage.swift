import Foundation

public enum MultiTimerPaths {
    public static var stateURL: URL {
        if let override = ProcessInfo.processInfo.environment["MULTITIMER_STATE_PATH"], !override.isEmpty {
            return URL(fileURLWithPath: override)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/multitimer/state.json")
    }

    public static var statsURL: URL {
        if let override = ProcessInfo.processInfo.environment["MULTITIMER_STATS_PATH"], !override.isEmpty {
            return URL(fileURLWithPath: override)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/multitimer/pomodoro-stats.json")
    }

    public static var socketURL: URL {
        if let override = ProcessInfo.processInfo.environment["MULTITIMER_SOCKET_PATH"], !override.isEmpty {
            return URL(fileURLWithPath: override)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".config/multitimer/control.sock")
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
        let dayStart = calendar.startOfDay(for: day).timeIntervalSince1970
        let dayEnd = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: day))!.timeIntervalSince1970
        return stats.sessions.filter { session in
            guard let endedAt = session.endedAt else { return false }
            return session.startedAt < dayEnd && endedAt > dayStart
        }
    }

    public func focusedSeconds(
        in day: Date,
        from stats: PomodoroStats? = nil,
        calendar: Calendar = .current
    ) -> TimeInterval {
        let dayStart = calendar.startOfDay(for: day).timeIntervalSince1970
        let dayEnd = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: day))!.timeIntervalSince1970
        return sessions(in: day, from: stats, calendar: calendar).reduce(0) { total, session in
            let start = max(dayStart, session.startedAt)
            let end = min(dayEnd, session.endedAt ?? start)
            return total + max(0, end - start)
        }
    }
}
