import json
import itertools
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import cv2
import numpy as np

from .__main__ import build_parser, main
from .client import GatewayAPIError, GatewayAuthorizationError
from .event_queue import EventQueueError
from .schedule import EncryptedScheduleCache, evaluate_schedule, sign_schedule
from .webcam import (
    PresenceRule, WebcamConfigurationError, WebcamError, YoloWebcamDetector,
    deliver_oldest, run_webcam, send_detection,
    watch_webcam,
)


class FakeNet:
    def setInput(self, blob):
        self.blob = blob

    def forward(self):
        output = np.zeros((1, 84, 2100), dtype=np.float32)
        output[0, :4, 0] = (160, 160, 100, 120)
        output[0, 4, 0] = 0.9
        return output


class WebcamTests(TestCase):
    def test_recipe_commands_use_a_separate_credentials_file(self):
        path = Path("tmp") / "schedule-recipe.credentials"
        credentials = SimpleNamespace(camera_id="recipe-camera")
        for command in ("pair", "run", "webcam"):
            with self.subTest(command=command), \
                 patch("gateway.__main__.load_credentials", return_value=credentials) as load, \
                 patch("gateway.__main__.save_credentials") as save, \
                 patch("gateway.__main__.GatewayAPIClient") as api, \
                 patch("gateway.__main__.getpass.getpass", return_value="123456"), \
                 patch("gateway.__main__.run_gateway", return_value=0) as rtsp, \
                 patch("gateway.webcam.watch_webcam", return_value=0) as webcam, \
                 patch("builtins.print"):
                api.return_value.pair.return_value = credentials
                arguments = [command, "--credentials-file", str(path)]
                if command == "pair":
                    arguments += ["--server", "http://127.0.0.1:8002"]
                elif command == "webcam":
                    arguments += ["--once", "--allow-development-model"]
                self.assertEqual(main(arguments), 0)
                if command == "pair":
                    save.assert_called_once_with(credentials, path=path)
                    load.assert_not_called()
                else:
                    load.assert_called_once_with(path=path)
                    save.assert_not_called()
                    (rtsp if command == "run" else webcam).assert_called_once()
        self.assertIsNone(build_parser().parse_args(["webcam"]).credentials_file)

    def test_offline_boot_uses_signed_schedule_then_applies_online_stop(self):
        camera_id = "11111111-1111-4111-8111-111111111111"
        key = "test-key"
        manifest = sign_schedule({
            "camera_id": camera_id, "camera_enabled": True,
            "timezone": "Africa/Kinshasa", "windows": [], "exceptions": [],
            "override": None, "analysis": {},
        }, key)
        frames = []
        heartbeats = []

        class Reader:
            def open(self):
                pass

            def read(self):
                frames.append(True)
                return np.zeros((32, 32, 3), dtype=np.uint8)

            def close(self):
                pass

        class Detector:
            def detect(self, frame, thresholds):
                return []

        class API:
            token_calls = 0

            def token(self, credentials):
                self.token_calls += 1
                if self.token_calls == 1:
                    raise GatewayAPIError("offline")
                return "token"

            def state(self, token):
                return {"monitoring_active": False, "analysis": {}, "schedule": manifest}

            def _request(self, path, **kwargs):
                heartbeats.append(kwargs["payload"])

        def stop_on_second_sleep(delay):
            if delay == 2:
                raise KeyboardInterrupt

        with TemporaryDirectory() as directory:
            cache = EncryptedScheduleCache(camera_id, key, path=Path(directory) / "schedule.bin")
            with patch("gateway.schedule.protect_local_data", side_effect=lambda data: b"sealed:" + data), patch(
                "gateway.schedule.unprotect_local_data", side_effect=lambda data: data.removeprefix(b"sealed:")
            ):
                cache.save(manifest)
                api = API()
                with patch("gateway.webcam.GatewayAPIClient", return_value=api):
                    result = run_webcam(
                        SimpleNamespace(server_url="https://sentinelle.example/",
                                        camera_id=camera_id, event_signing_key=key),
                        allow_development_model=True,
                        reader_factory=lambda index: Reader(), detector_factory=Detector,
                        queue_factory=lambda camera: SimpleNamespace(oldest=lambda: None),
                        schedule_cache_factory=lambda camera, signing_key: cache,
                        clock=iter([10, 10, 21]).__next__, sleep=stop_on_second_sleep,
                        output=lambda message: None,
                    )
                self.assertEqual(result, 0)
                self.assertEqual(api.token_calls, 2)
                self.assertEqual(len(frames), 1)
                self.assertEqual(heartbeats[0]["monitoring_active"], False)

    def test_explicit_auth_rejection_removes_cached_schedule(self):
        camera_id = "11111111-1111-4111-8111-111111111111"
        key = "test-key"
        manifest = sign_schedule({
            "camera_id": camera_id, "camera_enabled": True,
            "timezone": "Africa/Kinshasa", "windows": [], "exceptions": [],
            "override": None, "analysis": {},
        }, key)
        with TemporaryDirectory() as directory:
            cache = EncryptedScheduleCache(camera_id, key, path=Path(directory) / "schedule.bin")
            with patch("gateway.schedule.protect_local_data", side_effect=lambda data: b"sealed:" + data):
                cache.save(manifest)
            api = SimpleNamespace(token=lambda credentials: (_ for _ in ()).throw(
                GatewayAuthorizationError("revoked")
            ))
            with patch("gateway.webcam.GatewayAPIClient", return_value=api):
                with self.assertRaisesRegex(WebcamConfigurationError, "revoque"):
                    run_webcam(
                        SimpleNamespace(server_url="https://sentinelle.example/",
                                        camera_id=camera_id, event_signing_key=key),
                        allow_development_model=True,
                        reader_factory=lambda index: SimpleNamespace(open=lambda: None, close=lambda: None),
                        detector_factory=lambda: object(),
                        queue_factory=lambda camera: SimpleNamespace(oldest=lambda: None),
                        schedule_cache_factory=lambda camera, signing_key: cache,
                    )
            self.assertFalse(cache.path.exists())

    def test_state_auth_rejection_does_not_use_offline_cache(self):
        camera_id = "11111111-1111-4111-8111-111111111111"
        key = "test-key"
        manifest = sign_schedule({
            "camera_id": camera_id, "camera_enabled": True,
            "timezone": "Africa/Kinshasa", "windows": [], "exceptions": [],
            "override": None, "analysis": {},
        }, key)
        with TemporaryDirectory() as directory:
            cache = EncryptedScheduleCache(camera_id, key, path=Path(directory) / "schedule.bin")
            with patch("gateway.schedule.protect_local_data", side_effect=lambda data: b"sealed:" + data):
                cache.save(manifest)
            api = SimpleNamespace(
                token=lambda credentials: "token",
                state=lambda token: (_ for _ in ()).throw(GatewayAuthorizationError("forbidden")),
            )
            reader = SimpleNamespace(open=lambda: None, close=lambda: None,
                                     read=lambda: self.fail("No frame after authorization rejection"))
            with patch("gateway.webcam.GatewayAPIClient", return_value=api):
                with self.assertRaisesRegex(WebcamConfigurationError, "refuse"):
                    watch_webcam(
                        SimpleNamespace(server_url="https://sentinelle.example/",
                                        camera_id=camera_id, event_signing_key=key),
                        allow_development_model=True,
                        reader_factory=lambda index: reader, detector_factory=lambda: object(),
                        queue_factory=lambda camera: SimpleNamespace(oldest=lambda: None),
                        schedule_cache_factory=lambda camera, signing_key: cache,
                        sleep=lambda delay: self.fail("No retry after authorization rejection"),
                    )
            self.assertFalse(cache.path.exists())

    @patch("gateway.webcam._sign_event", return_value="a" * 64)
    def test_detection_authorization_failure_is_not_a_network_failure(self, signer):
        event = {
            "capture": b"jpeg", "detection": {"label": "person", "confidence": 0.9},
            "rule_context": {"type": "presence_prolonged"},
            "event_id": "11111111-1111-4111-8111-111111111111",
            "observed_at": "2026-10-13T12:00:00.000Z",
            "model_name": "yolo11n", "model_version": "320@test",
        }
        for status in (401, 403):
            with self.subTest(status=status):
                response = SimpleNamespace(ok=False, status_code=status)
                with self.assertRaises(GatewayAuthorizationError):
                    send_detection(
                        SimpleNamespace(server_url="https://sentinelle.example/"),
                        SimpleNamespace(camera_id="camera", event_signing_key="key"),
                        "token", None, event["detection"], event["rule_context"],
                        event=event, session=SimpleNamespace(post=lambda *args, **kwargs: response),
                    )

    def test_offline_schedule_changes_state_then_acknowledges_new_online_version(self):
        camera_id = "11111111-1111-4111-8111-111111111111"
        key = "test-key"
        payload = {
            "camera_id": camera_id, "camera_enabled": True,
            "timezone": "Africa/Kinshasa",
            "windows": [{"id": 1, "day": 1, "starts_at": "13:00:00",
                         "ends_at": "13:01:00", "active": True}],
            "exceptions": [], "override": None, "analysis": {},
        }
        offline_manifest = sign_schedule(payload, key)
        online_manifest = sign_schedule({**payload, "camera_enabled": False}, key)
        credentials = SimpleNamespace(server_url="https://sentinelle.example/",
                                      camera_id=camera_id, event_signing_key=key)
        frames, heartbeats, decisions, messages = [], [], [], []
        instants = iter([
            datetime(2026, 10, 13, 11, 59, 59, tzinfo=timezone.utc),
            datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc),
            datetime(2026, 10, 13, 12, 1, 0, tzinfo=timezone.utc),
        ])

        def local_decision(saved_payload):
            decision = evaluate_schedule(saved_payload, at=next(instants))
            decisions.append(decision)
            return decision

        class API:
            token_calls = 0

            def token(self, credentials):
                self.token_calls += 1
                if self.token_calls == 1:
                    raise GatewayAPIError("offline")
                return "token"

            def state(self, token):
                return {"monitoring_active": False, "analysis": {}, "schedule": online_manifest}

            def _request(self, path, **kwargs):
                heartbeats.append(kwargs["payload"])

        def read():
            frames.append(True)
            return np.zeros((32, 32, 3), dtype=np.uint8)

        def sleep(delay):
            if heartbeats:
                raise KeyboardInterrupt

        with TemporaryDirectory() as directory:
            cache = EncryptedScheduleCache(camera_id, key, path=Path(directory) / "schedule.bin")
            with patch("gateway.schedule.protect_local_data", side_effect=lambda data: b"sealed:" + data), \
                 patch("gateway.schedule.unprotect_local_data", side_effect=lambda data: data.removeprefix(b"sealed:")):
                cache.save(offline_manifest)
                api = API()
                with patch("gateway.webcam.GatewayAPIClient", return_value=api), \
                     patch("gateway.webcam.evaluate_schedule", side_effect=local_decision):
                    self.assertEqual(run_webcam(
                        credentials, allow_development_model=True,
                        reader_factory=lambda index: SimpleNamespace(open=lambda: None, read=read, close=lambda: None),
                        detector_factory=lambda: SimpleNamespace(detect=lambda frame, thresholds: []),
                        queue_factory=lambda camera: SimpleNamespace(oldest=lambda: None),
                        schedule_cache_factory=lambda camera, signing_key: cache,
                        clock=iter([10, 11, 11, 12, 21]).__next__, sleep=sleep,
                        output=messages.append,
                    ), 0)
                self.assertEqual(cache.load()["version"], online_manifest["version"])
        self.assertEqual(decisions, [(False, "default"), (True, "schedule"), (False, "default")])
        self.assertEqual(len(frames), 1)
        self.assertEqual(api.token_calls, 2)
        self.assertEqual(heartbeats, [{"monitoring_active": False, "analysis_state": "inactive",
                                       "schedule_version": online_manifest["version"]}])
        self.assertEqual(messages[:4], [
            "Surveillance arretee (planning local hors ligne).",
            "Surveillance active (planning local hors ligne).",
            "Surveillance arretee (planning local hors ligne).",
            "Surveillance arretee (serveur).",
        ])

    def test_auth_rejection_on_heartbeat_or_queue_prevents_offline_restart(self):
        camera_id = "11111111-1111-4111-8111-111111111111"
        key = "test-key"
        manifest = sign_schedule({
            "camera_id": camera_id, "camera_enabled": True,
            "timezone": "Africa/Kinshasa", "windows": [], "exceptions": [],
            "override": None, "analysis": {},
        }, key)
        credentials = SimpleNamespace(server_url="https://sentinelle.example/",
                                      camera_id=camera_id, event_signing_key=key)

        def rejected(*args, **kwargs):
            raise GatewayAuthorizationError("forbidden")

        for endpoint in ("heartbeat", "queue"):
            with self.subTest(endpoint=endpoint), TemporaryDirectory() as directory:
                cache = EncryptedScheduleCache(camera_id, key, path=Path(directory) / "schedule.bin")
                with patch("gateway.schedule.protect_local_data", side_effect=lambda data: b"sealed:" + data):
                    cache.save(manifest)
                    api = SimpleNamespace(
                        token=lambda credentials: "token",
                        state=lambda token: {"monitoring_active": True, "analysis": {}, "schedule": manifest},
                        _request=rejected,
                    )
                    reader = SimpleNamespace(open=lambda: None, close=lambda: None,
                                             read=lambda: np.zeros((32, 32, 3), dtype=np.uint8))
                    options = {
                        "allow_development_model": True,
                        "reader_factory": lambda index: reader,
                        "detector_factory": lambda: SimpleNamespace(detect=lambda frame, thresholds: []),
                        "queue_factory": lambda camera: SimpleNamespace(oldest=lambda: None),
                        "schedule_cache_factory": lambda camera, signing_key: cache,
                        "sleep": lambda delay: self.fail("No retry after authorization rejection"),
                    }
                    with patch("gateway.webcam.GatewayAPIClient", return_value=api), \
                         patch("gateway.webcam.deliver_oldest", side_effect=rejected if endpoint == "queue" else None):
                        with self.assertRaisesRegex(WebcamConfigurationError, "refuse"):
                            watch_webcam(credentials, **options)
                self.assertFalse(cache.path.exists())
                api.token = lambda credentials: (_ for _ in ()).throw(GatewayAPIError("offline"))
                reader.read = lambda: self.fail("No offline frame after authorization rejection")
                with patch("gateway.webcam.GatewayAPIClient", return_value=api):
                    with self.assertRaises(GatewayAPIError):
                        run_webcam(credentials, **options)

    def test_yolo_decodes_person_in_normalized_frame(self):
        detector = YoloWebcamDetector.__new__(YoloWebcamDetector)
        detector.cv = cv2
        detector.net = FakeNet()
        result = detector.detect(np.zeros((480, 640, 3), dtype=np.uint8))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["label"], "person")
        self.assertGreater(result[0]["confidence"], 0.8)
        self.assertTrue(all(0 <= value <= 1 for value in result[0]["bbox"]))

    def test_presence_requires_continuity_inside_zone(self):
        rule = PresenceRule()
        analysis = {"presence_seconds": 2, "zone": {"x": 0, "y": 0, "width": 0.5, "height": 1}}
        item = {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.2, 0.4],
                "track_id": "webcam-person"}
        self.assertIsNone(rule.evaluate([item], analysis, 10))
        self.assertIsNone(rule.evaluate([item], analysis, 11))
        match = rule.evaluate([item], analysis, 12)
        self.assertEqual(match[1]["type"], "presence_prolonged")
        self.assertEqual(match[1]["duration_seconds"], 2)
        self.assertIsNone(rule.evaluate([], analysis, 13))
        self.assertIsNone(rule.evaluate([item], analysis, 14))

    @patch("gateway.webcam._sign_event", return_value="a" * 64)
    def test_event_uses_signed_multipart_contract(self, signer):
        response = SimpleNamespace(ok=True, json=lambda: {"status": "accepted"})
        session = SimpleNamespace(post=lambda *args, **kwargs: response)
        sent = {}

        def post(url, **kwargs):
            sent.update({"url": url, **kwargs})
            return response

        session.post = post
        credentials = SimpleNamespace(camera_id="camera", event_signing_key="key")
        api = SimpleNamespace(server_url="https://sentinelle.example/")
        detection = {"label": "person", "confidence": 0.9,
                     "bbox": [0.1, 0.1, 0.2, 0.3], "track_id": "webcam-person"}
        context = {"type": "presence_prolonged", "id": "presence-zone", "version": 1,
                   "duration_seconds": 2, "zone": {"x": 0, "y": 0, "width": 1, "height": 1},
                   "track_ids": ["webcam-person"]}
        self.assertEqual(send_detection(api, credentials, "token", np.zeros((32, 32, 3), dtype=np.uint8),
                                        detection, context, session=session)["status"], "accepted")
        self.assertEqual(sent["data"]["contract_version"], "2")
        self.assertEqual(json.loads(sent["data"]["objects"])[0]["label"], "person")
        self.assertEqual(sent["headers"]["X-Camera-Signature"], "a" * 64)
        self.assertEqual(signer.call_args.kwargs["path"], "/api/camera/me/detections/")

        api.server_url = "http://127.0.0.1:8001/"
        send_detection(api, credentials, "token", np.zeros((32, 32, 3), dtype=np.uint8),
                       detection, context, session=session)
        self.assertEqual(sent["headers"]["X-Forwarded-Proto"], "https")

    def test_once_analyzes_and_reports_without_event(self):
        class Reader:
            closed = False

            def __init__(self, index):
                self.index = index

            def open(self):
                pass

            def read(self):
                return np.zeros((32, 32, 3), dtype=np.uint8)

            def close(self):
                Reader.closed = True

        class Detector:
            def __init__(self):
                pass

            def detect(self, frame, thresholds):
                return []

        class API:
            server_url = "http://127.0.0.1:8001/"

            def token(self, credentials):
                return "token"

            def state(self, token):
                return {"monitoring_active": True, "analysis": {}}

            def _request(self, *args, **kwargs):
                self.heartbeat = kwargs["payload"]

        api = API()
        messages = []
        with patch("gateway.webcam.GatewayAPIClient", return_value=api):
            self.assertEqual(run_webcam(SimpleNamespace(server_url=api.server_url), once=True,
                                        allow_development_model=True, reader_factory=Reader,
                                        detector_factory=Detector, output=messages.append), 0)
        self.assertEqual(api.heartbeat["analysis_state"], "running")
        self.assertTrue(Reader.closed)
        self.assertIn("analysee", messages[0])

    def test_model_requires_explicit_development_opt_in(self):
        with self.assertRaises(WebcamError):
            run_webcam(SimpleNamespace(server_url="http://127.0.0.1:8001/"))
        with self.assertRaises(WebcamError):
            watch_webcam(SimpleNamespace(server_url="http://127.0.0.1:8001/"))
        parsed = build_parser().parse_args(["webcam", "--once", "--allow-development-model"])
        self.assertTrue(parsed.allow_development_model)

    @patch("gateway.webcam.run_webcam")
    def test_watch_retries_transient_failure(self, run):
        run.side_effect = [WebcamError("camera busy"), 0]
        delays = []
        self.assertEqual(watch_webcam(object(), allow_development_model=True,
                                      sleep=delays.append, output=lambda message: None), 0)
        self.assertEqual(delays, [1])

    @patch("gateway.webcam.run_webcam", side_effect=WebcamConfigurationError("line active"))
    def test_watch_does_not_retry_invalid_configuration(self, run):
        with self.assertRaises(WebcamConfigurationError):
            watch_webcam(object(), allow_development_model=True, sleep=lambda delay: self.fail("retry"))
        self.assertEqual(run.call_count, 1)

    @patch("gateway.webcam.run_webcam", side_effect=EventQueueError("file illisible"))
    def test_watch_stops_on_unreadable_local_queue(self, run):
        with self.assertRaisesRegex(WebcamConfigurationError, "file illisible"):
            watch_webcam(object(), allow_development_model=True,
                         sleep=lambda delay: self.fail("retry"))
        self.assertEqual(run.call_count, 1)

    def test_recovery_releases_webcam_and_restores_running_heartbeat(self):
        readers = []
        heartbeats = []
        token_calls = 0

        class Reader:
            def __init__(self, index):
                self.closed = False
                readers.append(self)

            def open(self):
                pass

            def read(self):
                return np.zeros((32, 32, 3), dtype=np.uint8)

            def close(self):
                self.closed = True

        class Detector:
            def detect(self, frame, thresholds):
                return []

        class API:
            def token(self, credentials):
                nonlocal token_calls
                token_calls += 1
                if token_calls == 1:
                    raise WebcamError("network unavailable")
                return "token"

            def state(self, token):
                return {"monitoring_active": True, "analysis": {}}

            def _request(self, path, **kwargs):
                heartbeats.append(kwargs["payload"]["analysis_state"])

        delays = []

        def sleep(delay):
            delays.append(delay)
            if delay == 0.5:
                raise KeyboardInterrupt

        with patch("gateway.webcam.GatewayAPIClient", return_value=API()):
            self.assertEqual(watch_webcam(
                SimpleNamespace(server_url="http://127.0.0.1:8001/", camera_id="11111111-1111-4111-8111-111111111111",
                                event_signing_key="test-key"),
                allow_development_model=True, reader_factory=Reader,
                detector_factory=Detector, sleep=sleep, output=lambda message: None,
                queue_factory=lambda camera_id: SimpleNamespace(oldest=lambda: None),
            ), 0)
        self.assertEqual(token_calls, 2)
        self.assertEqual(delays, [1, 0.5])
        self.assertEqual(heartbeats, ["running"])
        self.assertEqual(len(readers), 2)
        self.assertTrue(all(reader.closed for reader in readers))

    @patch("gateway.webcam.run_webcam", side_effect=WebcamError("network unavailable"))
    def test_backoff_can_be_stopped_without_traceback(self, run):
        messages = []

        def stop(delay):
            raise KeyboardInterrupt

        self.assertEqual(watch_webcam(object(), allow_development_model=True,
                                      sleep=stop, output=messages.append), 0)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(messages[-1], "Webcam autonome arretee.")

    def test_failed_delivery_keeps_event_and_retry_uses_same_id(self):
        event = {
            "capture": b"jpeg", "detection": {"label": "person", "confidence": 0.9},
            "rule_context": {"type": "presence_prolonged"},
            "event_id": "11111111-1111-4111-8111-111111111111",
            "observed_at": "2026-10-12T12:00:00.000Z",
            "model_name": "yolo11n", "model_version": "320@test",
        }
        path = object()

        class Queue:
            pending = (path, event)

            def oldest(self):
                return self.pending

            def acknowledge(self, received_path):
                self.pending = None

        queue = Queue()
        with patch("gateway.webcam.send_detection", side_effect=[WebcamError("offline"), {"status": "ok"}]) as send:
            with self.assertRaises(WebcamError):
                deliver_oldest(queue, object(), object(), "token")
            self.assertIsNotNone(queue.oldest())
            self.assertTrue(deliver_oldest(queue, object(), object(), "token"))
        self.assertIsNone(queue.oldest())
        self.assertEqual(send.call_args_list[0].kwargs["event"]["event_id"], event["event_id"])
        self.assertEqual(send.call_args_list[1].kwargs["event"]["observed_at"], event["observed_at"])

    @patch("gateway.webcam._sign_event", return_value="a" * 64)
    def test_replayed_event_gets_fresh_timestamp_and_nonce(self, signer):
        sent = []
        responses = iter([SimpleNamespace(ok=False, status_code=503),
                          SimpleNamespace(ok=True, json=lambda: {"status": "accepted"})])

        def post(url, **kwargs):
            sent.append(kwargs)
            return next(responses)

        event = {
            "capture": b"jpeg", "detection": {"label": "person", "confidence": 0.9},
            "rule_context": {"type": "presence_prolonged"},
            "event_id": "11111111-1111-4111-8111-111111111111",
            "observed_at": "2026-10-12T12:00:00.000Z",
            "model_name": "yolo11n", "model_version": "320@test",
        }
        api = SimpleNamespace(server_url="https://sentinelle.example/")
        credentials = SimpleNamespace(camera_id="camera", event_signing_key="key")
        with patch("gateway.webcam.time.time", side_effect=[100, 200]):
            with self.assertRaises(GatewayAPIError):
                send_detection(api, credentials, "token", None, event["detection"],
                               event["rule_context"], event=event, session=SimpleNamespace(post=post))
            send_detection(api, credentials, "token", None, event["detection"],
                           event["rule_context"], event=event, session=SimpleNamespace(post=post))
        self.assertEqual([item["data"]["event_id"] for item in sent], [event["event_id"]] * 2)
        self.assertEqual([item["data"]["observed_at"] for item in sent], [event["observed_at"]] * 2)
        self.assertEqual([item["data"]["model_version"] for item in sent], ["320@test"] * 2)
        self.assertEqual([item["headers"]["X-Camera-Timestamp"] for item in sent], ["100", "200"])
        self.assertNotEqual(sent[0]["headers"]["X-Camera-Nonce"], sent[1]["headers"]["X-Camera-Nonce"])
        self.assertEqual(signer.call_count, 2)

    def test_detection_is_queued_before_a_failed_post(self):
        class Queue:
            pending = None

            def oldest(self):
                return self.pending

            def enqueue(self, **event):
                self.pending = (object(), event)

        class Reader:
            closed = False

            def __init__(self, index):
                pass

            def open(self):
                pass

            def read(self):
                return np.zeros((32, 32, 3), dtype=np.uint8)

            def close(self):
                self.closed = True

        class Detector:
            def detect(self, frame, thresholds):
                return [{"label": "person", "confidence": 0.9,
                         "bbox": [0.1, 0.1, 0.2, 0.4], "track_id": "webcam-person"}]

        class API:
            server_url = "http://127.0.0.1:8001/"

            def token(self, credentials):
                return "token"

            def state(self, token):
                return {"monitoring_active": True, "analysis": {"presence_seconds": 1}}

            def _request(self, *args, **kwargs):
                return {}

        queue = Queue()
        reader = Reader(0)
        ticks = itertools.count(1, 0.25)
        with patch("gateway.webcam.GatewayAPIClient", return_value=API()), \
             patch("gateway.webcam.send_detection", side_effect=WebcamError("offline")):
            with self.assertRaises(WebcamError):
                run_webcam(SimpleNamespace(server_url=API.server_url, camera_id="11111111-1111-4111-8111-111111111111",
                                           event_signing_key="test-key"),
                           allow_development_model=True, reader_factory=lambda index: reader,
                           detector_factory=Detector, queue_factory=lambda camera_id: queue,
                           sleep=lambda delay: None, clock=lambda: next(ticks))
        self.assertIsNotNone(queue.pending)
        self.assertTrue(reader.closed)
