import Foundation
import XCTest
@testable import MultiTimerCore

final class MultiTimerCoreTests: XCTestCase {
    func testDurationParsing() {
        XCTAssertEqual(DurationParser.parse("5"), 300)
        XCTAssertEqual(DurationParser.parse("01:30"), 90)
        XCTAssertEqual(DurationParser.parse("01:02:03"), 3_723)
        XCTAssertNil(DurationParser.parse("1:70"))
        XCTAssertNil(DurationParser.parse("0"))
    }

    func testTargetTimeRollsToTomorrow() {
        let calendar = Calendar(identifier: .gregorian)
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let earlier = calendar.dateComponents([.hour, .minute], from: now)
        let text = String(format: "%02d:%02d", earlier.hour ?? 0, earlier.minute ?? 0)
        let target = DurationParser.targetDate(text, now: now, calendar: calendar)
        XCTAssertNotNil(target)
        XCTAssertGreaterThan(target!, now)
    }

    func testCompactTargetTime() {
        let calendar = Calendar(identifier: .gregorian)
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let short = DurationParser.targetDate("930", now: now, calendar: calendar)
        let precise = DurationParser.targetDate("12345", now: now, calendar: calendar)
        XCTAssertEqual(calendar.component(.hour, from: short!), 9)
        XCTAssertEqual(calendar.component(.minute, from: short!), 30)
        XCTAssertEqual(calendar.component(.second, from: short!), 0)
        XCTAssertEqual(calendar.component(.hour, from: precise!), 1)
        XCTAssertEqual(calendar.component(.minute, from: precise!), 23)
        XCTAssertEqual(calendar.component(.second, from: precise!), 45)
    }

    func testLegacyStateMigration() throws {
        let data = Data(#"{"timers":[{"id":"old","label":"Tea","duration":300,"created_ts":1000,"paused":true,"paused_remaining":120}],"settings":{"show_remaining":true}}"#.utf8)
        let state = try JSONDecoder().decode(StateDocument.self, from: data)
        XCTAssertEqual(state.schemaVersion, 3)
        XCTAssertEqual(state.timers.first?.label, "Tea")
        XCTAssertTrue(state.timers.first?.isPaused == true)
        XCTAssertTrue(state.settings.showRemaining)
    }

    func testTimerPauseMath() {
        let timer = TimerRecord(label: "Tea", kind: .countdown, startTS: 100, endTS: 400, pausedAt: 250, originalDuration: 300)
        XCTAssertEqual(timer.remaining(at: 999), 150)
    }

    func testFormatting() {
        XCTAssertEqual(TimeFormat.clock(3_661), "01:01:01")
        XCTAssertEqual(TimeFormat.menuBar(61), "00:02")
        XCTAssertEqual(TimeFormat.menuBar(3_600), "01:00")
    }

    func testVersions() {
        XCTAssertEqual(VersionNumber.compare("0.6.2", "0.7.0"), .orderedAscending)
        XCTAssertEqual(VersionNumber.compare("0.7", "0.7.0"), .orderedSame)
        XCTAssertEqual(VersionNumber.compare("1.0.0", "0.9.9"), .orderedDescending)
    }

    func testAtomicStateRoundTrip() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = StateStore(url: root.appendingPathComponent("state.json"))
        let document = StateDocument(timers: [TimerRecord(label: "Work", kind: .stopwatch)])
        try store.save(document)
        XCTAssertEqual(store.load(), document)
    }
}
