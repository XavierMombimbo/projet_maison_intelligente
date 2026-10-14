from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from .worker_health import check_worker_heartbeats, record_worker_heartbeat


@override_settings(REDIS_URL="redis://localhost:6380/0")
class WorkerHealthTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.cache = self.enterContext(patch("homes.worker_health.cache"))

    def test_successful_cycle_records_bounded_heartbeat(self):
        with patch("homes.worker_health.timezone.now", return_value=self.now):
            record_worker_heartbeat("push", 5)
        self.cache.set.assert_called_once_with(
            "sentinelle:worker:push",
            {"at": self.now.timestamp(), "interval": 5},
            timeout=30,
        )

    def test_cache_failure_does_not_interrupt_delivery(self):
        self.cache.set.side_effect = RuntimeError("private Redis URL")
        record_worker_heartbeat("push", 5)

    def test_missing_or_stale_worker_is_warning(self):
        self.cache.get.side_effect = lambda key: (
            {"at": self.now.timestamp(), "interval": 5}
            if key == "sentinelle:worker:event_outbox" else None
        )
        report = check_worker_heartbeats(self.now)
        self.assertEqual(report["status"], "warning")
        self.assertIsNone(report["push_age_seconds"])
        self.cache.get.side_effect = lambda key: (
            {"at": self.now.timestamp(), "interval": 5}
            if key == "sentinelle:worker:event_outbox"
            else {"at": (self.now - timedelta(seconds=31)).timestamp(), "interval": 5}
        )
        self.assertEqual(check_worker_heartbeats(self.now)["status"], "warning")

    def test_fresh_workers_are_ok(self):
        self.cache.get.return_value = {
            "at": (self.now - timedelta(seconds=6)).timestamp(), "interval": 5,
        }
        report = check_worker_heartbeats(self.now)
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["push_age_seconds"], 6)

    def test_error_is_redacted(self):
        self.cache.get.side_effect = RuntimeError("password=private")
        self.assertEqual(check_worker_heartbeats(self.now)["status"], "unknown")

    @override_settings(REDIS_URL="")
    def test_without_shared_cache_is_unknown(self):
        self.assertEqual(check_worker_heartbeats(self.now)["status"], "unknown")
        record_worker_heartbeat("push", 5)
        self.cache.assert_not_called()
