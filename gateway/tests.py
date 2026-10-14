import base64
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from .client import GatewayAPIClient, GatewayAPIError, local_proxy_headers, validate_server_url
from .biometrics import (
    BiometricCacheExpired,
    BiometricCacheStore,
    synchronize_biometric_profiles,
)
from .rtsp import RTSPReader, authenticated_rtsp_url
from .runner import reconnect_delay, run_gateway


class FakeCapture:
    def __init__(self, url, backend, params):
        self.url = url
        self.params = params
        self.released = False

    def isOpened(self):
        return True

    def read(self):
        return True, SimpleNamespace(shape=(720, 1280, 3))

    def get(self, prop):
        return sum(ord(char) << (8 * index) for index, char in enumerate("H264"))

    def release(self):
        self.released = True


class FakeCV2:
    CAP_FFMPEG = 1900
    CAP_PROP_OPEN_TIMEOUT_MSEC = 53
    CAP_PROP_READ_TIMEOUT_MSEC = 54
    CAP_PROP_FOURCC = 6
    VideoCapture = FakeCapture

    @staticmethod
    def setLogLevel(level):
        return None


class FakeGatewayAPI:
    def __init__(self, active):
        self.active = active
        self.heartbeats = []

    def token(self, credentials):
        return "camera-token"

    def state(self, token):
        return {"monitoring_active": self.active}

    def source(self, token):
        return {"endpoint": "caméra test"}

    def heartbeat(self, token, *, monitoring_active=None, schedule_version=None):
        self.heartbeats.append(monitoring_active)
        return {"monitoring_active": monitoring_active}


class FakeReader:
    def __init__(self, source):
        self.closed = False

    def open(self):
        return None

    def read(self, *, require_h264=False):
        return object(), SimpleNamespace(width=640, height=480, codec="H264")

    def close(self):
        self.closed = True


class GatewayTests(TestCase):
    def test_only_loopback_uses_internal_proxy_header(self):
        self.assertEqual(local_proxy_headers("http://127.0.0.1:8001/"),
                         {"X-Forwarded-Proto": "https"})
        self.assertEqual(local_proxy_headers("https://sentinelle.example/"), {})
        self.assertEqual(local_proxy_headers("http://127.0.0.1.example/"), {})

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self):
                return b"{}"

        with patch("gateway.client.urlopen", return_value=Response()) as send:
            GatewayAPIClient("http://127.0.0.1:8001")._request("health/")
        self.assertEqual(send.call_args.args[0].get_header("X-forwarded-proto"), "https")

    def test_server_requires_https_except_localhost(self):
        self.assertEqual(validate_server_url("http://127.0.0.1:8001"), "http://127.0.0.1:8001/")
        self.assertEqual(validate_server_url("https://sentinelle.example"), "https://sentinelle.example/")
        with self.assertRaises(ValueError):
            validate_server_url("http://sentinelle.example")

    def test_credentials_are_only_inserted_in_internal_rtsp_url(self):
        result = authenticated_rtsp_url(
            "rtsp://192.0.2.50:554/live?profile=main", "cam user", "p@ss/word"
        )
        self.assertEqual(
            result,
            "rtsp://cam%20user:p%40ss%2Fword@192.0.2.50:554/live?profile=main",
        )

    def test_reader_uses_bounded_open_and_read_timeouts(self):
        reader = RTSPReader(
            {"url": "rtsp://192.0.2.50/live", "username": "u", "password": "p"},
            open_timeout_ms=7000,
            read_timeout_ms=4000,
            cv2=FakeCV2,
        )
        reader.open()
        frame, info = reader.read()
        self.assertEqual(info.width, 1280)
        self.assertEqual(info.height, 720)
        self.assertEqual(info.codec, "H264")
        self.assertEqual(reader.capture.params, [53, 7000, 54, 4000])
        self.assertEqual(reader.source["url"], "rtsp://192.0.2.50/live")
        reader.close()

    def test_reconnect_delay_is_exponential_and_capped(self):
        values = [reconnect_delay(index, maximum=30, jitter=0) for index in range(1, 8)]
        self.assertEqual(values, [1, 2, 4, 8, 16, 30, 30])

    def test_gateway_acknowledges_disabled_monitoring(self):
        api = FakeGatewayAPI(active=False)
        credentials = SimpleNamespace(server_url="https://sentinelle.example")

        with patch("gateway.runner.GatewayAPIClient", return_value=api):
            with self.assertRaises(GatewayAPIError):
                run_gateway(credentials, once=True, biometric_sync=lambda api, token: None)

        self.assertEqual(api.heartbeats, [False])

    def test_gateway_acknowledges_active_monitoring_after_first_frame(self):
        api = FakeGatewayAPI(active=True)
        credentials = SimpleNamespace(server_url="https://sentinelle.example")

        with patch("gateway.runner.GatewayAPIClient", return_value=api):
            result = run_gateway(
                credentials,
                once=True,
                output=lambda message: None,
                reader_factory=FakeReader,
                biometric_sync=lambda api, token: None,
            )

        self.assertEqual(result, 0)
        self.assertEqual(api.heartbeats, [True])


class FakeBiometricAPI:
    def __init__(self, manifest):
        self.manifest = manifest
        self.acknowledged = []

    def biometric_profiles(self, token):
        return self.manifest

    def acknowledge_biometric_purges(self, token, purges):
        self.acknowledged.extend(purges)
        return {"confirmed": purges}


class BiometricCacheTests(TestCase):
    def _manifest(self, *, valid_until, profiles=None, revoked=None):
        return {
            "generation": "generation-test",
            "valid_until": valid_until.isoformat(),
            "cache_ttl_seconds": 300,
            "profiles": profiles or [],
            "revoked": revoked or [],
        }

    def test_cache_is_protected_purged_and_acknowledged_after_write(self):
        now = datetime.now(timezone.utc)
        profile_id = "0a80ebf0-8c42-4d6a-9508-149ac724c5cb"
        revoked_id = "fdd2eb8f-c74e-4dd7-9688-4215503ce6fd"
        manifest = self._manifest(
            valid_until=now + timedelta(minutes=5),
            profiles=[
                {
                    "profile_id": profile_id,
                    "version": 2,
                    "format": "test-vector-v1",
                    "template": base64.b64encode(b"face-vector").decode("ascii"),
                }
            ],
            revoked=[{"profile_id": revoked_id, "version": 4}],
        )
        api = FakeBiometricAPI(manifest)
        with tempfile.TemporaryDirectory() as directory:
            store = BiometricCacheStore(Path(directory) / "cache.bin")
            with (
                patch(
                    "gateway.biometrics.protect_local_data",
                    side_effect=lambda value: b"protected:" + value,
                ),
                patch(
                    "gateway.biometrics.unprotect_local_data",
                    side_effect=lambda value: value.removeprefix(b"protected:"),
                ),
            ):
                synchronize_biometric_profiles(api, "token", store=store)
                cached = store.profiles_for_comparison(now=now)

            self.assertNotIn(b"face-vector", store.path.read_bytes())
            self.assertEqual(cached[0]["template"], b"face-vector")
            self.assertEqual(
                api.acknowledged,
                [{"profile_id": revoked_id, "version": 4}],
            )

    def test_expired_cache_forbids_comparison(self):
        now = datetime.now(timezone.utc)
        manifest = self._manifest(valid_until=now + timedelta(seconds=30))
        with tempfile.TemporaryDirectory() as directory:
            store = BiometricCacheStore(Path(directory) / "cache.bin")
            with (
                patch(
                    "gateway.biometrics.protect_local_data",
                    side_effect=lambda value: value,
                ),
                patch(
                    "gateway.biometrics.unprotect_local_data",
                    side_effect=lambda value: value,
                ),
            ):
                store.apply_manifest(manifest, now=now)
                with self.assertRaises(BiometricCacheExpired):
                    store.profiles_for_comparison(now=now + timedelta(seconds=31))
