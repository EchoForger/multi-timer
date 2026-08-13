import Foundation

public enum PresetColor: String, Codable, CaseIterable, Sendable {
    case blue, green, orange, pink, purple, red, teal, yellow
}

public enum PresetSoundKind: String, Codable, CaseIterable, Sendable {
    case system
    case muted
}

public struct PresetSound: Codable, Equatable, Sendable {
    public var kind: PresetSoundKind
    public var name: String?

    public init(kind: PresetSoundKind = .system, name: String? = "Glass") {
        self.kind = kind
        self.name = kind == .muted ? nil : name
    }

    public static let muted = PresetSound(kind: .muted, name: nil)
    public static let systemDefault = PresetSound()
}

public struct SyncMetadata: Codable, Equatable, Sendable {
    public var deviceID: String
    public var actionID: String
    public var revision: Int64
    public var modifiedAt: TimeInterval
    public var tombstone: Bool

    public init(
        deviceID: String,
        actionID: String = UUID().uuidString,
        revision: Int64 = 0,
        modifiedAt: TimeInterval = Date().timeIntervalSince1970,
        tombstone: Bool = false
    ) {
        self.deviceID = deviceID
        self.actionID = actionID
        self.revision = revision
        self.modifiedAt = modifiedAt
        self.tombstone = tombstone
    }

    public func supersedes(_ other: SyncMetadata) -> Bool {
        if revision != other.revision { return revision > other.revision }
        if modifiedAt != other.modifiedAt { return modifiedAt > other.modifiedAt }
        return actionID > other.actionID
    }
}

public struct TimerPreset: Identifiable, Codable, Equatable, Sendable {
    public var id: String
    public var name: String
    public var durationSeconds: Int
    public var color: PresetColor
    public var sound: PresetSound
    public var earlyReminderMinutes: Int?
    public var sortOrder: Int
    public var favoriteRank: Int?
    public var sync: SyncMetadata

    public init(
        id: String = UUID().uuidString,
        name: String,
        durationSeconds: Int,
        color: PresetColor = .blue,
        sound: PresetSound = .systemDefault,
        earlyReminderMinutes: Int? = nil,
        sortOrder: Int = 0,
        favoriteRank: Int? = nil,
        sync: SyncMetadata = SyncMetadata(deviceID: DeviceIdentity.current)
    ) {
        self.id = id
        self.name = name.trimmingCharacters(in: .whitespacesAndNewlines)
        self.durationSeconds = min(max(1, durationSeconds), DurationParser.maximumSeconds)
        self.color = color
        self.sound = sound
        if let earlyReminderMinutes, [1, 5, 10].contains(earlyReminderMinutes) {
            self.earlyReminderMinutes = earlyReminderMinutes
        } else {
            self.earlyReminderMinutes = nil
        }
        self.sortOrder = max(0, sortOrder)
        self.favoriteRank = favoriteRank.map { min(max(0, $0), 3) }
        self.sync = sync
    }
}

public enum SharedTimerKind: String, Codable, Sendable {
    case countdown
    case stopwatch
    case pomodoro
}

public struct SharedTimerState: Identifiable, Codable, Equatable, Sendable {
    public var id: String
    public var label: String
    public var kind: SharedTimerKind
    public var startedAt: TimeInterval
    public var endsAt: TimeInterval?
    public var pausedAt: TimeInterval?
    public var pausedValue: TimeInterval?
    public var pomodoroPhase: PomodoroPhase?
    public var completedRounds: Int
    public var isPrimaryPinned: Bool
    public var finished: Bool
    public var originalDuration: TimeInterval?
    public var color: PresetColor?
    public var sound: PresetSound?
    public var earlyReminderMinutes: Int?
    public var sync: SyncMetadata

    public init(
        id: String = UUID().uuidString,
        label: String,
        kind: SharedTimerKind,
        startedAt: TimeInterval = Date().timeIntervalSince1970,
        endsAt: TimeInterval? = nil,
        pausedAt: TimeInterval? = nil,
        pausedValue: TimeInterval? = nil,
        pomodoroPhase: PomodoroPhase? = nil,
        completedRounds: Int = 0,
        isPrimaryPinned: Bool = false,
        finished: Bool = false,
        originalDuration: TimeInterval? = nil,
        color: PresetColor? = nil,
        sound: PresetSound? = nil,
        earlyReminderMinutes: Int? = nil,
        sync: SyncMetadata = SyncMetadata(deviceID: DeviceIdentity.current)
    ) {
        self.id = id
        self.label = label
        self.kind = kind
        self.startedAt = startedAt
        self.endsAt = endsAt
        self.pausedAt = pausedAt
        self.pausedValue = pausedValue
        self.pomodoroPhase = pomodoroPhase
        self.completedRounds = max(0, completedRounds)
        self.isPrimaryPinned = isPrimaryPinned
        self.finished = finished
        self.originalDuration = originalDuration
        self.color = color
        self.sound = sound
        self.earlyReminderMinutes = earlyReminderMinutes
        self.sync = sync
    }

    public var isDeleted: Bool { sync.tombstone }

    public func remaining(at timestamp: TimeInterval) -> TimeInterval {
        if let pausedValue { return max(0, pausedValue) }
        return max(0, (endsAt ?? timestamp) - timestamp)
    }
}

public enum TimerActionKind: String, Codable, Sendable {
    case start, pause, resume, extend, skip, finish, delete, pinPrimary
}

public struct TimerAction: Identifiable, Codable, Equatable, Sendable {
    public var id: String
    public var timerID: String
    public var kind: TimerActionKind
    public var value: TimeInterval?
    public var occurredAt: TimeInterval
    public var deviceID: String
    public var serverRevision: Int64

    public init(
        id: String = UUID().uuidString,
        timerID: String,
        kind: TimerActionKind,
        value: TimeInterval? = nil,
        occurredAt: TimeInterval = Date().timeIntervalSince1970,
        deviceID: String = DeviceIdentity.current,
        serverRevision: Int64 = 0
    ) {
        self.id = id
        self.timerID = timerID
        self.kind = kind
        self.value = value
        self.occurredAt = occurredAt
        self.deviceID = deviceID
        self.serverRevision = serverRevision
    }
}

public enum SharedTimerReducer {
    @discardableResult
    public static func apply(
        _ action: TimerAction,
        to state: inout SharedTimerState,
        appliedActionIDs: inout Set<String>
    ) -> Bool {
        guard action.timerID == state.id, appliedActionIDs.insert(action.id).inserted else { return false }
        guard action.serverRevision >= state.sync.revision else { return false }
        switch action.kind {
        case .start:
            state.startedAt = action.occurredAt
            if let value = action.value { state.endsAt = action.occurredAt + value }
            state.pausedAt = nil
            state.pausedValue = nil
            state.sync.tombstone = false
        case .pause:
            state.pausedAt = action.occurredAt
            state.pausedValue = state.kind == .stopwatch
                ? max(0, action.occurredAt - state.startedAt)
                : state.remaining(at: action.occurredAt)
        case .resume:
            if let pausedValue = state.pausedValue {
                if state.kind == .stopwatch {
                    state.startedAt = action.occurredAt - pausedValue
                } else {
                    state.endsAt = action.occurredAt + pausedValue
                }
            }
            state.pausedAt = nil
            state.pausedValue = nil
        case .extend:
            let extensionValue = max(0, action.value ?? 0)
            if state.pausedValue != nil { state.pausedValue! += extensionValue }
            else { state.endsAt = (state.endsAt ?? action.occurredAt) + extensionValue }
        case .skip, .finish:
            state.endsAt = action.occurredAt
            state.pausedAt = nil
            state.pausedValue = nil
            state.finished = true
        case .delete:
            state.sync.tombstone = true
        case .pinPrimary:
            state.isPrimaryPinned = action.value != 0
        }
        state.sync = SyncMetadata(
            deviceID: action.deviceID,
            actionID: action.id,
            revision: action.serverRevision,
            modifiedAt: action.occurredAt,
            tombstone: state.sync.tombstone
        )
        return true
    }
}

public enum PresetCollection {
    public static func normalized(_ presets: [TimerPreset]) -> [TimerPreset] {
        var result = presets.sorted {
            if $0.sortOrder != $1.sortOrder { return $0.sortOrder < $1.sortOrder }
            return $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending
        }
        let favorites = result.indices
            .filter { result[$0].favoriteRank != nil }
            .sorted { result[$0].favoriteRank! < result[$1].favoriteRank! }
        for (rank, index) in favorites.enumerated() {
            result[index].favoriteRank = rank < 4 ? rank : nil
        }
        for index in result.indices { result[index].sortOrder = index }
        return result
    }

    public static func favorites(_ presets: [TimerPreset]) -> [TimerPreset] {
        normalized(presets).filter { $0.favoriteRank != nil }.sorted { $0.favoriteRank! < $1.favoriteRank! }
    }
}

public enum PrimaryTimerSelection {
    public static func select(from timers: [SharedTimerState]) -> SharedTimerState? {
        let active = timers.filter { !$0.isDeleted && !$0.finished }
        return active.filter(\.isPrimaryPinned).max { $0.sync.modifiedAt < $1.sync.modifiedAt }
            ?? active.max { $0.sync.modifiedAt < $1.sync.modifiedAt }
    }
}

public extension SharedTimerState {
    init(timer: TimerRecord) {
        self.init(
            id: timer.id,
            label: timer.label,
            kind: timer.kind == .countdown ? .countdown : .stopwatch,
            startedAt: timer.startTS,
            endsAt: timer.endTS,
            pausedAt: timer.pausedAt,
            pausedValue: timer.pausedAt.map {
                timer.kind == .countdown ? timer.remaining(at: $0) : timer.elapsed(at: $0)
            },
            isPrimaryPinned: timer.pinned,
            finished: timer.finished,
            originalDuration: timer.originalDuration,
            color: timer.color,
            sound: timer.sound,
            earlyReminderMinutes: timer.earlyReminderMinutes,
            sync: timer.sync
        )
    }

    func timerRecord() -> TimerRecord? {
        guard kind != .pomodoro else { return nil }
        return TimerRecord(
            id: id,
            label: label,
            kind: kind == .countdown ? .countdown : .stopwatch,
            startTS: startedAt,
            endTS: endsAt,
            pausedAt: pausedAt,
            pinned: isPrimaryPinned,
            finished: finished,
            originalDuration: originalDuration,
            color: color,
            sound: sound,
            earlyReminderMinutes: earlyReminderMinutes,
            sync: sync
        )
    }
}

public enum CloudSyncAvailability: String, Codable, Sendable {
    case localOnly
    case syncing
    case current
    case paused
}

public struct SharedStateDocument: Codable, Equatable, Sendable {
    public var schemaVersion: Int
    public var presets: [TimerPreset]
    public var timers: [SharedTimerState]
    public var settings: AppSettings
    public var appliedActionIDs: Set<String>

    public init(
        schemaVersion: Int = 1,
        presets: [TimerPreset] = [],
        timers: [SharedTimerState] = [],
        settings: AppSettings = AppSettings(),
        appliedActionIDs: Set<String> = []
    ) {
        self.schemaVersion = schemaVersion
        self.presets = PresetCollection.normalized(presets)
        self.timers = timers
        self.settings = settings
        self.appliedActionIDs = appliedActionIDs
    }
}

public final class SharedStateStore: @unchecked Sendable {
    public let url: URL

    public init(url: URL) { self.url = url }

    public func load() -> SharedStateDocument {
        AtomicJSON.load(SharedStateDocument.self, from: url, fallback: SharedStateDocument())
    }

    public func save(_ document: SharedStateDocument) throws {
        try AtomicJSON.save(document, to: url)
    }
}

public enum DeviceIdentity {
    public static var current: String {
        let key = "io.github.echoforger.multitimer.device-id"
        if let value = UserDefaults.standard.string(forKey: key) { return value }
        let value = UUID().uuidString
        UserDefaults.standard.set(value, forKey: key)
        return value
    }
}
