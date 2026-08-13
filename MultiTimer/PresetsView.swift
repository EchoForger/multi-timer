import AppKit
import MultiTimerCore
import SwiftUI

extension PresetColor {
    var swiftUIColor: Color {
        switch self {
        case .blue: return .blue
        case .green: return .green
        case .orange: return .orange
        case .pink: return .pink
        case .purple: return .purple
        case .red: return .red
        case .teal: return .teal
        case .yellow: return .yellow
        }
    }
}

struct PresetFavoritesView: View {
    @ObservedObject var model: AppModel
    let showAll: () -> Void

    private var favorites: [TimerPreset] { PresetCollection.favorites(model.presets) }

    var body: some View {
        if !model.presets.isEmpty {
            GroupBox {
                VStack(spacing: 7) {
                    if favorites.isEmpty {
                        Text("Favorite up to four presets for one-click access.")
                            .font(.caption).foregroundStyle(.secondary)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    } else {
                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 6) {
                            ForEach(favorites) { preset in
                                Button { model.startPreset(preset) } label: {
                                    HStack(spacing: 6) {
                                        Circle().fill(preset.color.swiftUIColor).frame(width: 7, height: 7)
                                        Text(preset.name).lineLimit(1)
                                        Spacer(minLength: 2)
                                        Text(TimeFormat.short(preset.durationSeconds)).monospacedDigit()
                                    }
                                    .font(.caption)
                                    .frame(maxWidth: .infinity)
                                }
                            }
                        }
                    }
                }
                .padding(2)
            } label: {
                HStack {
                    Label("Presets", systemImage: "square.grid.2x2")
                    Spacer()
                    Button("All", action: showAll).buttonStyle(.borderless).controlSize(.small)
                }
            }
        } else {
            Button(action: showAll) {
                Label("Create a one-click timer preset", systemImage: "square.grid.2x2")
                    .frame(maxWidth: .infinity)
            }
            .controlSize(.small)
        }
    }
}

struct PresetsView: View {
    @ObservedObject var model: AppModel
    @State private var search = ""
    @State private var editingPreset: TimerPreset?

    private var filtered: [TimerPreset] {
        guard !search.isEmpty else { return model.presets }
        return model.presets.filter { $0.name.localizedCaseInsensitiveContains(search) }
    }

    var body: some View {
        VStack(spacing: 10) {
            HStack {
                TextField("Search Presets", text: $search)
                    .textFieldStyle(.roundedBorder)
                Button { editingPreset = newPreset } label: { Image(systemName: "plus") }
                    .help("New Preset")
            }

            if filtered.isEmpty {
                VStack(spacing: 8) {
                    Image(systemName: "square.grid.2x2").font(.title).foregroundStyle(.secondary)
                    Text(search.isEmpty ? "No Presets" : "No Matching Presets").font(.headline)
                    Text("Save frequently used countdowns and start them with one click.")
                        .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    if search.isEmpty { Button("Create Preset") { editingPreset = newPreset } }
                }
                .frame(maxWidth: .infinity, minHeight: 280)
            } else {
                ScrollView {
                    LazyVStack(spacing: 7) {
                        ForEach(filtered) { preset in
                            presetRow(preset)
                                .draggable(preset.id)
                                .dropDestination(for: String.self) { ids, _ in
                                    guard let source = ids.first else { return false }
                                    model.movePreset(source, before: preset.id)
                                    return true
                                }
                        }
                    }
                }
            }
        }
        .padding(12)
        .sheet(item: $editingPreset) { preset in
            PresetEditorView(model: model, preset: preset)
        }
    }

    private func presetRow(_ preset: TimerPreset) -> some View {
        HStack(spacing: 8) {
            Button { model.startPreset(preset) } label: {
                Image(systemName: "play.fill")
                    .foregroundStyle(preset.color.swiftUIColor)
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.borderless)
            VStack(alignment: .leading, spacing: 2) {
                Text(preset.name).font(.subheadline.weight(.medium)).lineLimit(1)
                HStack(spacing: 5) {
                    Text(TimeFormat.clock(TimeInterval(preset.durationSeconds))).monospacedDigit()
                    if let reminder = preset.earlyReminderMinutes { Text("· \(reminder) min early") }
                    if preset.sound.kind == .muted { Image(systemName: "speaker.slash") }
                }
                .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button { model.togglePresetFavorite(preset.id) } label: {
                Image(systemName: preset.favoriteRank == nil ? "star" : "star.fill")
                    .foregroundStyle(preset.favoriteRank == nil ? Color.secondary : Color.yellow)
            }
            .buttonStyle(.borderless)
            Menu {
                Button("Edit") { editingPreset = preset }
                Button("Delete", role: .destructive) { model.deletePreset(preset.id) }
            } label: { Image(systemName: "ellipsis.circle") }
                .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
        }
        .padding(8)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 9))
        .overlay { RoundedRectangle(cornerRadius: 9).stroke(preset.color.swiftUIColor.opacity(0.45), lineWidth: 1) }
    }

    private var newPreset: TimerPreset {
        TimerPreset(name: "", durationSeconds: 300, sortOrder: model.presets.count)
    }
}

private struct PresetEditorView: View {
    @ObservedObject var model: AppModel
    @Environment(\.dismiss) private var dismiss
    @State private var preset: TimerPreset

    private let soundNames = ["Glass", "Hero", "Ping", "Pop", "Purr", "Submarine"]

    init(model: AppModel, preset: TimerPreset) {
        self.model = model
        _preset = State(initialValue: preset)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(preset.name.isEmpty ? "New Preset" : "Edit Preset").font(.title2.bold())
            TextField("Preset Name", text: $preset.name).textFieldStyle(.roundedBorder)

            VStack(alignment: .leading, spacing: 5) {
                HStack { Text("Duration"); Spacer(); Text(TimeFormat.clock(TimeInterval(preset.durationSeconds))).monospacedDigit() }
                Slider(
                    value: Binding(
                        get: { pow(Double(preset.durationSeconds) / 86_400, 1.0 / 3.0) },
                        set: { preset.durationSeconds = max(1, Int(86_400 * pow($0, 3))) }
                    ),
                    in: 0.01...1
                )
            }

            Picker("Color", selection: $preset.color) {
                ForEach(PresetColor.allCases, id: \.self) { color in
                    Label(color.rawValue.capitalized, systemImage: "circle.fill")
                        .foregroundStyle(color.swiftUIColor)
                        .tag(color)
                }
            }

            HStack {
                Picker("Sound", selection: soundSelection) {
                    Text("Muted").tag("muted")
                    ForEach(soundNames, id: \.self) { Text($0).tag($0) }
                }
                Button("Preview", action: previewSound).disabled(preset.sound.kind == .muted)
            }

            Picker("Early Reminder", selection: $preset.earlyReminderMinutes) {
                Text("None").tag(Int?.none)
                Text("1 min early").tag(Int?.some(1))
                Text("5 min early").tag(Int?.some(5))
                Text("10 min early").tag(Int?.some(10))
            }

            Toggle("Favorite", isOn: favoriteBinding)
                .disabled(preset.favoriteRank == nil && PresetCollection.favorites(model.presets).count >= 4)

            HStack {
                Button("Cancel") { dismiss() }
                Spacer()
                Button("Save") {
                    model.savePreset(preset)
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .disabled(preset.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(20)
        .frame(width: 390)
    }

    private var soundSelection: Binding<String> {
        Binding(
            get: { preset.sound.kind == .muted ? "muted" : (preset.sound.name ?? "Glass") },
            set: { preset.sound = $0 == "muted" ? .muted : PresetSound(kind: .system, name: $0) }
        )
    }

    private var favoriteBinding: Binding<Bool> {
        Binding(
            get: { preset.favoriteRank != nil },
            set: { value in preset.favoriteRank = value ? PresetCollection.favorites(model.presets).count : nil }
        )
    }

    private func previewSound() {
        guard let name = preset.sound.name else { return }
        NSSound(named: NSSound.Name(name))?.play()
    }
}
