import AppKit
import KeyboardShortcuts
import LaunchAtLogin
import MultiTimerCore
import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var launchAtLogin = LaunchAtLogin.observable

    var body: some View {
        Form {
            Section("Menu Bar") {
                Toggle("Show nearest remaining time", isOn: binding(\.showRemaining))
                Toggle("Show active timer count", isOn: binding(\.showCount))
                Toggle("Sort timers by nearest expiry", isOn: binding(\.sortByExpiry))
            }

            Section("Pomodoro") {
                durationRow("Focus duration", keyPath: \.pomodoroWorkSeconds)
                durationRow("Break duration", keyPath: \.pomodoroBreakSeconds)
                Toggle("Automatically start the next focus", isOn: binding(\.pomodoroAutoCycle))
                Toggle("Show Pomodoro in the menu", isOn: binding(\.showPomodoro))
            }

            Section("System") {
                Toggle("Launch at login", isOn: $launchAtLogin.isEnabled)
                Toggle("Check for updates when MultiTimer starts", isOn: binding(\.updateAutomatically))
                LabeledContent("Permissions shortcut") {
                    KeyboardShortcuts.Recorder(for: .openPermissions)
                }
                HStack {
                    Text("Language")
                    Spacer()
                    Button("Open Language Settings…", action: openLanguageSettings)
                }
                HStack {
                    Text("Permissions")
                    Spacer()
                    Button("Open Permissions…") { WindowRouter.shared.permissions() }
                }
            }

            Section {
                Text("Changes are saved automatically.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .padding(12)
        .frame(minWidth: 500, minHeight: 430)
    }

    private func binding(_ keyPath: WritableKeyPath<AppSettings, Bool>) -> Binding<Bool> {
        Binding(
            get: { model.settings[keyPath: keyPath] },
            set: { value in model.updateSettings { $0[keyPath: keyPath] = value } }
        )
    }

    private func durationRow(_ title: String, keyPath: WritableKeyPath<AppSettings, Int>) -> some View {
        HStack {
            Text(title)
            Spacer()
            TextField("MM:SS", text: Binding(
                get: { TimeFormat.clock(TimeInterval(model.settings[keyPath: keyPath])).dropFirst(3).description },
                set: { value in
                    if let seconds = DurationParser.parse(value) {
                        model.updateSettings { $0[keyPath: keyPath] = min(3_599, seconds) }
                    }
                }
            ))
            .multilineTextAlignment(.trailing)
            .font(.body.monospacedDigit())
            .frame(width: 72)
        }
    }

    private func openLanguageSettings() {
        let urls = [
            "x-apple.systempreferences:com.apple.Localization-Settings.extension",
            "x-apple.systempreferences:com.apple.preference.language",
        ]
        for value in urls {
            if let url = URL(string: value), NSWorkspace.shared.open(url) { break }
        }
    }
}
