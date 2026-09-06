from django.contrib.auth.hashers import identify_hasher
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

