import CloudKit
import Foundation

@available(macOS 14.0, iOS 17.0, *)
final class CloudKitSyncDriver: CKSyncEngineDelegate, @unchecked Sendable {
    static let containerIdentifier = "iCloud.io.github.echoforger.multitimer"
    static let zoneName = "MultiTimer"

    private let cache = CloudRecordCache()
    private let defaults: UserDefaults
    private let onRecords: @Sendable ([CKRecord]) async -> Void
    private let onAvailability: @Sendable (Bool) async -> Void
    private var engine: CKSyncEngine!

    init(
        defaults: UserDefaults = .standard,
        onRecords: @escaping @Sendable ([CKRecord]) async -> Void,
        onAvailability: @escaping @Sendable (Bool) async -> Void
    ) {
        self.defaults = defaults
        self.onRecords = onRecords
        self.onAvailability = onAvailability
        let state = defaults.data(forKey: "multitimer.cksync.state.v1")
            .flatMap { try? JSONDecoder().decode(CKSyncEngine.State.Serialization.self, from: $0) }
        var configuration = CKSyncEngine.Configuration(
            database: CKContainer(identifier: Self.containerIdentifier).privateCloudDatabase,
            stateSerialization: state,
            delegate: self
        )
        configuration.automaticallySync = true
        configuration.subscriptionID = "multitimer-private-sync"
        engine = CKSyncEngine(configuration)
        let zone = CKRecordZone(zoneID: Self.zoneID)
        engine.state.add(pendingDatabaseChanges: [.saveZone(zone)])
    }

    static var zoneID: CKRecordZone.ID {
        CKRecordZone.ID(zoneName: zoneName, ownerName: CKCurrentUserDefaultName)
    }

    func stage(_ records: [CKRecord]) async {
        await cache.stage(records)
        engine.state.add(pendingRecordZoneChanges: records.map { .saveRecord($0.recordID) })
        do {
            try await engine.sendChanges()
            await onAvailability(true)
        } catch {
            await onAvailability(false)
        }
    }

    func fetch() async {
        do {
            try await engine.fetchChanges()
            await onAvailability(true)
        } catch {
            await onAvailability(false)
        }
    }

    func handleEvent(_ event: CKSyncEngine.Event, syncEngine: CKSyncEngine) async {
        switch event {
        case .stateUpdate(let update):
            if let data = try? JSONEncoder().encode(update.stateSerialization) {
                defaults.set(data, forKey: "multitimer.cksync.state.v1")
            }
        case .accountChange:
            await onAvailability(false)
        case .fetchedRecordZoneChanges(let changes):
            let records = changes.modifications.map(\.record)
            if !records.isEmpty {
                await cache.storeServer(records)
                await onRecords(records)
            }
        case .sentRecordZoneChanges(let changes):
            await cache.acknowledge(changes.savedRecords)
            let serverRecords = changes.failedRecordSaves.compactMap { $0.error.serverRecord }
            if !serverRecords.isEmpty {
                await cache.storeServer(serverRecords)
                syncEngine.state.add(pendingRecordZoneChanges: serverRecords.map { .saveRecord($0.recordID) })
                await onRecords(serverRecords)
            }
        case .didFetchChanges, .didSendChanges:
            await onAvailability(true)
        default:
            break
        }
    }

    func nextRecordZoneChangeBatch(
        _ context: CKSyncEngine.SendChangesContext,
        syncEngine: CKSyncEngine
    ) async -> CKSyncEngine.RecordZoneChangeBatch? {
        await CKSyncEngine.RecordZoneChangeBatch(
            pendingChanges: syncEngine.state.pendingRecordZoneChanges.filter(context.options.scope.contains),
            recordProvider: { [cache] id in await cache.record(for: id) }
        )
    }
}

@available(macOS 14.0, iOS 17.0, *)
private actor CloudRecordCache {
    private var desiredRecords: [CKRecord.ID: CKRecord] = [:]
    private var serverRecords: [CKRecord.ID: CKRecord] = [:]

    func stage(_ values: [CKRecord]) {
        for value in values { desiredRecords[value.recordID] = value }
    }

    func storeServer(_ values: [CKRecord]) {
        for value in values { serverRecords[value.recordID] = value }
    }

    func acknowledge(_ values: [CKRecord]) {
        for value in values {
            serverRecords[value.recordID] = value
            desiredRecords.removeValue(forKey: value.recordID)
        }
    }

    func record(for id: CKRecord.ID) -> CKRecord? {
        guard let desired = desiredRecords[id] else { return nil }
        guard let server = serverRecords[id] else { return desired }
        server["payload"] = desired["payload"]
        server["modifiedAt"] = desired["modifiedAt"]
        return server
    }
}
