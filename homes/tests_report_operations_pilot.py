import json
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from homes.management.commands.report_operations_pilot import summarize_pilot


class ReportOperationsPilotTests(SimpleTestCase):
    def test_separates_infrastructure_from_analysis(self):
        lines = [
            json.dumps({"type": "sample", "at": "2026-10-09T20:25:00+00:00",
                        "status": "ok", "checks": self.checks("ok")}),
            json.dumps({"type": "sample", "at": "2026-10-09T20:26:00+00:00",
                        "status": "warning", "checks": self.checks("warning")}),
            json.dumps({"type": "summary", "complete": True}),
        ]
        result = summarize_pilot(lines)
        self.assertEqual(result["samples"], 2)
        self.assertEqual(result["infrastructure_degraded"], 0)
        self.assertEqual(result["analysis_degraded"], 1)
        self.assertEqual(result["largest_gap_seconds"], 60)
        self.assertTrue(result["complete"])

    def test_incomplete_or_degraded_journal_fails_final_verdict(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pilot.jsonl"
            path.write_text(json.dumps({"type": "sample", "at": "2026-10-09T20:25:00+00:00",
                                        "status": "warning", "checks": self.checks("warning")}) + "\n")
            output = StringIO()
            with self.assertRaises(CommandError):
                call_command("report_operations_pilot", str(path), "--require-complete", stdout=output)
            self.assertIn("analyse degradee : 1", output.getvalue())

    def test_invalid_line_is_counted_without_leaking_it(self):
        result = summarize_pilot(['{"secret":'])
        self.assertEqual(result["invalid_lines"], 1)
        self.assertEqual(result["samples"], 0)

    @staticmethod
    def checks(analysis):
        checks = {name: {"status": "ok"} for name in (
            "database", "event_queue", "push_queue", "camera_presence",
            "realtime", "push_configuration", "workers",
        )}
        checks["analysis"] = {"status": analysis}
        return checks
