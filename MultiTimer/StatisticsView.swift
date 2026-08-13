import AppKit
import MultiTimerCore
import SwiftUI
import UniformTypeIdentifiers

struct StatisticsView: View {
    @ObservedObject var model: AppModel
    @State private var selectedDay = Date()
    @State private var reviewPeriod: FocusReviewPeriod = .week
    @State private var reviewAnchor = Date()
    @State private var confirmClear = false

    private let store = StatsStore()
    private var daily: [String: DailyFocusSummary] { FocusAnalytics.dailySummaries(from: model.stats) }
    private var selectedKey: String { FocusAnalytics.dayKey(for: selectedDay) }
    private var selectedSummary: DailyFocusSummary { daily[selectedKey] ?? DailyFocusSummary(day: selectedKey) }
    private var sessions: [FocusSession] { store.sessions(in: selectedDay, from: model.stats) }
    private var review: FocusPeriodSummary {
        FocusAnalytics.periodSummary(
            stats: model.stats,
            period: reviewPeriod,
            containing: reviewAnchor,
            now: Date(timeIntervalSince1970: model.now)
        )
    }
    private var totalFocusedSeconds: TimeInterval { model.stats.sessions.reduce(0) { $0 + $1.focusedSeconds } }
    private var unlockedBadgeHours: Int { FocusAnalytics.badgeHours.last(where: { totalFocusedSeconds >= TimeInterval($0 * 3_600) }) ?? 0 }
    private var nextBadgeHours: Int? { FocusAnalytics.badgeHours.first(where: { totalFocusedSeconds < TimeInterval($0 * 3_600) }) }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            goalSection
            reviewSection
            badgeSection
            Divider()
            dayDetail
            exportAndClear
        }
        .padding(14)
        .alert("Clear all statistics?", isPresented: $confirmClear) {
            Button("Cancel", role: .cancel) {}
            Button("Clear", role: .destructive) { model.clearStats() }
        } message: {
            Text("This removes all recorded Pomodoro sessions and focus periods. Your daily goal is kept. This cannot be undone.")
        }
    }

    @ViewBuilder
    private var goalSection: some View {
        if model.settings.dailyFocusGoals.isEmpty && !model.settings.hasSeenFocusGoalPrompt {
            GroupBox {
                VStack(alignment: .leading, spacing: 8) {
                    Text("A small daily goal can make focus easier to sustain.")
                        .font(.subheadline)
                    HStack {
                        Button("Set 60 min goal") { model.setDailyFocusGoal(minutes: 60) }
                            .buttonStyle(.borderedProminent)
                        Button("Not now") { model.dismissFocusGoalPrompt() }
                    }
                    .controlSize(.small)
                }
                .padding(2)
            } label: { Label("Daily Focus Goal", systemImage: "target") }
        } else if let goal = model.todayGoalMinutes {
            GroupBox {
                VStack(spacing: 8) {
                    HStack {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Today’s progress").font(.subheadline.weight(.medium))
                            Text("\(Int(model.todayFocusedSeconds) / 60) / \(goal) min")
                                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                        }
                        Spacer()
                        Label("\(model.currentFocusStreak) day streak", systemImage: "flame.fill")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(model.currentFocusStreak > 0 ? .orange : .secondary)
                    }
                    ProgressView(value: min(1, model.todayFocusedSeconds / TimeInterval(goal * 60)))
                    HStack {
                        Slider(
                            value: Binding(
                                get: { Double(goal) },
                                set: { model.setDailyFocusGoal(minutes: Int($0.rounded() / 15) * 15) }
                            ),
                            in: 15...480,
                            step: 15
                        )
                        Text("\(goal) min").font(.caption.monospacedDigit()).frame(width: 52, alignment: .trailing)
                        Button("Disable") { model.setDailyFocusGoal(minutes: nil) }.controlSize(.small)
                    }
                }
                .padding(2)
            } label: { Label("Daily Focus Goal", systemImage: "target") }
        } else {
            HStack {
                Label("Daily Focus Goal", systemImage: "target")
                Spacer()
                Button("Set 60 min goal") { model.setDailyFocusGoal(minutes: 60) }.controlSize(.small)
            }
        }
    }

    private var reviewSection: some View {
        GroupBox {
            VStack(spacing: 10) {
                HStack {
                    Button { movePeriod(-1) } label: { Image(systemName: "chevron.left") }
                        .buttonStyle(.borderless)
                    Text(periodTitle).font(.subheadline.weight(.semibold)).frame(maxWidth: .infinity)
                    Button { movePeriod(1) } label: { Image(systemName: "chevron.right") }
                        .buttonStyle(.borderless)
                        .disabled(isCurrentPeriod)
                }
                Picker("Review period", selection: $reviewPeriod) {
                    Text("Week").tag(FocusReviewPeriod.week)
                    Text("Month").tag(FocusReviewPeriod.month)
                }
                .labelsHidden()
                .pickerStyle(.segmented)

                HStack(spacing: 8) {
                    metricCard("Focus Time", value: compactDuration(review.focusedSeconds), icon: "clock")
                    metricCard("Pomodoros", value: "\(review.completedPomodoros)", icon: "checkmark.circle")
                }
                FocusTrend(days: review.days)
                    .frame(height: 82)
                FocusHeatmap(days: review.days)
                comparisonText
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .padding(2)
        } label: { Label("Focus Review", systemImage: "chart.xyaxis.line") }
    }

    private var badgeSection: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 8) {
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 6), count: 4), spacing: 6) {
                    ForEach(FocusAnalytics.badgeHours, id: \.self) { hours in
                        let unlocked = hours <= unlockedBadgeHours
                        VStack(spacing: 3) {
                            Image(systemName: unlocked ? "medal.fill" : "medal")
                                .foregroundStyle(unlocked ? Color.orange : Color.secondary)
                            Text("\(hours)h").font(.caption2.monospacedDigit())
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 6)
                        .background(.quaternary.opacity(unlocked ? 0.8 : 0.35), in: RoundedRectangle(cornerRadius: 7))
                    }
                }
                if let nextBadgeHours {
                    let target = TimeInterval(nextBadgeHours * 3_600)
                    ProgressView(value: min(1, totalFocusedSeconds / target))
                    Text("Next badge: \(compactDuration(max(0, target - totalFocusedSeconds))) remaining")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Text("All focus badges unlocked")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }
            .padding(2)
        } label: { Label("Focus Milestones", systemImage: "medal") }
    }

    private var dayDetail: some View {
        VStack(alignment: .leading, spacing: 10) {
            dayPicker
            HStack(spacing: 8) {
                metricCard("Focus Sessions", value: "\(selectedSummary.focusSessions)", icon: "brain.head.profile")
                metricCard("Pomodoros", value: "\(selectedSummary.completedPomodoros)", icon: "checkmark.circle")
                metricCard("Focus Time", value: compactDuration(selectedSummary.focusedSeconds), icon: "clock")
            }
            GroupBox("24-Hour Focus Timeline") {
                FocusTimeline(day: selectedDay, sessions: sessions)
                    .frame(height: 74)
                    .padding(.vertical, 5)
            }
            if selectedSummary.containsEstimate {
                Label("Some legacy durations are estimated from their start and end times.", systemImage: "info.circle")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if sessions.isEmpty {
                VStack(spacing: 7) {
                    Image(systemName: "moon.zzz").font(.title2).foregroundStyle(.secondary)
                    Text("No Focus Sessions").font(.headline)
                    Text("Completed and interrupted focus periods will appear here.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 90)
            } else {
                GroupBox("Focus Periods") {
                    VStack(spacing: 0) {
                        ForEach(Array(sessions.sorted { $0.startedAt < $1.startedAt }.enumerated()), id: \.element.id) { index, session in
                            sessionRow(session)
                            if index < sessions.count - 1 { Divider() }
                        }
                    }
                    .padding(.horizontal, 4)
                }
            }
        }
    }

    private var exportAndClear: some View {
        HStack {
            Text("Stored locally · \(model.stats.sessions.count) sessions")
                .font(.caption).foregroundStyle(.secondary)
            Spacer()
            Menu("Export") {
                Button("Export CSV…", action: exportCSV)
                Button("Export JSON Backup…", action: exportJSON)
            }
            .controlSize(.small)
            Button("Clear All…") { confirmClear = true }.controlSize(.small)
        }
    }

    private var dayPicker: some View {
        HStack {
            Button { moveDay(-1) } label: { Image(systemName: "chevron.left") }.buttonStyle(.borderless)
            Spacer()
            Text(selectedDay.formatted(date: .complete, time: .omitted)).font(.headline)
            Spacer()
            Button { moveDay(1) } label: { Image(systemName: "chevron.right") }.buttonStyle(.borderless)
                .disabled(Calendar.current.isDateInToday(selectedDay))
        }
    }

    private func metricCard(_ title: LocalizedStringKey, value: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Image(systemName: icon).foregroundStyle(.tint)
            Text(value).font(.headline.monospacedDigit())
            Text(title).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
        }
        .padding(8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 8))
    }

    private func sessionRow(_ session: FocusSession) -> some View {
        HStack(spacing: 8) {
            Image(systemName: session.completed ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(session.completed ? Color.green : Color.secondary)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 4) {
                    Text(LocalizedStringKey(session.completed ? "Completed Pomodoro" : "Focus Session"))
                        .font(.subheadline.weight(.medium))
                    if session.legacyEstimated { Text("Estimated").font(.caption2).foregroundStyle(.secondary) }
                }
                Text(timeDescription(session)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            Spacer()
            Text(compactDuration(session.focusedSeconds)).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
        .padding(.vertical, 7)
    }

    private var periodTitle: String {
        let interval = FocusAnalytics.periodInterval(reviewPeriod, containing: reviewAnchor, calendar: Calendar.current)
        switch reviewPeriod {
        case .week:
            return "\(interval.start.formatted(date: .abbreviated, time: .omitted)) – \(interval.end.addingTimeInterval(-1).formatted(date: .abbreviated, time: .omitted))"
        case .month:
            return interval.start.formatted(.dateTime.year().month(.wide))
        }
    }

    private var isCurrentPeriod: Bool {
        let current = FocusAnalytics.periodInterval(reviewPeriod, containing: Date(), calendar: Calendar.current)
        return current.contains(reviewAnchor)
    }

    private var comparisonText: Text {
        let minuteDelta = Int((review.focusedSeconds - review.previousFocusedSeconds) / 60)
        let pomodoroDelta = review.completedPomodoros - review.previousCompletedPomodoros
        let value = String.localizedStringWithFormat(
            NSLocalizedString("Previous period: %@ focus · %@ Pomodoros", comment: "Period comparison"),
            signedMinutes(minuteDelta),
            signedCount(pomodoroDelta)
        )
        return Text(verbatim: value)
    }

    private func signedMinutes(_ value: Int) -> String {
        guard value != 0 else { return NSLocalizedString("no change", comment: "No period change") }
        return String.localizedStringWithFormat(
            NSLocalizedString("%@ min", comment: "Signed focus minute difference"),
            "\(value > 0 ? "+" : "")\(value)"
        )
    }
    private func signedCount(_ value: Int) -> String {
        value == 0 ? NSLocalizedString("no change", comment: "No period change") : "\(value > 0 ? "+" : "")\(value)"
    }

    private func movePeriod(_ amount: Int) {
        let component: Calendar.Component = reviewPeriod == .week ? .weekOfYear : .month
        if let date = Calendar.current.date(byAdding: component, value: amount, to: reviewAnchor) { reviewAnchor = min(date, Date()) }
    }

    private func moveDay(_ amount: Int) {
        if let date = Calendar.current.date(byAdding: .day, value: amount, to: selectedDay) { selectedDay = min(date, Date()) }
    }

    private func timeDescription(_ session: FocusSession) -> String {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        formatter.timeZone = TimeZone(identifier: session.timeZoneIdentifier)
        let start = formatter.string(from: Date(timeIntervalSince1970: session.startedAt))
        let end = session.endedAt.map { formatter.string(from: Date(timeIntervalSince1970: $0)) } ?? ""
        return "\(start)–\(end)"
    }

    private func compactDuration(_ seconds: TimeInterval) -> String {
        let minutes = Int(seconds) / 60
        if minutes >= 60 {
            return String.localizedStringWithFormat(
                NSLocalizedString("%lldh %02lldm", comment: "Compact hours and minutes"),
                minutes / 60,
                minutes % 60
            )
        }
        return String.localizedStringWithFormat(NSLocalizedString("%lldm", comment: "Compact minutes"), minutes)
    }

    private func exportCSV() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "MultiTimer-Focus-History.csv"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let formatter = ISO8601DateFormatter()
        var rows = ["id,started_at,ended_at,focused_seconds,completed,time_zone,legacy_estimated"]
        for session in model.stats.sessions {
            let start = formatter.string(from: Date(timeIntervalSince1970: session.startedAt))
            let end = session.endedAt.map { formatter.string(from: Date(timeIntervalSince1970: $0)) } ?? ""
            rows.append("\(session.id),\(start),\(end),\(Int(session.focusedSeconds)),\(session.completed),\(session.timeZoneIdentifier),\(session.legacyEstimated)")
        }
        try? (rows.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
    }

    private func exportJSON() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.json]
        panel.nameFieldStringValue = "MultiTimer-Focus-History.json"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        if let data = try? encoder.encode(model.stats) { try? data.write(to: url, options: .atomic) }
    }
}

private struct FocusTrend: View {
    let days: [DailyFocusSummary]
    private var maximum: TimeInterval { max(60, days.map(\.focusedSeconds).max() ?? 60) }

    var body: some View {
        HStack(alignment: .bottom, spacing: days.count > 14 ? 2 : 6) {
            ForEach(days) { day in
                VStack(spacing: 3) {
                    Spacer(minLength: 0)
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.accentColor.gradient)
                        .frame(height: max(2, 54 * day.focusedSeconds / maximum))
                    if days.count <= 7 { Text(String(day.day.suffix(2))).font(.system(size: 8).monospacedDigit()) }
                }
                .frame(maxWidth: .infinity)
                .help("\(day.day): \(Int(day.focusedSeconds) / 60) min · \(day.completedPomodoros) Pomodoros")
            }
        }
        .accessibilityLabel("Focus time trend")
    }
}

private struct FocusHeatmap: View {
    let days: [DailyFocusSummary]
    private let columns = Array(repeating: GridItem(.flexible(), spacing: 4), count: 7)

    var body: some View {
        LazyVGrid(columns: columns, spacing: 4) {
            ForEach(days) { day in
                RoundedRectangle(cornerRadius: 3)
                    .fill(color(for: day.completedPomodoros))
                    .frame(height: 15)
                    .help("\(day.day): \(day.completedPomodoros) Pomodoros")
            }
        }
        .accessibilityLabel("Completed Pomodoro heatmap")
    }

    private func color(for count: Int) -> Color {
        guard count > 0 else { return Color.secondary.opacity(0.12) }
        return Color.accentColor.opacity([0.28, 0.46, 0.66, 0.9][min(count, 4) - 1])
    }
}

private struct FocusTimeline: View {
    let day: Date
    let sessions: [FocusSession]

    var body: some View {
        VStack(spacing: 5) {
            HStack {
                ForEach([0, 6, 12, 18, 24], id: \.self) { hour in
                    Text(String(format: "%02d", hour)).font(.system(size: 9).monospacedDigit())
                    if hour != 24 { Spacer() }
                }
            }
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 5).fill(.quaternary.opacity(0.6))
                    ForEach(1..<4, id: \.self) { quarter in
                        Rectangle().fill(Color(nsColor: .separatorColor).opacity(0.65)).frame(width: 1)
                            .offset(x: proxy.size.width * CGFloat(quarter) / 4)
                    }
                    ForEach(Array(clippedIntervals.enumerated()), id: \.offset) { _, interval in
                        RoundedRectangle(cornerRadius: 4).fill(Color.accentColor.gradient)
                            .frame(width: max(2, proxy.size.width * interval.durationFraction), height: 26)
                            .offset(x: proxy.size.width * interval.offsetFraction)
                    }
                }
            }
            .frame(height: 32)
        }
    }

    private var clippedIntervals: [(offsetFraction: CGFloat, durationFraction: CGFloat)] {
        let selectedKey = FocusAnalytics.dayKey(for: day)
        return sessions.flatMap { session -> [(offsetFraction: CGFloat, durationFraction: CGFloat)] in
            let timeZone = TimeZone(identifier: session.timeZoneIdentifier) ?? .current
            var calendar = Calendar(identifier: .gregorian)
            calendar.timeZone = timeZone
            guard let localDay = FocusAnalytics.date(for: selectedKey, timeZone: timeZone),
                  let nextDay = calendar.date(byAdding: .day, value: 1, to: localDay) else { return [] }
            let start = localDay.timeIntervalSince1970
            let end = nextDay.timeIntervalSince1970
            let dayDuration = max(1, end - start)
            return session.focusIntervals.compactMap { interval in
                let clippedStart = max(start, interval.startedAt)
                let clippedEnd = min(end, interval.endedAt)
                guard clippedEnd > clippedStart else { return nil }
                return (CGFloat((clippedStart - start) / dayDuration), CGFloat((clippedEnd - clippedStart) / dayDuration))
            }
        }
    }
}
