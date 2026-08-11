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

    public static func dayKey(for date: Date = Date(), calendar: Calendar = .current) -> String {
        let components = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", components.year ?? 0, components.month ?? 0, components.day ?? 0)
    }

    public func recordCompletion(at date: Date = Date()) -> PomodoroStats {
        var stats = load()
        stats.days[Self.dayKey(for: date), default: 0] += 1
        stats.syncRevision = date.timeIntervalSince1970
        try? save(stats)
        return stats
    }

    public func denseSeries(days count: Int = 30, endingAt date: Date = Date()) -> [(String, Int)] {
        let stats = load()
        let calendar = Calendar.current
        return (0..<count).reversed().compactMap { offset in
            guard let day = calendar.date(byAdding: .day, value: -offset, to: date) else { return nil }
            let key = Self.dayKey(for: day, calendar: calendar)
            return (key, stats.days[key, default: 0])
        }
    }
}
