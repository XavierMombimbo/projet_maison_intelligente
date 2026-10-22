import hashlib
import json
import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from gateway.weapons import WeaponUnavailable
from . import tests_detection as fixtures
from .models import CaptureChiffree, Evenement, EvenementBoiteEnvoi, NiveauAlerte
from .realtime import _event_payload
from .request_signing import sign_event_payload
from .templatetags.presentation import event_summary
from . import tests_weapons as weapon_fixtures
from .weapon_messages import PERSON_WEAPON_TITLE


@override_settings(WEAPON_COMBINED_ENABLED=True, WEAPON_DETECTION_MODE="review",
                   WEAPON_MODEL_ROOT="/fixture", WEAPON_ACADEMIC_SITE_ENABLED=False,
                   BIOMETRIC_WEB_RECOGNITION_ENABLED=False)
class CombinedAnalysisTests(TestCase):
    setUpTestData = classmethod(fixtures.DetectionApiTests.setUpTestData.__func__)
    setUp = weapon_fixtures.WeaponAPITests.setUp
    advance = weapon_fixtures.WeaponAPITests.advance

    def submit(self, *, objects=None, rule=None, event_id=None, signature=None):
        objects = objects if objects is not None else [{"label": "person", "confidence": .95,
                   "bbox": [.02, .02, .7, .9], "track_id": "person-1"}]
        capture = fixtures.jpeg_upload()
        event_id, nonce = event_id or uuid.uuid4(), uuid.uuid4()
        observed, timestamp = self.at, int(self.at.timestamp())
        signature = signature or sign_event_payload(self.event_signing_key, contract_version=2,
            method="POST", path=reverse("api-camera-weapon"), camera_id=self.camera.pk, timestamp=timestamp,
            nonce=nonce, event_id=event_id, observed_at=observed, model_name="camera-combined",
            model_version=self.run_id, objects=objects, rule_context=rule, simulated=False,
            capture_type=capture.content_type, capture_digest=hashlib.sha256(capture.read()).hexdigest())
        capture.seek(0)
        body = {"contract_version": "2", "event_id": str(event_id), "observed_at": observed.isoformat(),
                "model_name": "camera-combined", "model_version": self.run_id,
                "objects": json.dumps(objects), "capture": capture}
        if rule:
            body["rule_context"] = json.dumps(rule)
        with patch("homes.weapon_analysis.timezone.now", return_value=observed):
            return self.client.post(reverse("api-camera-weapon"), body, HTTP_AUTHORIZATION=f"Bearer {self.token}",
                HTTP_X_CAMERA_TIMESTAMP=str(timestamp), HTTP_X_CAMERA_NONCE=str(nonce), HTTP_X_CAMERA_SIGNATURE=signature)

    def rule(self):
        return {"id": "presence-zone", "version": 1, "type": "presence_prolonged",
                "duration_seconds": self.camera.duree_presence_secondes, "zone": self.camera.zone_analyse,
                "track_ids": ["person-1"]}

    def confirmed(self, **kwargs):
        for _ in range(3):
            response = self.submit(**kwargs)
            self.assertEqual(response.status_code, 200, response.content)
            self.advance()
        return response.json()

    def test_one_event_contains_person_and_server_weapon_and_exact_notification_title(self):
        result = self.confirmed(rule=self.rule())
        event = Evenement.objects.get()
        self.assertEqual(result["alert_title"], PERSON_WEAPON_TITLE)
        self.assertTrue(result["notification_requested"])
        self.assertFalse(event.simule)
        self.assertEqual(event.priorite_alerte, NiveauAlerte.URGENTE)
        self.assertFalse(event.notification_supprimee)
        self.assertEqual(set(event.objets.values_list("classe", flat=True)), {"person", "firearm"})
        self.assertTrue(event.metadonnees["weapon_verification"]["evaluation_only"])
        self.assertEqual(CaptureChiffree.objects.count(), 1)
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 1)
        self.assertEqual(event_summary(event)["title"], PERSON_WEAPON_TITLE)
        self.assertTrue(_event_payload(event)["person_weapon_suspicion"])
        self.submit(rule=self.rule())
        self.assertEqual(Evenement.objects.count(), 1)

    def test_weapon_without_person_or_far_from_person_does_not_claim_possession(self):
        for objects in [[{"label": "scene", "confidence": 1, "bbox": [0, 0, 1, 1]}],
                        [{"label": "person", "confidence": .95, "bbox": [.8, .6, .18, .35]}]]:
            self.run_id = str(uuid.uuid4())
            result = self.confirmed(objects=objects)
            self.assertFalse(result["person_weapon_suspicion"])
            self.assertEqual(result["alert_title"], "Suspicion d’arme")
        self.assertTrue(all(event_summary(event)["title"] == "Suspicion d’arme" for event in Evenement.objects.all()))

    def test_person_needs_three_associated_samples_not_old_weapon_evidence(self):
        self.confirmed(objects=[{"label": "scene", "confidence": 1, "bbox": [0, 0, 1, 1]}])
        self.assertFalse(self.submit().json()["person_weapon_suspicion"])
        self.assertEqual(Evenement.objects.count(), 1)

    def test_ordinary_intrusion_continues_if_weapon_inference_fails(self):
        self.infer.side_effect = WeaponUnavailable("fixture")
        result = self.submit(rule=self.rule()).json()
        self.assertEqual(result["state"], "unavailable")
        self.assertTrue(result["event_id"])
        event = Evenement.objects.get()
        self.assertNotIn("weapon_verification", event.metadonnees)
        self.assertFalse(event.notification_supprimee)

    def test_clear_frame_records_regular_intrusion_without_weapon_claim(self):
        self.infer.return_value = []
        result = self.submit(rule=self.rule()).json()
        self.assertEqual(result["alert_title"], "Personne détectée")
        self.assertFalse(result["person_weapon_suspicion"])

    def test_feature_disabled_bad_signature_and_forged_weapon_are_rejected(self):
        with override_settings(WEAPON_COMBINED_ENABLED=False):
            self.assertEqual(self.submit().status_code, 403)
        self.assertEqual(self.submit(signature="0" * 64).status_code, 401)
        self.assertEqual(self.submit(objects=[self.found[0].public()]).status_code, 400)
        self.infer.assert_not_called()

    def test_schedule_pause_prevents_inference(self):
        with patch("homes.scheduling.effective_camera_monitoring", return_value=(False, "schedule")):
            self.assertEqual(self.submit().status_code, 403)
        self.infer.assert_not_called()

    def test_rights_or_feature_removed_during_inference_prevent_event(self):
        def disable(_capture, _mode):
            from django.conf import settings
            settings.WEAPON_COMBINED_ENABLED = False
            return self.found
        with override_settings(WEAPON_COMBINED_ENABLED=True):
            self.infer.side_effect = disable
            self.assertEqual(self.submit(rule=self.rule()).status_code, 403)
        self.assertFalse(Evenement.objects.exists())

    def test_new_run_does_not_reuse_confirmation(self):
        self.submit(); self.advance(); self.submit(); self.advance()
        self.run_id = str(uuid.uuid4())
        self.assertFalse(self.submit().json()["person_weapon_suspicion"])
        self.assertFalse(Evenement.objects.exists())

    def test_recognized_person_with_probable_weapon_is_not_silenced(self):
        from .browser_face import BrowserFaceResult
        known = BrowserFaceResult("recognized", "matched")
        with patch("homes.browser_face.verify_browser_face", return_value=known), patch(
                "homes.browser_face.confirm_browser_face", return_value=known):
            result = self.confirmed(rule=self.rule())
        self.assertTrue(result["notification_requested"])
        self.assertEqual(result["face_verification"]["state"], "recognized")

    def test_schedule_changed_during_face_inference_prevents_storage(self):
        from .browser_face import BrowserFaceResult
        self.infer.return_value = []
        with patch("homes.scheduling.effective_camera_monitoring", return_value=(True, "schedule")) as schedule:
            def pause(*_):
                schedule.return_value = (False, "schedule")
                return BrowserFaceResult("unavailable", "service")
            with patch("homes.browser_face.verify_browser_face", side_effect=pause):
                self.assertEqual(self.submit(rule=self.rule()).status_code, 400)
        self.assertFalse(Evenement.objects.exists())

    def test_combined_ui_describes_both_analyses_and_keeps_single_start(self):
        page = self.client.get(reverse("camera-monitor"), {"camera": str(self.camera.pk)})
        self.assertContains(page, 'data-combined-enabled="true"')
        self.assertContains(page, "Intrusion et suspicion d’arme")
        self.assertContains(page, 'id="start-weapon-test"', count=1)
