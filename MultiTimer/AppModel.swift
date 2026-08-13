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

    private let stateStore: StateStore
    private let statsStore: StatsStore
    private var document: StateDocument
    private var ticker: Timer?
    private var notifiedTimerIDs = Set<String>()

    var onStatusChanged: (() -> Void)?
    var onPersistenceChanged: (() -> Void)?
    var onTimerFinished: ((TimerRecord) -> Void)?
    var onPomodoroFinished: ((PomodoroPhase) -> Void)?

    init(stateStore: StateStore = StateStore(), statsStore: StatsStore = StatsStore()) {
        self.stateStore = stateStore
        self.statsStore = statsStore
        document = stateStore.load()
        timers = document.timers
        settings = document.settings
        pomodoro = document.pomodoro
        stats = statsStore.load()
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

    func startCountdown(label: String, seconds: Int) {
        let duration = min(max(1, seconds), DurationParser.maximumSeconds)
        let start = Date().timeIntervalSince1970
        timers.append(TimerRecord(
            label: cleanLabel(label, kind: .countdown),
            kind: .countdown,
            startTS: start,
            endTS: start + TimeInterval(duration),
            originalDuration: TimeInterval(duration)
        ))
        save()
    }

    func startCountdown(label: String, target: Date) {
        let start = Date().timeIntervalSince1970
        let duration = max(1, target.timeIntervalSince1970 - start)
        timers.append(TimerRecord(
            label: cleanLabel(label, kind: .countdown),
            kind: .countdown,
            startTS: start,
            endTS: target.timeIntervalSince1970,
            originalDuration: duration
        ))
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
    }

    func togglePin(_ id: String) { mutate(id) { $0.pinned.toggle() } }

    func duplicate(_ id: String) {
        guard let source = timers.first(where: { $0.id == id }) else { return }
        if source.kind == .stopwatch {
            startStopwatch(label: source.label)
        } else {
            let duration = Int(source.originalDuration ?? source.remaining(at: now))
            startCountdown(label: source.label, seconds: max(1, duration))
        }
    }

    func cancel(_ id: String) {
        timers.removeAll { $0.id == id }
        notifiedTimerIDs.remove(id)
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
        case .work, .rest:
            if let paused = pomodoro.pausedRemaining {
                pomodoro.finishAt = timestamp + paused
                pomodoro.pausedRemaining = nil
                if pomodoro.phase == .work { pomodoro.resumeFocus(at: timestamp) }
            }
        }
        save()
        onStatusChanged?()
    }

    func togglePomodoroPause() {
        guard pomodoro.phase == .work || pomodoro.phase == .rest else { return }
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
        save()
        onStatusChanged?()
    }

    func skipPomodoro() {
        let timestamp = Date().timeIntervalSince1970
        switch pomodoro.phase {
        case .work:
            finishFocusSession(completed: false, at: timestamp)
            beginRest(at: timestamp)
        case .rest:
            beginWork(at: timestamp)
        case .ready, .idle:
            beginWork(at: timestamp)
        }
        save()
    }

    func extendPomodoro(by seconds: Int = 300) {
        guard pomodoro.phase == .work || pomodoro.phase == .rest else { return }
        let timestamp = Date().timeIntervalSince1970
        if pomodoro.pausedRemaining != nil {
            pomodoro.pausedRemaining! += TimeInterval(seconds)
        } else {
            pomodoro.finishAt = (pomodoro.finishAt ?? timestamp) + TimeInterval(seconds)
        }
        save()
        onStatusChanged?()
    }

    func stopPomodoro() {
        let timestamp = Date().timeIntervalSince1970
        if pomodoro.phase == .work { finishFocusSession(completed: false, at: timestamp) }
        pomodoro = PomodoroSnapshot()
        save()
        onStatusChanged?()
    }

    func updateSettings(_ update: (inout AppSettings) -> Void) {
        update(&settings)
        settings.pomodoroWorkSeconds = min(max(60, settings.pomodoroWorkSeconds), 7_200)
        settings.pomodoroBreakSeconds = min(max(60, settings.pomodoroBreakSeconds), 3_600)
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
        save()
    }

    func dismissFocusGoalPrompt() {
        settings.hasSeenFocusGoalPrompt = true
        save()
    }

    func skip(version: String) {
        document.skippedUpdate = version
        save()
    }

    var skippedUpdate: String? { document.skippedUpdate }

    func mergeCloud(settings cloudSettings: AppSettings?) {
        var changed = false
        if let cloudSettings, cloudSettings.syncRevision > settings.syncRevision {
            settings = cloudSettings
            changed = true
        }
        if changed { save() }
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
        save()
    }

    private func save() {
        document.schemaVersion = 6
        document.timers = timers
        document.settings = settings
        document.pomodoro = pomodoro
        settings.syncRevision = Date().timeIntervalSince1970
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
                changed = true
                if notifiedTimerIDs.insert(timers[index].id).inserted {
                    onTimerFinished?(timers[index])
                }
            }
        }
        if changed { save() } else { onStatusChanged?() }

        guard pomodoro.pausedRemaining == nil,
              (pomodoro.phase == .work || pomodoro.phase == .rest),
              pomodoroRemaining <= 0 else { return }
        let completed = pomodoro.phase
        if completed == .work {
            finishFocusSession(completed: true, at: pomodoro.finishAt ?? now)
            beginRest(at: now)
        } else if settings.pomodoroAutoCycle {
            beginWork(at: now)
        } else {
            pomodoro.phase = .ready
            pomodoro.finishAt = nil
        }
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

    private func beginRest(at timestamp: TimeInterval) {
        pomodoro.phase = .rest
        pomodoro.pausedRemaining = nil
        pomodoro.finishAt = timestamp + TimeInterval(settings.pomodoroBreakSeconds)
        pomodoro.focusStartedAt = nil
        onStatusChanged?()
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
