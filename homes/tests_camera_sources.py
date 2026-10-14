from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .crypto import decrypt_camera_source_config
from .models import Camera, Maison, StatutAppairage, TypeSourceCamera
from .security import InvalidCameraToken, authenticate_camera_token
from .services import consume_pairing_code, create_pairing_code


class CameraSourceTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "source-owner", "source-owner@example.test", "Secret!2026"
        )
        self.house = Maison.objects.create(nom="Maison sources", proprietaire=self.owner)
        self.client.force_login(self.owner)

    def test_webcam_source_has_no_network_configuration(self):
        response = self.client.post(
            reverse("camera-create"),
            {
                "maison": self.house.pk,
                "nom": "Webcam bureau",
                "type_source": TypeSourceCamera.WEBCAM,
            },
        )

        camera = Camera.objects.get(nom="Webcam bureau")
        self.assertRedirects(response, reverse("camera-detail", kwargs={"pk": camera.pk}))
        self.assertIsNone(camera.configuration_source_chiffree)
        self.assertIsNone(camera.nonce_configuration_source)
        self.assertEqual(camera.endpoint_source_expurge, "Webcam locale")

    def test_rtsp_credentials_are_encrypted_and_never_rendered(self):
        response = self.client.post(
            reverse("camera-create"),
            {
                "maison": self.house.pk,
                "nom": "Entrée RTSP",
                "type_source": TypeSourceCamera.RTSP,
                "adresse_rtsp": "rtsp://192.0.2.50:8554/live/main?profile=primary",
                "utilisateur_rtsp": "private-rtsp-user-fixture",
                "mot_de_passe_rtsp": "mot-de-passe-confidentiel",
            },
        )

        camera = Camera.objects.get(nom="Entrée RTSP")
        self.assertRedirects(response, reverse("camera-detail", kwargs={"pk": camera.pk}))
        ciphertext = bytes(camera.configuration_source_chiffree)
        self.assertNotIn(b"192.0.2.50", ciphertext)
        self.assertNotIn(b"private-rtsp-user-fixture", ciphertext)
        self.assertNotIn(b"mot-de-passe-confidentiel", ciphertext)
        config = decrypt_camera_source_config(
            ciphertext, bytes(camera.nonce_configuration_source), camera.pk
        )
        self.assertEqual(config["username"], "private-rtsp-user-fixture")
        self.assertEqual(config["password"], "mot-de-passe-confidentiel")
        self.assertEqual(
            camera.endpoint_source_expurge,
            "rtsp://192.0.2.50:8554/live/main",
        )

        detail = self.client.get(reverse("camera-detail", kwargs={"pk": camera.pk}))
        api = self.client.get(reverse("api:camera-detail", kwargs={"pk": camera.pk}))
        for payload in (detail.content, api.content):
            self.assertNotIn(b"private-rtsp-user-fixture", payload)
            self.assertNotIn(b"mot-de-passe-confidentiel", payload)
            self.assertNotIn(b"profile=primary", payload)
        self.assertEqual(api.json()["endpoint_source"], "rtsp://192.0.2.50:8554/live/main")

    def test_rtsp_url_rejects_embedded_credentials(self):
        response = self.client.post(
            reverse("camera-create"),
            {
                "maison": self.house.pk,
                "nom": "RTSP invalide",
                "type_source": TypeSourceCamera.RTSP,
                "adresse_rtsp": "rtsp://admin:secret@192.0.2.80/live",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Retirez les identifiants de l’adresse")
        self.assertFalse(Camera.objects.filter(nom="RTSP invalide").exists())

    def test_gateway_token_is_limited_to_its_camera(self):
        first = Camera.objects.create(nom="Caméra A", maison=self.house)
        second = Camera.objects.create(nom="Caméra B", maison=self.house)
        _, plain_code = create_pairing_code(first)
        credentials = consume_pairing_code(plain_code)

        camera, _ = authenticate_camera_token(
            credentials.access_token, expected_camera_id=first.pk
        )
        self.assertEqual(camera.pk, first.pk)
        with self.assertRaises(InvalidCameraToken):
            authenticate_camera_token(
                credentials.access_token, expected_camera_id=second.pk
            )

    def test_revocation_erases_rtsp_credentials(self):
        self.client.post(
            reverse("camera-create"),
            {
                "maison": self.house.pk,
                "nom": "RTSP révocable",
                "type_source": TypeSourceCamera.RTSP,
                "adresse_rtsp": "rtsps://camera.example.test/private",
                "utilisateur_rtsp": "gateway",
                "mot_de_passe_rtsp": "secret",
            },
        )
        camera = Camera.objects.get(nom="RTSP révocable")
        _, plain_code = create_pairing_code(camera)
        consume_pairing_code(plain_code)

        response = self.client.post(reverse("camera-revoke", kwargs={"pk": camera.pk}))

        self.assertRedirects(response, reverse("camera-detail", kwargs={"pk": camera.pk}))
        camera.refresh_from_db()
        self.assertEqual(camera.statut_appairage, StatutAppairage.REVOQUEE)
        self.assertIsNone(camera.configuration_source_chiffree)
        self.assertIsNone(camera.nonce_configuration_source)

    def test_rtsp_source_api_is_limited_to_authenticated_camera(self):
        self.client.post(
            reverse("camera-create"),
            {
                "maison": self.house.pk,
                "nom": "RTSP passerelle",
                "type_source": TypeSourceCamera.RTSP,
                "adresse_rtsp": "rtsp://192.0.2.60:554/live",
                "utilisateur_rtsp": "lecture",
                "mot_de_passe_rtsp": "secret-source",
            },
        )
        camera = Camera.objects.get(nom="RTSP passerelle")
        _, plain_code = create_pairing_code(camera)
        credentials = consume_pairing_code(plain_code)
        self.client.logout()

        response = self.client.get(
            reverse("api-camera-source"),
            HTTP_AUTHORIZATION=f"Bearer {credentials.access_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(response.json()["camera_id"], str(camera.pk))
        self.assertEqual(response.json()["username"], "lecture")
        self.assertEqual(response.json()["password"], "secret-source")
        self.assertEqual(response.json()["endpoint"], "rtsp://192.0.2.60:554/live")
