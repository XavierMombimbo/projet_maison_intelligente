from datetime import datetime, time, timedelta, timezone as datetime_timezone
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gateway.schedule import evaluate_schedule, verify_schedule
from accounts.models import User
from .models import (
    Camera,
    DerogationSurveillance,
    ExceptionSurveillance,
    JournalAudit,
    Maison,
    PlageSurveillance,
)
from .scheduling import effective_camera_monitoring, evaluate_surveillance
from .services import consume_pairing_code, create_pairing_code


class SchedulingRulesTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "schedule-owner", "schedule@example.test", "Secret!2026"
        )
        self.house = Maison.objects.create(
            nom="Maison planning",
            proprietaire=self.owner,
            fuseau_horaire="Africa/Kinshasa",
        )

    def test_window_crossing_midnight_uses_house_timezone(self):
        PlageSurveillance.objects.create(
            maison=self.house,
            nom="Nuit",
            jour=0,
            heure_debut=time(23, 0),
            heure_fin=time(1, 0),
        )

        monday_evening = datetime(2026, 9, 21, 22, 30, tzinfo=datetime_timezone.utc)
        tuesday_early = datetime(2026, 9, 21, 23, 30, tzinfo=datetime_timezone.utc)
        tuesday_late = datetime(2026, 9, 22, 1, 0, tzinfo=datetime_timezone.utc)

        self.assertTrue(evaluate_surveillance(self.house, at=monday_evening).active)
        self.assertTrue(evaluate_surveillance(self.house, at=tuesday_early).active)
        self.assertFalse(evaluate_surveillance(self.house, at=tuesday_late).active)

    def test_exception_priority_is_deterministic(self):
        now = timezone.now()
        ExceptionSurveillance.objects.create(
            maison=self.house,
            nom="Activation basse",
            date_debut=now - timedelta(hours=1),
            date_fin=now + timedelta(hours=1),
            surveillance_active=True,
            priorite=10,
        )
        ExceptionSurveillance.objects.create(
            maison=self.house,
            nom="Arrêt prioritaire",
            date_debut=now - timedelta(hours=1),
            date_fin=now + timedelta(hours=1),
            surveillance_active=False,
            priorite=20,
        )

        decision = evaluate_surveillance(self.house, at=now)

        self.assertFalse(decision.active)
        self.assertEqual(decision.source, "exception")
        self.assertEqual(decision.libelle, "Arrêt prioritaire")

    def test_manual_override_wins_then_expires(self):
        now = timezone.now()
        ExceptionSurveillance.objects.create(
            maison=self.house,
            nom="Maintenance",
            date_debut=now - timedelta(hours=1),
            date_fin=now + timedelta(hours=1),
            surveillance_active=False,
            priorite=100,
        )
        override = DerogationSurveillance.objects.create(
            maison=self.house,
            surveillance_active=True,
            expire_le=now + timedelta(minutes=30),
            creee_par=self.owner,
        )

        self.assertEqual(evaluate_surveillance(self.house, at=now).source, "manual")
        override.expire_le = now - timedelta(seconds=1)
        override.save(update_fields=("expire_le",))
        self.assertEqual(evaluate_surveillance(self.house, at=now).source, "exception")

    def test_camera_without_schedule_keeps_explicit_switch(self):
        camera = Camera.objects.create(nom="Salon", maison=self.house)
        camera.surveillance_active = True
        self.assertEqual(effective_camera_monitoring(camera), (True, "camera"))
        camera.surveillance_active = False
        self.assertEqual(effective_camera_monitoring(camera), (False, "camera"))

    def test_camera_state_applies_schedule_and_manual_exception(self):
        camera = Camera.objects.create(nom="Salon", maison=self.house)
        camera.surveillance_active = True
        camera.save(update_fields=("surveillance_active",))
        _, code = create_pairing_code(camera)
        credentials = consume_pairing_code(code)
        token = credentials.access_token
        monday = datetime(2026, 9, 21, 19, 30, tzinfo=datetime_timezone.utc)
        PlageSurveillance.objects.create(
            maison=self.house, nom="Soir", jour=0,
            heure_debut=time(20), heure_fin=time(21),
        )

        def state_at(moment):
            with patch("homes.scheduling.timezone.now", return_value=moment):
                return self.client.get(
                    reverse("api-camera-state"),
                    HTTP_AUTHORIZATION=f"Bearer {token}",
                )

        active = state_at(monday)
        self.assertEqual(active.status_code, 200)
        self.assertTrue(active.json()["monitoring_active"])
        self.assertEqual(active.json()["monitoring_source"], "schedule")
        manifest = active.json()["schedule"]
        payload = verify_schedule(
            manifest, camera_id=camera.pk, key=credentials.event_signing_key,
        )
        self.assertEqual(evaluate_schedule(payload, at=monday), (True, "schedule"))
        ack = self.client.post(
            reverse("api-camera-heartbeat"),
            {"monitoring_active": True, "schedule_version": manifest["version"]},
            content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(ack.status_code, 200)
        camera.refresh_from_db()
        self.assertEqual(camera.version_planning_appliquee, manifest["version"])
        self.client.force_login(self.owner)
        detail = self.client.get(reverse("camera-detail", kwargs={"pk": camera.pk}))
        self.assertContains(detail, "Dernier état confirmé")
        self.assertContains(detail, "Active ·")
        self.client.logout()

        stopped = state_at(monday + timedelta(hours=1))
        self.assertFalse(stopped.json()["monitoring_active"])
        self.assertEqual(stopped.json()["monitoring_source"], "default")

        DerogationSurveillance.objects.create(
            maison=self.house, surveillance_active=False,
            expire_le=monday + timedelta(minutes=15), creee_par=self.owner,
        )
        overridden = state_at(monday)
        self.assertFalse(overridden.json()["monitoring_active"])
        self.assertEqual(overridden.json()["monitoring_source"], "manual")
        self.assertNotEqual(overridden.json()["schedule"]["version"], manifest["version"])
        stale_ack = self.client.post(
            reverse("api-camera-heartbeat"),
            {"monitoring_active": True, "schedule_version": manifest["version"]},
            content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}",
        )
        self.assertEqual(stale_ack.status_code, 409)

        camera.surveillance_active = False
        camera.save(update_fields=("surveillance_active",))
        disabled = state_at(monday)
        self.assertFalse(disabled.json()["monitoring_active"])
        self.assertEqual(disabled.json()["monitoring_source"], "camera")


class SchedulingViewsTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            "planning-owner", "owner@example.test", "Secret!2026"
        )
        self.other = User.objects.create_user(
            "planning-other", "other@example.test", "Secret!2026"
        )
        self.house = Maison.objects.create(nom="Maison UI", proprietaire=self.owner)

    def test_owner_can_create_update_and_delete_window_with_audit(self):
        self.client.force_login(self.owner)
        create = self.client.post(
            reverse("schedule-window-create", kwargs={"maison_pk": self.house.pk}),
            {
                "nom": "Soir",
                "jour": 4,
                "heure_debut": "20:00",
                "heure_fin": "06:00",
                "active": "on",
            },
        )
        window = PlageSurveillance.objects.get(maison=self.house)
        self.assertRedirects(create, reverse("planning-detail", kwargs={"pk": self.house.pk}))

        update = self.client.post(
            reverse(
                "schedule-window-update",
                kwargs={"maison_pk": self.house.pk, "plage_pk": window.pk},
            ),
            {
                "nom": "Nuit",
                "jour": 4,
                "heure_debut": "21:00",
                "heure_fin": "06:00",
                "active": "on",
            },
        )
        self.assertRedirects(update, reverse("planning-detail", kwargs={"pk": self.house.pk}))
        window.refresh_from_db()
        self.assertEqual(window.nom, "Nuit")

        delete = self.client.post(
            reverse(
                "schedule-window-delete",
                kwargs={"maison_pk": self.house.pk, "plage_pk": window.pk},
            )
        )
        self.assertRedirects(delete, reverse("planning-detail", kwargs={"pk": self.house.pk}))
        self.assertFalse(PlageSurveillance.objects.filter(pk=window.pk).exists())
        self.assertEqual(
            set(
                JournalAudit.objects.filter(action__startswith="schedule.window").values_list(
                    "action", flat=True
                )
            ),
            {
                "schedule.window.create",
                "schedule.window.update",
                "schedule.window.delete",
            },
        )

    def test_owner_sets_simple_daily_start_and_stop_times(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("schedule-daily-update", kwargs={"maison_pk": self.house.pk}),
            {"heure_activation": "20:00", "heure_arret": "06:00"},
        )

        self.assertRedirects(response, reverse("planning-detail", kwargs={"pk": self.house.pk}))
        windows = PlageSurveillance.objects.filter(
            maison=self.house, nom="Planning quotidien"
        )
        self.assertEqual(windows.count(), 7)
        self.assertEqual(set(windows.values_list("jour", flat=True)), set(range(7)))
        self.assertTrue(all(item.heure_debut == time(20, 0) for item in windows))
        self.assertTrue(all(item.heure_fin == time(6, 0) for item in windows))
        self.assertTrue(
            JournalAudit.objects.filter(action="schedule.daily.update").exists()
        )

        self.client.post(
            reverse("schedule-daily-update", kwargs={"maison_pk": self.house.pk}),
            {"heure_activation": "21:00", "heure_arret": "07:00"},
        )
        windows = PlageSurveillance.objects.filter(
            maison=self.house, nom="Planning quotidien"
        )
        self.assertEqual(windows.count(), 7)
        self.assertTrue(all(item.heure_debut == time(21, 0) for item in windows))

    def test_non_owner_cannot_change_schedule(self):
        self.client.force_login(self.other)
        response = self.client.post(
            reverse("schedule-window-create", kwargs={"maison_pk": self.house.pk}),
            {
                "nom": "Interdit",
                "jour": 0,
                "heure_debut": "08:00",
                "heure_fin": "18:00",
                "active": "on",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(PlageSurveillance.objects.filter(maison=self.house).exists())

        daily = self.client.post(
            reverse("schedule-daily-update", kwargs={"maison_pk": self.house.pk}),
            {"heure_activation": "20:00", "heure_arret": "06:00"},
        )
        self.assertEqual(daily.status_code, 404)

    def test_owner_sets_expiring_manual_override(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("schedule-override-update", kwargs={"maison_pk": self.house.pk}),
            {"surveillance_active": "False", "duree_minutes": "30"},
        )
        self.assertRedirects(response, reverse("planning-detail", kwargs={"pk": self.house.pk}))
        override = DerogationSurveillance.objects.get(maison=self.house)
        self.assertFalse(override.surveillance_active)
        self.assertGreater(override.expire_le, timezone.now() + timedelta(minutes=29))
        self.assertTrue(
            JournalAudit.objects.filter(action="schedule.override.set", maison=self.house).exists()
        )

    def test_exception_input_uses_house_timezone(self):
        self.house.fuseau_horaire = "America/New_York"
        self.house.save(update_fields=("fuseau_horaire",))
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse("schedule-exception-create", kwargs={"maison_pk": self.house.pk}),
            {
                "nom": "Visite",
                "date_debut": "2026-09-25T12:00",
                "date_fin": "2026-09-25T13:00",
                "surveillance_active": "False",
                "priorite": "50",
            },
        )

        self.assertRedirects(response, reverse("planning-detail", kwargs={"pk": self.house.pk}))
        exception = ExceptionSurveillance.objects.get(maison=self.house)
        self.assertEqual(
            exception.date_debut,
            datetime(2026, 9, 25, 16, 0, tzinfo=datetime_timezone.utc),
        )
        self.assertTrue(
            JournalAudit.objects.filter(action="schedule.exception.create").exists()
        )

    def test_schedule_page_exposes_current_decision(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("planning-detail", kwargs={"pk": self.house.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Activation automatique")
        self.assertContains(response, "Heure d’activation")
        self.assertContains(response, "Heure d’arrêt")
        self.assertContains(response, "Hors plage planifiée")
