import MultiTimerCore
import SwiftUI

struct MobileTimersView: View {
    @ObservedObject var model: MobileAppModel

    var body: some View {
        List {
            ForEach(model.timers) { timer in
                timerRow(timer)
                    .swipeActions(edge: .trailing) {
                        Button("End", role: .destructive) { model.pendingEndTimerID = timer.id }
                    }
                    .contextMenu {
                        Button(timer.isPrimaryPinned ? "Unpin from Live Activity" : "Pin to Live Activity") {
                            model.pinPrimary(timer.isPrimaryPinned ? nil : timer.id)
                        }
                    }
            }
        }
        .overlay {
            if model.timers.isEmpty {
                ContentUnavailableView(
                    "No Active Timers",
                    systemImage: "timer",
                    description: Text("Start a preset, stopwatch, or Pomodoro session.")
                )
            }
        }
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Menu {
                    Button("Start Stopwatch", systemImage: "stopwatch", action: model.startStopwatch)
                    Button("Start Pomodoro", systemImage: "flame", action: model.startPomodoro)
                } label: { Image(systemName: "plus") }
            }
        }
    }

    private func timerRow(_ timer: SharedTimerState) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: icon(timer))
                    .foregroundStyle(timer.kind == .pomodoro ? phaseColor(timer) : .accentColor)
                Text(timer.label).font(.headline).lineLimit(1)
                if timer.isPrimaryPinned { Image(systemName: "pin.fill").font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Text(displayTime(timer)).font(.title3.monospacedDigit()).foregroundStyle(.primary)
            }
            if timer.kind == .pomodoro {
                Text(pomodoroDetail(timer)).font(.caption).foregroundStyle(.secondary)
            }
            HStack {
                Button(timer.pausedValue == nil ? "Pause" : "Resume") {
                    model.perform(timer.pausedValue == nil ? .pause : .resume, timerID: timer.id)
                }
                .buttonStyle(.bordered)
                if timer.kind != .stopwatch {
                    Button("+5 min") { model.perform(.extend, timerID: timer.id, value: 300) }
                        .buttonStyle(.bordered)
                }
                Spacer()
                Button("End", role: .destructive) { model.pendingEndTimerID = timer.id }
                    .buttonStyle(.bordered)
            }
            .controlSize(.small)
        }
        .padding(.vertical, 5)
    }

    private func displayTime(_ timer: SharedTimerState) -> String {
        if timer.finished { return String(localized: "Done") }
        if timer.kind == .stopwatch {
            return TimeFormat.clock(timer.pausedValue ?? max(0, model.now - timer.startedAt))
        }
        return TimeFormat.clock(timer.pausedValue ?? max(0, (timer.endsAt ?? model.now) - model.now))
    }

    private func icon(_ timer: SharedTimerState) -> String {
        switch timer.kind {
        case .countdown: "timer"
        case .stopwatch: "stopwatch"
        case .pomodoro: timer.pomodoroPhase == .work ? "flame.fill" : "cup.and.saucer.fill"
        }
    }

    private func phaseColor(_ timer: SharedTimerState) -> Color {
        timer.pomodoroPhase == .work ? .red : .green
    }

    private func pomodoroDetail(_ timer: SharedTimerState) -> String {
        let phase = timer.pomodoroPhase == .work
            ? String(localized: "Focus")
            : (timer.pomodoroPhase == .longRest ? String(localized: "Long Break") : String(localized: "Short Break"))
        return "\(phase) · \(String(localized: "Round")) \(timer.completedRounds)/\(model.document.settings.pomodoroRoundsBeforeLongBreak)"
    }
}
