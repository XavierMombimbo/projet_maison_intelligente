import hashlib
import uuid
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from .crypto import decrypt_capture
from .models import Camera, CaptureChiffree, Evenement, JournalAudit, Maison, TypeEvenement
from .request_signing import sign_event_payload
from .services import consume_pairing_code, create_pairing_code


def jpeg_upload(name="capture.jpg", *, size=(320, 180), content_type="image/jpeg"):
    output = BytesIO()
    Image.new("RGB", size, color=(30, 90, 65)).save(output, format="JPEG", quality=80)
    return SimpleUploadedFile(name, output.getvalue(), content_type=content_type)


class DetectionApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@example.test", "Secret!2026")
        cls.attacker = User.objects.create_user(
            "attacker", "attacker@example.test", "Secret!2026"
        )
        cls.house = Maison.objects.create(nom="Maison IA", proprietaire=cls.owner)

    def setUp(self):
        self.camera = Camera.objects.create(nom="Entrée IA", maison=self.house)
        _, code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(code)
        self.camera.refresh_from_db()
        self.camera.surveillance_active = True
        self.camera.save(update_fields=("surveillance_active",))
        self.token = credentials.access_token
        self.event_signing_key = credentials.event_signing_key

    def send_detection(
        self,
        *,
        event_id=None,
        capture=None,
        simulated=False,
        confidence=0.87,
        request_nonce=None,
        timestamp=None,
        signature=None,
    ):
        event_id = event_id or uuid.uuid4()
        capture = capture or jpeg_upload()
        request_nonce = request_nonce or uuid.uuid4()
        timestamp = timestamp or int(timezone.now().timestamp())
        capture.seek(0)
        capture_digest = hashlib.sha256(capture.read()).hexdigest()
        capture.seek(0)
        signature = signature or sign_event_payload(
            self.event_signing_key,
            method="POST",
            path=reverse("api-camera-detection"),
            camera_id=self.camera.pk,
            timestamp=timestamp,
            nonce=request_nonce,
            event_id=event_id,
            confidence=confidence,
            simulated=simulated,
            capture_digest=capture_digest,
        )
        return self.client.post(
            reverse("api-camera-detection"),
            data={
                "event_id": str(event_id),
                "confidence": str(confidence),
                "simulated": "true" if simulated else "false",
                "capture": capture,
            },
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
            HTTP_X_CAMERA_TIMESTAMP=str(timestamp),
            HTTP_X_CAMERA_NONCE=str(request_nonce),
            HTTP_X_CAMERA_SIGNATURE=signature,
        )

    def test_detection_creates_event_and_aes_gcm_encrypted_capture(self):
        response = self.send_detection()

        self.assertEqual(response.status_code, 201)
        event = Evenement.objects.get()
        capture = CaptureChiffree.objects.get(evenement=event)
        self.assertEqual(event.type, TypeEvenement.PERSONNE_DETECTEE)
        self.assertFalse(event.simule)
        self.assertEqual(capture.type_mime, "image/jpeg")
        self.assertEqual(len(bytes(capture.nonce)), 12)

        plaintext = decrypt_capture(
            bytes(capture.contenu_chiffre), bytes(capture.nonce), event.pk
        )
        self.assertNotEqual(bytes(capture.contenu_chiffre), plaintext)
        with Image.open(BytesIO(plaintext)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertLessEqual(image.width, 1280)
            self.assertLessEqual(image.height, 720)

    def test_detection_publishes_realtime_alert_after_commit(self):
        with patch("homes.realtime.publish_event") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.send_detection()

        self.assertEqual(response.status_code, 201)
        publish.assert_called_once_with(Evenement.objects.get().pk)

    def test_simulation_is_clearly_recorded_as_simulation(self):
        response = self.send_detection(simulated=True, confidence=1.0)

        self.assertEqual(response.status_code, 201)
        event = Evenement.objects.get()
        self.assertTrue(event.simule)
        self.assertEqual(event.type, TypeEvenement.SIMULATION)

    def test_detection_is_rejected_when_monitoring_is_disabled(self):
        self.camera.surveillance_active = False
        self.camera.save(update_fields=("surveillance_active",))

        response = self.send_detection()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_invalid_mime_type_is_rejected(self):
        response = self.send_detection(capture=jpeg_upload(content_type="text/plain"))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_invalid_image_content_is_rejected(self):
        fake = SimpleUploadedFile("capture.jpg", b"not-an-image", content_type="image/jpeg")

        response = self.send_detection(capture=fake)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_oversized_capture_is_rejected(self):
        oversized = SimpleUploadedFile(
            "capture.jpg", b"x" * (settings.MAX_CAPTURE_BYTES + 1), content_type="image/jpeg"
        )

        response = self.send_detection(capture=oversized)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_excessive_dimensions_are_rejected(self):
        response = self.send_detection(capture=jpeg_upload(size=(5000, 1)))

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_replayed_event_identifier_is_rejected(self):
        event_id = uuid.uuid4()
        first = self.send_detection(event_id=event_id)
        replay = self.send_detection(event_id=event_id)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(Evenement.objects.count(), 1)

    def test_incorrect_hmac_signature_is_rejected(self):
        response = self.send_detection(signature="0" * 64)

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Evenement.objects.exists())
        self.assertTrue(
            JournalAudit.objects.filter(action="camera.detection.invalid_signature").exists()
        )

    def test_expired_signed_request_is_rejected(self):
        stale_timestamp = int((timezone.now() - timedelta(minutes=5)).timestamp())

        response = self.send_detection(timestamp=stale_timestamp)

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Evenement.objects.exists())

    def test_signed_request_nonce_cannot_be_reused(self):
        request_nonce = uuid.uuid4()
        first = self.send_detection(request_nonce=request_nonce)
        replay = self.send_detection(request_nonce=request_nonce)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(Evenement.objects.count(), 1)

    def test_capture_requires_object_authorization_and_is_not_cached(self):
        self.send_detection()
        event = Evenement.objects.get()
        self.client.force_login(self.owner)

        allowed = self.client.get(reverse("event-capture", kwargs={"pk": event.pk}))

        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.headers["Content-Type"], "image/jpeg")
        self.assertIn("no-store", allowed.headers["Cache-Control"])

        self.client.force_login(self.attacker)
        denied = self.client.get(reverse("event-capture", kwargs={"pk": event.pk}))
        self.assertEqual(denied.status_code, 404)

    def test_aes_gcm_associated_event_id_prevents_capture_substitution(self):
        self.send_detection()
        event = Evenement.objects.get()
        capture = event.capture

        with self.assertRaises(InvalidTag):
            decrypt_capture(
                bytes(capture.contenu_chiffre), bytes(capture.nonce), uuid.uuid4()
            )


class CameraMonitorPageTests(TestCase):
    def test_page_requires_explicit_click_and_exposes_demo_fallback(self):
        response = self.client.get(reverse("camera-monitor"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La webcam reste désactivée jusqu’à votre clic")
        self.assertContains(response, "Autoriser et démarrer la webcam")
        self.assertContains(response, "Simuler une détection (DÉMO)")
        self.assertNotContains(response, "<video autoplay")

    def test_authenticated_camera_page_receives_global_alerts(self):
        user = User.objects.create_user(
            "monitor-alert-user", "monitor-alert@example.test", "Secret!2026"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("camera-monitor"))

        self.assertContains(response, 'id="global-alert-runtime"')
        self.assertContains(response, 'id="sound-toggle"')
        self.assertContains(response, 'js/alerts.js')
