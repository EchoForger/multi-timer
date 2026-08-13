import MultiTimerCore
import SwiftUI
import WidgetKit

struct SharedEntry: TimelineEntry {
    let date: Date
    let document: SharedStateDocument
}

struct SharedProvider: TimelineProvider {
    func placeholder(in context: Context) -> SharedEntry { SharedEntry(date: .now, document: sampleDocument) }
    func getSnapshot(in context: Context, completion: @escaping (SharedEntry) -> Void) {
        completion(SharedEntry(date: .now, document: MobileAppGroup.store.load()))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<SharedEntry>) -> Void) {
        let entry = SharedEntry(date: .now, document: MobileAppGroup.store.load())
        completion(Timeline(entries: [entry], policy: .after(.now.addingTimeInterval(30))))
    }

    private var sampleDocument: SharedStateDocument {
        SharedStateDocument(presets: [
            TimerPreset(name: "Tea", durationSeconds: 300, color: .teal, favoriteRank: 0),
            TimerPreset(name: "Focus", durationSeconds: 1_500, color: .red, favoriteRank: 1),
        ])
    }
}

struct FavoritePresetsWidget: Widget {
    let kind = "FavoritePresetsWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SharedProvider()) { entry in
            FavoritePresetsWidgetView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Favorite Presets")
        .description("Start up to four favorite countdowns with one tap.")
        .supportedFamilies([.systemSmall, .systemMedium])
    }
}

private struct FavoritePresetsWidgetView: View {
    let entry: SharedEntry
    private var favorites: [TimerPreset] { PresetCollection.favorites(entry.document.presets) }

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label("MultiTimer", systemImage: "timer").font(.caption.bold())
            if favorites.isEmpty {
                Text("Favorite presets in MultiTimer to show them here.")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                ForEach(favorites.prefix(4)) { preset in
                    Button(intent: StartPresetIntent(presetID: preset.id)) {
                        HStack(spacing: 6) {
                            Circle().fill(color(preset.color)).frame(width: 7, height: 7)
                            Text(preset.name).lineLimit(1)
                            Spacer(minLength: 2)
                            Text(TimeFormat.short(preset.durationSeconds)).monospacedDigit()
                        }
                        .font(.caption)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
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
