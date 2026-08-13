import MultiTimerCore
import SwiftUI
import WidgetKit

struct CurrentTimerWidget: Widget {
    let kind = "CurrentTimerWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SharedProvider()) { entry in
            CurrentTimerWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Current Timer")
        .description("See and control the primary timer.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct CurrentTimerWidgetView: View {
    let entry: SharedEntry
    private var timer: SharedTimerState? { PrimaryTimerSelection.select(from: entry.document.timers) }

    var body: some View {
        if let timer {
            VStack(alignment: .leading, spacing: 8) {
                HStack {
                    Image(systemName: timer.kind == .stopwatch ? "stopwatch" : "timer")
                    Text(timer.label).font(.headline).lineLimit(1)
                }
                timerTime(timer).font(.title2.monospacedDigit()).contentTransition(.numericText())
                Spacer(minLength: 0)
                HStack {
                    Button(intent: TimerControlIntent(
                        timerID: timer.id,
                        action: timer.pausedValue == nil ? .pause : .resume
                    )) {
                        Image(systemName: timer.pausedValue == nil ? "pause.fill" : "play.fill")
                    }
                    if timer.kind != .stopwatch {
                        Button(intent: TimerControlIntent(timerID: timer.id, action: .extend)) {
                            Text("+5").font(.caption.bold())
                        }
                    }
                    Spacer()
                    Link(destination: URL(string: "multitimer://confirm-end?id=\(timer.id)")!) {
                        Image(systemName: "xmark")
                    }
                }
                .buttonStyle(.bordered)
            }
        } else {
            ContentUnavailableView("No Active Timer", systemImage: "timer")
        }
    }

    @ViewBuilder
    private func timerTime(_ timer: SharedTimerState) -> some View {
        if let paused = timer.pausedValue {
            Text(TimeFormat.clock(paused))
        } else if timer.kind == .stopwatch {
            Text(timerInterval: Date(timeIntervalSince1970: timer.startedAt)...Date.distantFuture, countsDown: false)
        } else if let end = timer.endsAt {
            Text(timerInterval: Date.now...Date(timeIntervalSince1970: end), countsDown: true)
        } else {
            Text("--:--")
        }
    }
}
