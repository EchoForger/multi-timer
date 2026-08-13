import CloudKit
import Foundation
import MultiTimerCore
import Security

@MainActor
final class CloudSyncService {
    private weak var model: AppModel?
    private var driver: AnyObject?
    private var lastPresets: [String: TimerPreset] = [:]
    private var lastTimers: [String: SharedTimerState] = [:]
    private var hasSnapshot = false
    private var applyingRemote = false
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    func configure(model: AppModel) {
        self.model = model
        guard hasCloudEntitlement else {
            model.setCloudSyncAvailability(.localOnly)
            return
        }
        guard #available(macOS 14.0, *) else {
            model.setCloudSyncAvailability(.paused)
            return
        }
        model.setCloudSyncAvailability(.syncing)
        let cloudDriver = CloudKitSyncDriver(
            onRecords: { [weak self] records in
                await self?.receive(records)
            },
            onAvailability: { [weak self] available in
                await self?.setAvailable(available)
            }
        )
        driver = cloudDriver
        push()
        Task { await cloudDriver.fetch() }
    }

    func push() {
        guard #available(macOS 14.0, *),
              !applyingRemote,
              let model,
              let driver = driver as? CloudKitSyncDriver else { return }

        let currentPresets = Dictionary(uniqueKeysWithValues: model.presets.map { ($0.id, $0) })
        let currentTimers = Dictionary(uniqueKeysWithValues: model.sharedTimerStates.map { ($0.id, $0) })
        var records: [CKRecord] = []
        records += currentPresets.values.compactMap(presetRecord)
        records += currentTimers.values.compactMap(timerRecord)
        if let settings = settingsRecord(model.settings) { records.append(settings) }

        if hasSnapshot {
            for id in lastPresets.keys where currentPresets[id] == nil {
                guard var removed = lastPresets[id] else { continue }
                removed.sync = tombstone(after: removed.sync)
                records.append(presetRecord(removed)!)
            }
            for id in lastTimers.keys where currentTimers[id] == nil {
                guard var removed = lastTimers[id] else { continue }
                removed.sync = tombstone(after: removed.sync)
                records.append(timerRecord(removed)!)
            }
        }
        lastPresets = currentPresets
        lastTimers = currentTimers
        hasSnapshot = true
        Task { await driver.stage(records) }
    }

    @available(macOS 14.0, *)
    private func receive(_ records: [CKRecord]) {
        guard let model else { return }
        var presets: [TimerPreset] = []
        var timers: [SharedTimerState] = []
        var settings: AppSettings?
        for record in records {
            guard let payload = record["payload"] as? Data else { continue }
            switch record.recordType {
            case "TimerPreset":
                if let value = try? decoder.decode(TimerPreset.self, from: payload) { presets.append(value) }
            case "SharedTimer":
                if let value = try? decoder.decode(SharedTimerState.self, from: payload) { timers.append(value) }
            case "SharedSettings":
                settings = try? decoder.decode(AppSettings.self, from: payload)
            default:
                break
            }
        }
        applyingRemote = true
        model.mergeCloud(presets: presets, timers: timers, settings: settings)
        applyingRemote = false
        lastPresets = Dictionary(uniqueKeysWithValues: model.presets.map { ($0.id, $0) })
        lastTimers = Dictionary(uniqueKeysWithValues: model.sharedTimerStates.map { ($0.id, $0) })
        push()
    }

    private func setAvailable(_ available: Bool) {
        model?.setCloudSyncAvailability(available ? .current : .paused)
    }

    @available(macOS 14.0, *)
    private func presetRecord(_ preset: TimerPreset) -> CKRecord? {
        makeRecord(type: "TimerPreset", id: "preset-\(preset.id)", value: preset)
    }

    @available(macOS 14.0, *)
    private func timerRecord(_ timer: SharedTimerState) -> CKRecord? {
        makeRecord(type: "SharedTimer", id: "timer-\(timer.id)", value: timer)
    }

    @available(macOS 14.0, *)
    private func settingsRecord(_ settings: AppSettings) -> CKRecord? {
        makeRecord(type: "SharedSettings", id: "settings", value: settings)
    }

    @available(macOS 14.0, *)
    private func makeRecord<T: Encodable>(type: String, id: String, value: T) -> CKRecord? {
        guard let data = try? encoder.encode(value) else { return nil }
        let record = CKRecord(
            recordType: type,
            recordID: CKRecord.ID(recordName: id, zoneID: CloudKitSyncDriver.zoneID)
        )
        record["payload"] = data as CKRecordValue
        record["modifiedAt"] = Date() as CKRecordValue
        return record
    }

    private func tombstone(after metadata: SyncMetadata) -> SyncMetadata {
        SyncMetadata(
            deviceID: DeviceIdentity.current,
            revision: metadata.revision + 1,
            modifiedAt: Date().timeIntervalSince1970,
            tombstone: true
        )
    }

    private var hasCloudEntitlement: Bool {
        if ProcessInfo.processInfo.environment["MULTITIMER_ENABLE_ICLOUD"] == "1" { return true }
        guard let task = SecTaskCreateFromSelf(nil) else { return false }
        for key in [
            "com.apple.developer.icloud-container-identifiers",
            "com.apple.developer.ubiquity-kvstore-identifier",
        ] {
            if SecTaskCopyValueForEntitlement(task, key as CFString, nil) != nil { return true }
        }
        return false
    }
}
