import re
import uuid

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from homes.models import Camera, Evenement, Maison, TypeEvenement
from homes.security import issue_camera_token

from .mfa import VERIFIED_USER_KEY, generate_secret
from .models import MFADevice, MobileSession, User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MobileAPITests(TestCase):
    password = "UnePhraseSecrete!2026"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="mobile-user", email="mobile@example.test", password=self.password
        )
        self.device = MFADevice(user=self.user, confirmed_at=timezone.now())
        self.device.set_secret(generate_secret())
        self.device.save()
        self.house = Maison.objects.create(nom="Chez mobile", proprietaire=self.user)
        self.camera = Camera.objects.create(nom="Entrée", maison=self.house)
        self.event = Evenement.objects.create(
            client_event_id=uuid.uuid4(),
            camera=self.camera,
            maison=self.house,
            type=TypeEvenement.PERSONNE_DETECTEE,
            confiance_ia=0.91,
        )

    def login(self, device_id="android-test-0001", device_name="Téléphone test"):
        response = self.client.post(
            reverse("mobile-api:login"),
            {
                "identifier": self.user.email,
                "password": self.password,
                "device_id": device_id,
                "device_name": device_name,
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 202)
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        verified = self.client.post(
            reverse("mobile-api:mfa-verify"),
            {"challenge": response.json()["challenge"], "code": code},
            content_type="application/json",
        )
        self.assertEqual(verified.status_code, 200)
        return verified.json()

    def auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def test_password_stage_returns_only_mfa_challenge(self):
        response = self.client.post(
            reverse("mobile-api:login"),
            {
                "identifier": self.user.username,
                "password": self.password,
                "device_id": "android-test-0001",
                "device_name": "Téléphone test",
            },
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 202)
        self.assertIn("challenge", response.json())
        self.assertNotIn("access_token", response.json())
        self.assertNotIn("refresh_token", response.json())
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(MOBILE_WEB_ALLOWED_ORIGINS=["http://127.0.0.1:8081"])
    def test_mobile_web_cors_is_limited_to_configured_origins(self):
        url = reverse("mobile-api:login")
        allowed = self.client.options(
            url,
            HTTP_ORIGIN="http://127.0.0.1:8081",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS="content-type",
        )
        denied = self.client.options(
            url,
            HTTP_ORIGIN="https://example.invalid",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        )

        self.assertEqual(allowed.status_code, 204)
        self.assertEqual(
            allowed["Access-Control-Allow-Origin"],
            "http://127.0.0.1:8081",
        )
        self.assertEqual(
            allowed["Access-Control-Allow-Headers"],
            "Authorization, Content-Type",
        )
        self.assertNotIn("Access-Control-Allow-Origin", denied)

    def test_mobile_capture_is_private_and_filtered(self):
        from homes.crypto import encrypt_capture
        from homes.models import CaptureChiffree

        image = b"test-private-capture"
        encrypted, nonce = encrypt_capture(image, self.event.pk)
        CaptureChiffree.objects.create(evenement=self.event, contenu_chiffre=encrypted,
                                      nonce=nonce, type_mime="image/jpeg", taille=len(image))
        url = reverse("mobile-api:event-capture", args=[self.event.pk])
        self.assertEqual(self.client.get(url).status_code, 401)
        token = self.login()["access_token"]
        response = self.client.get(url, **self.auth(token))
        self.assertEqual(response.content, image)
        self.assertIn("no-store", response["Cache-Control"])
        self.house.proprietaire = User.objects.create_user("new-owner")
        self.house.save()
        self.house.membres.filter(utilisateur=self.user).delete()
        self.assertEqual(self.client.get(url, **self.auth(token)).status_code, 404)

    def test_mobile_decision_is_persisted_and_cannot_be_overwritten(self):
        token = self.login()["access_token"]
        url = reverse("mobile-api:event-decision", args=[self.event.pk])
        for decision, expected in [("invalid", 400), ("false_alarm", 200), ("confirmed", 409)]:
            response = self.client.post(url, {"decision": decision}, content_type="application/json", **self.auth(token))
            self.assertEqual(response.status_code, expected)
        self.event.refresh_from_db()
        self.assertEqual(self.event.statut, "false_alarm")

    def test_monitoring_requires_owner_and_refuses_revoked_camera(self):
        token = self.login()["access_token"]
        url = reverse("mobile-api:camera-monitoring", args=[self.camera.pk])
        response = self.client.post(url, {"active": True}, content_type="application/json", **self.auth(token))
        self.assertEqual(response.status_code, 200)
        self.camera.refresh_from_db()
        self.assertTrue(self.camera.surveillance_active)
        self.camera.statut_appairage = "revoked"
        self.camera.save()
        response = self.client.post(url, {"active": False}, content_type="application/json", **self.auth(token))
        self.assertEqual(response.status_code, 404)

    def test_camera_list_exposes_requested_and_applied_monitoring(self):
        self.camera.surveillance_active = True
        self.camera.surveillance_appliquee = False
        self.camera.surveillance_appliquee_le = timezone.now()
        self.camera.save(
            update_fields=(
                "surveillance_active",
                "surveillance_appliquee",
                "surveillance_appliquee_le",
            )
        )
        token = self.login()["access_token"]

        response = self.client.get(
            reverse("mobile-api:camera-list"), **self.auth(token)
        )

        camera = response.json()["results"][0]
        self.assertTrue(camera["surveillance_active"])
        self.assertFalse(camera["surveillance_appliquee"])
        self.assertIsNotNone(camera["surveillance_appliquee_le"])

    def test_camera_history_is_filtered_and_newest_first(self):
        token = self.login()["access_token"]
        newer = Evenement.objects.create(client_event_id=uuid.uuid4(), camera=self.camera,
            maison=self.house, type=TypeEvenement.PERSONNE_DETECTEE, confiance_ia=0.5, priorite_alerte=10)
        response = self.client.get(reverse("mobile-api:event-list"), {"camera": str(self.camera.pk)}, **self.auth(token))
        self.assertEqual(response.json()["results"][0]["id"], str(newer.pk))
        response = self.client.get(reverse("mobile-api:event-list"), {"camera": "bad-id"}, **self.auth(token))
        self.assertEqual(response.status_code, 400)

    def test_camera_history_is_paginated(self):
        for _ in range(3):
            Evenement.objects.create(
                client_event_id=uuid.uuid4(),
                camera=self.camera,
                maison=self.house,
                type=TypeEvenement.PERSONNE_DETECTEE,
                confiance_ia=0.5,
            )
        token = self.login()["access_token"]
        url = reverse("mobile-api:event-list")

        first = self.client.get(
            url,
            {"camera": str(self.camera.pk), "page_size": 2},
            **self.auth(token),
        ).json()
        second = self.client.get(
            url,
            {"camera": str(self.camera.pk), "page_size": 2, "page": 2},
            **self.auth(token),
        ).json()

        self.assertEqual(first["count"], 4)
        self.assertEqual(len(first["results"]), 2)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(second["results"]), 2)

    def test_authenticated_user_can_open_manual_diagnostic(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[VERIFIED_USER_KEY] = self.user.pk
        session.save()
        response = self.client.get(reverse("mobile-api-test"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tester la connexion mobile")

    def test_email_mfa_issues_tokens_and_accesses_profile(self):
        tokens = self.login()

        response = self.client.get(reverse("mobile-api:me"), **self.auth(tokens["access_token"]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["email"], self.user.email)
        self.assertEqual(MobileSession.objects.filter(user=self.user).count(), 1)

    def test_refresh_token_is_rotated_and_old_value_is_rejected(self):
        tokens = self.login()
        first = self.client.post(
            reverse("mobile-api:refresh"),
            {"refresh_token": tokens["refresh_token"]},
            content_type="application/json",
        )
        replay = self.client.post(
            reverse("mobile-api:refresh"),
            {"refresh_token": tokens["refresh_token"]},
            content_type="application/json",
        )
        second = self.client.post(
            reverse("mobile-api:refresh"),
            {"refresh_token": first.json()["refresh_token"]},
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 401)
        self.assertEqual(second.status_code, 200)

    def test_one_device_session_can_be_revoked(self):
        first = self.login("android-test-0001", "Téléphone A")
        second = self.login("android-test-0002", "Téléphone B")
        revoke = self.client.post(
            reverse("mobile-api:session-revoke", args=[second["session_id"]]),
            **self.auth(first["access_token"]),
        )
        rejected = self.client.get(reverse("mobile-api:me"), **self.auth(second["access_token"]))
        accepted = self.client.get(reverse("mobile-api:me"), **self.auth(first["access_token"]))

        self.assertEqual(revoke.status_code, 204)
        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 200)

    def test_camera_jwt_is_rejected_by_mobile_api(self):
        self.camera.identifiant_appareil = "camera-device"
        self.camera.statut_appairage = "paired"
        self.camera.save(update_fields=("identifiant_appareil", "statut_appairage"))

        response = self.client.get(
            reverse("mobile-api:me"), **self.auth(issue_camera_token(self.camera))
        )

        self.assertEqual(response.status_code, 401)

    def test_resources_use_same_visibility_rules_as_web(self):
        stranger = User.objects.create_user("stranger", "stranger@example.test", self.password)
        foreign_house = Maison.objects.create(nom="Maison étrangère", proprietaire=stranger)
        foreign_camera = Camera.objects.create(nom="Caméra étrangère", maison=foreign_house)
        foreign_event = Evenement.objects.create(
            client_event_id=uuid.uuid4(),
            camera=foreign_camera,
            maison=foreign_house,
            type=TypeEvenement.PERSONNE_DETECTEE,
            confiance_ia=0.75,
        )
        token = self.login()["access_token"]

        houses = self.client.get(reverse("mobile-api:house-list"), **self.auth(token)).json()
        cameras = self.client.get(reverse("mobile-api:camera-list"), **self.auth(token)).json()
        events = self.client.get(reverse("mobile-api:event-list"), **self.auth(token)).json()

        self.assertEqual([row["id"] for row in houses["results"]], [self.house.pk])
        self.assertEqual([row["id"] for row in cameras["results"]], [str(self.camera.pk)])
        self.assertEqual([row["id"] for row in events["results"]], [str(self.event.pk)])
        self.assertNotIn(str(foreign_camera.pk), str(cameras))
        self.assertNotIn(str(foreign_event.pk), str(events))
