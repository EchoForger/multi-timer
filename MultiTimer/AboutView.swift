import AppKit
import SwiftUI

struct WindowVisualEffect: NSViewRepresentable {
    var material: NSVisualEffectView.Material = .underWindowBackground

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.blendingMode = .behindWindow
        nsView.state = .followsWindowActiveState
    }
}

struct AboutView: View {
    let version: String
    let build: String
    let onWebsite: () -> Void
    let onCheckUpdates: () -> Void

    @State private var copied = false

    var body: some View {
        ZStack {
            WindowVisualEffect(material: .underWindowBackground)
                .ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer(minLength: 30)

                Image(nsImage: NSApp.applicationIconImage)
                    .resizable()
                    .interpolation(.high)
                    .frame(width: 96, height: 96)
                    .shadow(color: .black.opacity(0.18), radius: 8, y: 3)

                Text("Multi").font(.system(size: 30, weight: .bold))
                    + Text("Timer").font(.system(size: 30, weight: .bold)).foregroundColor(.accentColor)

                Text("by EchoForger")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .padding(.top, 2)

                versionRow
                    .padding(.top, 14)

                Spacer(minLength: 24)

                HStack(spacing: 10) {
                    Button(action: onWebsite) {
                        Text("Website").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)

                    Button(action: onCheckUpdates) {
                        Text("Check for Updates").frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }
                .controlSize(.large)
                .padding(.horizontal, 40)

                Text("Open source under the MIT License · © 2026 EchoForger")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
                    .padding(.top, 16)

                Spacer(minLength: 26)
            }
        }
        .frame(width: 420, height: 384)
    }

    private var versionRow: some View {
        HStack(spacing: 7) {
            Text(String(format: NSLocalizedString("Version %@ (%@)", comment: "About"), version, build))
                .font(.system(.subheadline, design: .rounded).monospacedDigit())
                .foregroundStyle(.secondary)

            Button(action: copyVersion) {
                Image(systemName: copied ? "checkmark.circle.fill" : "doc.on.doc")
                    .foregroundStyle(copied ? Color.green : Color.secondary)
            }
            .buttonStyle(.borderless)
            .help("Copy version")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 7)
        .background(.quaternary.opacity(0.5), in: Capsule())
    }

    private func copyVersion() {
        let value = "MultiTimer \(version) (\(build))"
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(value, forType: .string)
        withAnimation { copied = true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.6) {
            withAnimation { copied = false }
        }
    }
}
