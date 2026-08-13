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
    public var dailyFocusGoals: [DailyFocusGoal] = []
    public var hasSeenFocusGoalPrompt = false
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
        case dailyFocusGoals = "daily_focus_goals"
        case hasSeenFocusGoalPrompt = "has_seen_focus_goal_prompt"
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
        dailyFocusGoals = (try? values.decode([DailyFocusGoal].self, forKey: .dailyFocusGoals)) ?? []
        hasSeenFocusGoalPrompt = (try? values.decode(Bool.self, forKey: .hasSeenFocusGoalPrompt)) ?? false
        syncRevision = (try? values.decode(TimeInterval.self, forKey: .syncRevision)) ?? 0
    }
}

public struct DailyFocusGoal: Codable, Equatable, Sendable, Identifiable {
    public var effectiveDay: String
    public var targetMinutes: Int?

    public var id: String { effectiveDay }

    public init(effectiveDay: String, targetMinutes: Int?) {
        self.effectiveDay = effectiveDay
        self.targetMinutes = targetMinutes.map { min(max(15, $0), 480) }
    }

    enum CodingKeys: String, CodingKey {
        case effectiveDay = "effective_day"
        case targetMinutes = "target_minutes"
    }
}

public struct StateDocument: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var timers: [TimerRecord]
    public var settings: AppSettings
    public var pomodoro: PomodoroSnapshot
    public var skippedUpdate: String?

    public init(
        schemaVersion: Int = 6,
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
        schemaVersion = 6
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
    public var focusSegmentStartedAt: TimeInterval?
    public var focusIntervals: [FocusInterval] = []

    public init() {}

    enum CodingKeys: String, CodingKey {
        case phase
        case finishAt = "finish_at"
        case pausedRemaining = "paused_remaining"
        case focusStartedAt = "focus_started_at"
        case focusSegmentStartedAt = "focus_segment_started_at"
        case focusIntervals = "focus_intervals"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        phase = (try? values.decode(PomodoroPhase.self, forKey: .phase)) ?? .idle
        finishAt = try? values.decodeIfPresent(TimeInterval.self, forKey: .finishAt)
        pausedRemaining = try? values.decodeIfPresent(TimeInterval.self, forKey: .pausedRemaining)
        focusStartedAt = try? values.decodeIfPresent(TimeInterval.self, forKey: .focusStartedAt)
        focusSegmentStartedAt = try? values.decodeIfPresent(TimeInterval.self, forKey: .focusSegmentStartedAt)
        focusIntervals = (try? values.decode([FocusInterval].self, forKey: .focusIntervals)) ?? []
        if phase == .work, pausedRemaining == nil, focusSegmentStartedAt == nil {
            focusSegmentStartedAt = focusStartedAt
        }
    }

    public mutating func beginFocus(at timestamp: TimeInterval) {
        focusStartedAt = timestamp
        focusSegmentStartedAt = timestamp
        focusIntervals = []
    }

    public mutating func pauseFocus(at timestamp: TimeInterval) {
        closeFocusSegment(at: timestamp)
    }

    public mutating func resumeFocus(at timestamp: TimeInterval) {
        if focusStartedAt != nil, focusSegmentStartedAt == nil {
            focusSegmentStartedAt = timestamp
        }
    }

    public mutating func finishFocus(at timestamp: TimeInterval, completed: Bool, timeZone: TimeZone = .current) -> FocusSession? {
        guard let startedAt = focusStartedAt else { return nil }
        closeFocusSegment(at: timestamp)
        let intervals = focusIntervals
        let focusedSeconds = intervals.reduce(0) { $0 + $1.duration }
        focusStartedAt = nil
        focusSegmentStartedAt = nil
        focusIntervals = []
        return FocusSession(
            startedAt: startedAt,
            endedAt: max(startedAt, timestamp),
            completed: completed,
            focusedSeconds: focusedSeconds,
            timeZoneIdentifier: timeZone.identifier,
            legacyEstimated: false,
            focusIntervals: intervals
        )
    }

    private mutating func closeFocusSegment(at timestamp: TimeInterval) {
        guard let segmentStart = focusSegmentStartedAt else { return }
        let end = max(segmentStart, timestamp)
        if end > segmentStart { focusIntervals.append(FocusInterval(startedAt: segmentStart, endedAt: end)) }
        focusSegmentStartedAt = nil
    }
}

public struct FocusInterval: Codable, Equatable, Sendable, Identifiable {
    public var startedAt: TimeInterval
    public var endedAt: TimeInterval
    public var id: String { "\(startedAt)-\(endedAt)" }
    public var duration: TimeInterval { max(0, endedAt - startedAt) }

    public init(startedAt: TimeInterval, endedAt: TimeInterval) {
        self.startedAt = startedAt
        self.endedAt = max(startedAt, endedAt)
    }

    enum CodingKeys: String, CodingKey {
        case startedAt = "started_at"
        case endedAt = "ended_at"
    }
}

public struct FocusSession: Identifiable, Codable, Equatable, Sendable {
    public var id: String
    public var startedAt: TimeInterval
    public var endedAt: TimeInterval?
    public var completed: Bool
    public var focusedSeconds: TimeInterval
    public var timeZoneIdentifier: String
    public var legacyEstimated: Bool
    public var focusIntervals: [FocusInterval]

    public init(
        id: String = UUID().uuidString,
        startedAt: TimeInterval,
        endedAt: TimeInterval? = nil,
        completed: Bool = false,
        focusedSeconds: TimeInterval? = nil,
        timeZoneIdentifier: String = TimeZone.current.identifier,
        legacyEstimated: Bool = false,
        focusIntervals: [FocusInterval] = []
    ) {
        self.id = id
        self.startedAt = startedAt
        self.endedAt = endedAt
        self.completed = completed
        self.focusedSeconds = max(0, focusedSeconds ?? endedAt.map { $0 - startedAt } ?? 0)
        self.timeZoneIdentifier = timeZoneIdentifier
        self.legacyEstimated = legacyEstimated
        self.focusIntervals = focusIntervals.isEmpty && endedAt != nil
            ? [FocusInterval(startedAt: startedAt, endedAt: endedAt!)]
            : focusIntervals
    }

    enum CodingKeys: String, CodingKey {
        case id, completed, intervals
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case focusedSeconds = "focused_seconds"
        case timeZoneIdentifier = "time_zone"
        case legacyEstimated = "legacy_estimated"
        case focusIntervals = "focus_intervals"
    }

    private struct LegacyInterval: Codable {
        var start: TimeInterval
        var end: TimeInterval?
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = (try? values.decode(String.self, forKey: .id)) ?? UUID().uuidString
        completed = (try? values.decode(Bool.self, forKey: .completed)) ?? false
        let intervals = (try? values.decode([LegacyInterval].self, forKey: .intervals)) ?? []
        startedAt = (try? values.decode(TimeInterval.self, forKey: .startedAt))
            ?? intervals.first?.start
            ?? 0
        endedAt = (try? values.decodeIfPresent(TimeInterval.self, forKey: .endedAt))
            ?? intervals.compactMap(\.end).max()
        let hasPreciseDuration = values.contains(.focusedSeconds)
        if let precise = try? values.decode(TimeInterval.self, forKey: .focusedSeconds) {
            focusedSeconds = max(0, precise)
        } else if let end = endedAt {
            focusedSeconds = max(0, end - startedAt)
        } else {
            focusedSeconds = 0
        }
        timeZoneIdentifier = (try? values.decode(String.self, forKey: .timeZoneIdentifier))
            ?? TimeZone.current.identifier
        legacyEstimated = (try? values.decode(Bool.self, forKey: .legacyEstimated)) ?? !hasPreciseDuration
        focusIntervals = (try? values.decode([FocusInterval].self, forKey: .focusIntervals)) ?? []
        if focusIntervals.isEmpty, let endedAt, endedAt > startedAt {
            focusIntervals = [FocusInterval(startedAt: startedAt, endedAt: endedAt)]
        }
    }

    public func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encode(startedAt, forKey: .startedAt)
        try values.encodeIfPresent(endedAt, forKey: .endedAt)
        try values.encode(completed, forKey: .completed)
        try values.encode(focusedSeconds, forKey: .focusedSeconds)
        try values.encode(timeZoneIdentifier, forKey: .timeZoneIdentifier)
        try values.encode(legacyEstimated, forKey: .legacyEstimated)
        try values.encode(focusIntervals, forKey: .focusIntervals)
    }
}

public struct PomodoroStats: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var sessions: [FocusSession]
    public var syncRevision: TimeInterval

    public init(
        schemaVersion: Int = 2,
        sessions: [FocusSession] = [],
        syncRevision: TimeInterval = 0
    ) {
        self.schemaVersion = schemaVersion
        self.sessions = sessions
        self.syncRevision = syncRevision
    }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case sessions
        case syncRevision = "sync_revision"
    }

    public init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        schemaVersion = 2
        sessions = ((try? values.decode([FocusSession].self, forKey: .sessions)) ?? [])
            .filter { $0.endedAt != nil }
        syncRevision = (try? values.decode(TimeInterval.self, forKey: .syncRevision)) ?? 0
    }
}
