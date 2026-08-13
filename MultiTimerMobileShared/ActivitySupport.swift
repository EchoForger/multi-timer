import ActivityKit
import Foundation
import MultiTimerCore

struct MultiTimerActivityAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var timerID: String
        var label: String
        var kind: String
        var endsAt: Date?
        var pausedValue: TimeInterval?
        var runningCount: Int
        var isPaused: Bool
        var color: String?
    }

    var createdByDevice: String
}

extension MultiTimerActivityAttributes.ContentState {
    init(primary: SharedTimerState, runningCount: Int) {
        timerID = primary.id
        label = primary.label
        kind = primary.kind.rawValue
        endsAt = primary.endsAt.map(Date.init(timeIntervalSince1970:))
        pausedValue = primary.pausedValue
        self.runningCount = runningCount
        isPaused = primary.pausedValue != nil
        color = primary.color?.rawValue
    }
}
