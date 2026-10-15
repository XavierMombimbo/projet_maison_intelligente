import re
import time
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from homes.models import JournalAudit

from .mfa import PREAUTH_USER_KEY, VERIFIED_USER_KEY, totp_code
from .models import MFADevice, MFAEmailChallenge, MFARecoveryCode, User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MFATests(TestCase):
    password = "UnePhraseSecrete!2026"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="mfa-user", email="mfa@example.test", password=self.password
        )
        self.client.force_login(self.user)
        self.client.get(reverse("mfa-setup"))
        self.device = MFADevice.objects.get(user=self.user)
        self.base_time = int(time.time() // 30 * 30)

    def activate(self):
        code = totp_code(self.device.get_secret(), at_time=self.base_time)
        with patch("accounts.mfa.time.time", return_value=self.base_time):
            response = self.client.post(reverse("mfa-setup"), {"code": code})
        self.device.refresh_from_db()
        self.recovery_codes = response.context["recovery_codes"]
        return response

    def test_enrollment_uses_qr_confirmation_and_encrypted_secret(self):
        secret = self.device.get_secret()
        self.assertNotIn(secret.encode("ascii"), bytes(self.device.encrypted_secret))
        self.assertFalse(self.device.is_confirmed)

        qr = self.client.get(reverse("mfa-qr"))
        invalid = self.client.post(reverse("mfa-setup"), {"code": "000000"})
        valid = self.activate()

        self.assertEqual(qr.status_code, 200)
        self.assertEqual(qr.headers["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", qr.content)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(self.device.is_confirmed)
        self.assertEqual(self.client.session[VERIFIED_USER_KEY], self.user.pk)
        self.assertTrue(JournalAudit.objects.filter(action="auth.mfa.enabled").exists())

    def test_login_has_no_authenticated_session_before_valid_otp(self):
        self.activate()
        self.client.logout()
        login_time = self.base_time + 30
        with patch("accounts.mfa.time.time", return_value=login_time):
            response = self.client.post(
                reverse("login"), {"username": self.user.username, "password": self.password}
            )

        self.assertRedirects(response, reverse("mfa-challenge"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.session[PREAUTH_USER_KEY], self.user.pk)

        code = totp_code(self.device.get_secret(), at_time=login_time)
        with patch("accounts.mfa.time.time", return_value=login_time):
            verified = self.client.post(reverse("mfa-challenge"), {"code": code})

        self.assertRedirects(verified, reverse("dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertEqual(self.client.session[VERIFIED_USER_KEY], self.user.pk)

    def test_login_sends_single_use_email_code_stored_as_digest(self):
        self.activate()
        self.client.logout()

        response = self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.password}
        )
        self.assertRedirects(response, reverse("mfa-challenge"), fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
        challenge = MFAEmailChallenge.objects.get(user=self.user)
        self.assertNotEqual(challenge.digest, code)

        accepted = self.client.post(reverse("mfa-challenge"), {"code": code})
        challenge.refresh_from_db()
        self.assertRedirects(accepted, reverse("dashboard"))
        self.assertIsNotNone(challenge.used_at)
        audit = JournalAudit.objects.filter(action="auth.mfa.success").latest("date_creation")
        self.assertEqual(audit.metadonnees["method"], "email")
        self.assertNotIn(code, str(audit.metadonnees))

        self.client.logout()
        cache.clear()
        self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.password}
        )
        replay = self.client.post(reverse("mfa-challenge"), {"code": code})
        self.assertEqual(replay.status_code, 400)

    def test_resend_invalidates_previous_email_code_and_is_rate_limited(self):
        self.activate()
        self.client.logout()
        self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.password}
        )
        first_code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)

        resent = self.client.post(reverse("mfa-email-code"))
        second_code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        self.assertRedirects(resent, reverse("mfa-challenge"))
        self.assertNotEqual(first_code, second_code)
        self.assertEqual(MFAEmailChallenge.objects.filter(user=self.user).count(), 1)
        rejected = self.client.post(reverse("mfa-challenge"), {"code": first_code})
        self.assertEqual(rejected.status_code, 400)

        cache.clear()
        with self.settings(RATE_LIMITS={**settings.RATE_LIMITS, "mfa_email": (1, 600)}):
            allowed = self.client.post(reverse("mfa-email-code"))
            limited = self.client.post(reverse("mfa-email-code"))
        self.assertEqual(allowed.status_code, 302)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited)

    def test_expired_email_code_is_rejected(self):
        self.activate()
        self.client.logout()
        self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.password}
        )
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        MFAEmailChallenge.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(seconds=1)
        )

        response = self.client.post(reverse("mfa-challenge"), {"code": code})

        self.assertEqual(response.status_code, 400)

    def test_totp_cannot_be_replayed(self):
        self.activate()
        self.client.logout()
        login_time = self.base_time + 30
        code = totp_code(self.device.get_secret(), at_time=login_time)
        for expected_status in (302, 400):
            with patch("accounts.mfa.time.time", return_value=login_time):
                self.client.post(
                    reverse("login"), {"username": self.user.username, "password": self.password}
                )
                response = self.client.post(reverse("mfa-challenge"), {"code": code})
            self.assertEqual(response.status_code, expected_status)
            self.client.logout()

    def test_preauthentication_expires(self):
        self.activate()
        self.client.logout()
        login_time = self.base_time + 30
        with patch("accounts.mfa.time.time", return_value=login_time):
            self.client.post(
                reverse("login"), {"username": self.user.username, "password": self.password}
            )
        with patch(
            "accounts.mfa.time.time",
            return_value=login_time + settings.MFA_PREAUTH_TTL_SECONDS + 1,
        ):
            response = self.client.get(reverse("mfa-challenge"))

        self.assertRedirects(response, reverse("login"))
        self.assertNotIn(PREAUTH_USER_KEY, self.client.session)

    def test_mfa_attempts_are_rate_limited(self):
        self.activate()
        self.client.logout()
        cache.clear()
        login_time = self.base_time + 30
        with patch("accounts.mfa.time.time", return_value=login_time):
            self.client.post(
                reverse("login"), {"username": self.user.username, "password": self.password}
            )
            with self.settings(RATE_LIMITS={**settings.RATE_LIMITS, "mfa": (2, 300)}):
                first = self.client.post(reverse("mfa-challenge"), {"code": "000000"})
                second = self.client.post(reverse("mfa-challenge"), {"code": "000000"})
                limited = self.client.post(reverse("mfa-challenge"), {"code": "000000"})

        self.assertEqual(first.status_code, 400)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Retry-After", limited)

    def test_admin_login_uses_same_mfa_challenge(self):
        self.user.is_staff = True
        self.user.is_superuser = True
        self.user.save(update_fields=("is_staff", "is_superuser"))
        self.activate()
        self.client.logout()

        response = self.client.post(
            "/admin/login/?next=/admin/",
            {"username": self.user.username, "password": self.password, "next": "/admin/"},
        )

        self.assertRedirects(response, reverse("mfa-challenge"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_middleware_blocks_unverified_authenticated_session(self):
        self.activate()
        self.client.logout()
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(response, reverse("mfa-challenge"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.session[PREAUTH_USER_KEY], self.user.pk)

    def test_recovery_code_is_hashed_single_use_and_audited_without_secret(self):
        self.activate()
        recovery_code = self.recovery_codes[0]
        stored = MFARecoveryCode.objects.filter(user=self.user).first()
        self.assertNotEqual(stored.digest, recovery_code)
        self.assertNotIn(recovery_code.replace("-", ""), stored.digest)
        self.assertNotIn(recovery_code, str(dict(self.client.session.items())))
        self.client.logout()
        cache.clear()

        self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.password}
        )
        accepted = self.client.post(reverse("mfa-challenge"), {"code": recovery_code})
        stored.refresh_from_db()

        self.assertRedirects(accepted, reverse("dashboard"))
        self.assertIsNotNone(stored.used_at)
        audit = JournalAudit.objects.filter(action="auth.mfa.success").latest("date_creation")
        self.assertEqual(audit.metadonnees["method"], "recovery")
        self.assertNotIn(recovery_code, str(audit.metadonnees))

        self.client.logout()
        cache.clear()
        self.client.post(
            reverse("login"), {"username": self.user.username, "password": self.password}
        )
        replay = self.client.post(reverse("mfa-challenge"), {"code": recovery_code})
        self.assertEqual(replay.status_code, 400)

    def test_lost_phone_replacement_rotates_factor_codes_and_other_sessions(self):
        self.activate()
        old_secret = self.device.get_secret()
        old_digests = set(MFARecoveryCode.objects.filter(user=self.user).values_list("digest", flat=True))
        recovery_codes = self.recovery_codes
        other_client = Client()
        other_client.force_login(self.user)
        other_session = other_client.session
        other_session[VERIFIED_USER_KEY] = self.user.pk
        other_session.save()
        self.assertEqual(other_client.get(reverse("dashboard")).status_code, 200)

        started = self.client.post(
            reverse("mfa-replace"),
            {"stage": "start", "password": self.password, "code": recovery_codes[0]},
        )
        self.device.refresh_from_db()
        pending_secret = self.device.get_pending_secret()

        self.assertRedirects(started, reverse("mfa-replace"))
        self.assertIsNotNone(pending_secret)
        self.assertEqual(self.client.get(reverse("mfa-replace-qr")).status_code, 200)

        confirmation_time = self.base_time + 30
        code = totp_code(pending_secret, at_time=confirmation_time)
        with patch("accounts.mfa.time.time", return_value=confirmation_time):
            confirmed = self.client.post(
                reverse("mfa-replace"), {"stage": "confirm", "code": code}
            )
        self.device.refresh_from_db()

        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(len(confirmed.context["recovery_codes"]), 10)
        self.assertNotEqual(self.device.get_secret(), old_secret)
        self.assertIsNone(self.device.get_pending_secret())
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.user, used_at__isnull=True).count(), 10)
        self.assertFalse(
            MFARecoveryCode.objects.filter(user=self.user, digest__in=old_digests).exists()
        )
        self.assertRedirects(
            other_client.get(reverse("dashboard")),
            f"{reverse('login')}?next={reverse('dashboard')}",
        )
        audit = JournalAudit.objects.get(action="auth.mfa.replacement_started")
        self.assertEqual(audit.metadonnees["method"], "recovery")
        self.assertNotIn(recovery_codes[0], str(audit.metadonnees))

    def test_user_can_revoke_other_sessions_after_reauthentication(self):
        self.activate()
        other_client = Client()
        other_client.force_login(self.user)
        other_session = other_client.session
        other_session[VERIFIED_USER_KEY] = self.user.pk
        other_session.save()
        code_time = self.base_time + 30
        code = totp_code(self.device.get_secret(), at_time=code_time)

        with patch("accounts.mfa.time.time", return_value=code_time):
            response = self.client.post(
                reverse("mfa-revoke-sessions"),
                {"password": self.password, "code": code},
            )

        self.assertRedirects(response, reverse("mfa-setup"))
        self.assertRedirects(
            other_client.get(reverse("dashboard")),
            f"{reverse('login')}?next={reverse('dashboard')}",
        )
        self.assertTrue(JournalAudit.objects.filter(action="auth.sessions.revoked").exists())
