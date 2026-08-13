import MultiTimerCore
import SwiftUI

struct MobileSettingsView: View {
    @ObservedObject var model: MobileAppModel
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Form {
                Section("Pomodoro Cycle") {
                    duration("Focus", keyPath: \.pomodoroWorkSeconds, range: 1...120)
                    duration("Short Break", keyPath: \.pomodoroBreakSeconds, range: 1...60)
                    duration("Long Break", keyPath: \.pomodoroLongBreakSeconds, range: 1...120)
                    Stepper(
                        "Long break every \(model.document.settings.pomodoroRoundsBeforeLongBreak) rounds",
                        value: Binding(
                            get: { model.document.settings.pomodoroRoundsBeforeLongBreak },
                            set: { value in model.updateSettings { $0.pomodoroRoundsBeforeLongBreak = value } }
                        ),
                        in: 2...12
                    )
                    Toggle("Automatically start next phase", isOn: Binding(
                        get: { model.document.settings.pomodoroAutoCycle },
                        set: { value in model.updateSettings { $0.pomodoroAutoCycle = value } }
                    ))
                }
                Section("iCloud") {
                    LabeledContent("Status", value: syncStatus)
                    Text("Presets, active timers, and settings sync. Focus history stays only on this device.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("About") {
                    Link("MultiTimer Website", destination: URL(string: "https://echoforger.github.io/multi-timer/")!)
                    Text("Free and open source. No account, ads, purchases, task management, or social features.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
    }

    private var syncStatus: String {
        switch model.syncAvailability {
        case .localOnly: String(localized: "Local only")
        case .syncing: String(localized: "Syncing…")
        case .current: String(localized: "Up to date")
        case .paused: String(localized: "Sync paused")
        }
    }

    private func duration(
        _ title: LocalizedStringKey,
        keyPath: WritableKeyPath<AppSettings, Int>,
        range: ClosedRange<Double>
    ) -> some View {
        VStack {
            HStack {
                Text(title)
                Spacer()
                Text("\(model.document.settings[keyPath: keyPath] / 60) min").monospacedDigit()
            }
            Slider(
                value: Binding(
                    get: { Double(model.document.settings[keyPath: keyPath]) / 60 },
                    set: { value in model.updateSettings { $0[keyPath: keyPath] = Int(value.rounded()) * 60 } }
                ),
                in: range,
                step: 1
            )
        }
    }
}
