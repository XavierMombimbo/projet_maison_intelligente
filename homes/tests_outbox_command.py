from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import OperationalError
from django.test import SimpleTestCase, override_settings


MODULE = "homes.management.commands.dispatch_event_outbox"
SHARED = {"default": {"BACKEND": "channels_redis.core.RedisChannelLayer"}}


@override_settings(CHANNEL_LAYERS=SHARED)
class OutboxCommandTests(SimpleTestCase):
    def setUp(self):
        self.stdout = StringIO()
        self.stderr = StringIO()
        self.dispatch = self.enterContext(patch(f"{MODULE}.dispatch_pending_outbox", return_value=(1, 0)))
        self.sleep = self.enterContext(patch(f"{MODULE}.time.sleep"))
        self.close = self.enterContext(patch(f"{MODULE}.close_old_connections"))
        self.heartbeat = self.enterContext(patch(f"{MODULE}.record_worker_heartbeat"))

    def run_command(self, **options):
        call_command("dispatch_event_outbox", stdout=self.stdout, stderr=self.stderr, **options)

    def test_once_keeps_existing_behavior(self):
        self.run_command(limit=17)
        self.dispatch.assert_called_once_with(limit=17)
        self.sleep.assert_not_called()
        self.assertEqual(self.close.call_count, 2)
        self.heartbeat.assert_not_called()

    def test_once_reports_pending_failures(self):
        self.dispatch.return_value = (0, 1)
        with self.assertRaises(CommandError):
            self.run_command()
        self.sleep.assert_not_called()

    def test_watch_retries_failed_entries(self):
        self.dispatch.side_effect = [(0, 1), (1, 0)]
        self.sleep.side_effect = [None, KeyboardInterrupt]
        self.run_command(watch=True, interval=2)
        self.assertEqual(self.dispatch.call_count, 2)
        self.sleep.assert_called_with(2)
        self.assertEqual(self.close.call_count, 4)
        self.assertEqual(self.heartbeat.call_count, 2)
        self.heartbeat.assert_called_with("event_outbox", 2)
        self.assertIn("arretee", self.stdout.getvalue())

    def test_watch_recovers_from_database_failure(self):
        self.dispatch.side_effect = [OperationalError("private connection details"), (1, 0)]
        self.sleep.side_effect = [None, KeyboardInterrupt]
        self.run_command(watch=True)
        self.assertEqual(self.dispatch.call_count, 2)
        self.assertIn("Base indisponible", self.stderr.getvalue())
        self.assertNotIn("private", self.stderr.getvalue())
        self.heartbeat.assert_called_once_with("event_outbox", 5)

    def test_watch_empty_cycles_are_quiet(self):
        self.dispatch.return_value = (0, 0)
        self.sleep.side_effect = KeyboardInterrupt
        self.run_command(watch=True)
        self.assertEqual(len(self.stdout.getvalue().splitlines()), 2)

    def test_watch_rejects_local_or_missing_transport_before_dispatch(self):
        for layers in ({}, {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}):
            with self.subTest(layers=layers), override_settings(CHANNEL_LAYERS=layers):
                with self.assertRaisesMessage(CommandError, "transport Redis partage"):
                    self.run_command(watch=True)
        self.dispatch.assert_not_called()

    def test_invalid_options_do_not_dispatch(self):
        for options in ({"limit": 0}, {"limit": 10001}, {"interval": 0}, {"interval": 3601}):
            with self.subTest(options=options), self.assertRaises(CommandError):
                self.run_command(**options)
        self.dispatch.assert_not_called()

    def test_once_propagates_database_failure(self):
        self.dispatch.side_effect = OperationalError("unavailable")
        with self.assertRaises(OperationalError):
            self.run_command()
        self.assertEqual(self.close.call_count, 2)

    def test_unexpected_failure_is_not_hidden(self):
        self.dispatch.side_effect = ValueError("bug")
        with self.assertRaises(ValueError):
            self.run_command(watch=True)
        self.sleep.assert_not_called()
