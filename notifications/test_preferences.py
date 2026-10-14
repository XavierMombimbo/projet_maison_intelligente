import uuid
from datetime import datetime, time, timezone
from unittest.mock import Mock, patch

from django.test import Client, TestCase
from django.urls import reverse

from accounts.mobile_security import issue_session_tokens
from accounts.models import User
from homes.models import Camera, Evenement, Maison, ObjetDetecte, TypeEvenement
from notifications.models import CameraPushPreference, PushDelivery, PushDeliveryStatus
from notifications.preferences import allows_push
from notifications.services import dispatch_push_delivery, enqueue_push_deliveries, register_installation
from notifications.views import CameraPushPreferenceForm


class CameraPushPreferenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("prefs-owner", "owner@example.test", password="TestPassword123!")
        self.other = User.objects.create_user("prefs-other", "other@example.test", password="TestPassword123!")
        self.house = Maison.objects.create(nom="Maison", proprietaire=self.user)
        self.camera = Camera.objects.create(nom="Entree", maison=self.house)
        self.event = Evenement.objects.create(
            client_event_id=uuid.uuid4(), camera=self.camera, maison=self.house,
            type=TypeEvenement.PERSONNE_DETECTEE, confiance_ia=0.9,
        )
        session, _, _ = issue_session_tokens(self.user, device_id="prefs-phone", device_name="Phone")
        register_installation(session=session, token="prefs-token", platform="android", permission="granted")
        self.url = reverse("camera-push-preferences", args=[self.camera.pk])

    def test_defaults_keep_delivery_and_get_does_not_write(self):
        self.client.force_login(self.user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"]["enabled"].value())
        self.assertFalse(CameraPushPreference.objects.exists())
        self.assertEqual(enqueue_push_deliveries(self.event.pk), 1)

    def test_muting_preserves_event_and_camera(self):
        self.client.force_login(self.user)
        response = self.client.post(self.url, {"people": "on", "objects_enabled": "on"})
        self.assertRedirects(response, self.url)
        self.assertEqual(enqueue_push_deliveries(self.event.pk), 0)
        self.assertTrue(Evenement.objects.filter(pk=self.event.pk).exists())
        self.camera.refresh_from_db()
        self.assertEqual(self.camera.maison, self.house)

    def test_category_filter_and_reenable(self):
        pref = CameraPushPreference.objects.create(user=self.user, camera=self.camera, people=False)
        self.assertFalse(allows_push(self.user, self.event))
        self.event.type = TypeEvenement.OBJETS_DETECTES
        self.assertTrue(allows_push(self.user, self.event))
        pref.objects_enabled = False
        pref.save()
        self.assertFalse(allows_push(self.user, self.event))
        pref.objects_enabled = True
        pref.save()
        self.assertTrue(allows_push(self.user, self.event))

    def test_v2_person_detection_follows_people_preference(self):
        self.event.type = TypeEvenement.OBJETS_DETECTES
        self.event.save(update_fields=("type",))
        ObjetDetecte.objects.create(
            evenement=self.event, classe="person", confiance=0.9,
            boite=[0.1, 0.1, 0.5, 0.5],
        )
        pref = CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, people=True, objects_enabled=False,
        )
        self.assertEqual(enqueue_push_deliveries(self.event.pk), 1)
        pref.people = False
        pref.objects_enabled = True
        pref.save()
        self.assertFalse(allows_push(self.user, self.event))

    def test_v2_mixed_detection_follows_either_enabled_category(self):
        self.event.type = TypeEvenement.OBJETS_DETECTES
        self.event.save(update_fields=("type",))
        for label in ("person", "dog"):
            ObjetDetecte.objects.create(
                evenement=self.event, classe=label, confiance=0.9,
                boite=[0.1, 0.1, 0.5, 0.5],
            )
        pref = CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, people=False, objects_enabled=True,
        )
        self.assertTrue(allows_push(self.user, self.event))
        pref.people = True
        pref.objects_enabled = False
        pref.save()
        self.assertTrue(allows_push(self.user, self.event))
        pref.people = False
        pref.save()
        self.assertFalse(allows_push(self.user, self.event))

    def test_mute_cancels_queued_delivery_before_provider_call(self):
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()
        CameraPushPreference.objects.create(user=self.user, camera=self.camera, enabled=False)
        provider = Mock()
        self.assertFalse(dispatch_push_delivery(delivery.pk, provider=provider))
        provider.send.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, PushDeliveryStatus.CANCELLED)
        self.assertEqual(delivery.attempts, 0)

    def test_preferences_are_scoped_to_user_and_camera(self):
        CameraPushPreference.objects.create(user=self.other, camera=self.camera, enabled=False)
        second = Camera.objects.create(nom="Autre", maison=self.house)
        CameraPushPreference.objects.create(user=self.user, camera=second, enabled=False)
        self.assertTrue(allows_push(self.user, self.event))

    def test_outsider_cannot_read_or_change_preferences(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {}).status_code, 404)
        self.assertFalse(CameraPushPreference.objects.exists())

    def test_post_ignores_forged_user_and_camera(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {"user": self.other.pk, "camera": uuid.uuid4(), "enabled": "on"})
        preference = CameraPushPreference.objects.get()
        self.assertEqual(preference.user, self.user)
        self.assertEqual(preference.camera, self.camera)

    def test_csrf_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url, {}).status_code, 403)
        self.assertFalse(CameraPushPreference.objects.exists())

    def test_overnight_quiet_hours_use_house_timezone_and_exclude_end(self):
        CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, quiet_start=time(22), quiet_end=time(7),
        )
        # Kinshasa is UTC+1: start inclusive, end exclusive.
        for hour, minute, expected in ((20, 59, True), (21, 0, False), (0, 0, False), (6, 0, True)):
            with self.subTest(hour=hour, minute=minute):
                self.assertEqual(allows_push(
                    self.user, self.event, now=datetime(2026, 10, 7, hour, minute, tzinfo=timezone.utc),
                ), expected)

    def test_daytime_quiet_hours(self):
        CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, quiet_start=time(12), quiet_end=time(14),
        )
        for hour, expected in ((10, True), (11, False), (12, False), (13, True)):
            with self.subTest(hour=hour):
                self.assertEqual(allows_push(
                    self.user, self.event, now=datetime(2026, 10, 7, hour, tzinfo=timezone.utc),
                ), expected)

    def test_delivery_entering_quiet_hours_is_cancelled(self):
        CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, quiet_start=time(22), quiet_end=time(7),
        )
        with patch("notifications.preferences.timezone.now", return_value=datetime(2026, 10, 7, 12, tzinfo=timezone.utc)):
            self.assertEqual(enqueue_push_deliveries(self.event.pk), 1)
        delivery = PushDelivery.objects.get()
        provider = Mock()
        with patch("notifications.preferences.timezone.now", return_value=datetime(2026, 10, 7, 22, tzinfo=timezone.utc)):
            self.assertFalse(dispatch_push_delivery(delivery.pk, provider=provider))
        provider.send.assert_not_called()
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, PushDeliveryStatus.CANCELLED)

    def test_urgent_exception_does_not_override_category_or_camera(self):
        pref = CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, quiet_start=time(22), quiet_end=time(7),
        )
        now = datetime(2026, 10, 7, 22, tzinfo=timezone.utc)
        self.event.priorite_alerte = 100
        self.assertFalse(allows_push(self.user, self.event, now=now))
        pref.urgent_during_quiet = True
        pref.save()
        self.assertTrue(allows_push(self.user, self.event, now=now))
        self.event.priorite_alerte = 80
        self.assertFalse(allows_push(self.user, self.event, now=now))
        self.event.priorite_alerte = 100
        pref.people = False
        pref.save()
        self.assertFalse(allows_push(self.user, self.event, now=now))
        pref.people, pref.enabled = True, False
        pref.save()
        self.assertFalse(allows_push(self.user, self.event, now=now))

    def test_quiet_form_rejects_partial_equal_and_invalid_hours(self):
        for data in (
            {"quiet_start": "22:00"}, {"quiet_end": "07:00"},
            {"quiet_start": "07:00", "quiet_end": "07:00"},
            {"quiet_start": "bad", "quiet_end": "07:00"},
        ):
            with self.subTest(data=data):
                self.assertFalse(CameraPushPreferenceForm(data).is_valid())
        self.assertTrue(CameraPushPreferenceForm({}).is_valid())

    def test_save_quiet_hours_then_clear_them(self):
        self.client.force_login(self.user)
        self.client.post(self.url, {
            "enabled": "on", "people": "on", "objects_enabled": "on",
            "quiet_start": "22:00", "quiet_end": "07:00", "urgent_during_quiet": "on",
        })
        pref = CameraPushPreference.objects.get()
        self.assertEqual(pref.quiet_start, time(22))
        self.assertEqual(pref.quiet_end, time(7))
        self.assertTrue(pref.urgent_during_quiet)
        self.client.post(self.url, {"enabled": "on", "people": "on"})
        pref.refresh_from_db()
        self.assertIsNone(pref.quiet_start)
        self.assertIsNone(pref.quiet_end)

    def test_quiet_hours_follow_daylight_saving(self):
        self.house.fuseau_horaire = "Europe/Paris"
        self.house.save()
        self.event.maison = self.house
        CameraPushPreference.objects.create(
            user=self.user, camera=self.camera, quiet_start=time(2), quiet_end=time(3),
        )
        for hour in (0, 1):
            self.assertFalse(allows_push(
                self.user, self.event, now=datetime(2026, 10, 25, hour, 30, tzinfo=timezone.utc),
            ))
