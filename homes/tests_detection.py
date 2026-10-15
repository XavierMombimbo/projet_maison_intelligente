import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone as datetime_timezone
from io import BytesIO, StringIO
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import requests
from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.core.cache import cache
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import User
from gateway.client import GatewayAPIError
from gateway.event_queue import EncryptedEventQueue
from gateway.webcam import deliver_oldest
from .crypto import decrypt_capture
from .models import (
    Camera,
    CaptureChiffree,
    Evenement,
    EvenementBoiteEnvoi,
    JournalAudit,
    Maison,
    NiveauAlerte,
    ObjetDetecte,
    StatutBoiteEnvoi,
    TypeEvenement,
)
from .request_signing import event_signature_payload_v2, sign_event_payload
from .services import consume_pairing_code, create_pairing_code
from .throttling import RateLimitResult


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
        contract_version=1,
        observed_at=None,
        model_name="yolo11n",
        model_version="320@test",
        objects=None,
        rule_context=None,
        form_overrides=None,
    ):
        event_id = event_id or uuid.uuid4()
        capture = capture or jpeg_upload()
        request_nonce = request_nonce or uuid.uuid4()
        timestamp = timestamp or int(timezone.now().timestamp())
        capture.seek(0)
        capture_digest = hashlib.sha256(capture.read()).hexdigest()
        capture.seek(0)
        observed_at = observed_at or timezone.now()
        objects = objects or [
            {"label": "person", "confidence": confidence, "bbox": [0.1, 0.1, 0.4, 0.7]}
        ]
        signature_values = {
            "method": "POST",
            "path": reverse("api-camera-detection"),
            "camera_id": self.camera.pk,
            "timestamp": timestamp,
            "nonce": request_nonce,
            "event_id": event_id,
            "simulated": simulated,
            "capture_digest": capture_digest,
        }
        if contract_version in (2, 3):
            signature_values.update(
                {
                    "contract_version": contract_version,
                    "observed_at": observed_at,
                    "model_name": model_name,
                    "model_version": model_version,
                    "objects": objects,
                    "rule_context": rule_context,
                    "capture_type": capture.content_type,
                }
            )
        else:
            signature_values["confidence"] = confidence
        signature = signature or sign_event_payload(self.event_signing_key, **signature_values)
        data = {
            "event_id": str(event_id),
            "confidence": str(confidence),
            "simulated": "true" if simulated else "false",
            "capture": capture,
        }
        if contract_version in (2, 3):
            data.update(
                {
                    "contract_version": str(contract_version),
                    "observed_at": observed_at.isoformat(),
                    "model_name": model_name,
                    "model_version": model_version,
                    "objects": json.dumps(objects),
                }
            )
            data.pop("confidence")
            if rule_context is not None:
                data["rule_context"] = json.dumps(rule_context)
        data.update(form_overrides or {})
        return self.client.post(
            reverse("api-camera-detection"),
            data=data,
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
        self.assertEqual(event.version_contrat, 1)
        self.assertFalse(ObjetDetecte.objects.exists())
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

    def test_v2_stores_multiple_objects_model_and_distinct_timestamps(self):
        observed_at = timezone.now() - timedelta(seconds=12)
        objects = [
            {"label": "person", "confidence": 0.91, "bbox": [0.1, 0.1, 0.3, 0.8], "track_id": "p-1"},
            {"label": "dog", "confidence": 0.82, "bbox": [0.55, 0.5, 0.3, 0.4]},
        ]

        response = self.send_detection(
            contract_version=2,
            observed_at=observed_at,
            model_name="yolo11n",
            model_version="320@18eac4f9d291",
            objects=objects,
        )

        self.assertEqual(response.status_code, 201, response.content)
        event = Evenement.objects.get()
        self.assertEqual(event.version_contrat, 2)
        self.assertEqual(event.type, TypeEvenement.OBJETS_DETECTES)
        self.assertEqual(event.nom_modele, "yolo11n")
        self.assertEqual(event.version_modele, "320@18eac4f9d291")
        self.assertEqual(event.horodatage_observation, observed_at)
        self.assertGreater(event.horodatage, event.horodatage_observation)
        self.assertEqual(event.objets.count(), 2)
        self.assertEqual(set(event.objets.values_list("classe", flat=True)), {"person", "dog"})
        self.assertEqual(event.objets.get(classe="person").identifiant_suivi, "p-1")
        self.assertEqual(event.confiance_ia, 0.91)
        self.assertEqual(response.json()["contract_version"], 2)
        self.assertIn("observed_at", response.json())
        self.assertIn("received_at", response.json())

    def test_v3_marks_known_and_unknown_people_without_a_profile_identifier(self):
        known = [{
            "label": "person", "confidence": 0.91, "bbox": [0.1, 0.1, 0.3, 0.8],
            "track_id": "p-known", "face_status": "recognized",
        }]
        known_response = self.send_detection(contract_version=3, objects=known)
        self.assertEqual(known_response.status_code, 201, known_response.content)
        known_event = Evenement.objects.get(pk=known_response.json()["event_id"])
        self.assertEqual(known_event.priorite_alerte, NiveauAlerte.NORMALE)
        self.assertEqual(known_event.metadonnees["identite_locale"]["statuts"], ["recognized"])
        self.assertNotIn("profile", str(known_event.metadonnees).lower())
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("event-detail", kwargs={"pk": known_event.pk}))
        self.assertContains(detail, "Profil volontaire reconnu")

        unknown = [{
            "label": "person", "confidence": 0.91, "bbox": [0.1, 0.1, 0.3, 0.8],
            "track_id": "p-unknown", "face_status": "unknown",
        }]
        unknown_response = self.send_detection(contract_version=3, objects=unknown)
        self.assertEqual(unknown_response.status_code, 201, unknown_response.content)
        unknown_event = Evenement.objects.get(pk=unknown_response.json()["event_id"])
        self.assertEqual(unknown_event.priorite_alerte, NiveauAlerte.ELEVEE)
        self.assertIn("non reconnue", unknown_event.raison_priorite)

    def test_v3_face_status_is_rejected_for_v2_or_a_non_person(self):
        face_status = [{
            "label": "person", "confidence": 0.91, "bbox": [0.1, 0.1, 0.3, 0.8],
            "face_status": "recognized",
        }]
        rejected_version = self.send_detection(contract_version=2, objects=face_status)
        self.assertEqual(rejected_version.status_code, 400)

        non_person = [{
            "label": "dog", "confidence": 0.91, "bbox": [0.1, 0.1, 0.3, 0.8],
            "face_status": "unknown",
        }]
        rejected_label = self.send_detection(contract_version=3, objects=non_person)
        self.assertEqual(rejected_label.status_code, 400)

    def test_stale_v2_observation_is_history_only_without_push(self):
        observed_at = timezone.now() - timedelta(minutes=2)
        response = self.send_detection(contract_version=2, observed_at=observed_at)
        self.assertEqual(response.status_code, 201, response.content)
        event = Evenement.objects.get()
        self.assertEqual(event.horodatage_observation, observed_at)
        self.assertTrue(event.notification_supprimee)
        self.assertTrue(event.metadonnees["alerte"]["retardee"])
        self.assertFalse(EvenementBoiteEnvoi.objects.exists())
        self.assertFalse(response.json()["notification_sent"])

    def test_stale_event_does_not_suppress_next_fresh_alert(self):
        rule_context = {
            "id": "presence-zone", "version": 1, "type": "presence_prolonged",
            "duration_seconds": 2, "zone": {"x": 0, "y": 0, "width": 1, "height": 1},
            "track_ids": ["webcam-person"],
        }
        objects = [{"label": "person", "confidence": 0.9,
                    "bbox": [0.1, 0.1, 0.4, 0.7], "track_id": "webcam-person"}]
        old = self.send_detection(contract_version=2,
                                  observed_at=timezone.now() - timedelta(minutes=2),
                                  objects=objects, rule_context=rule_context)
        fresh = self.send_detection(contract_version=2, observed_at=timezone.now(),
                                    objects=objects, rule_context=rule_context)
        self.assertEqual(old.status_code, 201, old.content)
        self.assertEqual(fresh.status_code, 201, fresh.content)
        self.assertFalse(fresh.json()["deduplicated"])
        self.assertTrue(fresh.json()["notification_sent"])
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 1)

    def test_v2_stores_signed_explainable_rule_context(self):
        rule_context = {
            "id": "presence-zone",
            "version": 1,
            "type": "presence_prolonged",
            "duration_seconds": 2.4,
            "zone": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "line": None,
            "direction": None,
            "track_ids": ["track-1"],
        }

        response = self.send_detection(
            contract_version=2,
            rule_context=rule_context,
            objects=[
                {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.4, 0.7], "track_id": "track-1"}
            ],
        )

        self.assertEqual(response.status_code, 201, response.content)
        event = Evenement.objects.get()
        self.assertEqual(event.metadonnees["regle"], rule_context)
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("event-detail", kwargs={"pk": event.pk}))
        self.assertContains(detail, "presence-zone")
        self.assertContains(detail, "2,4 s")

    def test_v2_accepts_only_the_configured_forbidden_crossing(self):
        self.camera.ligne_analyse = {"x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0}
        self.camera.sens_franchissement_interdit = "negative_to_positive"
        self.camera.save(update_fields=("ligne_analyse", "sens_franchissement_interdit"))
        base_rule = {
            "id": "line-crossing",
            "version": 1,
            "type": "line_crossing",
            "duration_seconds": 1.2,
            "zone": self.camera.zone_analyse,
            "line": self.camera.ligne_analyse,
            "direction": "negative_to_positive",
            "track_ids": ["track-1"],
        }
        objects = [
            {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.3, 0.8], "track_id": "track-1"}
        ]

        accepted = self.send_detection(
            contract_version=2, objects=objects, rule_context=base_rule
        )

        self.assertEqual(accepted.status_code, 201, accepted.content)

        self.camera.sens_franchissement_interdit = "positive_to_negative"
        self.camera.save(update_fields=("sens_franchissement_interdit",))
        rejected = self.send_detection(
            contract_version=2,
            objects=objects,
            rule_context={**base_rule, "direction": "negative_to_positive"},
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertContains(rejected, "autorisé", status_code=400)

    def test_repeated_animal_alerts_are_grouped_but_urgent_person_is_sent(self):
        self.camera.ligne_analyse = {"x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0}
        self.camera.fenetre_regroupement_secondes = 60
        self.camera.save(update_fields=("ligne_analyse", "fenetre_regroupement_secondes"))
        rule_context = {
            "id": "line-crossing",
            "version": 1,
            "type": "line_crossing",
            "duration_seconds": 1.2,
            "zone": self.camera.zone_analyse,
            "line": self.camera.ligne_analyse,
            "direction": "negative_to_positive",
            "track_ids": ["track-1"],
        }
        dog = [
            {"label": "dog", "confidence": 0.8, "bbox": [0.1, 0.1, 0.3, 0.4], "track_id": "track-1"}
        ]
        person = [
            {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.3, 0.8], "track_id": "track-1"}
        ]

        first = self.send_detection(contract_version=2, objects=dog, rule_context=rule_context)
        repeated = self.send_detection(contract_version=2, objects=dog, rule_context=rule_context)
        urgent = self.send_detection(contract_version=2, objects=person, rule_context=rule_context)

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(repeated.status_code, 201, repeated.content)
        self.assertEqual(urgent.status_code, 201, urgent.content)
        principal = Evenement.objects.get(pk=first.json()["event_id"])
        grouped = Evenement.objects.get(pk=repeated.json()["event_id"])
        urgent_event = Evenement.objects.get(pk=urgent.json()["event_id"])
        self.assertEqual(principal.priorite_alerte, NiveauAlerte.NORMALE)
        self.assertTrue(grouped.notification_supprimee)
        self.assertEqual(grouped.evenement_principal, principal)
        self.assertFalse(repeated.json()["notification_sent"])
        self.assertEqual(urgent_event.priorite_alerte, NiveauAlerte.URGENTE)
        self.assertFalse(urgent_event.notification_supprimee)
        self.assertTrue(urgent.json()["notification_sent"])
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 2)

        self.client.force_login(self.owner)
        grouped_detail = self.client.get(
            reverse("event-detail", kwargs={"pk": grouped.pk})
        )
        self.assertContains(grouped_detail, "aucune notification supplémentaire")
        urgent_detail = self.client.get(
            reverse("event-detail", kwargs={"pk": urgent_event.pk})
        )
        self.assertContains(urgent_detail, "Urgente")

    def test_grouping_window_rolls_from_the_latest_repetition(self):
        self.camera.ligne_analyse = {"x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0}
        self.camera.fenetre_regroupement_secondes = 30
        self.camera.save(update_fields=("ligne_analyse", "fenetre_regroupement_secondes"))
        rule_context = {
            "id": "line-crossing",
            "version": 1,
            "type": "line_crossing",
            "duration_seconds": 1.2,
            "zone": self.camera.zone_analyse,
            "line": self.camera.ligne_analyse,
            "direction": "negative_to_positive",
            "track_ids": ["track-1"],
        }
        objects = [
            {
                "label": "person",
                "confidence": 0.9,
                "bbox": [0.1, 0.1, 0.3, 0.8],
                "track_id": "track-1",
            }
        ]

        first = self.send_detection(
            contract_version=2, objects=objects, rule_context=rule_context
        )
        principal = Evenement.objects.get(pk=first.json()["event_id"])
        second = self.send_detection(
            contract_version=2, objects=objects, rule_context=rule_context
        )
        repeated = Evenement.objects.get(pk=second.json()["event_id"])
        self.assertEqual(repeated.evenement_principal, principal)
        Evenement.objects.filter(pk=principal.pk).update(
            horodatage=timezone.now() - timedelta(seconds=40)
        )
        Evenement.objects.filter(pk=repeated.pk).update(
            horodatage=timezone.now() - timedelta(seconds=20)
        )

        third = self.send_detection(
            contract_version=2, objects=objects, rule_context=rule_context
        )
        latest = Evenement.objects.get(pk=third.json()["event_id"])

        self.assertTrue(latest.notification_supprimee)
        self.assertEqual(latest.evenement_principal, principal)
        self.assertFalse(third.json()["notification_sent"])
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 1)

    def test_v2_rejects_tampered_rule_context(self):
        rule_context = {
            "id": "line-crossing",
            "version": 1,
            "type": "line_crossing",
            "duration_seconds": 1.2,
            "zone": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "line": {"x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0},
            "direction": "negative_to_positive",
            "track_ids": ["track-1"],
        }
        tampered = {**rule_context, "direction": "positive_to_negative"}

        response = self.send_detection(
            contract_version=2,
            rule_context=rule_context,
            form_overrides={"rule_context": json.dumps(tampered)},
        )

        self.assertEqual(response.status_code, 401)
        self.assertFalse(Evenement.objects.exists())

    def test_v2_hmac_covers_model_objects_and_observation(self):
        objects = [{"label": "person", "confidence": 0.9, "bbox": [0.1, 0.1, 0.4, 0.7]}]
        for field, tampered in (
            ("model_version", "tampered"),
            ("objects", json.dumps([{"label": "dog", "confidence": 0.9, "bbox": [0.1, 0.1, 0.4, 0.7]}])),
            ("observed_at", (timezone.now() - timedelta(minutes=1)).isoformat()),
        ):
            with self.subTest(field=field):
                response = self.send_detection(
                    contract_version=2,
                    objects=objects,
                    form_overrides={field: tampered},
                )
                self.assertEqual(response.status_code, 401, response.content)
        self.assertFalse(Evenement.objects.exists())

    def test_v2_schema_rejects_unknown_fields_and_more_than_64_objects(self):
        unknown = self.send_detection(
            contract_version=2,
            form_overrides={"unexpected": "value"},
        )
        self.assertEqual(unknown.status_code, 400)

        cache.clear()
        too_many = [
            {"label": "person", "confidence": 0.8, "bbox": [0, 0, 0.1, 0.1]}
            for _ in range(65)
        ]
        oversized = self.send_detection(contract_version=2, objects=too_many)
        self.assertEqual(oversized.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_v2_cross_language_signature_vector(self):
        values = {
            "method": "POST",
            "path": "/api/camera/me/detections/",
            "camera_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
            "timestamp": 1790150400,
            "nonce": uuid.UUID("22222222-2222-4222-8222-222222222222"),
            "event_id": uuid.UUID("33333333-3333-4333-8333-333333333333"),
            "observed_at": datetime(2026, 9, 23, 8, 0, 0, 123000, tzinfo=datetime_timezone.utc),
            "model_name": "yolo11n",
            "model_version": "320@18eac4f9d291",
            "objects": [
                {"label": "person", "confidence": 0.9123456, "bbox": [0.1, 0.2, 0.3, 0.4], "track_id": "p-1"},
                {"label": "dog", "confidence": 0.8, "bbox": [0.5, 0.6, 0.2, 0.3]},
            ],
            "simulated": False,
            "capture_type": "image/jpeg",
            "capture_digest": "a" * 64,
        }
        payload = event_signature_payload_v2(**values)
        signature = sign_event_payload("vector-key-2026", contract_version=2, **values)

        self.assertEqual(
            hashlib.sha256(payload.encode()).hexdigest(),
            "bb156ca0a941542e9bd842e73c248594f654a4d9b0f22267db89b0f103fb4176",
        )
        self.assertEqual(
            signature,
            "7a908759967ee766142a238eb633d0be7649d18f899bd7c01830a8d06b167c35",
        )

    def test_v2_rule_context_cross_language_signature_vector(self):
        rule_context = {
            "id": "line-crossing",
            "version": 1,
            "type": "line_crossing",
            "duration_seconds": 1.25,
            "zone": {"x": 0.1, "y": 0.2, "width": 0.7, "height": 0.6},
            "line": {"x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0},
            "direction": "negative_to_positive",
            "track_ids": ["track-2", "track-1"],
        }
        values = {
            "method": "POST",
            "path": "/api/camera/me/detections/",
            "camera_id": uuid.UUID("11111111-1111-4111-8111-111111111111"),
            "timestamp": 1790150400,
            "nonce": uuid.UUID("22222222-2222-4222-8222-222222222222"),
            "event_id": uuid.UUID("33333333-3333-4333-8333-333333333333"),
            "observed_at": datetime(2026, 9, 23, 8, 0, 0, 123000, tzinfo=datetime_timezone.utc),
            "model_name": "yolo11n",
            "model_version": "320@test",
            "objects": [
                {"label": "person", "confidence": 0.9, "bbox": [0.1, 0.2, 0.3, 0.4], "track_id": "track-1"}
            ],
            "simulated": False,
            "capture_type": "image/jpeg",
            "capture_digest": "a" * 64,
            "rule_context": rule_context,
        }

        signature = sign_event_payload("vector-key-2026", contract_version=2, **values)

        self.assertEqual(
            signature,
            "e650616b10356be84a7b1c84bd94a2afc7351706ca6100964d539be63c6ab50c",
        )

    def test_detection_publishes_realtime_alert_after_commit(self):
        with patch("homes.realtime.publish_event") as publish:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.send_detection()

        self.assertEqual(response.status_code, 201)
        publish.assert_called_once_with(
            Evenement.objects.get().pk, message_type="alert.created"
        )

    def test_simulation_is_rejected(self):
        response = self.send_detection(simulated=True, confidence=1.0)

        self.assertEqual(response.status_code, 400)
        self.assertContains(
            response,
            "La simulation n’est plus prise en charge",
            status_code=400,
        )
        self.assertFalse(Evenement.objects.exists())

    def test_detection_is_rejected_when_monitoring_is_disabled(self):
        self.camera.surveillance_active = False
        self.camera.save(update_fields=("surveillance_active",))

        response = self.send_detection()

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_rule_alert_is_rejected_outside_monitoring_hours(self):
        self.camera.surveillance_active = False
        self.camera.save(update_fields=("surveillance_active",))
        rule_context = {
            "id": "presence-zone",
            "version": 1,
            "type": "presence_prolonged",
            "duration_seconds": 2.0,
            "zone": {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
            "line": None,
            "direction": None,
            "track_ids": ["track-1"],
        }

        response = self.send_detection(contract_version=2, rule_context=rule_context)

        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "désactivée", status_code=400)
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

    def test_retransmitted_event_identifier_is_deduplicated(self):
        event_id = uuid.uuid4()
        first = self.send_detection(event_id=event_id)
        replay = self.send_detection(event_id=event_id)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["deduplicated"])
        self.assertEqual(first.json()["event_id"], replay.json()["event_id"])
        self.assertEqual(Evenement.objects.count(), 1)
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 1)

    def test_retransmitted_v2_event_is_deduplicated(self):
        event_id = uuid.uuid4()
        observed_at = timezone.now()
        first = self.send_detection(
            event_id=event_id, contract_version=2, observed_at=observed_at
        )
        replay = self.send_detection(
            event_id=event_id, contract_version=2, observed_at=observed_at
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()["deduplicated"])
        self.assertEqual(Evenement.objects.count(), 1)

    def test_webcam_queue_retries_lost_response_without_duplicate_alert(self):
        event_id = uuid.uuid4()
        observed_at = timezone.now().isoformat()
        capture = jpeg_upload().read()
        detection = {
            "label": "person", "confidence": 0.87,
            "bbox": [0.1, 0.1, 0.4, 0.7], "track_id": "webcam-person",
        }
        rule_context = {
            "id": "presence-zone", "version": 1, "type": "presence_prolonged",
            "duration_seconds": 2,
            "zone": {"x": 0, "y": 0, "width": 1, "height": 1},
            "track_ids": ["webcam-person"],
        }
        credentials = SimpleNamespace(
            camera_id=self.camera.pk, event_signing_key=self.event_signing_key,
        )
        api = SimpleNamespace(server_url="https://sentinelle.example/")
        statuses = []
        nonces = []

        def post_to_test_server(url, *, headers, data, files, timeout):
            self.assertEqual(url, "https://sentinelle.example/api/camera/me/detections/")
            self.assertEqual(timeout, 10)
            response = self.client.post(
                reverse("api-camera-detection"),
                data={**data, "capture": SimpleUploadedFile(
                    files["capture"][0], files["capture"][1],
                    content_type=files["capture"][2],
                )},
                HTTP_AUTHORIZATION=headers["Authorization"],
                HTTP_X_CAMERA_TIMESTAMP=headers["X-Camera-Timestamp"],
                HTTP_X_CAMERA_NONCE=headers["X-Camera-Nonce"],
                HTTP_X_CAMERA_SIGNATURE=headers["X-Camera-Signature"],
            )
            statuses.append(response.status_code)
            nonces.append(headers["X-Camera-Nonce"])
            if len(statuses) == 1:
                raise requests.ConnectionError("response lost after commit")
            self.assertTrue(response.json()["deduplicated"])
            return SimpleNamespace(
                ok=200 <= response.status_code < 300,
                status_code=response.status_code,
                json=response.json,
            )

        with TemporaryDirectory() as directory:
            with patch("gateway.event_queue.protect_local_data", side_effect=lambda value: b"test:" + value), patch(
                "gateway.event_queue.unprotect_local_data", side_effect=lambda value: value.removeprefix(b"test:")
            ):
                queue = EncryptedEventQueue(self.camera.pk, path=directory)
                queue.enqueue(
                    capture=capture, detection=detection, rule_context=rule_context,
                    event_id=event_id, observed_at=observed_at,
                    model_name="yolo11n", model_version="320@test",
                )
                with patch("gateway.webcam.requests.post", side_effect=post_to_test_server):
                    with self.assertRaises(GatewayAPIError):
                        deliver_oldest(queue, api, credentials, self.token)
                    self.assertIsNotNone(queue.oldest())
                    self.assertEqual(Evenement.objects.count(), 1)
                    self.assertTrue(deliver_oldest(queue, api, credentials, self.token))

                self.assertIsNone(queue.oldest())

        self.assertEqual(statuses, [201, 200])
        self.assertNotEqual(*nonces)
        self.assertEqual(Evenement.objects.count(), 1)
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 1)
        self.assertEqual(Evenement.objects.get().client_event_id, event_id)

    def test_reused_event_identifier_with_changed_content_is_rejected(self):
        event_id = uuid.uuid4()
        first = self.send_detection(event_id=event_id, confidence=0.87)
        conflict = self.send_detection(event_id=event_id, confidence=0.44)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(Evenement.objects.count(), 1)
        self.assertTrue(
            JournalAudit.objects.filter(
                action="camera.detection.idempotency_conflict"
            ).exists()
        )

    def test_failed_realtime_delivery_stays_pending_and_command_recovers_it(self):
        with patch("homes.outbox.logger.exception"), patch(
            "homes.realtime.publish_event", side_effect=RuntimeError("transport down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.send_detection()

        self.assertEqual(response.status_code, 201)
        entry = EvenementBoiteEnvoi.objects.get()
        self.assertEqual(entry.statut, StatutBoiteEnvoi.EN_ATTENTE)
        self.assertEqual(entry.tentatives, 1)
        self.assertIn("transport down", entry.derniere_erreur)

        output = StringIO()
        with patch("homes.realtime.publish_event") as publish:
            call_command("dispatch_event_outbox", stdout=output)

        entry.refresh_from_db()
        self.assertEqual(entry.statut, StatutBoiteEnvoi.ENVOYE)
        self.assertEqual(entry.tentatives, 2)
        publish.assert_called_once_with(entry.evenement_id, message_type="alert.created")
        self.assertIn("envoyés=1 échecs=0", output.getvalue())

    def test_event_and_outbox_roll_back_together_before_commit(self):
        with patch("homes.detection.encrypt_capture", side_effect=RuntimeError("cipher failed")):
            with self.assertRaises(RuntimeError):
                self.send_detection()

        self.assertFalse(Evenement.objects.exists())
        self.assertFalse(EvenementBoiteEnvoi.objects.exists())

    def test_camera_heartbeat_recovers_pending_delivery(self):
        with patch("homes.outbox.logger.exception"), patch(
            "homes.realtime.publish_event", side_effect=RuntimeError("redis down")
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.send_detection()

        entry = EvenementBoiteEnvoi.objects.get()
        self.assertEqual(entry.statut, StatutBoiteEnvoi.EN_ATTENTE)

        with patch("homes.realtime.publish_event") as publish:
            response = self.client.post(
                reverse("api-camera-heartbeat"),
                HTTP_AUTHORIZATION=f"Bearer {self.token}",
            )

        self.assertEqual(response.status_code, 200)
        entry.refresh_from_db()
        self.assertEqual(entry.statut, StatutBoiteEnvoi.ENVOYE)
        publish.assert_called_once_with(entry.evenement_id, message_type="alert.created")

    def test_camera_heartbeat_reports_analysis_without_changing_detection_data(self):
        with patch("homes.api.record_analysis_state") as record:
            response = self.client.post(
                reverse("api-camera-heartbeat"),
                data=json.dumps({"analysis_state": "running"}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {self.token}",
            )
        self.assertEqual(response.status_code, 200)
        record.assert_called_once_with(self.camera.pk, "running")
        self.assertFalse(Evenement.objects.exists())

    def test_camera_heartbeat_rejects_unknown_analysis_state(self):
        with patch("homes.api.record_analysis_state") as record:
            response = self.client.post(
                reverse("api-camera-heartbeat"),
                data=json.dumps({"analysis_state": "always_healthy"}),
                content_type="application/json",
                HTTP_AUTHORIZATION=f"Bearer {self.token}",
            )
        self.assertEqual(response.status_code, 400)
        record.assert_not_called()

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

    def test_camera_clock_header_is_sent_on_state_and_detection_errors(self):
        state = self.client.get(
            reverse("api-camera-state"),
            HTTP_AUTHORIZATION=f"Bearer {self.token}",
        )
        expired = self.send_detection(
            timestamp=int((timezone.now() - timedelta(minutes=5)).timestamp())
        )
        with patch(
            "homes.api.check_rate_limit",
            return_value=RateLimitResult(False, 30, 20, 21),
        ):
            limited = self.send_detection()

        for response in (state, expired, limited):
            self.assertLess(
                abs(int(response["X-Sentinelle-Time"]) / 1000 - timezone.now().timestamp()),
                5,
            )
        self.assertEqual(state.status_code, 200)
        self.assertEqual(expired.status_code, 401)
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited["Retry-After"], "30")

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
    def test_page_requires_explicit_click_without_simulation(self):
        response = self.client.get(reverse("camera-monitor"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La webcam reste désactivée jusqu’à votre clic")
        self.assertContains(response, "Autoriser et démarrer la webcam")
        self.assertNotContains(response, "Simuler une détection")
        self.assertNotContains(response, "<video autoplay")

    def test_page_displays_multiclass_detection_thresholds(self):
        response = self.client.get(reverse("camera-monitor"))

        self.assertContains(response, "Personne ≥ 45 %")
        self.assertContains(response, "Chien ≥ 50 %")
        self.assertContains(response, "Chat ≥ 50 %")
        self.assertContains(response, "js/detection-policy.js")

    def test_authenticated_camera_page_receives_global_alerts(self):
        user = User.objects.create_user(
            "monitor-alert-user", "monitor-alert@example.test", "Secret!2026"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("camera-monitor"))

        self.assertContains(response, 'id="global-alert-runtime"')
        self.assertContains(response, 'id="sound-toggle"')
        self.assertContains(response, 'js/alerts.js')
