import re
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import Camera, Maison, StatutAppairage
from .security import (
    InvalidCameraToken,
    authenticate_camera_token,
    hash_pairing_code,
    issue_camera_token,
)
from .services import PairingError, consume_pairing_code, create_pairing_code


class PairingServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@example.test", "Secret!2026")
        cls.house = Maison.objects.create(nom="Maison test", proprietaire=cls.owner)

    def setUp(self):
        self.camera = Camera.objects.create(nom="Entrée", maison=self.house)

    def test_code_is_six_digits_hashed_and_expires_after_five_minutes(self):
        before = timezone.now()
        pairing_code, plain_code = create_pairing_code(self.camera, now=before)

        self.assertRegex(plain_code, re.compile(r"^\d{6}$"))
        self.assertNotEqual(pairing_code.code_hash, plain_code)
        self.assertEqual(pairing_code.code_hash, hash_pairing_code(plain_code))
        self.assertEqual(pairing_code.date_expiration, before + timedelta(minutes=5))

    def test_expired_code_is_rejected(self):
        _, plain_code = create_pairing_code(self.camera, now=timezone.now() - timedelta(minutes=6))

        with self.assertRaises(PairingError):
            consume_pairing_code(plain_code)

        self.camera.refresh_from_db()
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.NON_APPAIREE)

    def test_code_can_only_be_used_once(self):
        pairing_code, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)

        with self.assertRaises(PairingError):
            consume_pairing_code(plain_code)

        pairing_code.refresh_from_db()
        self.assertTrue(pairing_code.utilise)
        self.assertIsNotNone(pairing_code.date_utilisation)
        self.assertEqual(credentials.camera.pk, self.camera.pk)

    def test_generating_new_code_invalidates_previous_code(self):
        first_pairing, first_code = create_pairing_code(self.camera)
        _, second_code = create_pairing_code(self.camera)

        first_pairing.refresh_from_db()
        self.assertTrue(first_pairing.utilise)
        with self.assertRaises(PairingError):
            consume_pairing_code(first_code)
        self.assertEqual(consume_pairing_code(second_code).camera.pk, self.camera.pk)

    def test_pairing_creates_distinct_device_identity_and_no_plain_secret_in_database(self):
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)

        self.camera.refresh_from_db()
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.APPAIREE)
        self.assertEqual(self.camera.identifiant_appareil, credentials.device_id)
        self.assertNotEqual(self.camera.secret_appareil_hash, credentials.device_secret)
        self.assertEqual(len(self.camera.secret_appareil_hash), 64)
        self.assertTrue(credentials.event_signing_key)
        self.assertNotIn(
            credentials.event_signing_key,
            bytes(self.camera.cle_signature_evenement_chiffree).decode("latin1"),
        )

    def test_expired_jwt_is_rejected(self):
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)
        expired_token = issue_camera_token(
            credentials.camera, now=timezone.now() - timedelta(minutes=10), ttl_seconds=60
        )

        with self.assertRaises(InvalidCameraToken):
            authenticate_camera_token(expired_token)

    def test_jwt_for_another_camera_is_rejected(self):
        other_camera = Camera.objects.create(nom="Couloir", maison=self.house)
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)

        with self.assertRaises(InvalidCameraToken):
            authenticate_camera_token(
                credentials.access_token, expected_camera_id=other_camera.pk
            )


class PairingViewsAndApiTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user("owner", "owner@example.test", "Secret!2026")
        cls.attacker = User.objects.create_user(
            "attacker", "attacker@example.test", "Secret!2026"
        )
        cls.house = Maison.objects.create(nom="Maison test", proprietaire=cls.owner)

    def setUp(self):
        self.camera = Camera.objects.create(nom="Salon", maison=self.house)

    def test_only_owner_can_generate_code_and_response_is_not_cached(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("pairing-code-create", kwargs={"pk": self.camera.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.context["plain_code"], r"^\d{6}$")
        self.assertIn("no-store", response.headers["Cache-Control"])

        self.client.force_login(self.attacker)
        denied = self.client.post(
            reverse("pairing-code-create", kwargs={"pk": self.camera.pk})
        )
        self.assertEqual(denied.status_code, 404)

    def test_browser_pairing_page_consumes_code_and_is_not_cached(self):
        _, plain_code = create_pairing_code(self.camera)

        response = self.client.post(reverse("connect-camera"), {"code": plain_code})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["paired"])
        self.assertContains(response, "Appairage réussi")
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_camera_can_renew_token_and_read_only_its_state(self):
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)

        renewal = self.client.post(
            reverse("api-camera-token"),
            data={"device_id": credentials.device_id, "device_secret": credentials.device_secret},
            content_type="application/json",
        )
        self.assertEqual(renewal.status_code, 200)
        token = renewal.json()["access_token"]

        state = self.client.get(
            reverse("api-camera-state"), HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state.json()["camera_id"], str(self.camera.pk))
        self.assertNotIn("users", state.json())

        heartbeat = self.client.post(
            reverse("api-camera-heartbeat"), HTTP_AUTHORIZATION=f"Bearer {token}"
        )
        self.assertEqual(heartbeat.status_code, 200)
        self.camera.refresh_from_db()
        self.assertIsNotNone(self.camera.derniere_connexion)

    def test_wrong_device_secret_is_rejected(self):
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)

        response = self.client.post(
            reverse("api-camera-token"),
            data={"device_id": credentials.device_id, "device_secret": "incorrect"},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 401)

    def test_token_renewal_provisions_signing_key_for_legacy_camera(self):
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)
        self.camera.refresh_from_db()
        self.camera.cle_signature_evenement_chiffree = None
        self.camera.nonce_cle_signature_evenement = None
        self.camera.save(
            update_fields=(
                "cle_signature_evenement_chiffree",
                "nonce_cle_signature_evenement",
            )
        )

        response = self.client.post(
            reverse("api-camera-token"),
            data={"device_id": credentials.device_id, "device_secret": credentials.device_secret},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["event_signing_key"])
        self.camera.refresh_from_db()
        self.assertTrue(self.camera.cle_signature_evenement_chiffree)
        self.assertTrue(self.camera.nonce_cle_signature_evenement)

    def test_revocation_invalidates_token_and_credential(self):
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)
        self.client.force_login(self.owner)

        response = self.client.post(reverse("camera-revoke", kwargs={"pk": self.camera.pk}))

        self.assertRedirects(response, reverse("camera-detail", kwargs={"pk": self.camera.pk}))
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.REVOQUEE)
        self.assertEqual(self.camera.secret_appareil_hash, "")
        self.assertFalse(self.camera.surveillance_active)

        state = self.client.get(
            reverse("api-camera-state"),
            HTTP_AUTHORIZATION=f"Bearer {credentials.access_token}",
        )
        self.assertEqual(state.status_code, 401)

        renewal = self.client.post(
            reverse("api-camera-token"),
            data={"device_id": credentials.device_id, "device_secret": credentials.device_secret},
            content_type="application/json",
        )
        self.assertEqual(renewal.status_code, 401)

    def test_other_owner_cannot_revoke_camera(self):
        self.client.force_login(self.attacker)

        response = self.client.post(reverse("camera-revoke", kwargs={"pk": self.camera.pk}))

        self.assertEqual(response.status_code, 404)
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.statut_appairage, StatutAppairage.NON_APPAIREE)
