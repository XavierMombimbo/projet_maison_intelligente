"""Synthetic fixtures only: no webcam, real profiles or model downloads."""
import json
import uuid
from unittest.mock import patch

import numpy as np
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gateway.facial import ARCFACE_TEMPLATE_FORMAT, FaceQualityError
from . import tests_detection as fixtures
from .alerting import decider_alerte
from .biometrics import revoke_biometric_profile
from .facial_enrollment import EnrollmentBusy, EnrollmentUnavailable
from .models import Evenement, JournalAudit, Maison, MembreMaison, ProfilBiometrique, StatutInvitation
from .outbox import dispatch_outbox_entry
from notifications.models import PushDelivery


@override_settings(BIOMETRIC_WEB_RECOGNITION_ENABLED=True, BIOMETRIC_FACE_MODEL_ROOT="/fixture-model")
class BrowserFaceTests(TestCase):
    setUpTestData = classmethod(fixtures.DetectionApiTests.setUpTestData.__func__)
    send_detection = fixtures.DetectionApiTests.send_detection

    def setUp(self):
        cache.clear()
        fixtures.DetectionApiTests.setUp(self)
        self.gateway_token = self.token
        self.client.force_login(self.owner)
        response = self.client.get(reverse("camera-monitor"))
        self.context = response.context["browser_camera_context"]
        grant = self.client.get(reverse("browser-camera-context"), {"camera": str(self.camera.pk)},
            HTTP_X_SENTINELLE_CAMERA_CONTEXT=self.context)
        self.assertEqual(grant.status_code, 200)
        self.token = grant.json()["access_token"]
        self.client.defaults.update(HTTP_X_SENTINELLE_CAMERA_CONTEXT=self.context, HTTP_SEC_FETCH_SITE="same-origin")
        self.member, _ = MembreMaison.objects.get_or_create(maison=self.house, utilisateur=self.owner,
            defaults={"statut": StatutInvitation.ACCEPTEE})
        self.profile = ProfilBiometrique.objects.create(maison=self.house, utilisateur=self.owner, libelle="Fixture")
        self.vector = np.eye(1, 512, 0, dtype="<f4")[0].tobytes()
        self.profile.set_template(self.vector, ARCFACE_TEMPLATE_FORMAT)
        p = patch("homes.browser_face.embedding_from_frame", return_value=self.vector)
        self.extract = p.start()
        self.addCleanup(p.stop)

    def submit(self, **kwargs):
        return self.send_detection(contract_version=2, **kwargs)

    def test_known_browser_capture_is_silent_and_result_contains_no_identity(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["face_verification"],
                         {"state": "recognized", "reason": "matched", "source": "server"})
        self.assertFalse(response.json()["notification_sent"])
        event = Evenement.objects.get()
        self.assertTrue(event.notification_supprimee)
        self.assertEqual(event.version_contrat, 2)  # original signed wire contract
        self.assertEqual(event.metadonnees["identite_locale"]["statuts"], ["recognized"])
        self.assertNotIn(str(self.profile.pk), json.dumps(event.metadonnees))
        self.assertNotIn(str(self.profile.pk), response.content.decode())
        self.assertNotIn(str(self.profile.pk), str(list(JournalAudit.objects.values("metadonnees"))))
        self.assertEqual(self.extract.call_args.kwargs["person_bbox"], [0.1, 0.1, 0.4, 0.7])

    def test_unknown_remains_notifiable(self):
        self.extract.return_value = np.eye(1, 512, 1, dtype="<f4")[0].tobytes()
        response = self.submit()
        self.assertEqual(response.json()["face_verification"]["state"], "unknown")
        self.assertTrue(response.json()["notification_sent"])

    def test_silent_browser_event_outbox_never_broadcasts_or_pushes_even_on_retry(self):
        self.submit()
        event = Evenement.objects.get()
        with patch("homes.realtime.get_channel_layer") as channel:
            dispatch_outbox_entry(event.boite_envoi.pk)
            dispatch_outbox_entry(event.boite_envoi.pk)
        channel.assert_not_called()
        self.assertFalse(PushDelivery.objects.filter(event=event).exists())
        detail = self.client.get(reverse("event-detail", kwargs={"pk": event.pk}))
        self.assertContains(detail, "Présence reconnue · notification silencieuse")
        self.assertNotContains(detail, "alerte principale a expiré")
        self.assertNotContains(detail, "Confirmer l’intrusion")

    def test_unknown_and_recognized_line_crossing_still_broadcast(self):
        from .realtime import publish_event
        from .models import NiveauAlerte
        from unittest.mock import AsyncMock
        for state, rule_type in (("unknown", "presence_prolonged"), ("recognized", "line_crossing")):
            with self.subTest(state=state, rule=rule_type):
                decision = decider_alerte(self.camera, [{"label": "person", "confidence": .9,
                    "face_status": state}], {"type": rule_type})
                event = Evenement.objects.create(camera=self.camera, maison=self.house,
                    client_event_id=uuid.uuid4(), type="person", confiance_ia=.9,
                    priorite_alerte=decision.priorite, notification_supprimee=decision.notification_supprimee)
                with patch("homes.realtime.get_channel_layer") as channel:
                    channel.return_value.group_send = AsyncMock()
                    publish_event(event.pk)
                payload = channel.return_value.group_send.call_args.args[1]["payload"]
                self.assertFalse(payload["notification_suppressed"])
                if rule_type == "line_crossing":
                    self.assertEqual(payload["alert_priority"], NiveauAlerte.URGENTE)

    def test_quality_busy_and_model_failure_are_not_unknown(self):
        for error in (FaceQualityError(), EnrollmentBusy(), EnrollmentUnavailable()):
            with self.subTest(error=type(error).__name__):
                self.extract.side_effect = error
                response = self.submit()
                self.assertEqual(response.status_code, 201)
                self.assertEqual(response.json()["face_verification"]["state"], "unavailable")
                self.assertTrue(response.json()["notification_sent"])

    def test_other_house_profile_is_never_compared(self):
        other_house = Maison.objects.create(nom="Other", proprietaire=self.owner)
        self.profile.maison = other_house
        self.profile.save(update_fields=["maison"])
        response = self.submit()
        self.assertEqual(response.json()["face_verification"]["reason"], "no_profiles")
        self.extract.assert_not_called()

    def test_departed_member_has_no_eligible_profile(self):
        self.member.delete()
        response = self.submit()
        self.assertEqual(response.json()["face_verification"]["reason"], "no_profiles")
        self.extract.assert_not_called()

    def test_revocation_during_inference_prevents_silencing(self):
        def revoke(*args, **kwargs):
            revoke_biometric_profile(self.profile)
            return self.vector
        self.extract.side_effect = revoke
        response = self.submit()
        self.assertEqual(response.json()["face_verification"]["reason"], "profile_changed")
        self.assertTrue(response.json()["notification_sent"])

    def test_membership_removed_during_inference_prevents_silencing(self):
        def leave(*args, **kwargs):
            self.member.delete()
            return self.vector
        self.extract.side_effect = leave
        response = self.submit()
        self.assertEqual(response.json()["face_verification"]["reason"], "profile_changed")
        self.assertTrue(response.json()["notification_sent"])

    def test_camera_revocation_during_inference_prevents_event(self):
        def revoke(*args, **kwargs):
            type(self.camera).objects.filter(pk=self.camera.pk).update(date_revocation=timezone.now())
            return self.vector
        self.extract.side_effect = revoke
        self.assertEqual(self.submit().status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_multiple_people_are_never_silenced_from_one_face(self):
        people = [{"label": "person", "confidence": .9, "bbox": [0, 0, .4, 1]},
                  {"label": "person", "confidence": .9, "bbox": [.5, 0, .4, 1]}]
        response = self.submit(objects=people)
        self.assertEqual(response.json()["face_verification"]["reason"], "multiple_people")
        self.assertTrue(response.json()["notification_sent"])
        self.extract.assert_not_called()

    def test_browser_cannot_supply_its_own_recognition(self):
        response = self.send_detection(contract_version=3, objects=[{
            "label": "person", "confidence": .9, "bbox": [0, 0, 1, 1], "face_status": "recognized"}])
        self.assertEqual(response.status_code, 400)
        self.extract.assert_not_called()
        self.assertFalse(Evenement.objects.exists())

    def test_invalid_signature_and_changed_session_cannot_start_comparison(self):
        self.assertEqual(self.submit(signature="bad").status_code, 401)
        self.client.logout()
        self.assertEqual(self.submit().status_code, 401)
        self.extract.assert_not_called()

    def test_retry_keeps_original_signature_fingerprint_and_single_comparison(self):
        event_id, observed_at = uuid.uuid4(), timezone.now()
        first = self.submit(event_id=event_id, observed_at=observed_at)
        retry = self.submit(event_id=event_id, observed_at=observed_at)
        self.assertEqual(first.status_code, 201)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertTrue(retry.json()["deduplicated"])
        self.assertEqual(retry.json()["face_verification"], first.json()["face_verification"])
        self.extract.assert_called_once()
        self.assertEqual(Evenement.objects.count(), 1)

    @override_settings(BIOMETRIC_WEB_RECOGNITION_ENABLED=False)
    def test_disabled_feature_does_not_load_model(self):
        response = self.submit()
        self.assertEqual(response.json()["face_verification"]["reason"], "disabled")
        self.extract.assert_not_called()

    def test_gateway_does_not_run_server_inference(self):
        self.client.defaults.clear()
        self.token = self.gateway_token
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.json()["face_verification"])
        self.extract.assert_not_called()

    def test_known_face_does_not_silence_line_crossing_or_unverified_second_person(self):
        known = {"label": "person", "confidence": .9, "face_status": "recognized"}
        crossing = decider_alerte(self.camera, [known], {"type": "line_crossing"})
        mixed = decider_alerte(self.camera, [known, {"label": "person", "confidence": .9}], {})
        self.assertFalse(crossing.notification_supprimee)
        self.assertFalse(mixed.notification_supprimee)

    def test_monitor_explains_server_processing_and_last_capture_result(self):
        response = self.client.get(reverse("camera-monitor"))
        self.assertContains(response, "Reconnaissance faciale activée")
        self.assertContains(response, "comparée sur le serveur")
        self.assertContains(response, 'id="face-result"')
