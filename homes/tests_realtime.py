import uuid

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse

from accounts.models import User
from config.asgi import application
from .models import (
    AccesCamera,
    Camera,
    Evenement,
    Maison,
    MembreMaison,
    RoleMaison,
    StatutEvenement,
    StatutInvitation,
    TypeEvenement,
)
from .realtime import alert_group_name


class AlertWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.owner_a = User.objects.create_user("ws-a", "ws-a@example.test", "Secret!2026")
        self.owner_b = User.objects.create_user("ws-b", "ws-b@example.test", "Secret!2026")
        self.limited_member = User.objects.create_user(
            "ws-limited", "ws-limited@example.test", "Secret!2026"
        )
        self.house_a = Maison.objects.create(nom="Maison WebSocket A", proprietaire=self.owner_a)
        self.house_b = Maison.objects.create(nom="Maison WebSocket B", proprietaire=self.owner_b)
        self.camera_a = Camera.objects.create(nom="Entrée A", maison=self.house_a)
        self.camera_b = Camera.objects.create(nom="Entrée B", maison=self.house_b)
        self.shared_camera = Camera.objects.create(nom="Salon partagé", maison=self.house_a)
        membership = MembreMaison.objects.create(
            maison=self.house_a,
            utilisateur=self.limited_member,
            role=RoleMaison.INVITE,
            statut=StatutInvitation.ACCEPTEE,
        )
        AccesCamera.objects.create(
            membre=membership,
            camera=self.shared_camera,
            peut_voir=True,
            peut_controler=False,
        )
        self.event_a = Evenement.objects.create(
            client_event_id=uuid.uuid4(),
            camera=self.camera_a,
            maison=self.house_a,
            type=TypeEvenement.PERSONNE_DETECTEE,
            confiance_ia=0.88,
        )

    def session_headers(self, user):
        client = Client()
        client.force_login(user)
        session_id = client.cookies[settings.SESSION_COOKIE_NAME].value
        cookie = f"{settings.SESSION_COOKIE_NAME}={session_id}".encode("ascii")
        return [(b"cookie", cookie), (b"origin", b"http://testserver")]

    def test_alert_is_delivered_only_to_authorized_house(self):
        headers_a = self.session_headers(self.owner_a)
        headers_b = self.session_headers(self.owner_b)
        async_to_sync(self._assert_house_isolation)(headers_a, headers_b)

    async def _assert_house_isolation(self, headers_a, headers_b):
        socket_a = WebsocketCommunicator(
            application, "/ws/alerts/", headers=headers_a
        )
        socket_b = WebsocketCommunicator(
            application, "/ws/alerts/", headers=headers_b
        )
        connected_a, _ = await socket_a.connect()
        connected_b, _ = await socket_b.connect()
        self.assertTrue(connected_a)
        self.assertTrue(connected_b)
        self.assertEqual((await socket_a.receive_json_from())["house_count"], 1)
        self.assertEqual((await socket_b.receive_json_from())["house_count"], 1)

        payload = {
            "event_id": str(self.event_a.pk),
            "house_id": self.house_a.pk,
            "camera_name": "Entrée",
        }
        await get_channel_layer().group_send(
            alert_group_name(self.house_a.pk),
            {"type": "alert.created", "payload": payload},
        )

        message = await socket_a.receive_json_from()
        self.assertEqual(message["type"], "alert.created")
        self.assertEqual(message["house_id"], self.house_a.pk)
        self.assertTrue(await socket_b.receive_nothing(timeout=0.15))
        await socket_a.disconnect()
        await socket_b.disconnect()

    def test_anonymous_connection_is_rejected(self):
        async_to_sync(self._assert_anonymous_rejected)()

    async def _assert_anonymous_rejected(self):
        socket = WebsocketCommunicator(
            application,
            "/ws/alerts/",
            headers=[(b"origin", b"http://testserver")],
        )
        connected, close_code = await socket.connect()
        self.assertFalse(connected)
        self.assertEqual(close_code, 4401)

    def test_member_does_not_receive_alert_for_unauthorized_camera(self):
        headers = self.session_headers(self.limited_member)
        async_to_sync(self._assert_camera_isolation)(headers)

    async def _assert_camera_isolation(self, headers):
        socket = WebsocketCommunicator(application, "/ws/alerts/", headers=headers)
        connected, _ = await socket.connect()
        self.assertTrue(connected)
        self.assertEqual((await socket.receive_json_from())["house_count"], 1)
        await get_channel_layer().group_send(
            alert_group_name(self.house_a.pk),
            {
                "type": "alert.created",
                "payload": {
                    "event_id": str(self.event_a.pk),
                    "house_id": self.house_a.pk,
                    "camera_name": self.camera_a.nom,
                },
            },
        )
        self.assertTrue(await socket.receive_nothing(timeout=0.15))
        await socket.disconnect()


class AlertDecisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user(
            "decision-owner", "decision-owner@example.test", "Secret!2026"
        )
        cls.controller = User.objects.create_user(
            "controller", "controller@example.test", "Secret!2026"
        )
        cls.viewer = User.objects.create_user(
            "viewer", "viewer@example.test", "Secret!2026"
        )
        cls.outsider = User.objects.create_user(
            "outsider", "outsider@example.test", "Secret!2026"
        )
        cls.house = Maison.objects.create(nom="Maison Décisions", proprietaire=cls.owner)
        cls.camera = Camera.objects.create(nom="Porte", maison=cls.house)
        for user, can_control in ((cls.controller, True), (cls.viewer, False)):
            member = MembreMaison.objects.create(
                maison=cls.house,
                utilisateur=user,
                role=RoleMaison.FAMILLE,
                statut=StatutInvitation.ACCEPTEE,
            )
            AccesCamera.objects.create(
                membre=member,
                camera=cls.camera,
                peut_voir=True,
                peut_controler=can_control,
            )

    def make_event(self):
        return Evenement.objects.create(
            client_event_id=uuid.uuid4(),
            camera=self.camera,
            maison=self.house,
            type=TypeEvenement.PERSONNE_DETECTEE,
            confiance_ia=0.9,
        )

    def decide(self, user, event, decision):
        self.client.force_login(user)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(
                reverse("event-decision", kwargs={"pk": event.pk}),
                {"decision": decision},
            )

    def test_owner_can_confirm_intrusion(self):
        event = self.make_event()
        response = self.decide(self.owner, event, "confirmed")

        self.assertRedirects(response, reverse("event-detail", kwargs={"pk": event.pk}))
        event.refresh_from_db()
        self.assertEqual(event.statut, StatutEvenement.INTRUSION_CONFIRMEE)

    def test_explicit_controller_can_mark_false_alarm(self):
        event = self.make_event()
        response = self.decide(self.controller, event, "false_alarm")

        self.assertEqual(response.status_code, 302)
        event.refresh_from_db()
        self.assertEqual(event.statut, StatutEvenement.FAUSSE_ALERTE)

    def test_view_only_member_cannot_decide(self):
        event = self.make_event()
        response = self.decide(self.viewer, event, "confirmed")

        self.assertEqual(response.status_code, 404)
        event.refresh_from_db()
        self.assertEqual(event.statut, StatutEvenement.NOUVEAU)

    def test_outsider_cannot_decide(self):
        event = self.make_event()
        response = self.decide(self.outsider, event, "confirmed")

        self.assertEqual(response.status_code, 404)
        event.refresh_from_db()
        self.assertEqual(event.statut, StatutEvenement.NOUVEAU)

    def test_invalid_decision_is_rejected(self):
        event = self.make_event()
        response = self.decide(self.owner, event, "erase")

        self.assertEqual(response.status_code, 400)
        event.refresh_from_db()
        self.assertEqual(event.statut, StatutEvenement.NOUVEAU)

    def test_processed_alert_cannot_be_reclassified(self):
        event = self.make_event()
        event.statut = StatutEvenement.FAUSSE_ALERTE
        event.save(update_fields=("statut",))

        response = self.decide(self.owner, event, "confirmed")

        self.assertEqual(response.status_code, 409)
        event.refresh_from_db()
        self.assertEqual(event.statut, StatutEvenement.FAUSSE_ALERTE)

    def test_dashboard_exposes_realtime_and_sound_controls(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("dashboard"))

        self.assertContains(response, "alertes en temps réel")
        self.assertContains(response, "Activer la sirène")
        self.assertContains(response, "/ws/alerts/")
