import AppKit
import Combine
import Foundation
import MultiTimerCore

@MainActor
final class AppModel: ObservableObject {
    static let shared = AppModel()

    @Published private(set) var timers: [TimerRecord]
    @Published var settings: AppSettings
    @Published private(set) var now = Date().timeIntervalSince1970
    @Published private(set) var pomodoro: PomodoroSnapshot
    @Published private(set) var stats: PomodoroStats
    @Published private(set) var presets: [TimerPreset]
    @Published private(set) var cloudSyncAvailability: CloudSyncAvailability = .localOnly

    private let stateStore: StateStore
    private let statsStore: StatsStore
    private var document: StateDocument
    private var ticker: Timer?
    private var notifiedTimerIDs = Set<String>()

    var onStatusChanged: (() -> Void)?
    var onPersistenceChanged: (() -> Void)?
    var onTimerFinished: ((TimerRecord) -> Void)?
    var onPomodoroFinished: ((PomodoroPhase) -> Void)?
    var onPresetTimerStarted: ((TimerRecord, TimerPreset) -> Void)?
    var onTimerScheduled: ((TimerRecord) -> Void)?
    var onTimerRemoved: ((String) -> Void)?

    init(stateStore: StateStore = StateStore(), statsStore: StatsStore = StatsStore()) {
        self.stateStore = stateStore
        self.statsStore = statsStore
        document = stateStore.load()
        timers = document.timers
        settings = document.settings
        pomodoro = document.pomodoro
        stats = statsStore.load()
        presets = PresetCollection.normalized(document.presets)
        if pomodoro.phase == .work, pomodoro.focusStartedAt == nil {
            if let pausedRemaining = pomodoro.pausedRemaining {
                let elapsed = max(0, TimeInterval(settings.pomodoroWorkSeconds) - pausedRemaining)
                pomodoro.focusStartedAt = max(0, now - elapsed)
            } else {
                pomodoro.focusStartedAt = max(0, (pomodoro.finishAt ?? now) - TimeInterval(settings.pomodoroWorkSeconds))
            }
        }
        if pomodoro.phase == .work, pomodoro.pausedRemaining == nil, pomodoro.focusSegmentStartedAt == nil {
            pomodoro.focusSegmentStartedAt = pomodoro.focusStartedAt
        }
        if pomodoro.phase == .work,
           pomodoro.pausedRemaining != nil,
           pomodoro.focusIntervals.isEmpty,
           let startedAt = pomodoro.focusStartedAt {
            let elapsed = max(0, TimeInterval(settings.pomodoroWorkSeconds) - (pomodoro.pausedRemaining ?? 0))
            if elapsed > 0 {
                pomodoro.focusIntervals = [FocusInterval(startedAt: startedAt, endedAt: startedAt + elapsed)]
            }
        }
        try? statsStore.save(stats)

        ticker = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    deinit { ticker?.invalidate() }

    var sortedTimers: [TimerRecord] {
        timers.sorted { lhs, rhs in
            if lhs.pinned != rhs.pinned { return lhs.pinned }
            if lhs.finished != rhs.finished { return lhs.finished }
            if settings.sortByExpiry, lhs.kind == .countdown, rhs.kind == .countdown {
                return (lhs.endTS ?? .greatestFiniteMagnitude) < (rhs.endTS ?? .greatestFiniteMagnitude)
            }
            return lhs.startTS < rhs.startTS
        }
    }

    var activeCount: Int { timers.filter { !$0.finished }.count }

    var nearestRemaining: TimeInterval? {
        timers
            .filter { $0.kind == .countdown && !$0.finished }
            .map { $0.remaining(at: now) }
            .min()
    }

    var nearestStopwatchElapsed: TimeInterval? {
        timers
            .filter { $0.kind == .stopwatch && !$0.finished }
            .map { $0.elapsed(at: now) }
            .max()
    }

    var pomodoroRemaining: TimeInterval {
        if let paused = pomodoro.pausedRemaining { return max(0, paused) }
        guard let finishAt = pomodoro.finishAt else { return 0 }
        return max(0, finishAt - now)
    }

    var todayCount: Int {
        todaySummary.completedPomodoros
    }

    var todayFocusSessionCount: Int {
        todaySummary.focusSessions
    }

    var todayFocusedSeconds: TimeInterval { todaySummary.focusedSeconds }

    var todayGoalMinutes: Int? {
        FocusAnalytics.targetMinutes(
            on: FocusAnalytics.dayKey(for: Date(timeIntervalSince1970: now)),
            goals: settings.dailyFocusGoals
        )
    }

    var currentFocusStreak: Int {
        FocusAnalytics.currentStreak(
            stats: stats,
            goals: settings.dailyFocusGoals,
            now: Date(timeIntervalSince1970: now)
        )
    }

    private var todaySummary: DailyFocusSummary {
        let key = FocusAnalytics.dayKey(for: Date(timeIntervalSince1970: now))
        return FocusAnalytics.dailySummaries(from: stats)[key] ?? DailyFocusSummary(day: key)
    }

    @discardableResult
    func startCountdown(
        label: String,
        seconds: Int,
        color: PresetColor? = nil,
        sound: PresetSound? = nil,
        earlyReminderMinutes: Int? = nil
    ) -> TimerRecord {
        let duration = min(max(1, seconds), DurationParser.maximumSeconds)
        let start = Date().timeIntervalSince1970
        let timer = TimerRecord(
            label: cleanLabel(label, kind: .countdown),
            kind: .countdown,
            startTS: start,
            endTS: start + TimeInterval(duration),
            originalDuration: TimeInterval(duration),
            color: color,
            sound: sound,
            earlyReminderMinutes: earlyReminderMinutes
        )
        timers.append(timer)
        save()
        onTimerScheduled?(timer)
        return timer
    }

    func startCountdown(label: String, target: Date) {
        let start = Date().timeIntervalSince1970
        let duration = max(1, target.timeIntervalSince1970 - start)
        let timer = TimerRecord(
            label: cleanLabel(label, kind: .countdown),
            kind: .countdown,
            startTS: start,
            endTS: target.timeIntervalSince1970,
            originalDuration: duration
        )
        timers.append(timer)
        save()
        onTimerScheduled?(timer)
    }

    func startPreset(_ preset: TimerPreset) {
        let timer = startCountdown(
            label: preset.name,
            seconds: preset.durationSeconds,
            color: preset.color,
            sound: preset.sound,
            earlyReminderMinutes: preset.earlyReminderMinutes
        )
        onPresetTimerStarted?(timer, preset)
    }

    func savePreset(_ preset: TimerPreset) {
        var value = preset
        value.sync = nextSyncMetadata(after: preset.sync)
        if let index = presets.firstIndex(where: { $0.id == value.id }) {
            presets[index] = value
        } else {
            value.sortOrder = presets.count
            presets.append(value)
        }
        presets = PresetCollection.normalized(presets)
        save()
    }

    func deletePreset(_ id: String) {
        presets.removeAll { $0.id == id }
        presets = PresetCollection.normalized(presets)
        save()
    }

    func togglePresetFavorite(_ id: String) {
        guard let index = presets.firstIndex(where: { $0.id == id }) else { return }
        if presets[index].favoriteRank != nil {
            presets[index].favoriteRank = nil
        } else {
            let favorites = PresetCollection.favorites(presets)
            guard favorites.count < 4 else { return }
            presets[index].favoriteRank = favorites.count
        }
        presets[index].sync = nextSyncMetadata(after: presets[index].sync)
        presets = PresetCollection.normalized(presets)
        save()
    }

    func movePreset(_ id: String, before targetID: String) {
        guard id != targetID,
              let source = presets.firstIndex(where: { $0.id == id }),
              let target = presets.firstIndex(where: { $0.id == targetID }) else { return }
        let value = presets.remove(at: source)
        let insertion = source < target ? target - 1 : target
        presets.insert(value, at: max(0, insertion))
        for index in presets.indices {
            presets[index].sortOrder = index
            presets[index].sync = nextSyncMetadata(after: presets[index].sync)
        }
        save()
    }

    func startStopwatch(label: String) {
        timers.append(TimerRecord(label: cleanLabel(label, kind: .stopwatch), kind: .stopwatch))
        save()
    }

    func rename(_ id: String, label: String) {
        guard let kind = timers.first(where: { $0.id == id })?.kind else { return }
        mutate(id) { $0.label = cleanLabel(label, kind: kind) }
    }

    func togglePause(_ id: String) {
        let timestamp = Date().timeIntervalSince1970
        mutate(id) { timer in
            if let pausedAt = timer.pausedAt {
                let pauseDuration = timestamp - pausedAt
                timer.startTS += pauseDuration
                if timer.endTS != nil { timer.endTS! += pauseDuration }
                timer.pausedAt = nil
            } else if !timer.finished {
                timer.pausedAt = timestamp
            }
        }
        if let timer = timers.first(where: { $0.id == id }) {
            timer.isPaused ? onTimerRemoved?(id) : onTimerScheduled?(timer)
        }
    }

    func togglePin(_ id: String) { mutate(id) { $0.pinned.toggle() } }

    func duplicate(_ id: String) {
        guard let source = timers.first(where: { $0.id == id }) else { return }
        if source.kind == .stopwatch {
            startStopwatch(label: source.label)
        } else {
            let duration = Int(source.originalDuration ?? source.remaining(at: now))
            _ = startCountdown(
                label: source.label,
                seconds: max(1, duration),
                color: source.color,
                sound: source.sound,
                earlyReminderMinutes: source.earlyReminderMinutes
            )
        }
    }

    func cancel(_ id: String) {
        timers.removeAll { $0.id == id }
        notifiedTimerIDs.remove(id)
        onTimerRemoved?(id)
        save()
    }

    func restart(_ id: String) {
        let timestamp = Date().timeIntervalSince1970
        mutate(id) { timer in
            timer.finished = false
            timer.pausedAt = nil
            timer.startTS = timestamp
            if timer.kind == .countdown {
                timer.endTS = timestamp + max(1, timer.originalDuration ?? 60)
            }
            timer.laps = []
        }
        notifiedTimerIDs.remove(id)
        if let timer = timers.first(where: { $0.id == id }) { onTimerScheduled?(timer) }
    }

    func setRemaining(_ id: String, seconds: Int) {
        let timestamp = Date().timeIntervalSince1970
        mutate(id) { timer in
            guard timer.kind == .countdown else { return }
            let duration = TimeInterval(min(max(1, seconds), DurationParser.maximumSeconds))
            let reference = timer.pausedAt ?? timestamp
            timer.endTS = reference + duration
            timer.originalDuration = duration
            timer.finished = false
        }
        notifiedTimerIDs.remove(id)
        if let timer = timers.first(where: { $0.id == id }) { onTimerScheduled?(timer) }
    }

    func setTarget(_ id: String, target: Date) {
        setRemaining(id, seconds: Int(max(1, target.timeIntervalSinceNow)))
    }

    func addLap(_ id: String) {
        let timestamp = Date().timeIntervalSince1970
        mutate(id) { timer in
            guard timer.kind == .stopwatch, !timer.finished else { return }
            timer.laps.append(timer.elapsed(at: timestamp))
        }
    }

    func startPomodoro() {
        let timestamp = Date().timeIntervalSince1970
        switch pomodoro.phase {
        case .idle, .ready:
            beginWork(at: timestamp)
        case .work, .rest, .longRest:
            if let paused = pomodoro.pausedRemaining {
                pomodoro.finishAt = timestamp + paused
                pomodoro.pausedRemaining = nil
                if pomodoro.phase == .work { pomodoro.resumeFocus(at: timestamp) }
            }
        }
        touchPomodoro()
        save()
        onStatusChanged?()
    }

    func togglePomodoroPause() {
        guard pomodoro.phase == .work || pomodoro.phase == .rest || pomodoro.phase == .longRest else { return }
        let timestamp = Date().timeIntervalSince1970
        if let paused = pomodoro.pausedRemaining {
            pomodoro.finishAt = timestamp + paused
            pomodoro.pausedRemaining = nil
            if pomodoro.phase == .work { pomodoro.resumeFocus(at: timestamp) }
        } else {
            if pomodoro.phase == .work { pomodoro.pauseFocus(at: timestamp) }
            pomodoro.pausedRemaining = max(0, (pomodoro.finishAt ?? timestamp) - timestamp)
            pomodoro.finishAt = nil
        }
        touchPomodoro()
        save()
        onStatusChanged?()
    }

    func skipPomodoro() {
        let timestamp = Date().timeIntervalSince1970
        switch pomodoro.phase {
        case .work:
            finishFocusSession(completed: false, at: timestamp)
            beginRest(at: timestamp)
        case .rest, .longRest:
            if pomodoro.phase == .longRest { pomodoro.completedRounds = 0 }
            beginWork(at: timestamp)
        case .ready, .idle:
            beginWork(at: timestamp)
        }
        touchPomodoro()
        save()
    }

    func extendPomodoro(by seconds: Int = 300) {
        guard pomodoro.phase == .work || pomodoro.phase == .rest || pomodoro.phase == .longRest else { return }
        let timestamp = Date().timeIntervalSince1970
        if pomodoro.pausedRemaining != nil {
            pomodoro.pausedRemaining! += TimeInterval(seconds)
        } else {
            pomodoro.finishAt = (pomodoro.finishAt ?? timestamp) + TimeInterval(seconds)
        }
        touchPomodoro()
        save()
        onStatusChanged?()
    }

    func stopPomodoro() {
        let timestamp = Date().timeIntervalSince1970
        if pomodoro.phase == .work { finishFocusSession(completed: false, at: timestamp) }
        pomodoro = PomodoroSnapshot()
        touchPomodoro()
        save()
        onStatusChanged?()
    }

    func updateSettings(_ update: (inout AppSettings) -> Void) {
        update(&settings)
        settings.pomodoroWorkSeconds = min(max(60, settings.pomodoroWorkSeconds), 7_200)
        settings.pomodoroBreakSeconds = min(max(60, settings.pomodoroBreakSeconds), 3_600)
        settings.pomodoroLongBreakSeconds = min(max(60, settings.pomodoroLongBreakSeconds), 7_200)
        settings.pomodoroRoundsBeforeLongBreak = min(max(2, settings.pomodoroRoundsBeforeLongBreak), 12)
        settings.syncRevision = Date().timeIntervalSince1970
        save()
    }

    func clearStats() {
        stats = PomodoroStats(syncRevision: Date().timeIntervalSince1970)
        try? statsStore.save(stats)
        onPersistenceChanged?()
    }

    func setDailyFocusGoal(minutes: Int?) {
        let day = FocusAnalytics.dayKey(for: Date(timeIntervalSince1970: now))
        let target = minutes.map { min(max(15, Int((Double($0) / 15).rounded()) * 15), 480) }
        settings.dailyFocusGoals.removeAll { $0.effectiveDay == day }
        settings.dailyFocusGoals.append(DailyFocusGoal(effectiveDay: day, targetMinutes: target))
        settings.dailyFocusGoals.sort { $0.effectiveDay < $1.effectiveDay }
        settings.hasSeenFocusGoalPrompt = true
        settings.syncRevision = Date().timeIntervalSince1970
        save()
    }

    func dismissFocusGoalPrompt() {
        settings.hasSeenFocusGoalPrompt = true
        settings.syncRevision = Date().timeIntervalSince1970
        save()
    }

    func skip(version: String) {
        document.skippedUpdate = version
        save()
    }

    var skippedUpdate: String? { document.skippedUpdate }

    var sharedTimerStates: [SharedTimerState] {
        var result = timers.map(SharedTimerState.init(timer:))
        if pomodoro.phase != .idle {
            result.append(SharedTimerState(
                id: "pomodoro",
                label: NSLocalizedString("Pomodoro", comment: "Shared timer name"),
                kind: .pomodoro,
                startedAt: pomodoro.focusStartedAt ?? now,
                endsAt: pomodoro.finishAt,
                pausedAt: pomodoro.pausedRemaining == nil ? nil : now,
                pausedValue: pomodoro.pausedRemaining,
                pomodoroPhase: pomodoro.phase,
                completedRounds: pomodoro.completedRounds,
                sync: pomodoro.sync
            ))
        }
        return result
    }

    func setCloudSyncAvailability(_ value: CloudSyncAvailability) {
        cloudSyncAvailability = value
    }

    func mergeCloud(
        presets cloudPresets: [TimerPreset],
        timers cloudTimers: [SharedTimerState],
        settings cloudSettings: AppSettings?
    ) {
        var changed = false
        for incoming in cloudPresets {
            if incoming.sync.tombstone {
                let oldCount = presets.count
                presets.removeAll { $0.id == incoming.id }
                changed = changed || presets.count != oldCount
            } else if let index = presets.firstIndex(where: { $0.id == incoming.id }) {
                if incoming.sync.supersedes(presets[index].sync) {
                    presets[index] = incoming
                    changed = true
                }
            } else {
                presets.append(incoming)
                changed = true
            }
        }
        presets = PresetCollection.normalized(presets)

        for incoming in cloudTimers {
            if incoming.kind == .pomodoro {
                guard incoming.sync.supersedes(pomodoro.sync) else { continue }
                if incoming.isDeleted || incoming.finished {
                    pomodoro = PomodoroSnapshot()
                } else {
                    pomodoro.phase = incoming.pomodoroPhase ?? .ready
                    pomodoro.finishAt = incoming.endsAt
                    pomodoro.pausedRemaining = incoming.pausedValue
                    pomodoro.completedRounds = incoming.completedRounds
                    pomodoro.sync = incoming.sync
                    if pomodoro.phase == .work, pomodoro.focusStartedAt == nil {
                        pomodoro.beginFocus(at: max(incoming.startedAt, now))
                    }
                }
                changed = true
            } else if incoming.isDeleted {
                let oldCount = timers.count
                timers.removeAll { $0.id == incoming.id }
                onTimerRemoved?(incoming.id)
                changed = changed || timers.count != oldCount
            } else if let record = incoming.timerRecord() {
                if record.kind == .countdown,
                   !record.finished,
                   record.endTS.map({ $0 <= now }) == true {
                    notifiedTimerIDs.insert(record.id)
                }
                if let index = timers.firstIndex(where: { $0.id == incoming.id }) {
                    if incoming.sync.supersedes(timers[index].sync) {
                        timers[index] = record
                        changed = true
                        record.isPaused ? onTimerRemoved?(record.id) : onTimerScheduled?(record)
                    }
                } else {
                    timers.append(record)
                    changed = true
                    if !record.finished { onTimerScheduled?(record) }
                }
            }
        }

        if let cloudSettings, cloudSettings.syncRevision > settings.syncRevision {
            settings = cloudSettings
            changed = true
        }
        if changed { save() }
    }

    func mergeCloud(settings cloudSettings: AppSettings?) {
        mergeCloud(presets: [], timers: [], settings: cloudSettings)
    }

    func timer(matching value: String) -> TimerRecord? {
        let needle = value.lowercased()
        return timers.first { $0.id.lowercased().hasPrefix(needle) }
            ?? timers.first { $0.label.lowercased() == needle }
    }

    private func cleanLabel(_ label: String, kind: TimerKind) -> String {
        let clean = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard clean.isEmpty else { return clean }
        let base = kind == .countdown
            ? NSLocalizedString("Countdown", comment: "Default countdown name")
            : NSLocalizedString("Stopwatch", comment: "Default stopwatch name")
        let existing = Set(timers.filter { $0.kind == kind }.map(\.label))
        var number = 1
        while existing.contains("\(base) \(number)") { number += 1 }
        return "\(base) \(number)"
    }

    private func mutate(_ id: String, operation: (inout TimerRecord) -> Void) {
        guard let index = timers.firstIndex(where: { $0.id == id }) else { return }
        operation(&timers[index])
        timers[index].sync = nextSyncMetadata(after: timers[index].sync)
        save()
    }

    private func save() {
        document.schemaVersion = 8
        document.timers = timers
        document.settings = settings
        document.pomodoro = pomodoro
        document.presets = presets
        document.settings = settings
        try? stateStore.save(document)
        onStatusChanged?()
        onPersistenceChanged?()
    }

    private func tick() {
        now = Date().timeIntervalSince1970
        var changed = false
        for index in timers.indices where timers[index].kind == .countdown && !timers[index].finished && !timers[index].isPaused {
            if timers[index].remaining(at: now) <= 0 {
                timers[index].finished = true
                timers[index].sync = nextSyncMetadata(after: timers[index].sync)
                changed = true
                if notifiedTimerIDs.insert(timers[index].id).inserted {
                    onTimerFinished?(timers[index])
                }
            }
        }
        if changed { save() } else { onStatusChanged?() }

        guard pomodoro.pausedRemaining == nil,
              (pomodoro.phase == .work || pomodoro.phase == .rest || pomodoro.phase == .longRest),
              pomodoroRemaining <= 0 else { return }
        let completed = pomodoro.phase
        if completed == .work {
            finishFocusSession(completed: true, at: pomodoro.finishAt ?? now)
            let step = PomodoroCycle.afterNaturalWork(
                completedRounds: pomodoro.completedRounds,
                longBreakEvery: settings.pomodoroRoundsBeforeLongBreak
            )
            pomodoro.completedRounds = step.completedRounds
            beginRest(
                at: now,
                long: step.phase == .longRest
            )
        } else {
            let step = PomodoroCycle.afterBreak(
                completed,
                completedRounds: pomodoro.completedRounds,
                autoCycle: settings.pomodoroAutoCycle
            )
            pomodoro.completedRounds = step.completedRounds
            if step.phase == .work {
                beginWork(at: now)
            } else {
                pomodoro.phase = .ready
                pomodoro.finishAt = nil
            }
        }
        touchPomodoro()
        save()
        onPomodoroFinished?(completed)
        onStatusChanged?()
    }

    private func beginWork(at timestamp: TimeInterval) {
        pomodoro.phase = .work
        pomodoro.pausedRemaining = nil
        pomodoro.finishAt = timestamp + TimeInterval(settings.pomodoroWorkSeconds)
        pomodoro.beginFocus(at: timestamp)
        onStatusChanged?()
    }

    private func beginRest(at timestamp: TimeInterval, long: Bool = false) {
        pomodoro.phase = long ? .longRest : .rest
        pomodoro.pausedRemaining = nil
        let duration = long ? settings.pomodoroLongBreakSeconds : settings.pomodoroBreakSeconds
        pomodoro.finishAt = timestamp + TimeInterval(duration)
        pomodoro.focusStartedAt = nil
        onStatusChanged?()
    }

    private func nextSyncMetadata(after metadata: SyncMetadata) -> SyncMetadata {
        SyncMetadata(
            deviceID: DeviceIdentity.current,
            revision: metadata.revision + 1,
            modifiedAt: Date().timeIntervalSince1970
        )
    }

    private func touchPomodoro() {
        pomodoro.sync = nextSyncMetadata(after: pomodoro.sync)
    }

    private func finishFocusSession(completed: Bool, at endedAt: TimeInterval) {
        guard let session = pomodoro.finishFocus(at: endedAt, completed: completed) else { return }
        stats.sessions.append(session)
        persistStats()
    }

    private func persistStats() {
        stats.syncRevision = Date().timeIntervalSince1970
        try? statsStore.save(stats)
        onPersistenceChanged?()
    }
}
