import Foundation

public enum DurationParser {
    public static let maximumSeconds = 24 * 60 * 60

    public static func parse(_ text: String) -> Int? {
        let value = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !value.isEmpty else { return nil }
        if value.contains(":") {
            let pieces = value.split(separator: ":", omittingEmptySubsequences: false)
            guard (2...3).contains(pieces.count), pieces.allSatisfy({ Int($0) != nil }) else { return nil }
            let numbers = pieces.compactMap { Int($0) }
            guard numbers.dropFirst().allSatisfy({ (0..<60).contains($0) }) else { return nil }
            let seconds = pieces.count == 2
                ? numbers[0] * 60 + numbers[1]
                : numbers[0] * 3600 + numbers[1] * 60 + numbers[2]
            return seconds > 0 && seconds <= maximumSeconds ? seconds : nil
        }
        guard let minutes = Double(value), minutes > 0 else { return nil }
        let seconds = Int((minutes * 60).rounded())
        return min(maximumSeconds, max(1, seconds))
    }

    public static func targetDate(_ text: String, now: Date = Date(), calendar: Calendar = .current) -> Date? {
        let raw = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let pieces: [Int]
        if raw.contains(":") {
            let split = raw.split(separator: ":", omittingEmptySubsequences: false)
            guard (2...3).contains(split.count), split.allSatisfy({ Int($0) != nil }) else { return nil }
            pieces = split.compactMap { Int($0) }
        } else {
            guard raw.allSatisfy(\.isNumber), (3...6).contains(raw.count) else { return nil }
            let width = raw.count <= 4 ? 4 : 6
            let padded = String(repeating: "0", count: width - raw.count) + raw
            pieces = stride(from: 0, to: width, by: 2).compactMap { index in
                let start = padded.index(padded.startIndex, offsetBy: index)
                let end = padded.index(start, offsetBy: 2)
                return Int(padded[start..<end])
            }
        }
        let hour = pieces[0], minute = pieces[1], second = pieces.count > 2 ? pieces[2] : 0
        guard (0..<24).contains(hour), (0..<60).contains(minute), (0..<60).contains(second) else { return nil }
        var components = calendar.dateComponents([.year, .month, .day], from: now)
        components.hour = hour
        components.minute = minute
        components.second = second
        guard var result = calendar.date(from: components) else { return nil }
        if result <= now { result = calendar.date(byAdding: .day, value: 1, to: result) ?? result }
        return result
    }
}

public enum TimeFormat {
    public static func clock(_ seconds: TimeInterval) -> String {
        let total = max(0, Int(seconds.rounded(.down)))
        return String(format: "%02d:%02d:%02d", total / 3600, (total % 3600) / 60, total % 60)
    }

    public static func menuBar(_ seconds: TimeInterval) -> String {
        let minutes = max(0, Int(ceil(seconds / 60)))
        return String(format: "%02d:%02d", minutes / 60, minutes % 60)
    }

    public static func short(_ seconds: Int) -> String {
        if seconds % 3600 == 0 { return "\(seconds / 3600)h" }
        if seconds % 60 == 0 { return "\(seconds / 60)min" }
        return clock(TimeInterval(seconds))
    }
}

public enum VersionNumber {
    public static func compare(_ lhs: String, _ rhs: String) -> ComparisonResult {
        let left = lhs.split(separator: ".").map { Int($0.prefix { $0.isNumber }) ?? 0 }
        let right = rhs.split(separator: ".").map { Int($0.prefix { $0.isNumber }) ?? 0 }
        for index in 0..<max(left.count, right.count) {
            let a = index < left.count ? left[index] : 0
            let b = index < right.count ? right[index] : 0
            if a < b { return .orderedAscending }
            if a > b { return .orderedDescending }
        }
        return .orderedSame
    }
}
