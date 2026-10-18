import re
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from homes.models import JournalAudit

from .mfa import SETUP_EMAIL_USER_KEY, VERIFIED_USER_KEY, issue_email_code
from .models import MFADevice, MFAEmailChallenge, MFARecoveryCode, User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MFAEmailSetupTests(TestCase):
    password = "UnePhraseSecrete!2026"

    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="email-setup", email="setup@example.test", password=self.password,
        )
        self.client.force_login(self.user)
        self.url = reverse("mfa-setup")
        self.client.get(self.url)
        self.device = MFADevice.objects.get(user=self.user)
        self.delivery = patch("accounts.views.email_delivery_configured", return_value=True)
        self.delivery.start()
        self.addCleanup(self.delivery.stop)

    def send(self, value=123456):
        with patch("accounts.mfa.secrets.randbelow", return_value=value):
            return self.client.post(self.url, {"action": "send_email"})

    def activate(self, code="123456"):
        return self.client.post(self.url, {"method": "email", "code": code})

    def test_get_never_sends_mail_and_offers_email_without_a_required_qr(self):
        response = self.client.get(self.url)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, "Envoyer le code par e-mail")
        self.assertContains(response, "Aucune application supplémentaire")
        self.assertNotContains(response, '<details class="mfa-app-option" open>')
        self.assertNotContains(response, self.device.get_secret())
        self.assertIn("no-store", response["Cache-Control"])

    def test_email_confirmation_activates_then_email_login_protects_the_account(self):
        self.assertRedirects(self.send(), self.url)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        self.assertIn("activation", mail.outbox[0].subject)
        self.assertEqual(self.client.session[SETUP_EMAIL_USER_KEY], self.user.pk)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_confirmed)
        self.assertNotIn(VERIFIED_USER_KEY, self.client.session)

        response = self.activate()
        self.assertEqual(response.status_code, 200)
        self.device.refresh_from_db()
        self.assertTrue(self.device.is_confirmed)
        self.assertEqual(len(response.context["recovery_codes"]), 10)
        self.assertEqual(MFARecoveryCode.objects.filter(user=self.user).count(), 10)
        self.assertEqual(self.client.session[VERIFIED_USER_KEY], self.user.pk)
        self.assertNotIn(SETUP_EMAIL_USER_KEY, self.client.session)
        challenge = MFAEmailChallenge.objects.get(user=self.user)
        self.assertNotEqual(challenge.digest, "123456")
        self.assertIsNotNone(challenge.used_at)
        audit = JournalAudit.objects.get(action="auth.mfa.enabled")
        self.assertEqual(audit.metadonnees, {"method": "email"})
        self.assertIsNone(self.client.get(self.url).context["recovery_codes"])

        self.client.logout()
        login = self.client.post(reverse("login"), {
            "username": self.user.username, "password": self.password,
        })
        self.assertRedirects(login, reverse("mfa-challenge"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        code = re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)
        accepted = self.client.post(reverse("mfa-challenge"), {"code": code})
        self.assertRedirects(accepted, reverse("dashboard"))
        self.assertEqual(self.client.session[VERIFIED_USER_KEY], self.user.pk)

    def test_no_confirmation_without_an_email_requested_from_this_session(self):
        with patch("accounts.mfa.secrets.randbelow", return_value=123456):
            issue_email_code(self.user, purpose="setup")
        self.assertEqual(self.activate().status_code, 400)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_confirmed)

    def test_another_users_code_does_not_activate_the_account(self):
        self.send()
        other = User.objects.create_user(username="other", email="other@example.test")
        with patch("accounts.mfa.secrets.randbelow", return_value=222222):
            issue_email_code(other, purpose="setup")
        self.assertEqual(self.activate("222222").status_code, 400)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_confirmed)
        self.assertFalse(MFARecoveryCode.objects.filter(user=self.user).exists())

    def test_resend_invalidates_the_previous_code(self):
        self.send(111111)
        self.send(222222)
        self.assertEqual(self.activate("111111").status_code, 400)
        self.assertEqual(self.activate("222222").status_code, 200)

    def test_expired_code_does_not_activate(self):
        self.send()
        MFAEmailChallenge.objects.filter(user=self.user).update(
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        response = self.activate()
        self.assertContains(response, "incorrect ou expiré", status_code=400)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_confirmed)

    def test_send_failure_never_claims_delivery_or_leaves_a_challenge(self):
        for outcome in (OSError("SMTP unavailable"), 0):
            with self.subTest(outcome=type(outcome).__name__):
                kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
                with patch("accounts.mfa.send_mail", **kwargs), self.assertLogs("accounts.views", level="ERROR"):
                    response = self.send()
                self.assertEqual(response.status_code, 503)
                self.assertNotIn(SETUP_EMAIL_USER_KEY, self.client.session)
                self.assertFalse(MFAEmailChallenge.objects.filter(user=self.user).exists())

    def test_email_sending_and_verification_are_rate_limited(self):
        with self.settings(RATE_LIMITS={**settings.RATE_LIMITS, "mfa_email": (1, 600), "mfa": (1, 300)}):
            self.assertEqual(self.send().status_code, 302)
            limited_send = self.send()
            self.assertEqual(limited_send.status_code, 429)
            self.assertIn("Retry-After", limited_send)
            self.assertEqual(self.activate("000000").status_code, 400)
            self.assertEqual(self.activate().status_code, 429)
        self.device.refresh_from_db()
        self.assertFalse(self.device.is_confirmed)

    def test_email_activation_rotates_an_abandoned_setup_qr(self):
        old_secret = self.device.get_secret()
        self.send()
        self.activate()
        self.device.refresh_from_db()
        self.assertNotEqual(self.device.get_secret(), old_secret)
        self.assertEqual(self.client.get(reverse("mfa-qr")).status_code, 404)

    def test_confirmed_account_cannot_replace_its_factor_through_enrollment(self):
        self.send()
        self.activate()
        self.device.refresh_from_db()
        secret, confirmed = self.device.get_secret(), self.device.confirmed_at
        sent = len(mail.outbox)
        self.client.force_login(self.user)
        self.assertRedirects(self.send(), self.url)
        self.assertRedirects(self.activate(), self.url)
        self.device.refresh_from_db()
        self.assertEqual(self.device.get_secret(), secret)
        self.assertEqual(self.device.confirmed_at, confirmed)
        self.assertEqual(len(mail.outbox), sent)

    def test_anonymous_request_cannot_send_an_activation_email(self):
        self.client.logout()
        self.assertEqual(self.send().status_code, 302)
        self.assertEqual(len(mail.outbox), 0)
