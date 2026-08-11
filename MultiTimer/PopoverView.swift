import AppKit
import MultiTimerCore
import SwiftUI

private enum CreationMode: String, CaseIterable, Identifiable {
    case duration, target, stopwatch
    var id: String { rawValue }
}

struct PopoverView: View {
    @ObservedObject var model: AppModel
    @EnvironmentObject private var router: WindowRouter
    @State private var name = ""
    @State private var durationText = "5"
    @State private var targetText = ""
    @State private var mode: CreationMode = .duration
    @State private var sliderPosition = pow(300.0 / 86_400.0, 1.0 / 3.0)

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            ScrollView {
                VStack(spacing: 10) {
                    creationCard
                    if model.settings.showPomodoro { PomodoroView(model: model) }
                    timerList
                }
                .padding(12)
            }
            Divider()
            footer
        }
        .background(Color(nsColor: .windowBackgroundColor))
        .frame(width: 360, height: 640)
    }

    private var header: some View {
        HStack(spacing: 9) {
            Image(systemName: "timer")
                .font(.system(size: 17, weight: .semibold))
                .foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 1) {
                Text("MultiTimer").font(.headline)
                Text(model.activeCount == 0 ? "Ready when you are" : "\(model.activeCount) active")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button { router.statistics() } label: { Image(systemName: "chart.bar.xaxis") }
                .buttonStyle(.borderless).help("Statistics")
            Button { router.settings() } label: { Image(systemName: "gearshape") }
                .buttonStyle(.borderless).help("Settings")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
    }

    private var creationCard: some View {
        GroupBox {
            VStack(spacing: 8) {
                TextField("Name this timer", text: $name)
                    .textFieldStyle(.roundedBorder)
                Picker("", selection: $mode) {
                    Text("Duration").tag(CreationMode.duration)
                    Text("At Time").tag(CreationMode.target)
                    Text("Stopwatch").tag(CreationMode.stopwatch)
                }
                .labelsHidden().pickerStyle(.segmented)

                switch mode {
                case .duration:
                    HStack(spacing: 7) {
                        TextField("Minutes or HH:MM:SS", text: $durationText)
                            .textFieldStyle(.roundedBorder)
                            .onSubmit(start)
                        Button("Start", action: start).keyboardShortcut(.defaultAction)
                    }
                    Slider(value: $sliderPosition, in: 0.01...1) { Text("Duration") }
                        .onChange(of: sliderPosition) { value in
                            let seconds = max(60, Int((86_400 * pow(value, 3) / 60).rounded()) * 60)
                            durationText = seconds % 60 == 0 ? String(seconds / 60) : TimeFormat.clock(TimeInterval(seconds))
                        }
                    HStack(spacing: 6) {
                        ForEach([60, 300, 600, 900, 1800], id: \.self) { seconds in
                            Button("\(seconds / 60)m") { quickStart(seconds) }
                                .controlSize(.small).frame(maxWidth: .infinity)
                        }
                    }
                case .target:
                    HStack(spacing: 7) {
                        TextField("HH:MM or HH:MM:SS", text: $targetText)
                            .textFieldStyle(.roundedBorder).onSubmit(start)
                        Button("Start", action: start).keyboardShortcut(.defaultAction)
                    }
                case .stopwatch:
                    Button("Start Stopwatch", action: start)
                        .frame(maxWidth: .infinity).keyboardShortcut(.defaultAction)
                }
            }
            .padding(2)
        } label: { Label("New Timer", systemImage: "plus.circle") }
    }

    @ViewBuilder
    private var timerList: some View {
        if model.sortedTimers.isEmpty {
            VStack(spacing: 7) {
                Image(systemName: "timer").font(.title2).foregroundStyle(.secondary)
                Text("No Timers").font(.headline)
                Text("Use the controls above to start one.").font(.caption).foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 120)
        } else {
            VStack(alignment: .leading, spacing: 7) {
                HStack {
                    Text("Timers").font(.headline)
                    Spacer()
                    Text("\(model.activeCount) active").font(.caption).foregroundStyle(.secondary)
                }
                ForEach(model.sortedTimers) { timer in TimerRow(model: model, timer: timer) }
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
        .padding(.vertical, 9)
    }

    private func quickStart(_ seconds: Int) {
        model.startCountdown(label: name, seconds: seconds)
        name = ""
    }

    private func start() {
        switch mode {
        case .duration:
            guard let seconds = DurationParser.parse(durationText) else { NSSound.beep(); return }
            model.startCountdown(label: name, seconds: seconds)
        case .target:
            guard let date = DurationParser.targetDate(targetText) else { NSSound.beep(); return }
            model.startCountdown(label: name, target: date)
        case .stopwatch:
            model.startStopwatch(label: name)
        }
        name = ""
    }
}

private struct TimerRow: View {
    @ObservedObject var model: AppModel
    let timer: TimerRecord
    @State private var editing = false
    @State private var editedName = ""
    @State private var editedTime = ""

    private var displayedTime: String {
        timer.kind == .countdown
            ? TimeFormat.clock(timer.remaining(at: model.now))
            : TimeFormat.clock(timer.elapsed(at: model.now))
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 7) {
                if timer.pinned { Image(systemName: "pin.fill").font(.caption).foregroundStyle(.secondary) }
                if editing {
                    TextField("Name", text: $editedName, onCommit: finishEditing)
                        .textFieldStyle(.roundedBorder)
                } else {
                    Text(timer.label)
                        .fontWeight(.medium).lineLimit(1)
                        .overlay(PressureRenameView(action: beginEditing))
                }
                Spacer(minLength: 4)
                Text(timer.finished ? "Done" : displayedTime)
                    .font(.system(.body, design: .monospaced).weight(.semibold))
                    .foregroundColor(timer.finished ? Color(nsColor: .secondaryLabelColor) : .accentColor)
            }

            if timer.kind == .countdown, !timer.finished {
                ProgressView(value: progress)
                    .progressViewStyle(.linear)
            }

            HStack(spacing: 6) {
                if timer.finished {
                    Button("Restart") { model.restart(timer.id) }.controlSize(.small)
                    Button("Done") { model.cancel(timer.id) }.controlSize(.small)
                } else {
                    Button(timer.isPaused ? "Resume" : "Pause") { model.togglePause(timer.id) }.controlSize(.small)
                    if timer.kind == .stopwatch {
                        Button("Lap") { model.addLap(timer.id) }.controlSize(.small)
                    } else {
                        TextField("HH:MM:SS", text: $editedTime)
                            .frame(width: 82).controlSize(.small)
                            .onSubmit(applyRemaining)
                    }
                    Spacer()
                    Menu {
                        Button(timer.pinned ? "Unpin" : "Pin") { model.togglePin(timer.id) }
                        Button("Duplicate") { model.duplicate(timer.id) }
                        Button("Rename", action: beginEditing)
                        if timer.kind == .countdown { Button("Set Target Time…", action: editTargetTime) }
                        Divider()
                        Button("Delete", role: .destructive) { model.cancel(timer.id) }
                    } label: { Image(systemName: "ellipsis.circle") }
                    .menuStyle(.borderlessButton).fixedSize()
                }
            }

            if timer.kind == .stopwatch, let lap = timer.laps.last {
                Text("Lap \(timer.laps.count) · \(TimeFormat.clock(lap))")
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .padding(8)
        .background(.quaternary.opacity(0.55), in: RoundedRectangle(cornerRadius: 9, style: .continuous))
        .contextMenu {
            Button(timer.isPaused ? "Resume" : "Pause") { model.togglePause(timer.id) }
            Button(timer.pinned ? "Unpin" : "Pin") { model.togglePin(timer.id) }
            Button("Duplicate") { model.duplicate(timer.id) }
            Button("Rename", action: beginEditing)
            if timer.kind == .countdown { Button("Set Target Time…", action: editTargetTime) }
            Divider()
            Button("Delete") { model.cancel(timer.id) }
        }
        .onAppear { editedTime = displayedTime }
        .onChange(of: displayedTime) { value in if !editing { editedTime = value } }
    }

    private var progress: Double {
        let total = max(1, timer.originalDuration ?? 1)
        return min(1, max(0, 1 - timer.remaining(at: model.now) / total))
    }

    private func beginEditing() { editedName = timer.label; editing = true }
    private func finishEditing() { model.rename(timer.id, label: editedName); editing = false }
    private func applyRemaining() {
        guard let seconds = DurationParser.parse(editedTime) else { NSSound.beep(); return }
        model.setRemaining(timer.id, seconds: seconds)
    }

    private func editTargetTime() {
        let alert = NSAlert()
        alert.messageText = NSLocalizedString("Set Target Time", comment: "Timer editor")
        alert.informativeText = NSLocalizedString("Enter a time today or tomorrow in HH:MM or HH:MM:SS format.", comment: "Timer editor")
        alert.addButton(withTitle: NSLocalizedString("Set", comment: "Timer editor"))
        alert.addButton(withTitle: NSLocalizedString("Cancel", comment: "Timer editor"))
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 220, height: 24))
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        field.stringValue = formatter.string(from: Date(timeIntervalSince1970: timer.endTS ?? model.now))
        alert.accessoryView = field
        guard alert.runModal() == .alertFirstButtonReturn,
              let target = DurationParser.targetDate(field.stringValue) else { return }
        model.setTarget(timer.id, target: target)
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
