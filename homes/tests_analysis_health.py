import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from .analysis_health import check_analysis_health, record_analysis_state


@override_settings(REDIS_URL="redis://localhost:6380/0")
class AnalysisHealthTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.camera_id = uuid.uuid4()
        self.key = f"sentinelle:analysis:{self.camera_id}"
        self.cache = self.enterContext(patch("homes.analysis_health.cache"))

    def test_records_only_bounded_state_and_time(self):
        with patch("homes.analysis_health.timezone.now", return_value=self.now):
            record_analysis_state(self.camera_id, "running")
        self.cache.set.assert_called_once_with(
            self.key, {"state": "running", "at": self.now.timestamp()}, timeout=90,
        )

    def test_running_requires_fresh_report_for_each_camera(self):
        self.cache.get.side_effect = lambda key: (
            {"state": "running", "at": (self.now - timedelta(seconds=30)).timestamp()}
            if key == self.key else None
        )
        self.assertEqual(check_analysis_health([self.camera_id], self.now)["status"], "ok")
        self.assertEqual(check_analysis_health([self.camera_id, uuid.uuid4()], self.now)["status"], "unknown")
        self.cache.get.side_effect = None
        self.cache.get.return_value = {
            "state": "running", "at": (self.now - timedelta(seconds=61)).timestamp(),
        }
        self.assertEqual(check_analysis_health([self.camera_id], self.now)["status"], "unknown")

    def test_failed_model_is_distinct_from_missing_report(self):
        self.cache.get.return_value = {"state": "failed", "at": self.now.timestamp()}
        report = check_analysis_health([self.camera_id], self.now)
        self.assertEqual(report["status"], "warning")
        self.assertEqual(report["degraded"], 1)
        self.assertEqual(report["running"], 0)

    def test_cache_failure_is_redacted(self):
        self.cache.get.side_effect = RuntimeError("redis://secret@private")
        self.assertEqual(check_analysis_health([self.camera_id], self.now)["status"], "unknown")
        self.cache.set.side_effect = RuntimeError("redis://secret@private")
        record_analysis_state(self.camera_id, "failed")

    @override_settings(REDIS_URL="")
    def test_unconfigured_analysis_is_unknown(self):
        self.assertEqual(check_analysis_health([self.camera_id], self.now)["status"], "unknown")
        record_analysis_state(self.camera_id, "running")
        self.cache.assert_not_called()
