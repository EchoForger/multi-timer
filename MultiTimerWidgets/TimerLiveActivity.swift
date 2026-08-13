import ActivityKit
import MultiTimerCore
import SwiftUI
import WidgetKit

struct TimerLiveActivity: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: MultiTimerActivityAttributes.self) { context in
            HStack(spacing: 12) {
                Image(systemName: context.state.kind == "stopwatch" ? "stopwatch" : "timer")
                VStack(alignment: .leading) {
                    Text(context.state.label).font(.headline).lineLimit(1)
                    activityTime(context.state).monospacedDigit()
                }
                Spacer()
                if context.state.runningCount > 1 {
                    Text("+\(context.state.runningCount - 1)").font(.caption.bold())
                }
                controls(context.state)
            }
            .padding(.horizontal)
            .activityBackgroundTint(.black.opacity(0.88))
            .activitySystemActionForegroundColor(.white)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.leading) { Image(systemName: "timer") }
                DynamicIslandExpandedRegion(.center) { Text(context.state.label).lineLimit(1) }
                DynamicIslandExpandedRegion(.trailing) { activityTime(context.state).monospacedDigit() }
                DynamicIslandExpandedRegion(.bottom) { controls(context.state) }
            } compactLeading: {
                Image(systemName: "timer")
            } compactTrailing: {
                activityTime(context.state).monospacedDigit().frame(width: 46)
            } minimal: {
                Image(systemName: "timer")
            }
        }
    }

    @ViewBuilder
    private func activityTime(_ state: MultiTimerActivityAttributes.ContentState) -> some View {
        if let paused = state.pausedValue {
            Text(TimeFormat.menuBar(paused))
        } else if state.kind == "stopwatch" {
            Text("Running")
        } else if let end = state.endsAt {
            Text(timerInterval: Date.now...end, countsDown: true)
        } else {
            Text("--:--")
        }
    }

    private func controls(_ state: MultiTimerActivityAttributes.ContentState) -> some View {
        HStack(spacing: 8) {
            Button(intent: TimerControlIntent(
                timerID: state.timerID,
                action: state.isPaused ? .resume : .pause
            )) { Image(systemName: state.isPaused ? "play.fill" : "pause.fill") }
            if state.kind != "stopwatch" {
                Button(intent: TimerControlIntent(timerID: state.timerID, action: .extend)) { Text("+5") }
            }
            Link(destination: URL(string: "multitimer://confirm-end?id=\(state.timerID)")!) {
                Image(systemName: "xmark")
            }
        }
        .buttonStyle(.bordered)
    }
}
