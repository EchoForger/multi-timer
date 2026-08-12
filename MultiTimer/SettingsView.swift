import AppKit
import KeyboardShortcuts
import LaunchAtLogin
import MultiTimerCore
import SwiftUI

struct SettingsView: View {
    @ObservedObject var model: AppModel
    @ObservedObject private var launchAtLogin = LaunchAtLogin.observable

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            settingSection("Menu Bar") {
                Toggle("Show countdown time", isOn: binding(\.showRemaining))
                Toggle("Show stopwatch time", isOn: binding(\.showCount))
                Toggle("Sort timers by nearest expiry", isOn: binding(\.sortByExpiry))
            }

            settingSection("Pomodoro") {
                durationSlider("Focus duration", keyPath: \.pomodoroWorkSeconds, range: 1...120)
                durationSlider("Break duration", keyPath: \.pomodoroBreakSeconds, range: 1...60)
                Toggle("Automatically start the next focus", isOn: binding(\.pomodoroAutoCycle))
                Toggle("Show Pomodoro in the menu", isOn: binding(\.showPomodoro))
            }

            settingSection("System") {
                Toggle("Launch at login", isOn: $launchAtLogin.isEnabled)
                Toggle("Check for updates when MultiTimer starts", isOn: binding(\.updateAutomatically))
                LabeledContent("Permissions shortcut") {
                    KeyboardShortcuts.Recorder(for: .openPermissions)
                }
                actionRow("Language", button: "Open Language Settings…", action: openLanguageSettings)
                actionRow("Permissions", button: "Open Permissions…") { WindowRouter.shared.permissions() }
            }

            Text("Changes are saved automatically.")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(14)
    }

    private func settingSection<Content: View>(
        _ title: LocalizedStringKey,
        @ViewBuilder content: () -> Content
    ) -> some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 10) { content() }
                .padding(3)
                .frame(maxWidth: .infinity, alignment: .leading)
        } label: { Text(title).fontWeight(.semibold) }
    }

    private func binding(_ keyPath: WritableKeyPath<AppSettings, Bool>) -> Binding<Bool> {
        Binding(
            get: { model.settings[keyPath: keyPath] },
            set: { value in model.updateSettings { $0[keyPath: keyPath] = value } }
        )
    }

    private func durationSlider(
        _ title: LocalizedStringKey,
        keyPath: WritableKeyPath<AppSettings, Int>,
        range: ClosedRange<Double>
    ) -> some View {
        VStack(spacing: 4) {
            HStack {
                Text(title)
                Spacer()
                Text("\(model.settings[keyPath: keyPath] / 60) min")
                    .font(.body.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
            Slider(
                value: Binding(
                    get: { Double(model.settings[keyPath: keyPath] / 60) },
                    set: { minutes in
                        model.updateSettings { $0[keyPath: keyPath] = Int(minutes.rounded()) * 60 }
                    }
                ),
                in: range,
                step: 1
            )
        }
    }

    private func actionRow(_ title: LocalizedStringKey, button: LocalizedStringKey, action: @escaping () -> Void) -> some View {
        HStack {
            Text(title)
            Spacer()
            Button(button, action: action).controlSize(.small)
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
