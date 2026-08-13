import CloudKit
import MultiTimerCore

@MainActor
final class MobileCloudSyncService {
    private weak var model: MobileAppModel?
    private var driver: CloudKitSyncDriver?
    private var lastPresets: [String: TimerPreset] = [:]
    private var lastTimers: [String: SharedTimerState] = [:]
    private var hasSnapshot = false
    private var applyingRemote = false
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(model: MobileAppModel) {
        self.model = model
        model.setSyncAvailability(.syncing)
        let value = CloudKitSyncDriver(
            onRecords: { [weak self] records in await self?.receive(records) },
            onAvailability: { [weak self] available in
                await self?.model?.setSyncAvailability(available ? .current : .paused)
            }
        )
        driver = value
        push(model.document)
        Task { await value.fetch() }
    }

    func push(_ document: SharedStateDocument) {
        guard !applyingRemote, let driver else { return }
        let presets = Dictionary(uniqueKeysWithValues: document.presets.map { ($0.id, $0) })
        let timers = Dictionary(uniqueKeysWithValues: document.timers.map { ($0.id, $0) })
        var records = presets.values.compactMap(presetRecord)
        records += timers.values.compactMap(timerRecord)
        if let settings = makeRecord(type: "SharedSettings", id: "settings", value: document.settings) {
            records.append(settings)
        }
        if hasSnapshot {
            for id in lastPresets.keys where presets[id] == nil {
                guard var value = lastPresets[id] else { continue }
                value.sync = tombstone(after: value.sync)
                if let record = presetRecord(value) { records.append(record) }
            }
            for id in lastTimers.keys where timers[id] == nil {
                guard var value = lastTimers[id] else { continue }
                value.sync = tombstone(after: value.sync)
                if let record = timerRecord(value) { records.append(record) }
            }
        }
        lastPresets = presets
        lastTimers = timers
        hasSnapshot = true
        Task { await driver.stage(records) }
    }

    private func receive(_ records: [CKRecord]) {
        var presets: [TimerPreset] = []
        var timers: [SharedTimerState] = []
        var settings: AppSettings?
        for record in records {
            guard let data = record["payload"] as? Data else { continue }
            switch record.recordType {
            case "TimerPreset":
                if let value = try? decoder.decode(TimerPreset.self, from: data) { presets.append(value) }
            case "SharedTimer":
                if let value = try? decoder.decode(SharedTimerState.self, from: data) { timers.append(value) }
            case "SharedSettings":
                settings = try? decoder.decode(AppSettings.self, from: data)
            default: break
            }
        }
        applyingRemote = true
        model?.receiveCloud(presets: presets, timers: timers, settings: settings)
        applyingRemote = false
        if let document = model?.document {
            lastPresets = Dictionary(uniqueKeysWithValues: document.presets.map { ($0.id, $0) })
            lastTimers = Dictionary(uniqueKeysWithValues: document.timers.map { ($0.id, $0) })
            push(document)
        }
    }

    private func presetRecord(_ value: TimerPreset) -> CKRecord? {
        makeRecord(type: "TimerPreset", id: "preset-\(value.id)", value: value)
    }

    private func timerRecord(_ value: SharedTimerState) -> CKRecord? {
        makeRecord(type: "SharedTimer", id: "timer-\(value.id)", value: value)
    }

    private func makeRecord<T: Encodable>(type: String, id: String, value: T) -> CKRecord? {
        guard let payload = try? encoder.encode(value) else { return nil }
        let record = CKRecord(
            recordType: type,
            recordID: CKRecord.ID(recordName: id, zoneID: CloudKitSyncDriver.zoneID)
        )
        record["payload"] = payload as CKRecordValue
        record["modifiedAt"] = Date() as CKRecordValue
        return record
    }

    private func tombstone(after value: SyncMetadata) -> SyncMetadata {
        SyncMetadata(
            deviceID: DeviceIdentity.current,
            revision: value.revision + 1,
            tombstone: true
        )
    }
}
