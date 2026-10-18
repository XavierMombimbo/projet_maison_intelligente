import base64
import io
import json
from unittest.mock import patch, Mock

import numpy as np
from PIL import Image
from django.conf import settings
from django.core.cache import cache
from django.test import Client, TestCase, SimpleTestCase, override_settings
from django.urls import reverse

from accounts.models import User
from gateway.facial import ARCFACE_TEMPLATE_FORMAT, FaceQualityError, deserialize_embedding
from .facial_enrollment import MAX_REQUEST_BYTES, EnrollmentUnavailable, template_from_capture
from .models import JournalAudit, Maison, MembreMaison, ProfilBiometrique, RoleMaison, StatutInvitation
from .biometrics import revoke_biometric_profile


@override_settings(BIOMETRIC_WEB_ENROLLMENT_ENABLED=True, BIOMETRIC_FACE_MODEL_ROOT="/reviewed/models")
class WebFacialEnrollmentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = User.objects.create_user("face-owner", "face-owner@example.test", "Secret!2026")
        self.member = User.objects.create_user("face-member", "face-member@example.test", "Secret!2026")
        self.other = User.objects.create_user("face-other", "face-other@example.test", "Secret!2026")
        self.house = Maison.objects.create(nom="Maison", proprietaire=self.owner)
        self.membership = MembreMaison.objects.create(maison=self.house, utilisateur=self.member,
            role=RoleMaison.FAMILLE, statut=StatutInvitation.ACCEPTEE)
        self.profile = ProfilBiometrique.objects.create(maison=self.house, utilisateur=self.member, libelle="Moi")
        self.url = reverse("biometric-profile-enroll", args=(self.house.pk, self.profile.pk))
        self.list_url = reverse("biometric-profile-list", args=(self.house.pk,))
        self.client.force_login(self.member)
        self.template = (np.ones(512, dtype="<f4") / np.sqrt(512)).astype("<f4").tobytes()
        self.extractor = patch("homes.facial_views.template_from_capture", return_value=self.template)
        self.extract = self.extractor.start()
        self.addCleanup(self.extractor.stop)

    def submit(self, **changes):
        return self.client.post(self.url, {"image": "synthetic-capture", "consent": True, **changes}, content_type="application/json")

    def test_get_has_explicit_camera_and_no_capture_or_template(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Ouvrir ma caméra")
        self.assertContains(response, "La photo n’est pas conservée")
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.extract.assert_not_called()
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.est_enrole)

    def test_enrollment_stores_only_encrypted_template_and_audits_without_image(self):
        response = self.submit()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "enrolled")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.decrypt_template(), self.template)
        self.assertEqual(self.profile.format_gabarit, ARCFACE_TEMPLATE_FORMAT)
        self.assertNotEqual(bytes(self.profile.gabarit_chiffre), self.template)
        self.assertEqual(self.profile.version, 2)
        self.assertNotContains(response, "synthetic-capture")
        audit = JournalAudit.objects.get(action="biometric.profile.enroll")
        self.assertEqual(audit.metadonnees, {"format": ARCFACE_TEMPLATE_FORMAT, "source": "web"})

    def test_owner_and_other_user_cannot_enroll_someone_else(self):
        for user in (self.owner, self.other):
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self.submit().status_code, 404)
        self.extract.assert_not_called()

    def test_anonymous_is_redirected_before_processing_capture(self):
        self.client.logout()
        self.assertEqual(self.submit().status_code, 302)
        self.extract.assert_not_called()

    def test_withdrawn_profile_and_departed_member_are_denied(self):
        revoke_biometric_profile(self.profile)
        self.assertEqual(self.submit().status_code, 404)
        self.membership.delete()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.extract.assert_not_called()

    def test_withdrawal_during_inference_prevents_recreation(self):
        def withdraw(_):
            revoke_biometric_profile(self.profile)
            return self.template
        self.extract.side_effect = withdraw
        self.assertEqual(self.submit().status_code, 404)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.est_enrole)
        self.assertFalse(JournalAudit.objects.filter(action="biometric.profile.enroll").exists())

    def test_membership_loss_during_inference_prevents_storage(self):
        def leave(_):
            self.membership.delete()
            return self.template
        self.extract.side_effect = leave
        self.assertEqual(self.submit().status_code, 404)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.est_enrole)

    def test_enrolled_profile_is_not_silently_replaced(self):
        self.profile.set_template(self.template, ARCFACE_TEMPLATE_FORMAT)
        self.assertEqual(self.submit().status_code, 409)
        self.extract.assert_not_called()
        self.assertContains(self.client.get(self.url), "Votre visage est enregistré")

    def test_consent_is_required_and_body_is_bounded(self):
        self.assertEqual(self.submit(consent=False).status_code, 400)
        self.assertEqual(self.client.post(self.url, "{", content_type="application/json").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"image": "x"}).status_code, 400)
        self.assertEqual(self.client.post(self.url, "x" * (MAX_REQUEST_BYTES + 1), content_type="application/json").status_code, 413)
        self.extract.assert_not_called()

    def test_csrf_is_enforced_for_capture(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.member)
        self.assertEqual(client.post(self.url, {"consent": True, "image": "x"}, content_type="application/json").status_code, 403)
        self.extract.assert_not_called()

    def test_disabled_or_unavailable_service_never_stores(self):
        with override_settings(BIOMETRIC_WEB_ENROLLMENT_ENABLED=False):
            self.assertEqual(self.submit().status_code, 503)
        self.extract.assert_not_called()
        self.extract.side_effect = EnrollmentUnavailable
        self.assertEqual(self.submit().status_code, 503)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.est_enrole)

    def test_quality_error_is_actionable_and_does_not_enroll(self):
        self.extract.side_effect = FaceQualityError("Un seul visage doit être visible pendant l’enrôlement.")
        response = self.submit()
        self.assertEqual(response.status_code, 422)
        self.assertIn("Un seul visage", response.json()["detail"])
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.est_enrole)

    def test_rate_limit_prevents_inference(self):
        limits = {**settings.RATE_LIMITS, "biometric_enrollment": (1, 300)}
        with override_settings(RATE_LIMITS=limits):
            self.submit(consent=False)
            self.assertEqual(self.submit().status_code, 429)
        self.extract.assert_not_called()

    def test_creation_flows_to_web_enrollment_and_pending_profile_can_resume(self):
        self.client.force_login(self.owner)
        response = self.client.post(self.list_url, {"libelle": "Mon profil", "consentement": "on"})
        profile = ProfilBiometrique.objects.get(utilisateur=self.owner, maison=self.house)
        self.assertRedirects(response, reverse("biometric-profile-enroll", args=(self.house.pk, profile.pk)))
        self.assertContains(self.client.get(self.list_url), "Enregistrer mon visage")


@override_settings(BIOMETRIC_WEB_ENROLLMENT_ENABLED=True, BIOMETRIC_FACE_MODEL_ROOT="/reviewed/models")
class WebCaptureDecoderTests(SimpleTestCase):
    def image(self, size=(640, 480), format="JPEG"):
        output = io.BytesIO()
        Image.new("RGB", size).save(output, format)
        return base64.b64encode(output.getvalue()).decode()

    def test_jpeg_decoded_in_memory_and_passed_as_bgr(self):
        expected = (np.ones(512, dtype="<f4") / np.sqrt(512)).astype("<f4").tobytes()
        embedder = Mock()
        embedder.embedding_from_bgr.return_value = expected
        with patch("homes.facial_enrollment._embedder", return_value=embedder):
            actual = template_from_capture(self.image())
        self.assertEqual(actual, expected)
        self.assertEqual(embedder.embedding_from_bgr.call_args.args[0].shape, (480, 640, 3))
        self.assertEqual(deserialize_embedding(actual).size, 512)

    def test_invalid_and_excessive_images_never_reach_the_model(self):
        with patch("homes.facial_enrollment._embedder") as model:
            for value in (None, "not-base64!", self.image(format="PNG"), self.image((1281, 480)), self.image((20, 20))):
                with self.assertRaises(FaceQualityError):
                    template_from_capture(value)
            model.assert_not_called()

    def test_unapproved_models_are_unavailable_and_quality_stays_distinct(self):
        from gateway.model_policy import ModelApprovalError
        with patch("homes.facial_enrollment._embedder", side_effect=ModelApprovalError("private path")):
            with self.assertRaises(EnrollmentUnavailable): template_from_capture(self.image())
        embedder = Mock()
        embedder.embedding_from_bgr.side_effect = FaceQualityError("Aucun visage suffisamment net n’est visible.")
        with patch("homes.facial_enrollment._embedder", return_value=embedder):
            with self.assertRaises(FaceQualityError): template_from_capture(self.image())
