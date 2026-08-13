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
        XCTAssertEqual(state.schemaVersion, 6)
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

    func testActivePomodoroRoundTrip() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = StateStore(url: root.appendingPathComponent("state.json"))
        var pomodoro = PomodoroSnapshot()
        pomodoro.phase = .work
        pomodoro.finishAt = 12_345
        pomodoro.beginFocus(at: 10_845)
        let document = StateDocument(pomodoro: pomodoro)
        try store.save(document)
        XCTAssertEqual(store.load().pomodoro, pomodoro)
    }

    func testLegacyPomodoroStatsMigration() throws {
        let data = Data(#"{"days":{"2026-08-12":3},"sync_revision":10}"#.utf8)
        let stats = try JSONDecoder().decode(PomodoroStats.self, from: data)
        XCTAssertTrue(stats.sessions.isEmpty)
    }

    func testFocusTimelineClipsIntervalsToDay() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let day = Date(timeIntervalSince1970: 86_400)
        let session = FocusSession(
            startedAt: 86_300,
            endedAt: 90_000,
            completed: true,
            timeZoneIdentifier: "GMT"
        )
        let stats = PomodoroStats(sessions: [session])
        let store = StatsStore()
        XCTAssertEqual(store.sessions(in: day, from: stats, calendar: calendar).count, 1)
        XCTAssertEqual(store.focusedSeconds(in: day, from: stats, calendar: calendar), 3_600)
    }

    func testRecordedTimeZoneKeepsSessionOnOriginalLocalDay() {
        var viewingCalendar = Calendar(identifier: .gregorian)
        viewingCalendar.timeZone = TimeZone(identifier: "Asia/Tokyo")!
        let selectedJanuaryFirst = viewingCalendar.date(from: DateComponents(year: 1970, month: 1, day: 1, hour: 12))!
        let session = FocusSession(
            startedAt: 84_600,
            endedAt: 85_200,
            focusedSeconds: 600,
            timeZoneIdentifier: "America/Los_Angeles"
        )
        let store = StatsStore()
        XCTAssertEqual(
            store.sessions(in: selectedJanuaryFirst, from: PomodoroStats(sessions: [session]), calendar: viewingCalendar).count,
            1
        )
    }

    func testLegacyIntervalSessionMigration() throws {
        let data = Data(#"{"sessions":[{"id":"old","started_at":100,"completed":true,"intervals":[{"start":100,"end":200},{"start":250,"end":400}]}]}"#.utf8)
        let stats = try JSONDecoder().decode(PomodoroStats.self, from: data)
        XCTAssertEqual(stats.sessions.first?.startedAt, 100)
        XCTAssertEqual(stats.sessions.first?.endedAt, 400)
        XCTAssertEqual(stats.sessions.first?.focusedSeconds, 300)
        XCTAssertTrue(stats.sessions.first?.legacyEstimated == true)
        XCTAssertTrue(stats.sessions.first?.completed == true)
    }

    func testStatsJSONStoresOnlySessionsAndDerivedFields() throws {
        let stats = PomodoroStats(
            sessions: [FocusSession(startedAt: 100, endedAt: 200, completed: true)],
            syncRevision: 300
        )
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(stats)) as? [String: Any])
        XCTAssertNil(object["days"])
        XCTAssertEqual(object["schema_version"] as? Int, 2)
        let sessions = try XCTUnwrap(object["sessions"] as? [[String: Any]])
        XCTAssertEqual(
            Set(sessions[0].keys),
            ["id", "started_at", "ended_at", "completed", "focused_seconds", "time_zone", "legacy_estimated", "focus_intervals"]
        )
    }

    func testPomodoroPauseResumeTracksOnlyFocusedSeconds() throws {
        var snapshot = PomodoroSnapshot()
        snapshot.beginFocus(at: 100)
        snapshot.pauseFocus(at: 220)
        snapshot.resumeFocus(at: 500)
        let session = try XCTUnwrap(snapshot.finishFocus(at: 680, completed: true, timeZone: TimeZone(identifier: "GMT")!))
        XCTAssertEqual(session.startedAt, 100)
        XCTAssertEqual(session.endedAt, 680)
        XCTAssertEqual(session.focusedSeconds, 300)
        XCTAssertEqual(session.focusIntervals, [
            FocusInterval(startedAt: 100, endedAt: 220),
            FocusInterval(startedAt: 500, endedAt: 680),
        ])
        XCTAssertTrue(session.completed)
        XCTAssertFalse(session.legacyEstimated)
    }

    func testPomodoroPauseStateSurvivesRestart() throws {
        var snapshot = PomodoroSnapshot()
        snapshot.beginFocus(at: 1_000)
        snapshot.pauseFocus(at: 1_600)
        snapshot.pausedRemaining = 900
        let restored = try JSONDecoder().decode(PomodoroSnapshot.self, from: JSONEncoder().encode(snapshot))
        XCTAssertNil(restored.focusSegmentStartedAt)
        XCTAssertEqual(restored.focusIntervals.reduce(0) { $0 + $1.duration }, 600)
    }

    func testCrossMidnightFocusIsSplitByRecordedTimeZone() {
        let session = FocusSession(
            startedAt: 86_100,
            endedAt: 87_000,
            completed: true,
            focusedSeconds: 600,
            timeZoneIdentifier: "GMT",
            focusIntervals: [
                FocusInterval(startedAt: 86_100, endedAt: 86_400),
                FocusInterval(startedAt: 86_700, endedAt: 87_000),
            ]
        )
        let summaries = FocusAnalytics.dailySummaries(from: PomodoroStats(sessions: [session]))
        XCTAssertEqual(summaries["1970-01-01"]?.focusedSeconds, 300)
        XCTAssertEqual(summaries["1970-01-02"]?.focusedSeconds, 300)
        XCTAssertEqual(summaries["1970-01-02"]?.completedPomodoros, 1)
    }

    func testGoalHistoryAppliesFromEffectiveDay() {
        let goals = [
            DailyFocusGoal(effectiveDay: "2026-08-01", targetMinutes: 60),
            DailyFocusGoal(effectiveDay: "2026-08-10", targetMinutes: 90),
        ]
        XCTAssertNil(FocusAnalytics.targetMinutes(on: "2026-07-31", goals: goals))
        XCTAssertEqual(FocusAnalytics.targetMinutes(on: "2026-08-09", goals: goals), 60)
        XCTAssertEqual(FocusAnalytics.targetMinutes(on: "2026-08-10", goals: goals), 90)
    }

    func testCurrentStreakUsesActualFocusedMinutes() {
        let timeZone = TimeZone(identifier: "GMT")!
        let now = Date(timeIntervalSince1970: 172_800 + 3_600)
        let stats = PomodoroStats(sessions: [
            FocusSession(startedAt: 3_600, endedAt: 7_200, focusedSeconds: 3_600, timeZoneIdentifier: "GMT"),
            FocusSession(startedAt: 90_000, endedAt: 93_600, focusedSeconds: 3_600, timeZoneIdentifier: "GMT"),
            FocusSession(startedAt: 176_400, endedAt: 180_000, focusedSeconds: 3_600, timeZoneIdentifier: "GMT"),
        ])
        let goals = [DailyFocusGoal(effectiveDay: "1970-01-01", targetMinutes: 60)]
        XCTAssertEqual(FocusAnalytics.currentStreak(stats: stats, goals: goals, now: now, timeZone: timeZone), 3)
    }

    func testLegacyRecordIsEstimatedFromStartAndEnd() throws {
        let data = Data(#"{"sessions":[{"started_at":100,"ended_at":400,"completed":false}]}"#.utf8)
        let stats = try JSONDecoder().decode(PomodoroStats.self, from: data)
        let session = try XCTUnwrap(stats.sessions.first)
        XCTAssertEqual(session.focusedSeconds, 300)
        XCTAssertTrue(session.legacyEstimated)
    }

    func testPeriodSummaryComparesEquivalentElapsedRange() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "GMT")!
        calendar.firstWeekday = 2
        let currentWednesday = calendar.date(from: DateComponents(year: 2026, month: 8, day: 12, hour: 12))!
        let previousMonday = calendar.date(from: DateComponents(year: 2026, month: 8, day: 3, hour: 9))!.timeIntervalSince1970
        let previousThursday = calendar.date(from: DateComponents(year: 2026, month: 8, day: 6, hour: 9))!.timeIntervalSince1970
        let currentMonday = calendar.date(from: DateComponents(year: 2026, month: 8, day: 10, hour: 9))!.timeIntervalSince1970
        let stats = PomodoroStats(sessions: [
            FocusSession(startedAt: previousMonday, endedAt: previousMonday + 1_800, focusedSeconds: 1_800, timeZoneIdentifier: "GMT"),
            FocusSession(startedAt: previousThursday, endedAt: previousThursday + 7_200, focusedSeconds: 7_200, timeZoneIdentifier: "GMT"),
            FocusSession(startedAt: currentMonday, endedAt: currentMonday + 3_600, focusedSeconds: 3_600, timeZoneIdentifier: "GMT"),
        ])
        let summary = FocusAnalytics.periodSummary(
            stats: stats,
            period: .week,
            containing: currentWednesday,
            now: currentWednesday,
            timeZone: TimeZone(identifier: "GMT")!
        )
        XCTAssertEqual(summary.focusedSeconds, 3_600)
        XCTAssertEqual(summary.previousFocusedSeconds, 1_800)
    }
}
