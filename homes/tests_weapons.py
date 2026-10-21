import hashlib
import json
import uuid
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gateway.weapons import WeaponDetection, WeaponUnavailable
from . import tests_detection as fixtures
from .models import Evenement, CaptureChiffree, EvenementBoiteEnvoi, NiveauAlerte
from .request_signing import sign_event_payload
from .templatetags.presentation import event_summary
from .weapon_analysis import SCENE


@override_settings(WEAPON_DETECTION_MODE="review", WEAPON_MODEL_ROOT="/fixture",
                   BIOMETRIC_WEB_RECOGNITION_ENABLED=False)
class WeaponAPITests(TestCase):
    setUpTestData = classmethod(fixtures.DetectionApiTests.setUpTestData.__func__)

    def setUp(self):
        cache.clear()
        fixtures.DetectionApiTests.setUp(self)
        self.gateway_token = self.token
        self.client.force_login(self.owner)
        self.context = self.client.get(reverse("camera-monitor")).context["browser_camera_context"]
        grant = self.client.get(reverse("browser-camera-context"), {"camera": str(self.camera.pk)},
                                HTTP_X_SENTINELLE_CAMERA_CONTEXT=self.context)
        self.token = grant.json()["access_token"]
        self.client.defaults.update(HTTP_X_SENTINELLE_CAMERA_CONTEXT=self.context, HTTP_SEC_FETCH_SITE="same-origin")
        self.run_id = str(uuid.uuid4())
        self.at = timezone.now()
        self.found = [WeaponDetection("firearm", .9, (.1, .1, .3, .3))]
        p = patch("homes.weapon_analysis.infer", return_value=self.found)
        self.infer = p.start()
        self.addCleanup(p.stop)

    def submit(self, *, event_id=None, objects=None, capture=None, signature=None, observed_at=None,
               model_name="weapon-observation"):
        capture = capture or fixtures.jpeg_upload()
        event_id = event_id or uuid.uuid4()
        now = observed_at or self.at
        timestamp, nonce = int(now.timestamp()), uuid.uuid4()
        objects = SCENE if objects is None else objects
        signature = signature or sign_event_payload(self.event_signing_key, contract_version=2,
            method="POST", path=reverse("api-camera-weapon"), camera_id=self.camera.pk, timestamp=timestamp,
            nonce=nonce, event_id=event_id, observed_at=now, model_name=model_name, model_version=self.run_id,
            objects=objects, simulated=False, capture_type=capture.content_type,
            capture_digest=hashlib.sha256(capture.read()).hexdigest())
        capture.seek(0)
        with patch("homes.weapon_analysis.timezone.now", return_value=now):
            return self.client.post(reverse("api-camera-weapon"), {
                "contract_version": "2", "event_id": str(event_id), "observed_at": now.isoformat(),
                "model_name": model_name, "model_version": self.run_id, "objects": json.dumps(objects),
                "capture": capture}, HTTP_AUTHORIZATION=f"Bearer {self.token}",
                HTTP_X_CAMERA_TIMESTAMP=str(timestamp), HTTP_X_CAMERA_NONCE=str(nonce), HTTP_X_CAMERA_SIGNATURE=signature)

    def advance(self, seconds=1.5):
        from datetime import timedelta
        self.at += timedelta(seconds=seconds)

    def test_review_repeated_suspicion_never_writes_events_or_captures(self):
        for state in ("candidate", "candidate", "suspected"):
            result = self.submit()
            self.assertEqual(result.status_code, 200, result.content)
            self.assertEqual(result.json()["state"], state)
            self.assertFalse(result.json()["notification_requested"])
            self.advance()
        self.assertEqual(Evenement.objects.count(), 0)
        self.assertEqual(CaptureChiffree.objects.count(), 0)
        self.assertEqual(EvenementBoiteEnvoi.objects.count(), 0)
        self.assertEqual(result.headers["Cache-Control"], "no-store, private")

    def test_retried_observation_does_not_supply_another_temporal_sample(self):
        event_id = uuid.uuid4()
        for _ in range(4):
            response = self.submit(event_id=event_id)
            self.assertEqual(response.json()["state"], "candidate")
            self.advance()
        self.assertFalse(Evenement.objects.exists())

    def test_new_run_does_not_reuse_old_evidence(self):
        self.submit(); self.advance(); self.submit(); self.advance()
        self.run_id = str(uuid.uuid4())
        self.assertEqual(self.submit().json()["state"], "candidate")

    def test_forged_client_weapon_or_signature_is_rejected_before_inference(self):
        self.assertEqual(self.submit(objects=[self.found[0].public()]).status_code, 400)
        self.assertEqual(self.submit(signature="0" * 64).status_code, 401)
        self.infer.assert_not_called()

    def test_gateway_and_other_web_account_cannot_use_review(self):
        self.token = self.gateway_token
        self.assertEqual(self.submit().status_code, 401)
        self.client.force_login(self.attacker)
        self.assertEqual(self.submit().status_code, 401)
        self.infer.assert_not_called()

    def test_paused_camera_rejects_before_inference(self):
        self.camera.surveillance_active = False
        self.camera.save()
        self.assertEqual(self.submit().status_code, 403)
        self.infer.assert_not_called()

    def test_withdrawn_rights_or_pause_during_inference_prevents_result(self):
        def pause(*args):
            type(self.camera).objects.filter(pk=self.camera.pk).update(surveillance_active=False)
            return self.found
        self.infer.side_effect = pause
        self.assertEqual(self.submit().status_code, 403)
        self.assertFalse(Evenement.objects.exists())

    def test_inference_failure_is_unavailable_and_resets_temporal_evidence(self):
        self.submit(); self.advance(); self.submit(); self.advance()
        self.infer.side_effect = WeaponUnavailable("failure")
        response = self.submit()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["state"], "unavailable")
        self.infer.side_effect = None
        self.advance()
        self.assertEqual(self.submit().json()["state"], "candidate")

    @override_settings(WEAPON_DETECTION_MODE="disabled")
    def test_disabled_module_never_runs(self):
        self.assertEqual(self.submit().json()["state"], "disabled")
        self.infer.assert_not_called()

    @override_settings(WEAPON_DETECTION_MODE="alerts")
    def test_qualified_server_result_records_urgent_event_and_cooldown(self):
        for _ in range(3):
            response = self.submit()
            self.advance()
        self.assertTrue(response.json()["event_id"])
        event = Evenement.objects.get()
        self.assertEqual(event.priorite_alerte, NiveauAlerte.URGENTE)
        self.assertFalse(event.notification_supprimee)
        self.assertEqual(list(event.objets.values_list("classe", flat=True)), ["firearm"])
        self.assertEqual(event.metadonnees["weapon_verification"]["source"], "server")
        self.assertEqual(event_summary(event)["title"], "Suspicion d’arme")
        self.assertFalse(self.submit().json()["event_id"])
        self.assertEqual(Evenement.objects.count(), 1)

    def test_actual_candidate_cannot_load_in_alert_mode(self):
        from gateway.weapons import verified_model
        with self.assertRaises(WeaponUnavailable):
            verified_model("tmp/weapon-review-20261020", mode="alerts")

    def test_ui_requires_explicit_opt_in_and_explains_snapshot_uploads(self):
        response = self.client.get(reverse("camera-monitor"))
        self.assertContains(response, 'id="start-weapon-test"')
        self.assertContains(response, 'id="stop-weapon-test"')
        self.assertContains(response, "Démarrer le test")
        self.assertContains(response, "1,5 seconde")
        self.assertContains(response, "aucune sirène d’arme")

    def test_clear_and_unavailable_never_mean_the_same_thing(self):
        self.infer.return_value = []
        self.assertEqual(self.submit().json()["state"], "clear")

    def test_confirmation_priority_is_not_suppressed_by_recognized_face(self):
        from .alerting import decider_alerte
        decision = decider_alerte(self.camera, [
            {"label": "person", "confidence": .9, "face_status": "recognized"},
            self.found[0].public(),
        ], None, verified_weapon={"state": "suspected", "group": "server-group"})
        self.assertEqual(decision.priorite, NiveauAlerte.URGENTE)
        self.assertFalse(decision.notification_supprimee)

    def test_disabled_ui_does_not_offer_model_review(self):
        with override_settings(WEAPON_DETECTION_MODE="disabled"):
            self.assertNotContains(self.client.get(reverse("camera-monitor")), 'id="start-weapon-test"')

    def test_web_csrf_is_required(self):
        self.client.handler.enforce_csrf_checks = True
        self.assertEqual(self.submit().status_code, 403)
        self.infer.assert_not_called()

    def demo_settings(self, **kwargs):
        return override_settings(DEBUG=True, FCM_ENABLED=False,
            WEAPON_ACADEMIC_DEMO_CAMERA_IDS=(str(self.camera.pk),), **kwargs)

    def test_academic_demo_creates_only_a_labelled_record_without_capture_or_outbox(self):
        with self.demo_settings():
            for _ in range(3):
                response = self.submit(model_name="weapon-observation-academic-demo")
                self.advance()
            self.assertEqual(response.status_code, 200, response.content)
            self.assertTrue(response.json()["academic_demo"])
            self.assertFalse(response.json()["notification_requested"])
            event = Evenement.objects.get()
            self.assertEqual(response.json()["event_id"], str(event.pk))
            self.assertTrue(event.simule)
            self.assertTrue(event.notification_supprimee)
            self.assertEqual(event.objets.get().classe, "firearm")
            self.assertFalse(Evenement.objects.operationnels().exists())
            self.assertFalse(CaptureChiffree.objects.exists())
            self.assertFalse(EvenementBoiteEnvoi.objects.exists())
            self.assertEqual(event_summary(event)["heading"], "Alerte d’essai")
            detail = self.client.get(response.json()["detail_url"])
            self.assertContains(detail, "Démo académique")
            self.assertContains(detail, "aucune image d’essai enregistrée")
            self.assertNotContains(detail, 'class="capture-frame"')
            self.assertNotContains(detail, "Confirmer le signalement")
            self.assertFalse(self.submit(model_name="weapon-observation-academic-demo").json()["event_id"])
            self.assertEqual(Evenement.objects.count(), 1)

    def test_academic_environment_does_not_record_without_explicit_signed_choice(self):
        with self.demo_settings():
            for _ in range(3):
                self.submit()
                self.advance()
            self.assertFalse(Evenement.objects.exists())

    def test_academic_demo_is_rejected_without_isolation_or_with_external_push(self):
        cases = [dict(DEBUG=False), dict(FCM_ENABLED=True),
                 dict(WEAPON_ACADEMIC_DEMO_CAMERA_IDS=()),
                 dict(WEAPON_DETECTION_MODE="alerts")]
        for changes in cases:
            with self.subTest(changes=changes), self.demo_settings(), override_settings(**changes):
                response = self.submit(model_name="weapon-observation-academic-demo")
                self.assertEqual(response.status_code, 403)
        self.infer.assert_not_called()
        self.assertFalse(Evenement.objects.exists())

    def test_academic_demo_rejects_remote_address_before_inference(self):
        with self.demo_settings():
            self.client.defaults["REMOTE_ADDR"] = "192.0.2.1"
            self.assertEqual(self.submit(model_name="weapon-observation-academic-demo").status_code, 403)
            self.infer.assert_not_called()

    def test_academic_demo_rechecks_isolation_after_inference(self):
        from django.conf import settings
        def change(*args):
            settings.WEAPON_ACADEMIC_DEMO_CAMERA_IDS = ()
            return self.found
        with self.demo_settings():
            self.infer.side_effect = change
            self.assertEqual(self.submit(model_name="weapon-observation-academic-demo").status_code, 403)
            self.assertFalse(Evenement.objects.exists())

    def test_demo_selection_cannot_supply_temporal_evidence_for_regular_review(self):
        with self.demo_settings():
            self.submit(); self.advance(); self.submit(); self.advance()
            self.assertEqual(self.submit(model_name="weapon-observation-academic-demo").json()["state"], "candidate")
            self.assertFalse(Evenement.objects.exists())

    def test_academic_demo_ui_is_only_offered_for_the_explicitly_isolated_camera(self):
        with self.demo_settings():
            url = reverse("camera-monitor") + "?camera=" + str(self.camera.pk)
            page = self.client.get(url)
            self.assertContains(page, "Démarrer la démo")
            self.assertContains(page, 'id="start-weapon-test"', count=1)
            self.assertNotContains(page, 'id="start-weapon-demo"')
            self.assertContains(page, "Alerte d’essai activée")
        self.assertNotContains(self.client.get(url), "Démarrer la démo")

    def academic_site_settings(self):
        return override_settings(DEBUG=False, FCM_ENABLED=True,
            WEAPON_ACADEMIC_SITE_ENABLED=True,
            WEAPON_ACADEMIC_SITE_CAMERA_IDS=[str(self.camera.pk)])

    def test_academic_site_uses_normal_browser_rights_and_never_creates_capture_or_outbox(self):
        with self.academic_site_settings():
            self.client.defaults["REMOTE_ADDR"] = "192.0.2.1"
            for _ in range(3):
                response = self.submit(model_name="weapon-observation-academic-demo")
                self.assertEqual(response.status_code, 200, response.content)
                self.advance()
            self.assertTrue(response.json()["academic_demo"])
            self.assertFalse(response.json()["notification_requested"])
            event = Evenement.objects.get()
            self.assertTrue(event.simule)
            self.assertTrue(event.notification_supprimee)
            self.assertFalse(Evenement.objects.operationnels().exists())
            self.assertFalse(CaptureChiffree.objects.exists())
            self.assertFalse(EvenementBoiteEnvoi.objects.exists())

    def test_academic_site_does_not_allow_an_unlisted_camera_or_plain_review(self):
        with self.academic_site_settings():
            self.assertEqual(self.submit().status_code, 403)
            with override_settings(WEAPON_ACADEMIC_SITE_CAMERA_IDS=[]):
                self.assertEqual(self.submit(model_name="weapon-observation-academic-demo").status_code, 403)
                page = self.client.get(reverse("camera-monitor"), {"camera": str(self.camera.pk)})
                self.assertNotContains(page, 'id="start-weapon-test"')
            self.infer.assert_not_called()

    def test_academic_site_camera_list_alone_does_not_enable_remote_demo(self):
        with self.academic_site_settings(), override_settings(WEAPON_ACADEMIC_SITE_ENABLED=False):
            self.assertEqual(self.submit(model_name="weapon-observation-academic-demo").status_code, 403)
            self.infer.assert_not_called()

    def test_academic_site_rechecks_allowlist_after_inference(self):
        from django.conf import settings
        def remove(*args):
            settings.WEAPON_ACADEMIC_SITE_CAMERA_IDS = []
            return self.found
        with self.academic_site_settings():
            self.infer.side_effect = remove
            self.assertEqual(self.submit(model_name="weapon-observation-academic-demo").status_code, 403)
            self.assertFalse(Evenement.objects.exists())

    def test_site_demo_is_not_offered_to_another_house_or_on_invalid_id(self):
        with self.academic_site_settings():
            url = reverse("camera-monitor")
            self.assertContains(self.client.get(url, {"camera": str(self.camera.pk)}), "Démarrer la démo")
            self.client.force_login(self.attacker)
            self.assertNotContains(self.client.get(url, {"camera": str(self.camera.pk)}), "Démarrer la démo")
            with override_settings(WEAPON_ACADEMIC_SITE_CAMERA_IDS=["invalid"]):
                self.assertNotContains(self.client.get(url, {"camera": "invalid"}), "Démarrer la démo")

    def test_enabling_site_during_plain_review_drops_the_result(self):
        from django.conf import settings
        def enable(*args):
            settings.WEAPON_ACADEMIC_SITE_ENABLED = True
            return self.found
        with override_settings(WEAPON_ACADEMIC_SITE_ENABLED=False):
            self.infer.side_effect = enable
            self.assertEqual(self.submit().status_code, 403)
            self.assertFalse(Evenement.objects.exists())

    def test_generic_mode_camera_offers_explicit_choice_without_changing_local_camera(self):
        with self.academic_site_settings():
            page = self.client.get(reverse("camera-monitor"))
            self.assertContains(page, 'id="academic-camera-choice"')
            self.assertContains(page, '?camera=' + str(self.camera.pk))
            self.assertEqual(page.context["requested_camera_id"], "")
            self.assertNotContains(page, 'id="start-weapon-test"')
            self.client.force_login(self.attacker)
            self.assertNotContains(self.client.get(reverse("camera-monitor")), 'id="academic-camera-choice"')

    def test_site_demo_invalid_camera_configuration_does_not_crash_generic_page(self):
        with self.academic_site_settings(), override_settings(WEAPON_ACADEMIC_SITE_CAMERA_IDS=["invalid"]):
            self.assertNotContains(self.client.get(reverse("camera-monitor")), 'id="academic-camera-choice"')
