import json
import tempfile
import time
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

    def test_status_item_uses_separate_stable_names_for_release_and_development(self):
        with mock.patch.object(multitimer.sys, "frozen", True, create=True):
            release_name = multitimer._status_item_autosave_name()
        with mock.patch.object(multitimer.sys, "frozen", False, create=True):
            development_name = multitimer._status_item_autosave_name()
        self.assertEqual(release_name, multitimer.STATUS_ITEM_AUTOSAVE_NAME)
        self.assertEqual(development_name, f"{release_name}.development")

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
