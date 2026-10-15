import os
import tempfile
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from .event_queue import EncryptedEventQueue, EventQueueError


class EncryptedEventQueueTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.camera_id = uuid.uuid4()
        self.event_id = uuid.uuid4()

    def _queue(self):
        return EncryptedEventQueue(self.camera_id, Path(self.directory.name))

    def _enqueue(self, queue):
        queue.enqueue(
            capture=b"private jpeg bytes", detection={"label": "person", "confidence": 0.9},
            rule_context={"type": "presence_prolonged"}, event_id=self.event_id,
            observed_at="2026-10-12T12:00:00.000Z",
            model_name="yolo11n", model_version="320@test",
        )

    @patch("gateway.event_queue.unprotect_local_data", side_effect=lambda payload: payload[10:])
    @patch("gateway.event_queue.protect_local_data", side_effect=lambda payload: b"encrypted:" + payload)
    def test_event_is_encrypted_persistent_and_acknowledged(self, protect, unprotect):
        queue = self._queue()
        self.assertIsNone(queue.oldest())
        self._enqueue(queue)
        path, event = self._queue().oldest()
        self.assertNotIn(b"private jpeg bytes", path.read_bytes())
        self.assertEqual(event["event_id"], str(self.event_id))
        self.assertEqual(event["model_version"], "320@test")
        self.assertEqual(event["capture"], b"private jpeg bytes")
        queue.acknowledge(path)
        self.assertIsNone(queue.oldest())

    @patch("gateway.event_queue.unprotect_local_data", side_effect=lambda payload: payload[10:])
    @patch("gateway.event_queue.protect_local_data", side_effect=lambda payload: b"encrypted:" + payload)
    def test_v3_identity_state_keeps_its_contract_on_retry(self, protect, unprotect):
        queue = self._queue()
        queue.enqueue(
            capture=b"private jpeg bytes",
            detection={"label": "person", "confidence": 0.9, "face_status": "unknown"},
            rule_context={"type": "presence_prolonged"}, event_id=self.event_id,
            observed_at="2026-10-12T12:00:00.000Z",
            model_name="yolo11n", model_version="320@test", contract_version=3,
        )
        _path, event = queue.oldest()
        self.assertEqual(event["contract_version"], 3)
        self.assertEqual(event["detection"]["face_status"], "unknown")

    @patch("gateway.event_queue.protect_local_data", side_effect=lambda payload: payload[::-1])
    def test_full_queue_refuses_to_drop_an_event(self, protect):
        queue = self._queue()
        self._enqueue(queue)
        with patch("gateway.event_queue.MAX_PENDING_EVENTS", 1):
            with self.assertRaises(EventQueueError):
                self._enqueue(queue)
        self.assertEqual(len(list(queue.path.glob("*.event"))), 1)

    @patch("gateway.event_queue.unprotect_local_data", side_effect=ValueError("invalid"))
    def test_corrupt_event_is_preserved_for_inspection(self, unprotect):
        queue = self._queue()
        (queue.path / "0001.event").write_bytes(b"invalid")
        with self.assertRaises(EventQueueError):
            queue.oldest()
        self.assertEqual(len(list(queue.path.glob("*.event"))), 1)

    def test_windows_dpapi_round_trip(self):
        if os.name != "nt":
            self.skipTest("DPAPI est propre a Windows")
        queue = self._queue()
        self._enqueue(queue)
        path, event = self._queue().oldest()
        self.assertNotIn(b"private jpeg bytes", path.read_bytes())
        self.assertEqual(event["capture"], b"private jpeg bytes")
