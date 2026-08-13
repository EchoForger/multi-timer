import Foundation
import MultiTimerCore

enum MobileAppGroup {
    static let identifier = "group.io.github.echoforger.multitimer"

    static var stateURL: URL {
        let root = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: identifier)
            ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return root.appendingPathComponent("shared-state.json")
    }

    static var store: SharedStateStore { SharedStateStore(url: stateURL) }
}
