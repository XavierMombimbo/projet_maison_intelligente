from unittest.mock import patch

from django.contrib.auth.hashers import identify_hasher
from django.core import mail
from django.db import DatabaseError
from django.test import Client, TestCase
from django.urls import reverse

from .models import User


class AuthenticationTests(TestCase):
    def test_signup_creates_authenticated_user_with_argon2(self):
        response = self.client.post(
            reverse("signup"),
            {
                "username": "alice",
                "email": "alice@example.test",
                "password1": "UnePhraseSecrete!2026",
                "password2": "UnePhraseSecrete!2026",
            },
        )

        self.assertRedirects(response, reverse("dashboard"))
        user = User.objects.get(username="alice")
        self.assertEqual(identify_hasher(user.password).algorithm, "argon2")
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_login_with_valid_credentials(self):
        User.objects.create_user(
            username="bernard", email="bernard@example.test", password="MotDePasse!2026"
        )

        response = self.client.post(
            reverse("login"), {"username": "bernard", "password": "MotDePasse!2026"}
        )

        self.assertRedirects(response, reverse("dashboard"))

    def test_login_page_exposes_account_recovery_options(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, reverse("signup"))
        self.assertContains(response, "Créer un compte")
        self.assertContains(response, reverse("password-reset"))
        self.assertContains(response, "Mot de passe oublié ?")

    def test_authenticated_user_is_redirected_away_from_public_auth_pages(self):
        user = User.objects.create_user(
            username="already-connected",
            email="connected@example.test",
            password="MotDePasse!2026",
        )
        self.client.force_login(user)

        for route_name in ("login", "signup", "password-reset"):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertRedirects(response, reverse("dashboard"))

    def test_anonymous_user_cannot_open_dashboard_directly(self):
        response = self.client.get(reverse("dashboard"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('dashboard')}",
        )

    def test_password_reset_sends_a_non_disclosing_email(self):
        User.objects.create_user(
            username="recoverable",
            email="recoverable@example.test",
            password="MotDePasse!2026",
        )

        response = self.client.post(
            reverse("password-reset"),
            {"email": "recoverable@example.test"},
        )

        self.assertRedirects(response, reverse("password-reset-done"))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("/reinitialiser/", mail.outbox[0].body)

        unknown_response = self.client.post(
            reverse("password-reset"),
            {"email": "unknown@example.test"},
        )
        self.assertRedirects(unknown_response, reverse("password-reset-done"))
        self.assertEqual(len(mail.outbox), 1)

    def test_signup_post_without_csrf_token_is_rejected(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("signup"),
            {
                "username": "sanscsrf",
                "email": "sanscsrf@example.test",
                "password1": "MotDePasse!2026",
                "password2": "MotDePasse!2026",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(User.objects.filter(username="sanscsrf").exists())

    def test_signup_uses_local_rate_limit_fallback_when_cache_is_unavailable(self):
        with patch(
            "homes.throttling.cache.add",
            side_effect=ConnectionError("Redis indisponible"),
        ), self.assertLogs("homes.throttling", level="ERROR"):
            response = self.client.post(
                reverse("signup"),
                {
                    "username": "cache-fallback",
                    "email": "cache-fallback@example.test",
                    "password1": "UnePhraseSecrete!2026",
                    "password2": "UnePhraseSecrete!2026",
                },
            )

        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(User.objects.filter(username="cache-fallback").exists())

    def test_signup_database_failure_returns_a_service_unavailable_message(self):
        with patch(
            "accounts.forms.SignUpForm.save",
            side_effect=DatabaseError("Base indisponible"),
        ), self.assertLogs("accounts.views", level="ERROR"):
            response = self.client.post(
                reverse("signup"),
                {
                    "username": "db-unavailable",
                    "email": "db-unavailable@example.test",
                    "password1": "UnePhraseSecrete!2026",
                    "password2": "UnePhraseSecrete!2026",
                },
            )

        self.assertEqual(response.status_code, 503)
        self.assertContains(
            response,
            "Le service d’inscription est temporairement indisponible.",
            status_code=503,
        )
        self.assertFalse(User.objects.filter(username="db-unavailable").exists())
