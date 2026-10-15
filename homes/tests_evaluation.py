from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import AnnotationClasseEvaluation, Camera, CampagneEvaluation, Maison


class FieldEvaluationCampaignTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("eval-owner", "eval@example.test", "Secret!2026")
        self.other = User.objects.create_user("eval-other", "other@example.test", "Secret!2026")
        self.house = Maison.objects.create(nom="Maison terrain", proprietaire=self.owner)
        self.camera = Camera.objects.create(nom="Webcam terrain", maison=self.house)

    def start(self):
        return self.client.post(
            reverse("camera-evaluation-start", kwargs={"pk": self.camera.pk}),
            {"partition": "evaluation", "condition": "day", "notes": "contre-jour"},
        )

    def completed_campaign(self, partition="evaluation", duration_seconds=60):
        campaign = CampagneEvaluation.objects.create(
            camera=self.camera,
            partition=partition,
            condition="day",
            creee_par=self.owner,
        )
        end = timezone.now()
        CampagneEvaluation.objects.filter(pk=campaign.pk).update(
            date_debut=end - timedelta(seconds=duration_seconds),
            date_fin=end,
        )
        campaign.refresh_from_db()
        return campaign

    @staticmethod
    def annotation_payload(**overrides):
        payload = {
            "person_attendues": 0,
            "person_correctes": 0,
            "person_fausses": 0,
            "dog_attendues": 0,
            "dog_correctes": 0,
            "dog_fausses": 0,
            "cat_attendues": 0,
            "cat_correctes": 0,
            "cat_fausses": 0,
            "cpu_moyen_pourcent": "",
            "ram_pic_mo": "",
        }
        payload.update(overrides)
        return payload

    def test_owner_starts_and_stops_real_campaign(self):
        self.client.force_login(self.owner)
        page = self.client.get(reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        self.assertContains(page, "Démarrer une campagne")
        self.assertContains(page, "Évaluation indépendante")
        response = self.start()

        self.assertRedirects(response, reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        campaign = CampagneEvaluation.objects.get(camera=self.camera)
        self.assertEqual(campaign.partition, "evaluation")
        self.assertEqual(campaign.condition, "day")
        self.assertTrue(campaign.active)

        page = self.client.get(reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        monitor_url = f'{reverse("camera-monitor")}?camera={self.camera.pk}'
        self.assertContains(page, monitor_url)

        response = self.client.post(
            reverse("camera-evaluation-stop", kwargs={"pk": self.camera.pk, "campagne_pk": campaign.pk})
        )
        self.assertRedirects(response, reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        campaign.refresh_from_db()
        self.assertFalse(campaign.active)
        self.assertGreaterEqual(campaign.duree_secondes, 0)

    def test_only_one_campaign_can_be_active_for_camera(self):
        self.client.force_login(self.owner)
        self.start()
        self.start()

        self.assertEqual(CampagneEvaluation.objects.filter(camera=self.camera, date_fin__isnull=True).count(), 1)

    def test_other_user_cannot_access_or_start_campaign(self):
        self.client.force_login(self.other)

        page = self.client.get(reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        start = self.start()

        self.assertEqual(page.status_code, 404)
        self.assertEqual(start.status_code, 404)
        self.assertFalse(CampagneEvaluation.objects.exists())

    def test_duration_uses_recorded_end_time(self):
        campaign = CampagneEvaluation.objects.create(
            camera=self.camera,
            partition="calibration",
            condition="night",
            creee_par=self.owner,
        )
        start = timezone.now() - timedelta(minutes=5)
        end = start + timedelta(minutes=3)
        CampagneEvaluation.objects.filter(pk=campaign.pk).update(date_debut=start, date_fin=end)
        campaign.refresh_from_db()

        self.assertAlmostEqual(campaign.duree_secondes, 180, delta=0.1)

    def test_monitor_receives_requested_camera_identifier(self):
        response = self.client.get(reverse("camera-monitor"), {"camera": self.camera.pk})

        self.assertContains(response, f'data-requested-camera-id="{self.camera.pk}"')

    def test_owner_annotates_completed_campaign_and_gets_metrics(self):
        campaign = self.completed_campaign()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "camera-evaluation-annotation",
                kwargs={"pk": self.camera.pk, "campagne_pk": campaign.pk},
            ),
            self.annotation_payload(
                person_attendues=2,
                person_correctes=1,
                person_fausses=1,
                cpu_moyen_pourcent=25,
                ram_pic_mo=512,
            ),
        )

        self.assertRedirects(response, reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        self.assertEqual(AnnotationClasseEvaluation.objects.filter(campagne=campaign).count(), 3)
        person = AnnotationClasseEvaluation.objects.get(campagne=campaign, classe="person")
        self.assertEqual(person.faux_negatifs, 1)
        self.assertEqual(person.precision, 0.5)
        self.assertEqual(person.rappel, 0.5)
        campaign.refresh_from_db()
        self.assertEqual(campaign.cpu_moyen_pourcent, 25)
        self.assertEqual(campaign.ram_pic_mo, 512)

        report = self.client.get(reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))
        evaluation_report = next(item for item in report.context["rapports"] if item["label"] == "Évaluation indépendante")
        person_metric = next(item for item in evaluation_report["metrics"] if item["label"] == "Personne")
        self.assertEqual(person_metric["expected"], 2)
        self.assertEqual(person_metric["precision"], 50)
        self.assertEqual(person_metric["recall"], 50)
        self.assertEqual(evaluation_report["cpu_average"], 25)
        self.assertEqual(evaluation_report["ram_peak"], 512)

    def test_reports_do_not_mix_calibration_and_evaluation(self):
        calibration = self.completed_campaign("calibration")
        evaluation = self.completed_campaign("evaluation")
        for campaign, expected, correct in ((calibration, 10, 10), (evaluation, 2, 1)):
            for class_name in ("person", "dog", "cat"):
                AnnotationClasseEvaluation.objects.create(
                    campagne=campaign,
                    classe=class_name,
                    occurrences_attendues=expected if class_name == "person" else 0,
                    vrais_positifs=correct if class_name == "person" else 0,
                    faux_positifs=0,
                    annotee_par=self.owner,
                )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))

        reports = {item["label"]: item["metrics"] for item in response.context["rapports"]}
        calibration_person = next(item for item in reports["Ajustement des seuils"] if item["label"] == "Personne")
        evaluation_person = next(item for item in reports["Évaluation indépendante"] if item["label"] == "Personne")
        self.assertEqual(calibration_person["recall"], 100)
        self.assertEqual(evaluation_person["recall"], 50)

    def test_false_alert_rate_uses_annotated_camera_hours(self):
        campaign = self.completed_campaign("evaluation", duration_seconds=3600)
        for class_name, false_positives in (("person", 1), ("dog", 0), ("cat", 0)):
            AnnotationClasseEvaluation.objects.create(
                campagne=campaign,
                classe=class_name,
                occurrences_attendues=0,
                vrais_positifs=0,
                faux_positifs=false_positives,
                annotee_par=self.owner,
            )
        self.client.force_login(self.owner)

        response = self.client.get(reverse("camera-evaluation", kwargs={"pk": self.camera.pk}))

        evaluation_report = next(item for item in response.context["rapports"] if item["label"] == "Évaluation indépendante")
        self.assertEqual(evaluation_report["duration_hours"], 1)
        self.assertEqual(evaluation_report["false_alerts"], 1)
        self.assertEqual(evaluation_report["false_alerts_per_hour"], 1)
        self.assertContains(response, 'class="evaluation-reports"')

    def test_annotation_rejects_more_correct_detections_than_expected(self):
        campaign = self.completed_campaign()
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse(
                "camera-evaluation-annotation",
                kwargs={"pk": self.camera.pk, "campagne_pk": campaign.pk},
            ),
            self.annotation_payload(person_attendues=1, person_correctes=2),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ne peuvent pas dépasser")
        self.assertFalse(AnnotationClasseEvaluation.objects.filter(campagne=campaign).exists())

    def test_other_user_cannot_annotate_campaign(self):
        campaign = self.completed_campaign()
        self.client.force_login(self.other)

        response = self.client.get(
            reverse(
                "camera-evaluation-annotation",
                kwargs={"pk": self.camera.pk, "campagne_pk": campaign.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
