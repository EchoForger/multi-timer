import AppIntents
import CloudKit
import MultiTimerCore
import UserNotifications
import WidgetKit

struct StartPresetIntent: AppIntent {
    static let title: LocalizedStringResource = "Start Preset"
    static let openAppWhenRun = false

    @Parameter(title: "Preset ID") var presetID: String

    init() {}
    init(presetID: String) { self.presetID = presetID }

    func perform() async throws -> some IntentResult {
        var document = MobileAppGroup.store.load()
        guard let preset = document.presets.first(where: { $0.id == presetID }) else { return .result() }
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
        try MobileAppGroup.store.save(document)
        scheduleFinish(for: timer)
        await syncSharedDocument(document)
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}

struct TimerControlIntent: AppIntent {
    static let title: LocalizedStringResource = "Control Timer"
    static let openAppWhenRun = false

    @Parameter(title: "Timer ID") var timerID: String
    @Parameter(title: "Action") var action: String

    init() {}
    init(timerID: String, action: TimerActionKind) {
        self.timerID = timerID
        self.action = action.rawValue
    }

    func perform() async throws -> some IntentResult {
        var document = MobileAppGroup.store.load()
        guard let index = document.timers.firstIndex(where: { $0.id == timerID }),
              let kind = TimerActionKind(rawValue: action) else { return .result() }
        let value: TimeInterval? = kind == .extend ? 300 : nil
        let operation = TimerAction(
            timerID: timerID,
            kind: kind,
            value: value,
            deviceID: DeviceIdentity.current,
            serverRevision: document.timers[index].sync.revision + 1
        )
        _ = SharedTimerReducer.apply(
            operation,
            to: &document.timers[index],
            appliedActionIDs: &document.appliedActionIDs
        )
        try MobileAppGroup.store.save(document)
        if kind == .finish || kind == .delete {
            UNUserNotificationCenter.current().removePendingNotificationRequests(
                withIdentifiers: ["finish-\(timerID)", "early-\(timerID)"]
            )
        } else {
            scheduleFinish(for: document.timers[index])
        }
        await syncSharedDocument(document)
        WidgetCenter.shared.reloadAllTimelines()
        return .result()
    }
}

private func scheduleFinish(for timer: SharedTimerState) {
    UNUserNotificationCenter.current().removePendingNotificationRequests(
        withIdentifiers: ["finish-\(timer.id)", "early-\(timer.id)"]
    )
    guard let end = timer.endsAt, timer.pausedValue == nil else { return }
    let delay = end - Date().timeIntervalSince1970
    guard delay > 1 else { return }
    let content = UNMutableNotificationContent()
    content.title = timer.label
    content.body = String(localized: "Timer finished.")
    content.sound = timer.sound?.kind == .muted ? nil : .default
    UNUserNotificationCenter.current().add(UNNotificationRequest(
        identifier: "finish-\(timer.id)",
        content: content,
        trigger: UNTimeIntervalNotificationTrigger(timeInterval: delay, repeats: false)
    ))
    if let minutes = timer.earlyReminderMinutes {
        let earlyDelay = delay - TimeInterval(minutes * 60)
        guard earlyDelay > 1 else { return }
        let early = UNMutableNotificationContent()
        early.title = timer.label
        early.body = String(localized: "Timer finishes in \(minutes) minutes.")
        early.sound = content.sound
        UNUserNotificationCenter.current().add(UNNotificationRequest(
            identifier: "early-\(timer.id)",
            content: early,
            trigger: UNTimeIntervalNotificationTrigger(timeInterval: earlyDelay, repeats: false)
        ))
    }
}

private func syncSharedDocument(_ document: SharedStateDocument) async {
    let encoder = JSONEncoder()
    func record<T: Encodable>(_ type: String, _ id: String, _ value: T) -> CKRecord? {
        guard let payload = try? encoder.encode(value) else { return nil }
        let item = CKRecord(
            recordType: type,
            recordID: CKRecord.ID(recordName: id, zoneID: CloudKitSyncDriver.zoneID)
        )
        item["payload"] = payload as CKRecordValue
        item["modifiedAt"] = Date() as CKRecordValue
        return item
    }
    var records = document.presets.compactMap { record("TimerPreset", "preset-\($0.id)", $0) }
    records += document.timers.compactMap { record("SharedTimer", "timer-\($0.id)", $0) }
    if let settings = record("SharedSettings", "settings", document.settings) { records.append(settings) }
    let driver = CloudKitSyncDriver(onRecords: { _ in }, onAvailability: { _ in })
    await driver.stage(records)
}
