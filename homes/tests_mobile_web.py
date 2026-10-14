import os
import uuid
from pathlib import Path

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.mfa import VERIFIED_USER_KEY, generate_secret
from accounts.models import MFADevice, User
from .models import Camera, Evenement, Maison


class MobileWebParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("mobile-parity", email="mobile-parity@example.test", password="Test-only!2026")
        cls.house = Maison.objects.create(nom="Maison test", proprietaire=cls.user)
        cls.camera = Camera.objects.create(nom="Entrée", maison=cls.house)
        cls.event = Evenement.objects.create(client_event_id=uuid.uuid4(), camera=cls.camera,
            maison=cls.house, type="person_detected", confiance_ia=0.92, priorite_alerte=100)
        cls.device = MFADevice(user=cls.user, confirmed_at=timezone.now())
        cls.device.set_secret(generate_secret())
        cls.device.save()

    def sign_in(self):
        self.client.force_login(self.user)
        session = self.client.session
        session[VERIFIED_USER_KEY] = self.user.pk
        session.save()

    def test_all_mobile_pages_keep_web_functions_and_navigation(self):
        self.sign_in()
        routes = [
            ("dashboard", []), ("maison-list", []), ("maison-create", []),
            ("maison-detail", [self.house.pk]), ("planning-detail", [self.house.pk]),
            ("camera-list", []), ("camera-create", []), ("camera-detail", [self.camera.pk]),
            ("camera-analysis-update", [self.camera.pk]), ("camera-evaluation", [self.camera.pk]),
            ("event-list", []), ("event-detail", [self.event.pk]), ("camera-monitor", []), ("connect-camera", []), ("mfa-setup", []),
        ]
        for name, args in routes:
            with self.subTest(page=name):
                response = self.client.get(reverse(name, args=args), HTTP_USER_AGENT="Mobile")
                self.assertEqual(response.status_code, 200)
                if os.environ.get("MOBILE_WEB_ARTIFACTS"):
                    directory = Path(os.environ["MOBILE_WEB_ARTIFACTS"])
                    directory.mkdir(parents=True, exist_ok=True)
                    (directory / f"{name}.html").write_bytes(response.content)
                self.assertContains(response, 'class="mobile-tabbar"')
                self.assertContains(response, reverse("app-manifest"))
                for target in ["dashboard", "maison-list", "camera-list", "event-list", "mfa-setup", "camera-monitor"]:
                    self.assertContains(response, f'href="{reverse(target)}"')

    def test_install_assets_do_not_interrupt_pending_mfa(self):
        self.client.force_login(self.user)
        for route in ["app-manifest", "app-service-worker", "app-offline"]:
            response = self.client.get(reverse(route))
            self.assertEqual(response.status_code, 200)
            self.assertIn("_auth_user_id", self.client.session)
            self.assertNotContains(response, self.user.username)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("mfa-challenge"), fetch_redirect_response=False)

    def test_manifest_opens_real_authenticated_dashboard(self):
        response = self.client.get(reverse("app-manifest"))
        manifest = response.json()
        self.assertEqual(manifest["start_url"], reverse("dashboard"))
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(len(manifest["shortcuts"]), 3)

    def test_worker_does_not_cache_private_responses(self):
        response = self.client.get(reverse("app-service-worker"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertContains(response, "cache.add(OFFLINE)")
        self.assertNotContains(response, "cache.put(")
        self.assertContains(response, "event.request.method !== 'GET'")

    def test_mobile_keeps_foreign_camera_access_denied(self):
        self.sign_in()
        stranger = User.objects.create_user("foreign-mobile", email="foreign-mobile@example.test")
        house = Maison.objects.create(nom="Private house", proprietaire=stranger)
        camera = Camera.objects.create(nom="Private camera", maison=house)
        response = self.client.get(reverse("camera-detail", args=[camera.pk]), HTTP_USER_AGENT="Mobile")
        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "Private camera", status_code=404)
