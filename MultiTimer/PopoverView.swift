import AppKit
import MultiTimerCore
import SwiftUI

enum PopoverPage: Equatable {
    case timers
    case presets
    case statistics
    case settings
}

private enum CreationKind: String, CaseIterable, Identifiable {
    case countdown, stopwatch
    var id: String { rawValue }
}

struct PopoverView: View {
    @ObservedObject var model: AppModel
    @EnvironmentObject private var router: WindowRouter
    let onPreferredHeight: (CGFloat) -> Void

    @State private var name = ""
    @State private var kind: CreationKind = .countdown
    @State private var sliderPosition = pow(300.0 / 86_400.0, 1.0 / 3.0)

    init(model: AppModel, onPreferredHeight: @escaping (CGFloat) -> Void = { _ in }) {
        self.model = model
        self.onPreferredHeight = onPreferredHeight
    }

    private var durationSeconds: Int {
        max(1, Int((86_400 * pow(sliderPosition, 3)).rounded()))
    }

    private var preferredHeight: CGFloat {
        switch router.page {
        case .presets:
            if model.presets.isEmpty { return 440 }
            return min(650, max(330, 190 + CGFloat(min(model.presets.count, 7)) * 58))
        case .settings: return 620
        case .statistics: return 680
        case .timers:
            let creation: CGFloat = kind == .countdown ? 166 : 105
            let pomodoro: CGFloat = model.settings.showPomodoro ? 80 : 0
            let timers: CGFloat = model.sortedTimers.isEmpty
                ? 80
                : 26 + CGFloat(min(model.sortedTimers.count, 4)) * 66
            return min(680, max(390, 139 + creation + pomodoro + timers))
        }
    }

    var body: some View {
        ZStack {
            PopoverVisualEffect()
                .ignoresSafeArea()

            VStack(spacing: 0) {
                header
                Divider()
                Group {
                    switch router.page {
                    case .timers: timerPage
                    case .presets: PresetsView(model: model)
                    case .statistics: ScrollView { StatisticsView(model: model) }
                    case .settings: ScrollView { SettingsView(model: model) }
                    }
                }
                .id(router.page)
                .transition(.opacity.combined(with: .move(edge: .trailing)))
                Divider()
                footer
            }
        }
        .frame(width: 360, height: preferredHeight)
        .animation(.easeInOut(duration: 0.22), value: router.page)
        .animation(.easeInOut(duration: 0.22), value: model.sortedTimers.count)
        .animation(.easeInOut(duration: 0.22), value: model.presets.count)
        .animation(.easeInOut(duration: 0.18), value: kind)
        .onAppear { onPreferredHeight(preferredHeight) }
        .onChange(of: preferredHeight) { onPreferredHeight($0) }
    }

    private var header: some View {
        HStack(spacing: 9) {
            if router.page == .timers {
                Image(systemName: "timer")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.tint)
            } else {
                Button { router.main() } label: { Image(systemName: "chevron.left") }
                    .buttonStyle(.borderless)
            }
            VStack(alignment: .leading, spacing: 1) {
                Text(headerTitle).font(.headline)
                if router.page == .timers {
                    Text(model.activeCount == 0 ? "Ready when you are" : "\(model.activeCount) active")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            Spacer()
            if router.page == .timers {
                Button { router.settings() } label: { Image(systemName: "gearshape") }
                    .buttonStyle(.borderless).help("Settings")
            }
        }
        .padding(.horizontal, 14)
        .frame(height: 55)
    }

    private var headerTitle: LocalizedStringKey {
        switch router.page {
        case .timers: return "MultiTimer"
        case .presets: return "Timer Presets"
        case .statistics: return "Focus Statistics"
        case .settings: return "Settings"
        }
    }

    private var timerPage: some View {
        ScrollView {
            VStack(spacing: 10) {
                PresetFavoritesView(model: model) { router.presets() }
                creationCard
                if model.settings.showPomodoro {
                    PomodoroView(model: model) { router.statistics() }
                }
                timerList
            }
            .padding(12)
        }
    }

    private var creationCard: some View {
        GroupBox {
            VStack(spacing: 8) {
                TextField("Name this timer", text: $name)
                    .textFieldStyle(.roundedBorder)
                    .onSubmit(start)
                Picker("", selection: $kind) {
                    Text("Countdown").tag(CreationKind.countdown)
                    Text("Stopwatch").tag(CreationKind.stopwatch)
                }
                .labelsHidden()
                .pickerStyle(.segmented)

                if kind == .countdown {
                    HStack {
                        Text(TimeFormat.clock(TimeInterval(durationSeconds)))
                            .font(.body.monospacedDigit().weight(.medium))
                        Spacer()
                        Text("Alarm \(alarmTime)")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    Slider(value: $sliderPosition, in: 0.01...1) { Text("Duration") }
                    Button(action: start) {
                        Text("Start Countdown")
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity)
                    }
                        .buttonStyle(.borderedProminent)
                } else {
                    Button("Start Stopwatch", action: start)
                        .frame(maxWidth: .infinity)
                }
            }
            .padding(2)
        } label: { Label("New Timer", systemImage: "plus.circle") }
    }

    private var alarmTime: String {
        let formatter = DateFormatter()
        formatter.timeStyle = .medium
        formatter.dateStyle = .none
        return formatter.string(from: Date().addingTimeInterval(TimeInterval(durationSeconds)))
    }

    @ViewBuilder
    private var timerList: some View {
        if model.sortedTimers.isEmpty {
            VStack(spacing: 7) {
                Image(systemName: "timer").font(.title2).foregroundStyle(.secondary)
                Text("No Timers").font(.headline)
                Text("Use the controls above to start one.").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 80)
            .transition(.opacity)
        } else {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("Timers").font(.headline)
                    Spacer()
                    Text("\(model.activeCount) active").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(model.sortedTimers) { timer in
                    TimerRow(model: model, timer: timer)
                        .transition(.asymmetric(
                            insertion: .opacity.combined(with: .scale(scale: 0.96)),
                            removal: .opacity.combined(with: .move(edge: .trailing))
                        ))
                }
            }
        }
    }

    private var footer: some View {
        HStack(spacing: 12) {
            Button("About") { router.about() }.buttonStyle(.plain)
            Button("Check for Updates") { router.updates() }.buttonStyle(.plain)
            Spacer()
            Button("Quit") { NSApp.terminate(nil) }.buttonStyle(.plain)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
        .padding(.horizontal, 14)
        .frame(height: 39)
    }

    private func start() {
        switch kind {
        case .countdown: model.startCountdown(label: name, seconds: durationSeconds)
        case .stopwatch: model.startStopwatch(label: name)
        }
        name = ""
    }
}

private struct PopoverVisualEffect: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .popover
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = .popover
        nsView.blendingMode = .behindWindow
        nsView.state = .followsWindowActiveState
    }
}

private struct TimerRow: View {
    @ObservedObject var model: AppModel
    let timer: TimerRecord
    @State private var editing = false
    @State private var editedName = ""
    @FocusState private var nameFocused: Bool

    private var displayedTime: String {
        timer.kind == .countdown
            ? TimeFormat.clock(timer.remaining(at: model.now))
            : TimeFormat.clock(timer.elapsed(at: model.now))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 7) {
                if timer.pinned { Image(systemName: "pin.fill").font(.caption).foregroundStyle(.secondary) }
                if editing {
                    TextField("Name", text: $editedName)
                        .textFieldStyle(.roundedBorder)
                        .focused($nameFocused)
                        .onSubmit(finishEditing)
                        .onChange(of: nameFocused) { focused in
                            if !focused, editing { finishEditing() }
                        }
                } else {
                    Text(timer.label)
                        .fontWeight(.medium)
                        .lineLimit(1)
                        .overlay(PressureRenameView(action: beginEditing))
                }
                Spacer(minLength: 4)
                Text(timer.finished ? "Done" : displayedTime)
                    .font(.system(.body, design: .monospaced).weight(.semibold))
                    .foregroundColor(timer.finished ? Color(nsColor: .secondaryLabelColor) : .accentColor)
            }

            HStack(spacing: 6) {
                if timer.finished {
                    Button("Restart") { model.restart(timer.id) }.controlSize(.small)
                    Button("Done") { model.cancel(timer.id) }.controlSize(.small)
                } else {
                    Button(timer.isPaused ? "Resume" : "Pause") { model.togglePause(timer.id) }.controlSize(.small)
                    if timer.kind == .stopwatch {
                        Button("Lap") { model.addLap(timer.id) }.controlSize(.small)
                    }
                    Spacer()
                    Menu {
                        Button(timer.pinned ? "Unpin" : "Pin") { model.togglePin(timer.id) }
                        Button("Duplicate") { model.duplicate(timer.id) }
                        Button("Rename", action: beginEditing)
                        Divider()
                        Button("Delete", role: .destructive) { model.cancel(timer.id) }
                    } label: { Image(systemName: "ellipsis.circle") }
                    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
                }
            }

            if timer.kind == .stopwatch, let lap = timer.laps.last {
                Text("Lap \(timer.laps.count) · \(TimeFormat.clock(lap))")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .padding(8)
        .background(.quaternary.opacity(0.55), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .stroke(timer.color?.swiftUIColor.opacity(0.55) ?? .clear, lineWidth: 1)
        }
        .contentShape(Rectangle())
        .contextMenu {
            Button(timer.isPaused ? "Resume" : "Pause") { model.togglePause(timer.id) }
            Button(timer.pinned ? "Unpin" : "Pin") { model.togglePin(timer.id) }
            Button("Duplicate") { model.duplicate(timer.id) }
            Button("Rename", action: beginEditing)
            Divider()
            Button("Delete") { model.cancel(timer.id) }
        }
        .onDisappear {
            if editing { finishEditing() }
        }
    }

    private func beginEditing() {
        editedName = timer.label
        editing = true
        DispatchQueue.main.async { nameFocused = true }
    }

    private func finishEditing() {
        guard editing else { return }
        model.rename(timer.id, label: editedName)
        editing = false
    }
}

private struct PressureRenameView: NSViewRepresentable {
    let action: () -> Void
    func makeNSView(context: Context) -> NSView { PressureView(action: action) }
    func updateNSView(_ nsView: NSView, context: Context) {}

    private final class PressureView: NSView {
        let action: () -> Void
        var fired = false
        init(action: @escaping () -> Void) { self.action = action; super.init(frame: .zero) }
        required init?(coder: NSCoder) { nil }
        override func mouseDown(with event: NSEvent) {
            if event.clickCount == 2 { action() }
        }
        override func rightMouseDown(with event: NSEvent) {
            nextResponder?.rightMouseDown(with: event)
        }
        override func pressureChange(with event: NSEvent) {
            if event.stage >= 2, !fired { fired = true; action() }
            if event.stage == 0 { fired = false }
        }
    }
}
