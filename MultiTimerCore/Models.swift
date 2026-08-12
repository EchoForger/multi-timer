import Foundation

public enum TimerKind: String, Codable, Sendable {
    case countdown
    case stopwatch
}

public struct TimerRecord: Identifiable, Codable, Equatable, Sendable {
    public var id: String
    public var label: String
    public var kind: TimerKind
    public var startTS: TimeInterval
    public var endTS: TimeInterval?
    public var pausedAt: TimeInterval?
    public var pinned: Bool
    public var finished: Bool
    public var laps: [TimeInterval]
    public var originalDuration: TimeInterval?

    public init(
        id: String = UUID().uuidString,
        label: String,
        kind: TimerKind,
        startTS: TimeInterval = Date().timeIntervalSince1970,
        endTS: TimeInterval? = nil,
        pausedAt: TimeInterval? = nil,
        pinned: Bool = false,
        finished: Bool = false,
        laps: [TimeInterval] = [],
        originalDuration: TimeInterval? = nil
    ) {
        self.id = id
        self.label = label
        self.kind = kind
        self.startTS = startTS
        self.endTS = endTS
        self.pausedAt = pausedAt
        self.pinned = pinned
        self.finished = finished
        self.laps = laps
        self.originalDuration = originalDuration
    }

    enum CodingKeys: String, CodingKey {
        case id, label, kind, pinned, finished, laps, duration
        case startTS = "start_ts"
        case endTS = "end_ts"
        case pausedAt = "paused_at"
        case createdTS = "created_ts"
        case paused
        case pausedRemaining = "paused_remaining"
        case elapsedBefore = "elapsed_before"
        case originalDuration = "original_duration"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? values.decode(String.self, forKey: .id)) ?? UUID().uuidString
        label = (try? values.decode(String.self, forKey: .label)) ?? "Timer"
        kind = (try? values.decode(TimerKind.self, forKey: .kind)) ?? .countdown
        pinned = (try? values.decode(Bool.self, forKey: .pinned)) ?? false
        finished = (try? values.decode(Bool.self, forKey: .finished)) ?? false
        laps = (try? values.decode([TimeInterval].self, forKey: .laps)) ?? []

        let now = Date().timeIntervalSince1970
        startTS = (try? values.decode(TimeInterval.self, forKey: .startTS))
            ?? (try? values.decode(TimeInterval.self, forKey: .createdTS))
            ?? now
        endTS = try? values.decodeIfPresent(TimeInterval.self, forKey: .endTS)
        pausedAt = try? values.decodeIfPresent(TimeInterval.self, forKey: .pausedAt)
        originalDuration = (try? values.decodeIfPresent(TimeInterval.self, forKey: .originalDuration))
            ?? (try? values.decodeIfPresent(TimeInterval.self, forKey: .duration))

        if kind == .countdown, endTS == nil, let duration = originalDuration {
            endTS = startTS + duration
        }
        if (try? values.decode(Bool.self, forKey: .paused)) == true, pausedAt == nil {
            pausedAt = now
            if kind == .countdown,
               let remaining = try? values.decode(TimeInterval.self, forKey: .pausedRemaining) {
                endTS = now + max(0, remaining)
            } else if kind == .stopwatch,
                      let elapsed = try? values.decode(TimeInterval.self, forKey: .elapsedBefore) {
                startTS = now - max(0, elapsed)
            }
        }
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encode(label, forKey: .label)
        try values.encode(kind, forKey: .kind)
        try values.encode(startTS, forKey: .startTS)
        try values.encodeIfPresent(endTS, forKey: .endTS)
        try values.encodeIfPresent(pausedAt, forKey: .pausedAt)
        try values.encode(pinned, forKey: .pinned)
        try values.encode(finished, forKey: .finished)
        try values.encode(laps, forKey: .laps)
        try values.encodeIfPresent(originalDuration, forKey: .originalDuration)
    }

    public var isPaused: Bool { pausedAt != nil }

    public func remaining(at now: TimeInterval) -> TimeInterval {
        guard kind == .countdown, let endTS else { return 0 }
        return max(0, endTS - (pausedAt ?? now))
    }

    public func elapsed(at now: TimeInterval) -> TimeInterval {
        guard kind == .stopwatch else { return 0 }
        return max(0, (pausedAt ?? now) - startTS)
    }
}

public struct AppSettings: Codable, Equatable, Sendable {
    public var showRemaining = false
    public var showCount = false
    public var sortByExpiry = true
    public var pomodoroWorkSeconds = 1_500
    public var pomodoroBreakSeconds = 300
    public var pomodoroAutoCycle = false
    public var showPomodoro = true
    public var updateAutomatically = true
    public var updatePreferenceSet = false
    public var syncRevision: TimeInterval = 0

    public init() {}

    enum CodingKeys: String, CodingKey {
        case showRemaining = "show_remaining"
        case showCount = "show_count"
        case sortByExpiry = "sort_by_expiry"
        case pomodoroWorkSeconds = "pomodoro_work_seconds"
        case pomodoroBreakSeconds = "pomodoro_break_seconds"
        case pomodoroAutoCycle = "pomodoro_auto_cycle"
        case showPomodoro = "show_pomodoro"
        case updateAutomatically = "update_automatically"
        case updatePreferenceSet = "update_preference_set"
        case syncRevision = "sync_revision"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        showRemaining = (try? values.decode(Bool.self, forKey: .showRemaining)) ?? false
        showCount = (try? values.decode(Bool.self, forKey: .showCount)) ?? false
        sortByExpiry = (try? values.decode(Bool.self, forKey: .sortByExpiry)) ?? true
        pomodoroWorkSeconds = (try? values.decode(Int.self, forKey: .pomodoroWorkSeconds)) ?? 1_500
        pomodoroBreakSeconds = (try? values.decode(Int.self, forKey: .pomodoroBreakSeconds)) ?? 300
        pomodoroAutoCycle = (try? values.decode(Bool.self, forKey: .pomodoroAutoCycle)) ?? false
        showPomodoro = (try? values.decode(Bool.self, forKey: .showPomodoro)) ?? true
        updateAutomatically = (try? values.decode(Bool.self, forKey: .updateAutomatically)) ?? true
        updatePreferenceSet = (try? values.decode(Bool.self, forKey: .updatePreferenceSet)) ?? false
        syncRevision = (try? values.decode(TimeInterval.self, forKey: .syncRevision)) ?? 0
    }
}

public struct StateDocument: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var timers: [TimerRecord]
    public var settings: AppSettings
    public var pomodoro: PomodoroSnapshot
    public var skippedUpdate: String?

    public init(
        schemaVersion: Int = 5,
        timers: [TimerRecord] = [],
        settings: AppSettings = AppSettings(),
        pomodoro: PomodoroSnapshot = PomodoroSnapshot(),
        skippedUpdate: String? = nil
    ) {
        self.schemaVersion = schemaVersion
        self.timers = timers
        self.settings = settings
        self.pomodoro = pomodoro
        self.skippedUpdate = skippedUpdate
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case timers, settings, pomodoro
        case skippedUpdate = "skipped_update"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = (try? values.decode(Int.self, forKey: .schemaVersion)) ?? 1
        timers = (try? values.decode([TimerRecord].self, forKey: .timers)) ?? []
        settings = (try? values.decode(AppSettings.self, forKey: .settings)) ?? AppSettings()
        pomodoro = (try? values.decode(PomodoroSnapshot.self, forKey: .pomodoro)) ?? PomodoroSnapshot()
        skippedUpdate = try? values.decodeIfPresent(String.self, forKey: .skippedUpdate)
        schemaVersion = 5
    }
}

public enum PomodoroPhase: String, Codable, Sendable {
    case idle, ready, work, rest
}

public struct PomodoroSnapshot: Codable, Equatable, Sendable {
    public var phase: PomodoroPhase = .idle
    public var finishAt: TimeInterval?
    public var pausedRemaining: TimeInterval?
    public var focusStartedAt: TimeInterval?

    public init() {}

    enum CodingKeys: String, CodingKey {
        case phase
        case finishAt = "finish_at"
        case pausedRemaining = "paused_remaining"
        case focusStartedAt = "focus_started_at"
    }
}

public struct FocusSession: Identifiable, Codable, Equatable, Sendable {
    public var startedAt: TimeInterval
    public var endedAt: TimeInterval?
    public var completed: Bool

    public var id: String { "\(startedAt)-\(endedAt ?? 0)" }

    public init(
        startedAt: TimeInterval,
        endedAt: TimeInterval? = nil,
        completed: Bool = false
    ) {
        self.startedAt = startedAt
        self.endedAt = endedAt
        self.completed = completed
    }

    enum CodingKeys: String, CodingKey {
        case completed, intervals
        case startedAt = "started_at"
        case endedAt = "ended_at"
    }

    private struct LegacyInterval: Codable {
        var start: TimeInterval
        var end: TimeInterval?
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        completed = (try? values.decode(Bool.self, forKey: .completed)) ?? false
        let intervals = (try? values.decode([LegacyInterval].self, forKey: .intervals)) ?? []
        startedAt = (try? values.decode(TimeInterval.self, forKey: .startedAt))
            ?? intervals.first?.start
            ?? 0
        endedAt = (try? values.decodeIfPresent(TimeInterval.self, forKey: .endedAt))
            ?? intervals.compactMap(\.end).max()
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(startedAt, forKey: .startedAt)
        try values.encodeIfPresent(endedAt, forKey: .endedAt)
        try values.encode(completed, forKey: .completed)
    }
}

public struct PomodoroStats: Codable, Equatable, Sendable {
    public var sessions: [FocusSession]
    public var syncRevision: TimeInterval

    public init(
        sessions: [FocusSession] = [],
        syncRevision: TimeInterval = 0
    ) {
        self.sessions = sessions
        self.syncRevision = syncRevision
    }

    enum CodingKeys: String, CodingKey {
        case sessions
        case syncRevision = "sync_revision"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        sessions = ((try? values.decode([FocusSession].self, forKey: .sessions)) ?? [])
            .filter { $0.endedAt != nil }
        syncRevision = (try? values.decode(TimeInterval.self, forKey: .syncRevision)) ?? 0
    }
}
