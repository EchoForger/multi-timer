import datetime
import json
import tempfile
import threading
import time
import urllib.request
import unittest
from pathlib import Path
from unittest import mock

import multitimer


class _Switch:
    def __init__(self, state):
        self._state = state

    def state(self):
        return self._state


class MultiTimerLogicTests(unittest.TestCase):
    def test_homebrew_updater_uses_generic_tap(self):
        with (
            mock.patch.object(multitimer, "_find_brew", return_value="/opt/homebrew/bin/brew"),
            mock.patch.object(multitimer, "_run_checked") as run_checked,
            mock.patch.object(multitimer, "_best_installed_bundle_path", return_value=None),
        ):
            multitimer._upgrade_via_homebrew("9.0.0")

        run_checked.assert_called_once_with(
            [
                "/opt/homebrew/bin/brew",
                "upgrade",
                "--cask",
                "--no-quit",
                "echoforger/tap/multi-timer",
            ],
            1200,
            "Homebrew 升级 MultiTimer 失败",
        )

    def test_frozen_gui_relaunches_when_it_inherits_a_foreign_xpc_identity(self):
        completed = mock.Mock(returncode=0)
        with (
            mock.patch.object(multitimer.sys, "frozen", True, create=True),
            mock.patch.object(
                multitimer, "_current_app_bundle_path",
                return_value=Path("/Applications/MultiTimer.app"),
            ),
            mock.patch.object(multitimer.subprocess, "run", return_value=completed) as run,
            mock.patch.dict(
                multitimer.os.environ,
                {
                    "XPC_SERVICE_NAME": "application.com.openai.codex.123",
                    "MULTITIMER_STATE_PATH": "/private/tmp/multitimer-test.json",
                },
                clear=True,
            ),
        ):
            self.assertTrue(multitimer._relaunch_via_launchservices_if_needed())
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/open", "-n", "-g"])
        self.assertIn("MULTITIMER_STATE_PATH=/private/tmp/multitimer-test.json", command)
        self.assertEqual(command[-1], "/Applications/MultiTimer.app")

    def test_frozen_gui_keeps_running_with_its_own_launchservices_identity(self):
        with (
            mock.patch.object(multitimer.sys, "frozen", True, create=True),
            mock.patch.dict(
                multitimer.os.environ,
                {"XPC_SERVICE_NAME": f"application.{multitimer.APP_BUNDLE_ID}.123"},
                clear=True,
            ),
            mock.patch.object(multitimer.subprocess, "run") as run,
        ):
            self.assertFalse(multitimer._relaunch_via_launchservices_if_needed())
        run.assert_not_called()

    def test_status_item_cannot_be_removed_from_menu_bar(self):
        status_item = mock.Mock()
        status_item.respondsToSelector_.return_value = True
        status_bar = mock.Mock()
        status_bar.statusItemWithLength_.return_value = status_item
        app = mock.Mock()
        app.settings = {"show_remaining": False, "show_count": False}
        app._retain = []
        app._status_images = {}
        app._refresh_status_item = mock.Mock()

        status_bar_class = mock.Mock()
        status_bar_class.systemStatusBar.return_value = status_bar
        with (
            mock.patch.object(multitimer, "NSStatusBar", status_bar_class),
            mock.patch.object(multitimer, "NSImage") as image,
            mock.patch.object(multitimer, "_Action") as action,
        ):
            image.imageWithSystemSymbolName_accessibilityDescription_.return_value = None
            image.imageNamed_.return_value = None
            action.alloc.return_value.initWithCallback_.return_value = mock.Mock()
            multitimer.MultiTimerApp._build_status_item(app)

        status_item.setAutosaveName_.assert_not_called()
        status_item.setBehavior_.assert_not_called()
        status_item.setVisible_.assert_not_called()

    def test_status_item_check_respects_control_center_visibility(self):
        status_item = mock.Mock()
        status_item.respondsToSelector_.side_effect = lambda selector: selector == "isVisible"
        status_item.isVisible.return_value = False
        app = mock.Mock(status_item=status_item)

        with mock.patch.object(multitimer.AppHelper, "callLater") as call_later:
            multitimer.MultiTimerApp._verify_status_item(app)

        status_item.setVisible_.assert_not_called()
        call_later.assert_called_once_with(0.8, app._status_item_recheck)

    def test_hidden_status_item_opens_menu_bar_settings(self):
        status_item = mock.Mock()
        status_item.respondsToSelector_.side_effect = lambda selector: selector == "isVisible"
        status_item.isVisible.return_value = False
        app = mock.Mock(status_item=status_item)
        app._show_alert.return_value = 1000

        multitimer.MultiTimerApp._status_item_recheck(app)

        app._open_url.assert_called_once_with(
            "x-apple.systempreferences:com.apple.ControlCenter-Settings.extension?MenuBar"
        )

    def test_hidden_status_item_can_be_dismissed_without_changing_visibility(self):
        status_item = mock.Mock()
        status_item.respondsToSelector_.side_effect = lambda selector: selector == "isVisible"
        status_item.isVisible.return_value = False
        app = mock.Mock(status_item=status_item)
        app._show_alert.return_value = 1001

        multitimer.MultiTimerApp._status_item_recheck(app)

        app._open_url.assert_not_called()
        status_item.setVisible_.assert_not_called()

    def test_main_lets_lsui_element_own_normal_activation_policy(self):
        for preview in (False, True):
            with self.subTest(preview=preview):
                app = mock.Mock()
                delegate = mock.Mock()
                application_class = mock.Mock()
                application_class.sharedApplication.return_value = app
                running_application_class = mock.Mock()
                running_application_class.runningApplicationsWithBundleIdentifier_.return_value = []
                app_class = mock.Mock()
                app_class.alloc.return_value.init.return_value = delegate
                environment = {"MULTITIMER_PREVIEW": "1"} if preview else {}
                with (
                    mock.patch.object(
                        multitimer, "_relaunch_via_launchservices_if_needed", return_value=False
                    ),
                    mock.patch.object(multitimer, "NSApplication", application_class),
                    mock.patch.object(
                        multitimer, "NSRunningApplication", running_application_class
                    ),
                    mock.patch.object(multitimer, "MultiTimerApp", app_class),
                    mock.patch.object(multitimer.AppHelper, "runEventLoop"),
                    mock.patch.dict(multitimer.os.environ, environment, clear=True),
                ):
                    multitimer.main()
                if preview:
                    app.setActivationPolicy_.assert_called_once_with(
                        multitimer.NSApplicationActivationPolicyRegular
                    )
                else:
                    app.setActivationPolicy_.assert_not_called()

    def test_status_time_uses_stable_hour_minute_format(self):
        self.assertEqual(multitimer.fmt_status_remaining(0), "00:00")
        self.assertEqual(multitimer.fmt_status_remaining(1), "00:01")
        self.assertEqual(multitimer.fmt_status_remaining(60), "00:01")
        self.assertEqual(multitimer.fmt_status_remaining(61), "00:02")
        self.assertEqual(multitimer.fmt_status_remaining(3_599), "01:00")
        self.assertEqual(multitimer.fmt_status_remaining(127_789), "35:30")

    def test_multitimer_url_countdown(self):
        request = multitimer._parse_multitimer_url(
            "multitimer://start?name=Green%20Tea&minutes=5"
        )
        self.assertEqual(request, {
            "command": "start", "kind": "countdown", "name": "Green Tea", "seconds": 300,
        })

    def test_multitimer_url_pomodoro_actions(self):
        self.assertEqual(
            multitimer._parse_multitimer_url("multitimer://pomodoro/start"),
            {"command": "pomodoro", "action": "start"},
        )
        self.assertEqual(
            multitimer._parse_multitimer_url("multitimer://pomodoro/status"),
            {"command": "pomodoro", "action": "status"},
        )
        with self.assertRaises(ValueError):
            multitimer._parse_multitimer_url("multitimer://pomodoro/invalid")

    def test_multitimer_url_stopwatch(self):
        request = multitimer._parse_multitimer_url(
            "multitimer://start?name=Focus&mode=stopwatch"
        )
        self.assertEqual(request["kind"], "stopwatch")
        self.assertEqual(request["name"], "Focus")

    def test_multitimer_url_rejects_invalid_requests(self):
        for url in ("https://example.com", "multitimer://cancel", "multitimer://start?minutes=0"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                multitimer._parse_multitimer_url(url)

    def test_duration_display_uses_fixed_hour_minute_second_fields(self):
        self.assertEqual(multitimer.fmt_remaining(0), "00:00:00")
        self.assertEqual(multitimer.fmt_remaining(65), "00:01:05")
        self.assertEqual(multitimer.fmt_remaining(40_320), "11:12:00")
        self.assertEqual(multitimer.split_time(40_320), (11, 12, 0))
        self.assertEqual(multitimer.join_time(11, 12, 0), 40_320)
        with self.assertRaises(ValueError):
            multitimer.join_time(1, 60, 0)

    def test_duration_text_treats_a_bare_number_as_minutes(self):
        self.assertEqual(multitimer.parse_duration_text("16"), 960)
        self.assertEqual(multitimer.parse_duration_text("16:30"), 990)
        self.assertEqual(multitimer.parse_duration_text("1:16:30"), 4590)
        self.assertEqual(multitimer.parse_duration_text(" 5 "), 300)
        self.assertEqual(multitimer.parse_duration_text("2000"), multitimer.MAX_DURATION_SECONDS)

    def test_duration_text_rejects_unusable_input(self):
        for text in ("", "abc", "1:2:3:4", "-5", "1::2", "nan", "inf", "-inf"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                multitimer.parse_duration_text(text)

    def test_url_and_cli_reject_non_finite_durations(self):
        for url in (
            "multitimer://start?minutes=nan",
            "multitimer://start?minutes=inf",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                multitimer._parse_multitimer_url(url)
        for value in ("nan", "inf", "-inf", "0"):
            with self.subTest(value=value):
                self.assertEqual(multitimer._run_cli(["start", "Tea", value]), 2)

    def test_clock_text_resolves_the_next_matching_time(self):
        now = time.mktime(time.struct_time((2026, 8, 4, 20, 0, 0, 1, 216, -1)))
        for text in ("21:30", "2130", "21：30：00", "213000"):
            with self.subTest(text=text):
                target = multitimer.parse_clock_text(text, now)
                self.assertEqual(multitimer.fmt_clock_time(target), "21:30:00")
                self.assertEqual(target - now, 90 * 60)
        with_seconds = multitimer.parse_clock_text("21:30:45", now)
        self.assertEqual(multitimer.fmt_clock_time(with_seconds), "21:30:45")
        self.assertEqual(with_seconds - now, 90 * 60 + 45)
        tomorrow = multitimer.parse_clock_text("19:00", now)
        self.assertEqual(multitimer.fmt_clock_time(tomorrow), "19:00:00")
        self.assertEqual(tomorrow - now, 23 * 3600)

    def test_clock_text_rejects_impossible_times(self):
        now = time.time()
        for text in ("", "25:00", "12:75", "12:30:75", "abc", "1234567"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                multitimer.parse_clock_text(text, now)

    def test_source_mode_disables_user_notifications(self):
        with mock.patch.object(multitimer, "_current_app_bundle_path", return_value=None):
            self.assertFalse(multitimer._can_use_user_notifications())

    def test_app_bundle_enables_user_notifications(self):
        with mock.patch.object(
            multitimer, "_current_app_bundle_path",
            return_value=Path("/Applications/MultiTimer.app"),
        ):
            self.assertTrue(multitimer._can_use_user_notifications())
        with (
            mock.patch.object(
                multitimer, "_current_app_bundle_path",
                return_value=Path("/Applications/MultiTimer.app"),
            ),
            mock.patch.dict(
                multitimer.os.environ,
                {"MULTITIMER_DISABLE_NOTIFICATIONS": "1"},
            ),
        ):
            self.assertFalse(multitimer._can_use_user_notifications())

    def test_pomodoro_stats_reject_non_finite_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.json"
            path.write_text(
                json.dumps({"2026-08-04": 2, "nan": float("nan"), "inf": float("inf")}),
                encoding="utf-8",
            )
            self.assertEqual(multitimer.load_pomodoro_stats(path), {"2026-08-04": 2})

    def test_pomodoro_stats_round_trip_series_csv_and_html(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stats.json"
            stats = {"2026-08-04": 2, "2026-08-05": 3}
            multitimer.save_pomodoro_stats(stats, path)
            self.assertEqual(multitimer.load_pomodoro_stats(path), stats)
            series = multitimer.pomodoro_stats_last_days(
                stats, days=3, today=datetime.date(2026, 8, 5)
            )
            self.assertEqual([item["count"] for item in series], [0, 2, 3])
            export = multitimer.pomodoro_stats_csv(
                stats, days=3, today=datetime.date(2026, 8, 5)
            )
            self.assertIn("2026-08-05,3", export)
            page = multitimer.pomodoro_stats_html(series, "secret")
            self.assertIn("最近 30 天专注统计", page)
            self.assertIn("/clear?token=secret", page)

    def test_local_stats_server_serves_html_csv_and_clear(self):
        app = mock.Mock()
        app.pomodoro_stats_snapshot.return_value = {"2026-08-05": 3}
        app.clear_pomodoro_stats_from_server.return_value = True
        server = multitimer.ThreadingHTTPServer(("127.0.0.1", 0), multitimer._StatsHandler)
        server.app = app
        server.token = "secret"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            self.assertIn("专注统计", urllib.request.urlopen(base + "/").read().decode())
            self.assertIn(
                "completed_pomodoros",
                urllib.request.urlopen(base + "/stats.csv").read().decode(),
            )
            request = urllib.request.Request(
                base + "/clear?token=secret", method="POST"
            )
            self.assertEqual(urllib.request.urlopen(request).status, 204)
            app.clear_pomodoro_stats_from_server.assert_called_once_with()
        finally:
            server.shutdown()
            server.server_close()

    def test_pomodoro_control_requests_cover_all_actions(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.settings = dict(multitimer.DEFAULT_SETTINGS)
        app.pomodoro_stats = {}
        app.pomodoro = {
            "phase": "idle", "end_ts": 0.0, "paused_at": 0.0, "session_id": "",
        }
        app._update_pomodoro_view = mock.Mock()
        app._refresh_status_item = mock.Mock()
        app._update_size = mock.Mock()
        started = app._execute_control_request({"command": "pomodoro", "action": "start"})
        self.assertEqual(started["phase"], "work")
        paused = app._execute_control_request({"command": "pomodoro", "action": "pause"})
        self.assertTrue(paused["paused"])
        skipped = app._execute_control_request({"command": "pomodoro", "action": "skip"})
        self.assertEqual(skipped["phase"], "break")
        skipped_break = app._execute_control_request({"command": "pomodoro", "action": "skip"})
        self.assertEqual(skipped_break["phase"], "work")
        stopped = app._execute_control_request({"command": "pomodoro", "action": "stop"})
        self.assertEqual(stopped["phase"], "idle")
        with self.assertRaisesRegex(ValueError, "not active"):
            app._execute_control_request({"command": "pomodoro", "action": "pause"})

    def test_control_request_rejects_excessive_duration(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.settings = dict(multitimer.DEFAULT_SETTINGS)
        app.timers = []
        app._add_timer_row = mock.Mock()
        with self.assertRaisesRegex(ValueError, "24 hours"):
            app._execute_control_request({
                "command": "start",
                "kind": "countdown",
                "seconds": multitimer.MAX_DURATION_SECONDS + 1,
            })

    def test_icloud_payload_rejects_invalid_values(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.settings = dict(multitimer.DEFAULT_SETTINGS)
        app.pomodoro_stats = {"2026-08-05": 3}
        app._settings_revision = 10.0
        self.assertFalse(app._merge_icloud_payload(json.dumps({
            "settings_revision": float("nan"),
            "pomodoro_stats": {"2026-08-05": float("inf")},
        })))
        self.assertEqual(app.pomodoro_stats, {"2026-08-05": 3})

    def test_icloud_payload_merges_settings_and_maximum_counts(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.settings = dict(multitimer.DEFAULT_SETTINGS)
        app.pomodoro_stats = {"2026-08-05": 3}
        app._settings_revision = 10.0
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            multitimer, "POMODORO_STATS_PATH", Path(directory) / "stats.json"
        ):
            app._merge_icloud_payload(json.dumps({
                "settings": {"show_pomodoro": False, "unknown": True},
                "settings_revision": 20.0,
                "pomodoro_stats": {"2026-08-05": 2, "2026-08-04": 4},
            }))
        self.assertFalse(app.settings["show_pomodoro"])
        self.assertNotIn("unknown", app.settings)
        self.assertEqual(app.pomodoro_stats["2026-08-05"], 3)
        self.assertEqual(app.pomodoro_stats["2026-08-04"], 4)

    def test_completed_work_is_consumed_once_and_uses_deadline_date(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.settings = dict(multitimer.DEFAULT_SETTINGS)
        deadline = datetime.datetime(2026, 8, 4, 23, 59).timestamp()
        app.pomodoro = {
            "phase": "work", "end_ts": deadline, "paused_at": 0.0,
            "session_id": "work-session",
        }
        app.pomodoro_stats = {}
        app._update_pomodoro_view = mock.Mock()
        app._refresh_status_item = mock.Mock()
        app._update_size = mock.Mock()
        app._sync_to_icloud = mock.Mock()
        app._send_pomodoro_notification = mock.Mock()
        original_record = app._record_completed_pomodoro

        def record_with_reentry(completed_at):
            app._complete_pomodoro_phase()
            original_record(completed_at)

        app._record_completed_pomodoro = record_with_reentry
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            multitimer, "POMODORO_STATS_PATH", Path(directory) / "stats.json"
        ):
            app._complete_pomodoro_phase()
        self.assertEqual(app.pomodoro_stats, {"2026-08-04": 1})
        self.assertEqual(app.pomodoro["phase"], "break")

    def test_old_notification_cannot_extend_a_new_session(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.pomodoro = {
            "phase": "break", "end_ts": 1_000.0, "paused_at": 0.0,
            "session_id": "current",
        }
        app._update_pomodoro_view = mock.Mock()
        app._refresh_status_item = mock.Mock()
        app._extend_pomodoro_by_five_minutes("old")
        self.assertEqual(app.pomodoro["end_ts"], 1_000.0)
        with mock.patch.object(multitimer.time, "time", return_value=900.0):
            app._extend_pomodoro_by_five_minutes("current")
        self.assertEqual(app.pomodoro["end_ts"], 1_300.0)

    def test_pomodoro_display_uses_minute_second_format(self):
        self.assertEqual(multitimer.fmt_pomodoro_remaining(0), "00:00")
        self.assertEqual(multitimer.fmt_pomodoro_remaining(1), "00:01")
        self.assertEqual(multitimer.fmt_pomodoro_remaining(61), "01:01")
        self.assertEqual(multitimer.fmt_pomodoro_remaining(25 * 60), "25:00")
        self.assertEqual(multitimer.fmt_pomodoro_remaining(59 * 60 + 59), "59:59")
        self.assertEqual(multitimer.fmt_pomodoro_remaining(3600), "59:59")

    def test_pomodoro_phase_transitions_follow_auto_cycle_setting(self):
        self.assertEqual(multitimer.next_pomodoro_phase("work", False), "break")
        self.assertEqual(multitimer.next_pomodoro_phase("work", True), "break")
        self.assertEqual(multitimer.next_pomodoro_phase("break", False), "ready")
        self.assertEqual(multitimer.next_pomodoro_phase("break", True), "work")

    def test_preview_window_counts_as_visible_main_view(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.popover = mock.Mock()
        app.popover.isShown.return_value = False
        app._preview_window = mock.Mock()
        app._preview_window.isVisible.return_value = True
        self.assertTrue(app._main_view_is_visible())
        app._preview_window.isVisible.return_value = False
        self.assertFalse(app._main_view_is_visible())

    def test_pomodoro_remaining_freezes_while_paused(self):
        pomodoro = {"phase": "work", "end_ts": 1_300.0, "paused_at": 1_100.0}
        self.assertEqual(multitimer.pomodoro_remaining(pomodoro, now=1_250), 200)
        pomodoro["paused_at"] = 0.0
        self.assertEqual(multitimer.pomodoro_remaining(pomodoro, now=1_250), 50)
        pomodoro["phase"] = "ready"
        self.assertEqual(multitimer.pomodoro_remaining(pomodoro, now=1_250), 0)

    def test_pomodoro_settings_have_backward_compatible_defaults(self):
        self.assertEqual(multitimer.DEFAULT_SETTINGS["pomodoro_work_seconds"], 25 * 60)
        self.assertEqual(multitimer.DEFAULT_SETTINGS["pomodoro_break_seconds"], 5 * 60)
        self.assertFalse(multitimer.DEFAULT_SETTINGS["pomodoro_auto_cycle"])

    def test_paused_timer_keeps_its_remaining_time_and_duration(self):
        now = time.time()
        timer = {
            "kind": "countdown", "start_ts": now - 100, "end_ts": now + 200,
            "paused_at": now,
        }
        self.assertTrue(multitimer.timer_is_paused(timer))
        self.assertAlmostEqual(multitimer.timer_remaining(timer), 200, places=3)
        self.assertAlmostEqual(multitimer.timer_duration(timer), 300, places=3)
        self.assertAlmostEqual(multitimer.timer_elapsed(timer), 100, places=3)

    def test_state_round_trip_keeps_only_start_and_end_times(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            now = time.time()
            timers = [
                {
                    "id": "tea", "label": "Tea", "kind": "countdown",
                    "start_ts": now - 180, "end_ts": now + 120, "paused_at": now,
                    "pinned": True, "finished": False, "laps": [],
                },
                {
                    "id": "focus", "label": "Focus", "kind": "stopwatch",
                    "start_ts": now - 42, "end_ts": 0.0, "paused_at": 0.0,
                    "pinned": False, "finished": False, "laps": [20, 42],
                },
            ]
            settings = dict(multitimer.DEFAULT_SETTINGS)
            settings.update({"show_remaining": True, "show_count": True, "language": "en"})
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                multitimer.save_state(timers, "0.6.0", settings)
                restored = multitimer.load_state()
            payload = json.loads(state_path.read_text())
            self.assertEqual(payload["schema_version"], 3)
            self.assertNotIn("presets", payload)
            self.assertNotIn("pomodoro", payload)
            self.assertEqual(
                set(payload["timers"][0]),
                {"id", "label", "kind", "start_ts", "end_ts", "paused_at", "pinned", "finished", "laps"},
            )
            self.assertEqual(restored["skipped_update"], "0.6.0")
            self.assertTrue(restored["settings"]["show_count"])
            self.assertNotIn("language", restored["settings"])
            self.assertTrue(restored["timers"][0]["pinned"])
            self.assertAlmostEqual(multitimer.timer_remaining(restored["timers"][0]), 120, places=3)
            self.assertEqual(restored["timers"][1]["laps"], [20, 42])

    def test_state_loader_skips_damaged_records(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            now = time.time()
            state_path.write_text(json.dumps({
                "timers": [
                    None,
                    "invalid",
                    {"id": "broken", "start_ts": "bad", "end_ts": now + 60},
                    {"id": "tea", "label": "Tea", "start_ts": now, "end_ts": now + 60},
                ],
                "settings": [],
            }))
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                restored = multitimer.load_state()
            self.assertEqual([timer["id"] for timer in restored["timers"]], ["tea"])
            self.assertEqual(restored["settings"], multitimer.DEFAULT_SETTINGS)

    def test_state_loader_accepts_null_or_non_list_timers(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                for timers in (None, {}, "invalid"):
                    with self.subTest(timers=timers):
                        state_path.write_text(json.dumps({"timers": timers}))
                        self.assertEqual(multitimer.load_state()["timers"], [])

    def test_atomic_save_preserves_existing_state_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text('{"original": true}')
            with (
                mock.patch.object(multitimer, "STATE_PATH", state_path),
                mock.patch.object(multitimer.os, "replace", side_effect=OSError("disk error")),
                self.assertRaises(OSError),
            ):
                multitimer.save_state([])
            self.assertEqual(state_path.read_text(), '{"original": true}')
            self.assertEqual(list(state_path.parent.glob(".state.json.*.tmp")), [])

    def test_old_state_is_migrated_to_start_and_end_times(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            now = time.time()
            state_path.write_text(json.dumps({
                "presets": [{"name": "5min", "seconds": 300}],
                "timers": [
                    {
                        "id": "old", "label": "Old", "duration": 300,
                        "created_ts": now - 60, "end_ts": now + 240,
                    },
                    {
                        "id": "held", "label": "Held", "duration": 600, "paused": True,
                        "paused_remaining": 300, "created_ts": now - 900, "end_ts": now - 300,
                    },
                    {
                        "id": "watch", "label": "Watch", "kind": "stopwatch",
                        "start_ts": now - 30, "elapsed_before": 12, "paused": True,
                    },
                ],
            }))
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                restored = multitimer.load_state()
            countdown, held, watch = restored["timers"]
            self.assertEqual(countdown["kind"], "countdown")
            self.assertFalse(countdown["pinned"])
            self.assertNotIn("duration", countdown)
            self.assertAlmostEqual(multitimer.timer_duration(countdown), 300, places=0)
            self.assertTrue(multitimer.timer_is_paused(held))
            self.assertAlmostEqual(multitimer.timer_remaining(held), 300, places=0)
            self.assertAlmostEqual(multitimer.timer_duration(held), 600, places=0)
            self.assertAlmostEqual(multitimer.timer_elapsed(watch), 12, places=0)
            self.assertEqual(restored["settings"], multitimer.DEFAULT_SETTINGS)

    def test_launch_waits_for_notification_permission(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app._finish_launch = mock.Mock()
        app._show_alert = mock.Mock(return_value=1000)
        app._open_notification_settings = mock.Mock()
        with mock.patch.object(multitimer.AppHelper, "callLater") as call_later:
            app._handle_launch_permission(multitimer.UNAuthorizationStatusDenied)
        app._finish_launch.assert_not_called()
        app._show_alert.assert_called_once()
        app._open_notification_settings.assert_called_once_with()
        call_later.assert_called_once_with(1.5, app._prepare_launch_permissions)

    def test_authorized_notification_permission_finishes_launch(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app._finish_launch = mock.Mock()
        app._handle_launch_permission(2)
        app._finish_launch.assert_called_once_with()

    def test_update_dialog_choices_and_future_auto_update(self):
        app = multitimer.MultiTimerApp.alloc().init()
        app.settings = dict(multitimer.DEFAULT_SETTINGS)
        app.settings["update_preference_set"] = False
        app._skipped_update = ""
        app._persist = mock.Mock()
        app._show_update_alert = mock.Mock(return_value=(1001, True))
        app._start_update_install = mock.Mock()
        app.status_item = mock.Mock()
        release = {"tag_name": "v9.0.0", "body": "New features"}
        app._present_update(release, "dmg", automatic=True)
        app._show_update_alert.assert_called_once()
        app._start_update_install.assert_called_once_with(
            release, "9.0.0", "dmg", relaunch=False
        )
        self.assertTrue(app.settings["update_preference_set"])
        self.assertTrue(app.settings["update_automatically"])

        app._show_update_alert.reset_mock()
        app._start_update_install.reset_mock()
        app._present_update(release, "dmg", automatic=True)
        app._show_update_alert.assert_not_called()
        app._start_update_install.assert_called_once_with(
            release, "9.0.0", "dmg", relaunch=True
        )

    def test_setting_switch_persists_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                app = multitimer.MultiTimerApp.alloc().init()
                app._boolean_setting_changed("show_count", _Switch(1))
                restored = multitimer.load_state()
            self.assertTrue(restored["settings"]["show_count"])

    def test_slider_uses_slow_then_fast_exponential_curve(self):
        seconds = multitimer.seconds_for_slider_position
        self.assertEqual(seconds(0), 0)
        self.assertEqual(seconds(1), multitimer.MAX_DURATION_SECONDS)
        self.assertEqual(seconds(0.5), 3 * 3600)
        self.assertLess(seconds(0.25) - seconds(0), seconds(1) - seconds(0.75))
        for duration in (0, 300, 3600, 3 * 3600, 12 * 3600, 24 * 3600):
            with self.subTest(duration=duration):
                position = multitimer.slider_position_for_seconds(duration)
                self.assertAlmostEqual(seconds(position), duration, delta=1)

    def test_time_segment_digit_input_replaces_selected_pair(self):
        replace = multitimer.replace_time_segment_digit
        self.assertEqual(replace("00:25:00", 0, "1", 0), "01:25:00")
        self.assertEqual(replace("01:25:00", 0, "2", 1), "12:25:00")
        self.assertEqual(replace("00:25:00", 1, "1", 0), "00:01:00")
        self.assertEqual(replace("00:01:00", 1, "0", 1), "00:10:00")
        self.assertEqual(replace("00:25:00", 2, "4", 0), "00:25:04")
        self.assertEqual(replace("00:25:04", 2, "5", 1), "00:25:45")

    def test_time_segment_hit_testing_selects_each_pair(self):
        segment = multitimer.time_segment_for_position
        self.assertEqual(segment(0, 90), 0)
        self.assertEqual(segment(29, 90), 0)
        self.assertEqual(segment(30, 90), 1)
        self.assertEqual(segment(59, 90), 1)
        self.assertEqual(segment(60, 90), 2)
        self.assertEqual(segment(100, 90), 2)
        self.assertEqual(multitimer.time_segment_range(0), (0, 2))
        self.assertEqual(multitimer.time_segment_range(1), (3, 2))
        self.assertEqual(multitimer.time_segment_range(2), (6, 2))

    def test_slider_snapping_keeps_short_timers_precise(self):
        snap = multitimer.MultiTimerApp._snap_minutes
        self.assertEqual(snap(0.4), 0)
        self.assertEqual(snap(17.2), 17)
        self.assertEqual(snap(133.0), 135)
        self.assertEqual(snap(1000.0), 1005)


if __name__ == "__main__":
    unittest.main()
