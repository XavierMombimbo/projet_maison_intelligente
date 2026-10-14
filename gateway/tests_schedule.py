import os
import uuid
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch

from .schedule import (
    EncryptedScheduleCache, ScheduleError, evaluate_schedule, sign_schedule,
    verify_schedule,
)


class ScheduleTests(TestCase):
    def setUp(self):
        self.camera_id = str(uuid.uuid4())
        self.key = "test-signing-key"
        self.payload = {
            "camera_id": self.camera_id, "camera_enabled": True,
            "timezone": "Africa/Kinshasa",
            "windows": [{"id": 1, "day": 0, "starts_at": "23:00:00",
                         "ends_at": "01:00:00", "active": True}],
            "exceptions": [], "override": None, "analysis": {},
        }

    def test_signature_is_stable_and_bound_to_camera_and_content(self):
        first = sign_schedule(self.payload, self.key)
        self.assertEqual(first, sign_schedule(self.payload, self.key))
        self.assertEqual(verify_schedule(first, camera_id=self.camera_id, key=self.key), self.payload)
        changed = {**first, "payload": {**self.payload, "camera_enabled": False}}
        with self.assertRaises(ScheduleError):
            verify_schedule(changed, camera_id=self.camera_id, key=self.key)
        with self.assertRaises(ScheduleError):
            verify_schedule(first, camera_id=uuid.uuid4(), key=self.key)
        with self.assertRaises(ScheduleError):
            verify_schedule(first, camera_id=self.camera_id, key="other-key")

    def test_local_decision_crosses_midnight_and_honors_priority(self):
        monday = datetime(2026, 9, 21, 22, 30, tzinfo=timezone.utc)
        tuesday = datetime(2026, 9, 21, 23, 30, tzinfo=timezone.utc)
        later = datetime(2026, 9, 22, 1, 0, tzinfo=timezone.utc)
        self.assertEqual(evaluate_schedule(self.payload, at=monday), (True, "schedule"))
        self.assertEqual(evaluate_schedule(self.payload, at=tuesday), (True, "schedule"))
        self.assertEqual(evaluate_schedule(self.payload, at=later), (False, "default"))
        self.payload["override"] = {"active": False, "expires_at": "2026-09-22T00:00:00+00:00"}
        self.assertEqual(evaluate_schedule(self.payload, at=tuesday), (False, "manual"))
        self.payload["camera_enabled"] = False
        self.assertEqual(evaluate_schedule(self.payload, at=monday), (False, "camera"))

    def test_encrypted_cache_refuses_corruption_and_revokes(self):
        with TemporaryDirectory() as directory:
            path = os.path.join(directory, "schedule.bin")
            cache = EncryptedScheduleCache(self.camera_id, self.key, path=path)
            with patch("gateway.schedule.protect_local_data", side_effect=lambda data: b"sealed:" + data), patch(
                "gateway.schedule.unprotect_local_data", side_effect=lambda data: data.removeprefix(b"sealed:")
            ):
                manifest = sign_schedule(self.payload, self.key)
                cache.save(manifest)
                self.assertEqual(cache.load(), manifest)
                with open(path, "wb") as stream:
                    stream.write(b"damaged")
                with self.assertRaises(ScheduleError):
                    cache.load()
                cache.revoke()
                with self.assertRaises(ScheduleError):
                    cache.load()

    @skipUnless(os.name == "nt", "Windows DPAPI only")
    def test_real_dpapi_cache_roundtrip(self):
        with TemporaryDirectory() as directory:
            cache = EncryptedScheduleCache(
                self.camera_id, self.key, path=os.path.join(directory, "schedule.bin"),
            )
            manifest = sign_schedule(self.payload, self.key)
            cache.save(manifest)
            self.assertEqual(cache.load(), manifest)
