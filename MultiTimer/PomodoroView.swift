import MultiTimerCore
import SwiftUI

struct PomodoroView: View {
    @ObservedObject var model: AppModel
    let showStatistics: () -> Void

    var body: some View {
        GroupBox {
            VStack(spacing: 8) {
                HStack {
                    Image(systemName: phaseIcon)
                        .foregroundColor(model.pomodoro.phase == .rest ? .green : .accentColor)
                    Text(LocalizedStringKey(phaseTitle)).fontWeight(.medium)
                    Spacer()
                    if model.pomodoro.phase == .work || model.pomodoro.phase == .rest {
                        Text(TimeFormat.clock(model.pomodoroRemaining))
                            .font(.system(.title3, design: .monospaced).weight(.semibold))
                    } else {
                        Text("Today \(model.todayFocusSessionCount) · \(model.todayCount) completed")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                }

                if model.pomodoro.phase == .work || model.pomodoro.phase == .rest {
                    HStack(spacing: 6) {
                        Button(model.pomodoro.pausedRemaining == nil ? "Pause" : "Resume") {
                            model.togglePomodoroPause()
                        }
                        Button("+5 min") { model.extendPomodoro() }
                        Button("Skip") { model.skipPomodoro() }
                        Spacer()
                        Button("Stop") { model.stopPomodoro() }
                    }
                    .controlSize(.small)
                } else {
                    Button("Start Focus") {
                        model.startPomodoro()
                    }
                        .frame(maxWidth: .infinity)
                }

                if let goal = model.todayGoalMinutes {
                    VStack(spacing: 3) {
                        ProgressView(value: min(1, model.todayFocusedSeconds / TimeInterval(goal * 60)))
                        HStack {
                            Text("Daily goal")
                            Spacer()
                            Text("\(Int(model.todayFocusedSeconds) / 60) / \(goal) min")
                                .monospacedDigit()
                        }
                        .font(.caption2)
                        .foregroundStyle(.secondary)
                    }
                }
            }
            .padding(2)
        } label: {
            HStack {
                Label("Pomodoro", systemImage: "brain.head.profile")
                Spacer()
                Button(action: showStatistics) {
                    Label("Statistics", systemImage: "chart.bar.xaxis")
                        .labelStyle(.iconOnly)
                }
                .buttonStyle(.borderless)
                .help("Statistics")
            }
        }
    }

    private var phaseTitle: String {
        switch model.pomodoro.phase {
        case .idle: return "Ready to focus"
        case .ready: return "Break complete"
        case .work: return model.pomodoro.pausedRemaining == nil ? "Focus" : "Focus paused"
        case .rest: return model.pomodoro.pausedRemaining == nil ? "Break" : "Break paused"
        }
    }

    private var phaseIcon: String {
        switch model.pomodoro.phase {
        case .idle, .ready: return "circle.dashed"
        case .work: return "flame.fill"
        case .rest: return "cup.and.saucer.fill"
        }
    }
}
