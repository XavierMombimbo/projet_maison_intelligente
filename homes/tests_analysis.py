from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from .models import Camera, Maison
from .services import consume_pairing_code, create_pairing_code


class CameraAnalysisConfigurationTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "analysis-owner", "analysis-owner@example.test", "Secret!2026"
        )
        self.attacker = User.objects.create_user(
            "analysis-attacker", "analysis-attacker@example.test", "Secret!2026"
        )
        self.house = Maison.objects.create(nom="Maison analyse", proprietaire=self.owner)
        self.camera = Camera.objects.create(nom="Webcam analyse", maison=self.house)

    def test_owner_configures_normalized_zone_line_and_duration(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("camera-analysis-update", kwargs={"pk": self.camera.pk}),
            {
                "zone_x": "10",
                "zone_y": "20",
                "zone_width": "60",
                "zone_height": "70",
                "duree_presence_secondes": "2.5",
                "seuil_alerte_personne_pourcent": "60",
                "seuil_alerte_animal_pourcent": "70",
                "fenetre_regroupement_secondes": "45",
                "ligne_active": "on",
                "sens_franchissement_interdit": "negative_to_positive",
                "ligne_x1": "50",
                "ligne_y1": "0",
                "ligne_x2": "50",
                "ligne_y2": "100",
            },
        )

        self.assertRedirects(response, reverse("camera-detail", kwargs={"pk": self.camera.pk}))
        self.camera.refresh_from_db()
        self.assertEqual(
            self.camera.zone_analyse,
            {"x": 0.1, "y": 0.2, "width": 0.6, "height": 0.7},
        )
        self.assertEqual(
            self.camera.ligne_analyse,
            {"x1": 0.5, "y1": 0.0, "x2": 0.5, "y2": 1.0},
        )
        self.assertEqual(self.camera.duree_presence_secondes, 2.5)
        self.assertEqual(self.camera.seuil_alerte_personne, 0.6)
        self.assertEqual(self.camera.seuil_alerte_animal, 0.7)
        self.assertEqual(self.camera.fenetre_regroupement_secondes, 45)
        self.assertEqual(self.camera.sens_franchissement_interdit, "negative_to_positive")

    def test_zone_cannot_exceed_image_boundaries(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("camera-analysis-update", kwargs={"pk": self.camera.pk}),
            {
                "zone_x": "70",
                "zone_y": "0",
                "zone_width": "40",
                "zone_height": "100",
                "duree_presence_secondes": "1",
                "seuil_alerte_personne_pourcent": "45",
                "seuil_alerte_animal_pourcent": "50",
                "fenetre_regroupement_secondes": "30",
                "sens_franchissement_interdit": "any",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La zone dépasse le bord droit")
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.zone_analyse["width"], 1.0)

    def test_non_owner_cannot_configure_analysis(self):
        self.client.force_login(self.attacker)

        response = self.client.get(
            reverse("camera-analysis-update", kwargs={"pk": self.camera.pk})
        )

        self.assertEqual(response.status_code, 404)

    def test_camera_state_contains_only_valid_analysis_configuration(self):
        self.camera.zone_analyse = {"x": 0.25, "y": 0.1, "width": 0.5, "height": 0.8}
        self.camera.ligne_analyse = {"x1": 0.0, "y1": 0.5, "x2": 1.0, "y2": 0.5}
        self.camera.duree_presence_secondes = 3.0
        self.camera.save()
        _, plain_code = create_pairing_code(self.camera)
        credentials = consume_pairing_code(plain_code)

        response = self.client.get(
            reverse("api-camera-state"),
            HTTP_AUTHORIZATION=f"Bearer {credentials.access_token}",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["analysis"]["zone"], self.camera.zone_analyse)
        self.assertEqual(response.json()["analysis"]["line"], self.camera.ligne_analyse)
        self.assertEqual(response.json()["analysis"]["presence_seconds"], 3.0)
        self.assertEqual(response.json()["analysis"]["forbidden_crossing_direction"], "any")
        self.assertEqual(response.json()["analysis"]["alert_thresholds"]["person"], 0.45)
        self.assertEqual(response.json()["analysis"]["alert_thresholds"]["dog"], 0.5)
        self.assertEqual(response.json()["analysis"]["grouping_window_seconds"], 30)
        self.assertEqual(
            response.json()["analysis_settings_url"],
            reverse("camera-analysis-update", kwargs={"pk": self.camera.pk}),
        )
        self.assertEqual(
            response.json()["monitoring_toggle_url"],
            reverse("camera-toggle", kwargs={"pk": self.camera.pk}),
        )

    def test_model_rejects_invalid_normalized_line(self):
        self.camera.ligne_analyse = {"x1": 0.5, "y1": 0.5, "x2": 0.5, "y2": 0.5}

        with self.assertRaises(ValidationError):
            self.camera.full_clean()
