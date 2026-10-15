import json
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from homes.management.commands.watch_operations import safe_snapshot


class WatchOperationsTests(SimpleTestCase):
    def test_snapshot_keeps_only_aggregate_counts(self):
        from django.utils import timezone

        result = safe_snapshot({"status": "ok", "checks": {
            "analysis": {"status": "ok", "running": 1, "camera_name": "secret", "message": "secret"}
        }}, timezone.now())
        text = json.dumps(result)
        self.assertIn('"running": 1', text)
        self.assertNotIn("secret", text)

    @patch("homes.management.commands.watch_operations.close_old_connections")
    @patch("homes.management.commands.watch_operations.time.sleep")
    @patch("homes.management.commands.watch_operations.time.monotonic", side_effect=[0, 1, 2])
    @patch("homes.management.commands.watch_operations.collect_operations")
    def test_writes_samples_and_summary(self, collect, _clock, _sleep, _close):
        collect.return_value = {"status": "ok", "checks": {"database": {"status": "ok"}}}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.jsonl"
            call_command("watch_operations", output=str(path), interval=1,
                         duration_seconds=2, stdout=StringIO())
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([item["type"] for item in records], ["sample", "sample", "summary"])
            self.assertEqual(records[-1]["degraded"], 0)
            with self.assertRaises(CommandError):
                call_command("watch_operations", output=str(path), interval=1,
                             duration_seconds=2, stdout=StringIO())
