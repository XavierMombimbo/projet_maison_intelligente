from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from .audit import record_audit
from .models import JournalAudit, Maison, ResultatAudit


class SecurityHeaderTests(TestCase):
    def test_csp_and_browser_permission_headers_are_present(self):
        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        policy = response.headers["Content-Security-Policy"]
        self.assertIn("default-src 'self'", policy)
        self.assertIn("object-src 'none'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertNotIn("'unsafe-inline'", policy)
        self.assertNotIn("'unsafe-eval'", policy)
        self.assertEqual(
            response.headers["Permissions-Policy"],
            "camera=(self), microphone=(), geolocation=()",
        )
        self.assertEqual(response.headers["Cross-Origin-Resource-Policy"], "same-origin")

    def test_camera_model_libraries_are_served_locally_in_strict_order(self):
        user = User.objects.create_user(
            "model-owner", "model@example.test", "Secret!2026"
        )
        self.client.force_login(user)

        response = self.client.get(reverse("camera-monitor"))
        content = response.content.decode()

        bootstrap_position = content.index('src="/static/js/vision-runtime-bootstrap.js')
        tensorflow_position = content.index('src="/static/vendor/tf-4.22.0.min.js')
        coco_position = content.index('src="/static/vendor/coco-ssd-2.2.3.min.js')
        monitor_position = content.index('src="/static/js/camera-monitor.js')
        self.assertLess(bootstrap_position, tensorflow_position)
        self.assertLess(tensorflow_position, coco_position)
        self.assertLess(coco_position, monitor_position)
        self.assertNotIn("cdn.jsdelivr.net", content)
        self.assertIn("data-tensorflow-url=", content)
        self.assertIn("data-coco-url=", content)


class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @override_settings(RATE_LIMITS={"login": (2, 60)})
    def test_login_attempts_are_rate_limited(self):
        for _ in range(2):
            response = self.client.post(
                reverse("login"), {"username": "unknown", "password": "incorrect"}
            )
            self.assertEqual(response.status_code, 200)

        limited = self.client.post(
            reverse("login"), {"username": "unknown", "password": "incorrect"}
        )

        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)
        self.assertTrue(
            JournalAudit.objects.filter(action="auth.login.rate_limited").exists()
        )

    @override_settings(RATE_LIMITS={"pairing": (1, 60)})
    def test_pairing_attempts_are_rate_limited(self):
        first = self.client.post(reverse("api-camera-pair"), {"code": "000000"})
        limited = self.client.post(reverse("api-camera-pair"), {"code": "000000"})

        self.assertEqual(first.status_code, 400)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited.headers)


class AuditLogTests(TestCase):
    def test_audit_hashes_ip_and_redacts_sensitive_metadata(self):
        request = RequestFactory().post("/connexion/", REMOTE_ADDR="203.0.113.42")

        record = record_audit(
            "security.test",
            ResultatAudit.REFUS,
            request=request,
            metadata={
                "device_secret": "must-not-leak",
                "authorization": "Bearer hidden",
                "reason": "invalid",
            },
        )

        self.assertEqual(len(record.ip_hash), 64)
        self.assertNotIn("203.0.113.42", record.ip_hash)
        self.assertEqual(record.metadonnees["device_secret"], "[REDACTED]")
        self.assertEqual(record.metadonnees["authorization"], "[REDACTED]")
        self.assertEqual(record.metadonnees["reason"], "invalid")

    def test_house_creation_is_audited_with_user_and_target(self):
        user = User.objects.create_user("audit-owner", "audit@example.test", "Secret!2026")
        self.client.force_login(user)

        response = self.client.post(reverse("maison-create"), {"nom": "Maison auditée"})

        self.assertEqual(response.status_code, 302)
        house = Maison.objects.get(nom="Maison auditée")
        record = JournalAudit.objects.get(action="house.create")
        self.assertEqual(record.utilisateur, user)
        self.assertEqual(record.maison, house)
        self.assertEqual(record.cible_id, str(house.pk))
