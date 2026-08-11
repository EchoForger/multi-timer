import AppKit
import MultiTimerCore
import SwiftUI

struct StatisticsView: View {
    @ObservedObject var model: AppModel
    @State private var confirmClear = false

    private var series: [(String, Int)] { StatsStore().denseSeries(days: 30) }
    private var maximum: Int { max(1, series.map(\.1).max() ?? 1) }
    private var total: Int { series.reduce(0) { $0 + $1.1 } }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                summaryCard(title: "Today", value: "\(model.todayCount)", icon: "sun.max")
                summaryCard(title: "Last 30 Days", value: "\(total)", icon: "calendar")
                summaryCard(title: "Daily Average", value: String(format: "%.1f", Double(total) / 30), icon: "chart.line.uptrend.xyaxis")
            }

            GroupBox("Completed Focus Sessions") {
                HStack(alignment: .bottom, spacing: 5) {
                    ForEach(Array(series.enumerated()), id: \.offset) { index, item in
                        VStack(spacing: 4) {
                            Spacer(minLength: 0)
                            RoundedRectangle(cornerRadius: 3)
                                .fill(Color.accentColor.gradient)
                                .frame(height: max(2, 180 * CGFloat(item.1) / CGFloat(maximum)))
                                .help("\(item.0): \(item.1)")
                            if index % 7 == 1 {
                                Text(String(item.0.suffix(5))).font(.system(size: 9)).foregroundStyle(.secondary)
                            } else {
                                Text(" ").font(.system(size: 9))
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                }
                .frame(height: 215)
                .padding(8)
            }

            HStack {
                Text("Statistics stay on this Mac and contain only daily totals.")
                    .font(.caption).foregroundStyle(.secondary)
                Spacer()
                Button("Export CSV…", action: exportCSV)
                Button("Clear All…") { confirmClear = true }
            }
        }
        .padding(22)
        .alert("Clear all statistics?", isPresented: $confirmClear) {
            Button("Cancel", role: .cancel) {}
            Button("Clear", role: .destructive) { model.clearStats() }
        } message: {
            Text("This removes all recorded Pomodoro completion counts. This cannot be undone.")
        }
    }

    private func summaryCard(title: String, value: String, icon: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon).font(.title2).foregroundStyle(.tint)
            VStack(alignment: .leading, spacing: 2) {
                Text(value).font(.title2.monospacedDigit().bold())
                Text(title).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(13)
        .frame(maxWidth: .infinity)
        .background(.quaternary.opacity(0.5), in: RoundedRectangle(cornerRadius: 10))
    }

    private func exportCSV() {
        let panel = NSSavePanel()
        panel.allowedContentTypes = [.commaSeparatedText]
        panel.nameFieldStringValue = "MultiTimer-Pomodoro-30-days.csv"
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let content = (["date,completed"] + series.map { "\($0.0),\($0.1)" }).joined(separator: "\n") + "\n"
        try? content.write(to: url, atomically: true, encoding: .utf8)
    }
}
