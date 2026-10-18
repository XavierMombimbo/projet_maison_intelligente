from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import User
from .browser_camera import browser_camera_context
from .models import AccesCamera, Camera, Maison, MembreMaison, RoleMaison, StatutInvitation
from .services import consume_pairing_code, create_pairing_code
from .security import authenticate_camera_token


class BrowserCameraIsolationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a = User.objects.create_user("scope-a", "scope-a@example.test", "Secret!2026")
        self.b = User.objects.create_user("scope-b", "scope-b@example.test", "Secret!2026")
        self.house_a = Maison.objects.create(nom="Maison A", proprietaire=self.a)
        self.house_b = Maison.objects.create(nom="Maison B", proprietaire=self.b)
        self.camera_a = Camera.objects.create(nom="Camera privee A", maison=self.house_a)
        self.camera_b = Camera.objects.create(nom="Camera privee B", maison=self.house_b)
        _, code = create_pairing_code(self.camera_a)
        self.gateway = consume_pairing_code(code)
        self.client.force_login(self.a)
        self.context_url = reverse("browser-camera-context")
        self.state_url = reverse("api-camera-state")

    def context(self, client=None):
        response = (client or self.client).get(reverse("camera-monitor"))
        return response.context["browser_camera_context"]

    def grant(self, camera=None, context=None, client=None):
        return (client or self.client).get(self.context_url, {"camera": str((camera or self.camera_a).pk)},
            HTTP_X_SENTINELLE_CAMERA_CONTEXT=context or self.context(client))

    def state(self, token, context, client=None, **extra):
        return (client or self.client).get(self.state_url, HTTP_AUTHORIZATION=f"Bearer {token}",
            HTTP_X_SENTINELLE_CAMERA_CONTEXT=context, HTTP_SEC_FETCH_SITE="same-origin", **extra)

    def test_anonymous_cannot_open_monitor_or_pair_browser(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("camera-monitor")).status_code, 302)
        self.assertEqual(self.client.get(reverse("connect-camera")).status_code, 302)

    def test_allowed_ids_are_scoped_and_cannot_be_overridden(self):
        _, code = create_pairing_code(self.camera_b)
        consume_pairing_code(code)
        self.client.force_login(self.b)
        context = self.context()
        response = self.client.get(self.context_url, HTTP_X_SENTINELLE_CAMERA_CONTEXT=context)
        self.assertEqual(response.json(), {"camera_ids": [str(self.camera_b.pk)]})
        self.assertEqual(self.grant(context=context).status_code, 404)
        self.assertEqual(self.client.get(self.context_url, {"camera": "invalid"}, HTTP_X_SENTINELLE_CAMERA_CONTEXT=context).status_code, 404)
        self.assertNotContains(response, self.camera_a.nom)

    def test_grant_contains_no_device_secret_and_only_works_for_current_session(self):
        context = self.context()
        response = self.grant(context=context)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(set(payload), {"camera_id", "access_token", "event_signing_key"})
        _, claims = authenticate_camera_token(payload["access_token"])
        self.assertEqual(claims["browser_session"], context)
        state = self.state(payload["access_token"], context)
        self.assertEqual(state.status_code, 200)
        self.assertEqual(state["Cache-Control"], "no-store, private")
        self.assertIn("no-store", response["Cache-Control"])

    def test_account_switch_invalidates_old_page_context_and_token(self):
        old_context = self.context()
        token = self.grant(context=old_context).json()["access_token"]
        self.client.force_login(self.b)
        self.assertEqual(self.state(token, old_context).status_code, 401)
        self.assertEqual(self.client.get(self.context_url, HTTP_X_SENTINELLE_CAMERA_CONTEXT=old_context).status_code, 409)
        self.assertNotEqual(old_context, self.context())

    def test_logout_and_new_session_of_same_account_invalidate_old_grant(self):
        context = self.context()
        token = self.grant(context=context).json()["access_token"]
        self.client.logout()
        self.assertEqual(self.state(token, context).status_code, 401)
        self.client.force_login(self.a)
        self.assertEqual(self.state(token, context).status_code, 401)

    def test_token_cannot_be_replayed_without_cookie_or_context_header(self):
        context = self.context()
        token = self.grant(context=context).json()["access_token"]
        self.assertEqual(self.state(token, context, client=Client()).status_code, 401)
        self.assertEqual(self.client.get(self.state_url, HTTP_AUTHORIZATION=f"Bearer {token}").status_code, 401)

    def test_removed_control_permission_rejects_existing_token(self):
        member = MembreMaison.objects.create(maison=self.house_a, utilisateur=self.b,
            role=RoleMaison.FAMILLE, statut=StatutInvitation.ACCEPTEE)
        access = AccesCamera.objects.create(camera=self.camera_a, membre=member, peut_voir=True, peut_controler=True)
        self.client.force_login(self.b)
        context = self.context()
        token = self.grant(context=context).json()["access_token"]
        access.peut_controler = False; access.save()
        self.assertEqual(self.state(token, context).status_code, 401)
        self.assertEqual(self.grant(context=context).status_code, 404)

    def test_legacy_device_token_is_rejected_in_browser_but_gateway_still_works(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.state_url, HTTP_AUTHORIZATION=f"Bearer {self.gateway.access_token}").status_code, 200)
        self.assertEqual(self.client.get(self.state_url, HTTP_AUTHORIZATION=f"Bearer {self.gateway.access_token}", HTTP_SEC_FETCH_SITE="same-origin").status_code, 401)
        response = self.client.post(reverse("api-camera-token"), {"device_id": self.gateway.device_id,
            "device_secret": self.gateway.device_secret}, content_type="application/json", HTTP_ORIGIN="https://testserver")
        self.assertEqual(response.status_code, 403)

    def test_browser_pairing_cannot_consume_another_accounts_code(self):
        camera = Camera.objects.create(nom="New A", maison=self.house_a)
        pairing, code = create_pairing_code(camera)
        self.client.force_login(self.b)
        response = self.client.post(reverse("connect-camera"), {"code": code})
        self.assertFalse(response.context.get("paired", False))
        pairing.refresh_from_db(); self.assertFalse(pairing.utilise)

    def test_browser_post_requires_csrf_even_with_valid_bearer(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.a)
        context = self.context(client)
        token = self.grant(context=context, client=client).json()["access_token"]
        response = client.post(reverse("api-camera-heartbeat"), {}, content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_SENTINELLE_CAMERA_CONTEXT=context)
        self.assertEqual(response.status_code, 403)
        accepted = client.post(reverse("api-camera-heartbeat"), {}, content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_SENTINELLE_CAMERA_CONTEXT=context,
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        self.assertEqual(accepted.status_code, 200)
