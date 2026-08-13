import AudioToolbox
import MultiTimerCore
import SwiftUI

struct MobileRootView: View {
    @ObservedObject var model: MobileAppModel
    @State private var showSettings = false

    var body: some View {
        TabView {
            NavigationStack {
                MobilePresetsView(model: model)
                    .navigationTitle("Presets")
                    .toolbar { settingsButton }
            }
            .tabItem { Label("Presets", systemImage: "square.grid.2x2") }

            NavigationStack {
                MobileTimersView(model: model)
                    .navigationTitle("Timers")
                    .toolbar { settingsButton }
            }
            .tabItem { Label("Timers", systemImage: "timer") }
        }
        .sheet(isPresented: $showSettings) { MobileSettingsView(model: model) }
    }

    private var settingsButton: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Button { showSettings = true } label: { Image(systemName: "gearshape") }
        }
    }
}

struct MobilePresetsView: View {
    @ObservedObject var model: MobileAppModel
    @State private var search = ""
    @State private var editing: TimerPreset?

    private var filtered: [TimerPreset] {
        search.isEmpty ? model.presets : model.presets.filter { $0.name.localizedCaseInsensitiveContains(search) }
    }

    var body: some View {
        List {
            if !model.favorites.isEmpty {
                Section("Favorites") {
                    ForEach(model.favorites) { preset in
                        Button { model.startPreset(preset) } label: {
                            Label {
                                HStack {
                                    Text(preset.name)
                                    Spacer()
                                    Text(TimeFormat.short(preset.durationSeconds)).monospacedDigit().foregroundStyle(.secondary)
                                }
                            } icon: { Image(systemName: "play.circle.fill").foregroundStyle(color(preset.color)) }
                        }
                    }
                }
            }
            Section("All Presets") {
                ForEach(filtered) { preset in
                    HStack(spacing: 12) {
                        Button { model.startPreset(preset) } label: {
                            Image(systemName: "play.fill").foregroundStyle(color(preset.color))
                        }
                        .buttonStyle(.plain)
                        VStack(alignment: .leading) {
                            Text(preset.name)
                            Text(TimeFormat.clock(TimeInterval(preset.durationSeconds)))
                                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Button { model.toggleFavorite(preset.id) } label: {
                            Image(systemName: preset.favoriteRank == nil ? "star" : "star.fill")
                                .foregroundStyle(preset.favoriteRank == nil ? Color.secondary : .yellow)
                        }
                        .buttonStyle(.plain)
                    }
                    .contentShape(Rectangle())
                    .onTapGesture { editing = preset }
                    .swipeActions {
                        Button("Delete", role: .destructive) { model.deletePreset(preset.id) }
                    }
                }
                .onMove(perform: model.movePresets)
            }
        }
        .searchable(text: $search, prompt: "Search Presets")
        .overlay {
            if model.presets.isEmpty {
                ContentUnavailableView(
                    "No Presets",
                    systemImage: "square.grid.2x2",
                    description: Text("Save a countdown once, then start it with one tap.")
                )
            }
        }
        .toolbar {
            ToolbarItem(placement: .topBarLeading) { EditButton() }
            ToolbarItem(placement: .primaryAction) {
                Button { editing = TimerPreset(name: "", durationSeconds: 300) } label: { Image(systemName: "plus") }
            }
        }
        .sheet(item: $editing) { MobilePresetEditor(model: model, preset: $0) }
    }

    private func color(_ value: PresetColor) -> Color {
        switch value {
        case .blue: .blue
        case .green: .green
        case .orange: .orange
        case .pink: .pink
        case .purple: .purple
        case .red: .red
        case .teal: .teal
        case .yellow: .yellow
        }
    }
}

private struct MobilePresetEditor: View {
    @ObservedObject var model: MobileAppModel
    @Environment(\.dismiss) private var dismiss
    @State private var preset: TimerPreset

    init(model: MobileAppModel, preset: TimerPreset) {
        self.model = model
        _preset = State(initialValue: preset)
    }

    var body: some View {
        NavigationStack {
            Form {
                TextField("Name", text: $preset.name)
                Section("Duration") {
                    HStack { Spacer(); Text(TimeFormat.clock(TimeInterval(preset.durationSeconds))).monospacedDigit(); Spacer() }
                    Slider(
                        value: Binding(
                            get: { pow(Double(preset.durationSeconds) / 86_400, 1 / 3) },
                            set: { preset.durationSeconds = max(1, Int(86_400 * pow($0, 3))) }
                        ),
                        in: 0.01...1
                    )
                }
                Picker("Color", selection: $preset.color) {
                    ForEach(PresetColor.allCases, id: \.self) { Text($0.rawValue.capitalized).tag($0) }
                }
                Picker("Sound", selection: sound) {
                    Text("Muted").tag("muted")
                    ForEach(["Glass", "Hero", "Ping", "Pop", "Purr", "Submarine"], id: \.self) { Text($0).tag($0) }
                }
                Button("Preview Sound") { AudioServicesPlaySystemSound(1007) }
                    .disabled(preset.sound.kind == .muted)
                Picker("Early Reminder", selection: $preset.earlyReminderMinutes) {
                    Text("None").tag(Int?.none)
                    Text("1 minute").tag(Int?.some(1))
                    Text("5 minutes").tag(Int?.some(5))
                    Text("10 minutes").tag(Int?.some(10))
                }
                Toggle("Favorite", isOn: favorite)
                    .disabled(preset.favoriteRank == nil && model.favorites.count >= 4)
            }
            .navigationTitle(preset.name.isEmpty ? "New Preset" : "Edit Preset")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") { model.savePreset(preset); dismiss() }
                        .disabled(preset.name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    private var sound: Binding<String> {
        Binding(
            get: { preset.sound.kind == .muted ? "muted" : preset.sound.name ?? "Glass" },
            set: { preset.sound = $0 == "muted" ? .muted : PresetSound(kind: .system, name: $0) }
        )
    }

    private var favorite: Binding<Bool> {
        Binding(
            get: { preset.favoriteRank != nil },
            set: { preset.favoriteRank = $0 ? min(model.favorites.count, 3) : nil }
        )
    }
}
