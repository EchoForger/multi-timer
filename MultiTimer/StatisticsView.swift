import AppKit
import MultiTimerCore
import SwiftUI

struct StatisticsView: View {
    @ObservedObject var model: AppModel
    @State private var selectedDay = Date()
    @State private var confirmClear = false

    private let store = StatsStore()
    private var sessions: [FocusSession] { store.sessions(in: selectedDay, from: model.stats) }
    private var startedSessions: [FocusSession] {
        model.stats.sessions.filter { Calendar.current.isDate(Date(timeIntervalSince1970: $0.startedAt), inSameDayAs: selectedDay) }
    }
    private var completed: Int {
        model.stats.sessions.filter { session in
            session.completed && session.endedAt.map { Calendar.current.isDate(Date(timeIntervalSince1970: $0), inSameDayAs: selectedDay) } == true
        }.count
    }
    private var focusedSeconds: TimeInterval { store.focusedSeconds(in: selectedDay, from: model.stats) }
    private var allCompleted: Int { model.stats.sessions.filter(\.completed).count }

    var body: some View {
        VStack(alignment: .leading, spacing: 13) {
            dayPicker

            HStack(spacing: 8) {
                summaryCard("Focus Sessions", value: "\(startedSessions.count)", icon: "brain.head.profile")
                summaryCard("Pomodoros", value: "\(completed)", icon: "checkmark.circle")
                summaryCard("Focus Time", value: compactDuration(focusedSeconds), icon: "clock")
            }

            GroupBox("24-Hour Focus Timeline") {
                FocusTimeline(day: selectedDay, sessions: sessions)
                    .frame(height: 74)
                    .padding(.vertical, 5)
            }

            if sessions.isEmpty {
                VStack(spacing: 7) {
                    Image(systemName: "moon.zzz").font(.title2).foregroundStyle(.secondary)
                    Text("No Focus Sessions").font(.headline)
                    Text("Completed and interrupted focus periods will appear here.")
                        .font(.caption).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 140)
            } else {
                GroupBox("Focus Periods") {
                    VStack(spacing: 0) {
                        ForEach(sessions.sorted { $0.startedAt < $1.startedAt }) { session in
                            sessionRow(session)
                            if session.id != sessions.sorted(by: { $0.startedAt < $1.startedAt }).last?.id { Divider() }
                        }
                    }
                    .padding(.horizontal, 4)
                }
            }

            Text("All time: \(model.stats.sessions.count) sessions · \(allCompleted) completed Pomodoros")
                .font(.caption).foregroundStyle(.secondary)
            HStack {
                Spacer()
                Button("Export CSV…", action: exportCSV).controlSize(.small)
                Button("Clear All…") { confirmClear = true }.controlSize(.small)
            }
        }
        .padding(14)
        .alert("Clear all statistics?", isPresented: $confirmClear) {
            Button("Cancel", role: .cancel) {}
            Button("Clear", role: .destructive) { model.clearStats() }
        } message: {
            Text("This removes all recorded Pomodoro sessions and focus periods. This cannot be undone.")
        }
    }

    private var dayPicker: some View {
        HStack {
            Button { moveDay(-1) } label: { Image(systemName: "chevron.left") }
                .buttonStyle(.borderless)
            Spacer()
            Text(selectedDay.formatted(date: .complete, time: .omitted))
                .font(.headline)
            Spacer()
            Button { moveDay(1) } label: { Image(systemName: "chevron.right") }
                .buttonStyle(.borderless)
                .disabled(Calendar.current.isDateInToday(selectedDay))
        }
    }

    private func summaryCard(_ title: LocalizedStringKey, value: String, icon: String) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Image(systemName: icon).foregroundStyle(.tint)
            Text(value).font(.headline.monospacedDigit())
            Text(title).font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
        }
        .padding(9)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 9))
    }

    private func sessionRow(_ session: FocusSession) -> some View {
        HStack(spacing: 8) {
            Image(systemName: session.completed ? "checkmark.circle.fill" : "circle.dashed")
                .foregroundStyle(session.completed ? Color.green : Color.secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text(LocalizedStringKey(session.completed ? "Completed Pomodoro" : "Focus Session"))
                    .font(.subheadline.weight(.medium))
                Text(timeDescription(session))
                    .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
            Spacer()
            Text(compactDuration(sessionDuration(session)))
                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        }
        .padding(.vertical, 7)
    }

    private func timeDescription(_ session: FocusSession) -> String {
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        let start = formatter.string(from: Date(timeIntervalSince1970: session.startedAt))
        let end = session.endedAt.map { formatter.string(from: Date(timeIntervalSince1970: $0)) } ?? ""
        return "\(start)–\(end)"
    }

    private func sessionDuration(_ session: FocusSession) -> TimeInterval {
        max(0, (session.endedAt ?? session.startedAt) - session.startedAt)
    }

    private func compactDuration(_ seconds: TimeInterval) -> String {
        let minutes = Int(seconds) / 60
        return minutes >= 60 ? String(format: "%dh %02dm", minutes / 60, minutes % 60) : "\(minutes)m"
    }

    private func moveDay(_ amount: Int) {
        guard let date = Calendar.current.date(byAdding: .day, value: amount, to: selectedDay) else { return }
        selectedDay = min(date, Date())
    }

    private func exportCSV() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "MultiTimer-Pomodoro-Sessions.csv"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let formatter = ISO8601DateFormatter()
        var rows = ["started_at,ended_at,completed"]
        for session in model.stats.sessions {
            let start = formatter.string(from: Date(timeIntervalSince1970: session.startedAt))
            let end = session.endedAt.map { formatter.string(from: Date(timeIntervalSince1970: $0)) } ?? ""
            rows.append("\(start),\(end),\(session.completed)")
        }
        try? (rows.joined(separator: "\n") + "\n").write(to: url, atomically: true, encoding: .utf8)
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
                        Rectangle().fill(Color(nsColor: .separatorColor).opacity(0.65))
                            .frame(width: 1)
                            .offset(x: proxy.size.width * CGFloat(quarter) / 4)
                    }
                    ForEach(Array(clippedIntervals.enumerated()), id: \.offset) { _, interval in
                        RoundedRectangle(cornerRadius: 4)
                            .fill(Color.accentColor.gradient)
                            .frame(width: max(2, proxy.size.width * interval.duration / 86_400), height: 26)
                            .offset(x: proxy.size.width * interval.offset / 86_400)
                    }
                }
            }
            .frame(height: 32)
        }
    }

    private var clippedIntervals: [(offset: CGFloat, duration: CGFloat)] {
        let calendar = Calendar.current
        let start = calendar.startOfDay(for: day).timeIntervalSince1970
        let end = calendar.date(byAdding: .day, value: 1, to: calendar.startOfDay(for: day))!.timeIntervalSince1970
        let now = Date().timeIntervalSince1970
        return sessions.compactMap { session in
            let clippedStart = max(start, session.startedAt)
            let clippedEnd = min(end, session.endedAt ?? now)
            guard clippedEnd > clippedStart else { return nil }
            return (CGFloat(clippedStart - start), CGFloat(clippedEnd - clippedStart))
        }
    }
}
