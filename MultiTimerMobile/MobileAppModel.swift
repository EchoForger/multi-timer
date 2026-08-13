import ActivityKit
import Foundation
import MultiTimerCore
import SwiftUI
import UserNotifications
import WidgetKit

@MainActor
final class MobileAppModel: ObservableObject {
    @Published private(set) var document: SharedStateDocument
    @Published private(set) var now = Date().timeIntervalSince1970
    @Published var pendingEndTimerID: String?
    @Published private(set) var syncAvailability: CloudSyncAvailability = .localOnly

    private let store = MobileAppGroup.store
    private let statsStore = StatsStore()
    private let focusSnapshotURL = MultiTimerPaths.stateURL.deletingLastPathComponent()
        .appendingPathComponent("active-pomodoro.json")
    private var focusSnapshot: PomodoroSnapshot
    private var ticker: Timer?
    private var activity: Activity<MultiTimerActivityAttributes>?
    private var cloudSync: MobileCloudSyncService?

    init() {
        document = store.load()
        focusSnapshot = AtomicJSON.load(
            PomodoroSnapshot.self,
            from: MultiTimerPaths.stateURL.deletingLastPathComponent().appendingPathComponent("active-pomodoro.json"),
            fallback: PomodoroSnapshot()
        )
        ticker = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
        Task { await requestNotifications() }
        cloudSync = MobileCloudSyncService(model: self)
        refreshActivity()
    }

    deinit { ticker?.invalidate() }

    var presets: [TimerPreset] { document.presets }
    var timers: [SharedTimerState] { document.timers.filter { !$0.isDeleted } }
    var favorites: [TimerPreset] { PresetCollection.favorites(presets) }

    func savePreset(_ preset: TimerPreset) {
        var value = preset
        value.sync = nextMetadata(after: value.sync)
        if let index = document.presets.firstIndex(where: { $0.id == value.id }) {
            document.presets[index] = value
        } else {
            value.sortOrder = document.presets.count
            document.presets.append(value)
        }
        document.presets = PresetCollection.normalized(document.presets)
        save()
    }

    func deletePreset(_ id: String) {
        document.presets.removeAll { $0.id == id }
        document.presets = PresetCollection.normalized(document.presets)
        save()
    }

    func toggleFavorite(_ id: String) {
        guard let index = document.presets.firstIndex(where: { $0.id == id }) else { return }
        if document.presets[index].favoriteRank != nil {
            document.presets[index].favoriteRank = nil
        } else {
            guard favorites.count < 4 else { return }
            document.presets[index].favoriteRank = favorites.count
        }
        document.presets[index].sync = nextMetadata(after: document.presets[index].sync)
        document.presets = PresetCollection.normalized(document.presets)
        save()
    }

    func movePresets(from offsets: IndexSet, to destination: Int) {
        var values = document.presets
        values.move(fromOffsets: offsets, toOffset: destination)
        for index in values.indices {
            values[index].sortOrder = index
            values[index].sync = nextMetadata(after: values[index].sync)
        }
        document.presets = values
        save()
    }

    func startPreset(_ preset: TimerPreset) {
        let now = Date().timeIntervalSince1970
        let timer = SharedTimerState(
            label: preset.name,
            kind: .countdown,
            startedAt: now,
            endsAt: now + TimeInterval(preset.durationSeconds),
            originalDuration: TimeInterval(preset.durationSeconds),
            color: preset.color,
            sound: preset.sound,
            earlyReminderMinutes: preset.earlyReminderMinutes
        )
        document.timers.append(timer)
        scheduleNotifications(for: timer)
        save()
    }

    func startStopwatch() {
        document.timers.append(SharedTimerState(
            label: nextName(prefix: String(localized: "Stopwatch"), kind: .stopwatch),
            kind: .stopwatch
        ))
        save()
    }

    func startPomodoro() {
        let timestamp = Date().timeIntervalSince1970
        if let index = document.timers.firstIndex(where: { $0.id == "pomodoro" }) {
            document.timers.remove(at: index)
        }
        let timer = SharedTimerState(
            id: "pomodoro",
            label: String(localized: "Pomodoro"),
            kind: .pomodoro,
            startedAt: timestamp,
            endsAt: timestamp + TimeInterval(document.settings.pomodoroWorkSeconds),
            pomodoroPhase: .work,
            sync: SyncMetadata(deviceID: DeviceIdentity.current, revision: 1)
        )
        document.timers.append(timer)
        focusSnapshot = PomodoroSnapshot()
        focusSnapshot.phase = .work
        focusSnapshot.beginFocus(at: timestamp)
        persistFocusSnapshot()
        scheduleNotifications(for: timer)
        save()
    }

    func perform(_ kind: TimerActionKind, timerID: String, value: TimeInterval? = nil) {
        guard let index = document.timers.firstIndex(where: { $0.id == timerID }) else { return }
        let original = document.timers[index]
        if original.kind == .pomodoro, original.pomodoroPhase == .work {
            if kind == .pause { focusSnapshot.pauseFocus(at: Date().timeIntervalSince1970) }
            if kind == .resume { focusSnapshot.resumeFocus(at: Date().timeIntervalSince1970) }
            if kind == .finish || kind == .delete || kind == .skip {
                finishLocalFocus(completed: false, at: Date().timeIntervalSince1970)
            }
            persistFocusSnapshot()
        }
        let revision = document.timers[index].sync.revision + 1
        let action = TimerAction(
            timerID: timerID,
            kind: kind,
            value: value,
            deviceID: DeviceIdentity.current,
            serverRevision: revision
        )
        var timer = document.timers[index]
        var appliedActionIDs = document.appliedActionIDs
        guard SharedTimerReducer.apply(
            action,
            to: &timer,
            appliedActionIDs: &appliedActionIDs
        ) else { return }
        document.timers[index] = timer
        document.appliedActionIDs = appliedActionIDs
        if kind == .delete || kind == .finish { removeNotifications(timerID) }
        else { scheduleNotifications(for: document.timers[index]) }
        save()
    }

    func pinPrimary(_ id: String?) {
        for index in document.timers.indices {
            let shouldPin = document.timers[index].id == id
            if document.timers[index].isPrimaryPinned != shouldPin {
                document.timers[index].isPrimaryPinned = shouldPin
                document.timers[index].sync = nextMetadata(after: document.timers[index].sync)
            }
        }
        save()
    }

    func confirmPendingEnd() {
        guard let id = pendingEndTimerID else { return }
        perform(.finish, timerID: id)
        pendingEndTimerID = nil
    }

    func handle(url: URL) {
        guard url.host == "confirm-end",
              let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let id = components.queryItems?.first(where: { $0.name == "id" })?.value else { return }
        pendingEndTimerID = id
    }

    func updateSettings(_ update: (inout AppSettings) -> Void) {
        update(&document.settings)
        document.settings.pomodoroWorkSeconds = min(max(60, document.settings.pomodoroWorkSeconds), 7_200)
        document.settings.pomodoroBreakSeconds = min(max(60, document.settings.pomodoroBreakSeconds), 3_600)
        document.settings.pomodoroLongBreakSeconds = min(max(60, document.settings.pomodoroLongBreakSeconds), 7_200)
        document.settings.pomodoroRoundsBeforeLongBreak = min(max(2, document.settings.pomodoroRoundsBeforeLongBreak), 12)
        document.settings.syncRevision = Date().timeIntervalSince1970
        save()
    }

    func receiveCloud(
        presets: [TimerPreset],
        timers: [SharedTimerState],
        settings: AppSettings?
    ) {
        var changed = false
        for incoming in presets {
            if incoming.sync.tombstone {
                let count = document.presets.count
                document.presets.removeAll { $0.id == incoming.id }
                changed = changed || count != document.presets.count
            } else if let index = document.presets.firstIndex(where: { $0.id == incoming.id }) {
                if incoming.sync.supersedes(document.presets[index].sync) {
                    document.presets[index] = incoming
                    changed = true
                }
            } else {
                document.presets.append(incoming)
                changed = true
            }
        }
        document.presets = PresetCollection.normalized(document.presets)
        for incoming in timers {
            let previous = document.timers.first(where: { $0.id == incoming.id })
            reconcileLocalFocus(previous: previous, incoming: incoming)
            if incoming.sync.tombstone {
                let count = document.timers.count
                document.timers.removeAll { $0.id == incoming.id }
                removeNotifications(incoming.id)
                changed = changed || count != document.timers.count
            } else if let index = document.timers.firstIndex(where: { $0.id == incoming.id }) {
                if incoming.sync.supersedes(document.timers[index].sync) {
                    document.timers[index] = incoming
                    changed = true
                    if !incoming.finished { scheduleNotifications(for: incoming) }
                }
            } else {
                document.timers.append(incoming)
                changed = true
                if !incoming.finished, incoming.endsAt.map({ $0 > now }) != false {
                    scheduleNotifications(for: incoming)
                }
            }
        }
        if let settings, settings.syncRevision > document.settings.syncRevision {
            document.settings = settings
            changed = true
        }
        if changed { save() }
    }

    func setSyncAvailability(_ value: CloudSyncAvailability) {
        syncAvailability = value
    }

    private func tick() {
        now = Date().timeIntervalSince1970
        var changed = false
        for index in document.timers.indices where !document.timers[index].finished && document.timers[index].pausedValue == nil {
            guard let end = document.timers[index].endsAt, end <= now else { continue }
            if document.timers[index].kind == .pomodoro {
                advancePomodoro(at: index)
            } else if document.timers[index].kind == .countdown {
                document.timers[index].finished = true
                document.timers[index].sync = nextMetadata(after: document.timers[index].sync)
            }
            changed = true
        }
        if changed { save() } else { refreshActivity() }
    }

    private func advancePomodoro(at index: Int) {
        let phase = document.timers[index].pomodoroPhase ?? .work
        let timestamp = Date().timeIntervalSince1970
        switch phase {
        case .work:
            finishLocalFocus(completed: true, at: document.timers[index].endsAt ?? timestamp)
            let step = PomodoroCycle.afterNaturalWork(
                completedRounds: document.timers[index].completedRounds,
                longBreakEvery: document.settings.pomodoroRoundsBeforeLongBreak
            )
            document.timers[index].completedRounds = step.completedRounds
            document.timers[index].pomodoroPhase = step.phase
            let seconds = step.phase == .longRest
                ? document.settings.pomodoroLongBreakSeconds
                : document.settings.pomodoroBreakSeconds
            document.timers[index].endsAt = timestamp + TimeInterval(seconds)
        case .rest, .longRest:
            let step = PomodoroCycle.afterBreak(
                phase,
                completedRounds: document.timers[index].completedRounds,
                autoCycle: document.settings.pomodoroAutoCycle
            )
            document.timers[index].completedRounds = step.completedRounds
            if step.phase == .work {
                document.timers[index].pomodoroPhase = .work
                document.timers[index].startedAt = timestamp
                document.timers[index].endsAt = timestamp + TimeInterval(document.settings.pomodoroWorkSeconds)
                focusSnapshot = PomodoroSnapshot()
                focusSnapshot.phase = .work
                focusSnapshot.beginFocus(at: timestamp)
            } else {
                document.timers[index].finished = true
            }
        case .idle, .ready:
            document.timers[index].pomodoroPhase = .work
            document.timers[index].endsAt = timestamp + TimeInterval(document.settings.pomodoroWorkSeconds)
        }
        document.timers[index].sync = nextMetadata(after: document.timers[index].sync)
        persistFocusSnapshot()
        scheduleNotifications(for: document.timers[index])
    }

    private func save() {
        try? store.save(document)
        WidgetCenter.shared.reloadAllTimelines()
        refreshActivity()
        cloudSync?.push(document)
    }

    private func refreshActivity() {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }
        let running = timers.filter { !$0.finished }
        guard let primary = PrimaryTimerSelection.select(from: running) else {
            if let activity {
                Task { await activity.end(nil, dismissalPolicy: .immediate) }
                self.activity = nil
            }
            return
        }
        let state = MultiTimerActivityAttributes.ContentState(primary: primary, runningCount: running.count)
        let content = ActivityContent(state: state, staleDate: primary.endsAt.map(Date.init(timeIntervalSince1970:)))
        if let activity {
            Task { await activity.update(content) }
        } else if let value = try? Activity.request(
            attributes: MultiTimerActivityAttributes(createdByDevice: DeviceIdentity.current),
            content: content,
            pushType: nil
        ) {
            activity = value
        }
    }

    private func nextMetadata(after value: SyncMetadata) -> SyncMetadata {
        SyncMetadata(deviceID: DeviceIdentity.current, revision: value.revision + 1)
    }

    private func reconcileLocalFocus(previous: SharedTimerState?, incoming: SharedTimerState) {
        guard incoming.kind == .pomodoro else { return }
        let wasWorking = previous?.pomodoroPhase == .work && previous?.finished == false
        let isWorking = incoming.pomodoroPhase == .work && !incoming.finished && !incoming.isDeleted
        if wasWorking, !isWorking {
            let naturallyCompleted = incoming.completedRounds > (previous?.completedRounds ?? 0)
            finishLocalFocus(completed: naturallyCompleted, at: min(now, incoming.sync.modifiedAt))
        } else if !wasWorking, isWorking, focusSnapshot.focusStartedAt == nil {
            focusSnapshot = PomodoroSnapshot()
            focusSnapshot.phase = .work
            focusSnapshot.beginFocus(at: max(now, incoming.startedAt))
            if incoming.pausedValue != nil { focusSnapshot.pauseFocus(at: now) }
            persistFocusSnapshot()
        }
    }

    private func finishLocalFocus(completed: Bool, at timestamp: TimeInterval) {
        guard let session = focusSnapshot.finishFocus(at: timestamp, completed: completed) else { return }
        var stats = statsStore.load()
        stats.sessions.append(session)
        stats.syncRevision = Date().timeIntervalSince1970
        try? statsStore.save(stats)
        focusSnapshot = PomodoroSnapshot()
        persistFocusSnapshot()
    }

    private func persistFocusSnapshot() {
        try? AtomicJSON.save(focusSnapshot, to: focusSnapshotURL)
    }

    private func nextName(prefix: String, kind: SharedTimerKind) -> String {
        let count = document.timers.filter { $0.kind == kind }.count + 1
        return "\(prefix) \(count)"
    }

    private func requestNotifications() async {
        _ = try? await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound])
    }

    private func scheduleNotifications(for timer: SharedTimerState) {
        removeNotifications(timer.id)
        guard let end = timer.endsAt, end > now else { return }
        let center = UNUserNotificationCenter.current()
        let content = UNMutableNotificationContent()
        content.title = timer.label
        content.body = String(localized: "Timer finished.")
        content.sound = timer.sound?.kind == .muted ? nil : .default
        center.add(UNNotificationRequest(
            identifier: "finish-\(timer.id)",
            content: content,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: max(1, end - now), repeats: false)
        ))
        if let minutes = timer.earlyReminderMinutes {
            let delay = end - now - TimeInterval(minutes * 60)
            guard delay > 1 else { return }
            let early = UNMutableNotificationContent()
            early.title = timer.label
            early.body = String(localized: "Timer finishes in \(minutes) minutes.")
            early.sound = content.sound
            center.add(UNNotificationRequest(
                identifier: "early-\(timer.id)",
                content: early,
                trigger: UNTimeIntervalNotificationTrigger(timeInterval: delay, repeats: false)
            ))
        }
    }

    private func removeNotifications(_ id: String) {
        UNUserNotificationCenter.current().removePendingNotificationRequests(
            withIdentifiers: ["finish-\(id)", "early-\(id)"]
        )
    }
}
