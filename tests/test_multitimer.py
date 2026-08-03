import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import multitimer


class MultiTimerLogicTests(unittest.TestCase):
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

    def test_state_round_trip_preserves_new_timer_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            now = time.time()
            timers = [
                {
                    "id": "tea", "label": "Tea", "kind": "countdown", "duration": 300,
                    "end_ts": now + 120, "created_ts": now, "pinned": True,
                    "paused": True, "paused_remaining": 120, "finished": False,
                },
                {
                    "id": "focus", "label": "Focus", "kind": "stopwatch", "duration": 0,
                    "start_ts": now, "elapsed_before": 42, "created_ts": now,
                    "pinned": False, "paused": True, "finished": False, "laps": [20, 42],
                },
            ]
            settings = dict(multitimer.DEFAULT_SETTINGS)
            settings.update({"show_remaining": True, "show_count": True, "language": "en"})
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                multitimer.save_state([], timers, "0.5.0", settings)
                restored = multitimer.load_state()
            self.assertEqual(restored["skipped_update"], "0.5.0")
            self.assertTrue(restored["settings"]["show_count"])
            self.assertTrue(restored["timers"][0]["pinned"])
            self.assertEqual(restored["timers"][1]["laps"], [20, 42])
            self.assertEqual(json.loads(state_path.read_text())["schema_version"], 2)

    def test_old_state_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "state.json"
            state_path.write_text(json.dumps({
                "presets": [{"name": "5min", "seconds": 300}],
                "timers": [{
                    "id": "old", "label": "Old", "duration": 300,
                    "end_ts": time.time() + 300,
                }],
            }))
            with mock.patch.object(multitimer, "STATE_PATH", state_path):
                restored = multitimer.load_state()
            self.assertEqual(restored["timers"][0]["kind"], "countdown")
            self.assertFalse(restored["timers"][0]["pinned"])
            self.assertEqual(restored["settings"], multitimer.DEFAULT_SETTINGS)


if __name__ == "__main__":
    unittest.main()
