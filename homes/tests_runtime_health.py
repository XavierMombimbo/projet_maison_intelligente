import json
import uuid
from datetime import timedelta
from io import StringIO
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.models import User
from notifications.models import PushDelivery, PushDeliveryStatus
from .models import Camera, Evenement, EvenementBoiteEnvoi, Maison, StatutAppairage, StatutBoiteEnvoi
from .operations import _probe_channel, collect_operations


@override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
class ChannelProbeTests(SimpleTestCase):
    def test_private_channel_roundtrip(self):
        async_to_sync(_probe_channel)()


@override_settings(FCM_ENABLED=True, FCM_PROJECT_ID="test-project", REDIS_URL="",
    CHANNEL_LAYERS={"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}})
class OperationsTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.enterContext(patch("homes.operations.timezone.now", return_value=self.now))
        self.probe = self.enterContext(patch("homes.operations._probe_channel", new_callable=AsyncMock))
        self.user = User.objects.create_user(username="private-user")
        self.house = Maison.objects.create(nom="private-house", proprietaire=self.user)
        self.camera = Camera.objects.create(nom="private-camera", maison=self.house,
            statut_appairage=StatutAppairage.APPAIREE, surveillance_active=True,
            derniere_connexion=self.now)

    def event(self):
        return Evenement.objects.create(camera=self.camera, maison=self.house,
            client_event_id=uuid.uuid4(), type="person_detected", confiance_ia=0.9)

    def test_empty_queues_do_not_claim_workers_or_analysis_healthy(self):
        report = collect_operations()
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["checks"]["analysis"]["status"], "unknown")
        self.assertEqual(report["checks"]["workers"]["status"], "unknown")
        self.assertEqual(report["checks"]["push_queue"]["pending"], 0)
        self.assertEqual(report["checks"]["camera_presence"]["expected"], 1)

    def test_queue_boundary_and_sent_entries(self):
        entry = EvenementBoiteEnvoi.objects.create(evenement=self.event())
        EvenementBoiteEnvoi.objects.filter(pk=entry.pk).update(date_creation=self.now - timedelta(seconds=60))
        self.assertEqual(collect_operations()["checks"]["event_queue"]["overdue"], 0)
        EvenementBoiteEnvoi.objects.filter(pk=entry.pk).update(date_creation=self.now - timedelta(seconds=61))
        result = collect_operations()["checks"]["event_queue"]
        self.assertEqual(result["overdue"], 1)
        self.assertEqual(result["oldest_due_seconds"], 61)
        self.assertEqual(result["status"], "warning")
        entry.statut = StatutBoiteEnvoi.ENVOYE
        entry.save(update_fields=["statut"])
        self.assertEqual(collect_operations()["checks"]["event_queue"]["pending"], 0)

    def test_retries_are_measured_from_due_time_not_creation(self):
        delivery = PushDelivery.objects.create(event=self.event(), recipient=self.user,
            status=PushDeliveryStatus.RETRY, next_attempt_at=self.now + timedelta(minutes=5))
        PushDelivery.objects.filter(pk=delivery.pk).update(created_at=self.now - timedelta(days=1))
        report = collect_operations()["checks"]["push_queue"]
        self.assertEqual((report["pending"], report["due"], report["overdue"]), (1, 0, 0))
        delivery.next_attempt_at = self.now - timedelta(seconds=5)
        delivery.save(update_fields=["next_attempt_at"])
        report = collect_operations()["checks"]["push_queue"]
        self.assertEqual((report["due"], report["overdue"], report["oldest_due_seconds"]), (1, 0, 5))
        delivery.next_attempt_at = self.now - timedelta(seconds=100)
        delivery.save(update_fields=["next_attempt_at"])
        self.assertEqual(collect_operations()["checks"]["push_queue"]["overdue"], 1)

    def test_pending_push_without_schedule_and_terminal_states(self):
        delivery = PushDelivery.objects.create(event=self.event(), recipient=self.user)
        PushDelivery.objects.filter(pk=delivery.pk).update(created_at=self.now - timedelta(seconds=90))
        self.assertEqual(collect_operations()["checks"]["push_queue"]["overdue"], 1)
        for status in ("accepted", "received", "failed", "invalid", "cancelled"):
            delivery.status = status
            delivery.save(update_fields=["status"])
            self.assertEqual(collect_operations()["checks"]["push_queue"]["pending"], 0)

    def test_only_paired_active_cameras_are_expected(self):
        for status, active in (("revoked", True), ("unpaired", True), ("paired", False)):
            Camera.objects.create(nom="ignored", maison=self.house,
                statut_appairage=status, surveillance_active=active)
        self.assertEqual(collect_operations()["checks"]["camera_presence"]["expected"], 1)
        self.camera.derniere_connexion = self.now - timedelta(seconds=120)
        self.camera.save(update_fields=["derniere_connexion"])
        self.assertEqual(collect_operations()["checks"]["camera_presence"]["stale"], 0)
        self.camera.derniere_connexion = None
        self.camera.save(update_fields=["derniere_connexion"])
        self.assertEqual(collect_operations()["checks"]["camera_presence"]["stale"], 1)

    def test_database_failure_is_redacted_and_metrics_unknown(self):
        with patch("homes.operations.connection.cursor", side_effect=OperationalError("password=secret host=private")):
            report = collect_operations()
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["checks"]["event_queue"]["status"], "unknown")
        self.assertNotIn("password", json.dumps(report))

    def test_channel_timeout_is_redacted(self):
        self.probe.side_effect = TimeoutError("redis://secret@private")
        report = collect_operations()
        self.assertEqual(report["checks"]["realtime"]["status"], "error")
        self.assertNotIn("secret", json.dumps(report))

    @override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}})
    def test_in_memory_backend_is_not_reported_as_shared(self):
        self.assertEqual(collect_operations()["checks"]["realtime"]["status"], "warning")

    @override_settings(FCM_ENABLED=False)
    def test_disabled_fcm_has_warning_even_with_empty_queue(self):
        self.assertEqual(collect_operations()["checks"]["push_configuration"]["status"], "warning")

    def test_command_json_is_read_only_and_contains_no_names(self):
        out = StringIO()
        call_command("check_operations", as_json=True, stdout=out)
        self.assertEqual(json.loads(out.getvalue())["schema_version"], 1)
        self.assertNotIn("private-", out.getvalue())
        self.assertEqual(Evenement.objects.count(), 0)
        self.assertEqual(PushDelivery.objects.count(), 0)

    def test_command_error_still_writes_parseable_json(self):
        self.probe.side_effect = RuntimeError("secret")
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command("check_operations", as_json=True, stdout=out)
        self.assertEqual(json.loads(out.getvalue())["status"], "error")
        self.assertNotIn("secret", out.getvalue())

    def test_invalid_thresholds_do_not_probe(self):
        for options in ({"max_queue_age": 0}, {"camera_timeout": -1}, {"camera_timeout": 86401}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                call_command("check_operations", **options)
        self.probe.assert_not_called()
