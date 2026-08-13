import Foundation
import MultiTimerCore
import Security

@MainActor
final class CloudSyncService {
    private let store = NSUbiquitousKeyValueStore.default
    private weak var model: AppModel?
    private let settingsKey = "multitimer.settings.v1"
    private var enabled = false

    func configure(model: AppModel) {
        self.model = model
        enabled = hasCloudEntitlement
        guard enabled else { return }
        NotificationCenter.default.addObserver(
            forName: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: store,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.pull() }
        }
        _ = store.synchronize()
        pull()
        push()
    }

    func push() {
        guard enabled, let model else { return }
        let encoder = JSONEncoder()
        if let settings = try? encoder.encode(model.settings) { store.set(settings, forKey: settingsKey) }
        _ = store.synchronize()
    }

    private func pull() {
        guard enabled, let model else { return }
        let decoder = JSONDecoder()
        let settings = store.data(forKey: settingsKey).flatMap { try? decoder.decode(AppSettings.self, from: $0) }
        model.mergeCloud(settings: settings)
    }

    private var hasCloudEntitlement: Bool {
        if ProcessInfo.processInfo.environment["MULTITIMER_ENABLE_ICLOUD"] == "1" { return true }
        guard let task = SecTaskCreateFromSelf(nil),
              let value = SecTaskCopyValueForEntitlement(
                task,
                "com.apple.developer.ubiquity-kvstore-identifier" as CFString,
                nil
              ) else { return false }
        return value is String
    }
}
