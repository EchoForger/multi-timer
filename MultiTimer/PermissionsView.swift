import AppKit
import LaunchAtLogin
import SwiftUI
import UserNotifications

struct PermissionsView: View {
    let notificationManager: NotificationManager
    @ObservedObject private var launchAtLogin = LaunchAtLogin.observable
    @State private var notificationStatus: UNAuthorizationStatus = .notDetermined

    var body: some View {
        ZStack {
            WindowVisualEffect(material: .underWindowBackground)
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 14) {
                    Image(systemName: "timer")
                        .font(.system(size: 36, weight: .medium)).foregroundStyle(.tint)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("MultiTimer Permissions").font(.title2.bold())
                        Text("These settings keep the menu bar timer available and let it alert you on time.")
                            .foregroundStyle(.secondary)
                    }
                }

                permissionRow(
                    icon: "menubar.rectangle",
                    title: "Menu Bar",
                    detail: "Shows the timer icon so MultiTimer is always available.",
                    status: "Available",
                    statusColor: .green,
                    button: "Menu Bar Settings…",
                    action: openMenuBarSettings
                )
                permissionRow(
                    icon: "bell.badge",
                    title: "Notifications",
                    detail: "Alerts you when a timer or Pomodoro session finishes.",
                    status: notificationStatusText,
                    statusColor: notificationStatus == .authorized ? .green : .orange,
                    button: notificationStatus == .notDetermined ? "Allow…" : "Open Settings…",
                    action: requestOrOpenNotifications
                )
                permissionRow(
                    icon: "arrow.clockwise.circle",
                    title: "Launch at Login",
                    detail: "Starts MultiTimer after login so the menu bar timer is ready.",
                    status: launchAtLogin.isEnabled ? "Enabled" : "Off",
                    statusColor: launchAtLogin.isEnabled ? .green : .secondary,
                    button: launchAtLogin.isEnabled ? "Disable" : "Enable",
                    action: { launchAtLogin.isEnabled.toggle() }
                )

                Spacer()
                HStack {
                    Text("Press ⌘⇧⌥M anytime, or run `multitimer permissions` in Terminal.")
                        .font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    Button("Check Again", action: refresh)
                    Button("Close") { NSApp.keyWindow?.close() }.keyboardShortcut(.cancelAction)
                }
            }
            .padding(EdgeInsets(top: 34, leading: 24, bottom: 24, trailing: 24))
        }
        .onAppear(perform: refresh)
    }

    private func permissionRow(
        icon: String,
        title: String,
        detail: String,
        status: String,
        statusColor: Color,
        button: String,
        action: @escaping () -> Void
    ) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon).font(.title2).frame(width: 28).foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 3) {
                Text(LocalizedStringKey(title)).font(.headline)
                Text(LocalizedStringKey(detail)).font(.callout).foregroundStyle(.secondary)
            }
            Spacer()
            Text(LocalizedStringKey(status)).fontWeight(.semibold).foregroundStyle(statusColor)
            Button(action: action) { Text(LocalizedStringKey(button)) }.frame(width: 142)
        }
        .padding(14)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }

    private var notificationStatusText: String {
        switch notificationStatus {
        case .authorized, .provisional, .ephemeral: return "Allowed"
        case .denied: return "Denied"
        case .notDetermined: return "Not Set"
        @unknown default: return "Unknown"
        }
    }

    private func refresh() {
        notificationManager.authorizationStatus { status in
            DispatchQueue.main.async { notificationStatus = status }
        }
    }

    private func requestOrOpenNotifications() {
        if notificationStatus == .notDetermined {
            notificationManager.requestAuthorization { refresh() }
        } else if let url = URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=io.github.echoforger.multitimer") {
            NSWorkspace.shared.open(url)
        }
    }

    private func openMenuBarSettings() {
        let urls = [
            "x-apple.systempreferences:com.apple.ControlCenter-Settings.extension",
            "x-apple.systempreferences:com.apple.preference.dock",
        ]
        for value in urls where NSWorkspace.shared.open(URL(string: value)!) { break }
    }
}
