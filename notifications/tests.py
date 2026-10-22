import uuid
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.mobile_security import issue_session_tokens
from accounts.models import User
from homes.models import Camera, Evenement, Maison, TypeEvenement

from .crypto import decrypt_token
from .models import CameraPushPreference, PushDelivery, PushDeliveryStatus, PushInstallation, PushPermission
from .services import (
    FirebasePushProvider,
    PushProviderError,
    PushTokenInvalid,
    dispatch_push_delivery,
    enqueue_push_deliveries,
    register_installation,
)


class AcceptingProvider:
    def send(self, delivery):
        return f"projects/test/messages/{delivery.pk}"


class FailingProvider:
    def send(self, delivery):
        raise PushProviderError("fournisseur indisponible")


class InvalidTokenProvider:
    def send(self, delivery):
        raise PushTokenInvalid("jeton non enregistré")


@override_settings(PUSH_MAX_ATTEMPTS=2, PUSH_RETRY_BASE_SECONDS=1)
class PushNotificationTests(TestCase):
    def test_combined_alert_text_keeps_personal_lock_screen_visibility(self):
        from firebase_admin import exceptions, messaging
        from homes.weapon_messages import PERSON_WEAPON_TITLE
        self.event.metadonnees = {"weapon_verification": {"state": "suspected", "person_associated": True}}
        self.event.save(update_fields=["metadonnees"])
        self.register()
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()
        provider = FirebasePushProvider()
        with patch.object(provider, "_messaging", return_value=(messaging, exceptions, None)), patch.object(
            messaging, "send", return_value="message-id") as send:
            provider.send(delivery)
        message = send.call_args.args[0]
        self.assertEqual(message.notification.body, PERSON_WEAPON_TITLE)
        self.assertEqual(message.data["person_weapon_suspicion"], "true")
        self.assertEqual(message.android.notification.visibility, "private")

    def test_android_notification_uses_audible_alert_channel(self):
        from firebase_admin import exceptions, messaging

        self.register()
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()
        provider = FirebasePushProvider()
        with patch.object(provider, "_messaging", return_value=(messaging, exceptions, None)), patch.object(
            messaging, "send", return_value="message-id"
        ) as send:
            provider.send(delivery)
        message = send.call_args.args[0]
        self.assertEqual(message.android.priority, "high")
        self.assertEqual(message.android.notification.channel_id, "sentinelle_alerts")
        self.assertEqual(message.android.notification.sound, "default")
        self.assertEqual(message.android.notification.tag, str(delivery.pk))
        self.assertEqual(message.notification.body, "Une nouvelle alerte est disponible.")
        self.assertEqual(message.android.notification.visibility, "private")
        self.assertEqual(message.data['lock_screen'], "private")

    def test_lock_screen_choice_is_personal_and_read_at_send_time(self):
        from firebase_admin import exceptions, messaging

        self.register()
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()
        provider = FirebasePushProvider()
        for visibility in ('secret', 'public', 'private'):
            CameraPushPreference.objects.update_or_create(user=self.user, camera=self.camera,
                defaults={'lock_screen': visibility})
            with patch.object(provider, '_messaging', return_value=(messaging, exceptions, None)), patch.object(
                messaging, 'send', return_value='message-id'
            ) as send:
                provider.send(delivery)
            message = send.call_args.args[0]
            self.assertEqual(message.android.notification.visibility, visibility)
            self.assertEqual(message.data, {'type': 'alert.created', 'event_id': str(self.event.pk),
                'delivery_id': str(delivery.pk), 'lock_screen': visibility})
            self.assertEqual(message.notification.body, 'Une nouvelle alerte est disponible.')

    def setUp(self):
        self.user = User.objects.create_user(
            username="push-user",
            email="push@example.test",
            password="UnePhraseSecrete!2026",
        )
        self.house = Maison.objects.create(nom="Maison push", proprietaire=self.user)
        self.camera = Camera.objects.create(nom="Entrée", maison=self.house)
        self.event = Evenement.objects.create(
            client_event_id=uuid.uuid4(),
            camera=self.camera,
            maison=self.house,
            type=TypeEvenement.PERSONNE_DETECTEE,
            confiance_ia=0.92,
        )
        self.session, self.access_token, _refresh = issue_session_tokens(
            self.user,
            device_id="android-push-test",
            device_name="Téléphone push",
        )

    def auth(self):
        return {"HTTP_AUTHORIZATION": f"Bearer {self.access_token}"}

    def register(self, token="fcm-token-secret-123"):
        return register_installation(
            session=self.session,
            token=token,
            platform="android",
            permission=PushPermission.GRANTED,
        )

    def test_mobile_api_encrypts_registration_token_and_never_returns_it(self):
        token = "fcm-token-secret-123"
        response = self.client.put(
            reverse("mobile-api:push-installation"),
            {"platform": "android", "permission": "granted", "token": token},
            content_type="application/json",
            **self.auth(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("token", response.json())
        installation = PushInstallation.objects.get(session=self.session)
        self.assertNotEqual(bytes(installation.token_ciphertext), token.encode())
        self.assertEqual(
            decrypt_token(
                bytes(installation.token_ciphertext),
                bytes(installation.token_nonce),
                self.session.pk,
            ),
            token,
        )

    def test_permission_denied_keeps_no_token(self):
        self.register()
        response = self.client.put(
            reverse("mobile-api:push-installation"),
            {"platform": "android", "permission": "denied"},
            content_type="application/json",
            **self.auth(),
        )

        self.assertEqual(response.status_code, 200)
        installation = PushInstallation.objects.get(session=self.session)
        self.assertFalse(installation.active)
        self.assertEqual(installation.permission, PushPermission.DENIED)
        self.assertIsNone(installation.token_ciphertext)
        self.assertIsNone(installation.token_digest)

    def test_same_token_is_rotated_to_the_latest_session_only(self):
        first = self.register("rotating-token")
        second_session, _access, _refresh = issue_session_tokens(
            self.user,
            device_id="android-push-second",
            device_name="Téléphone B",
        )

        second = register_installation(
            session=second_session,
            token="rotating-token",
            platform="android",
            permission=PushPermission.GRANTED,
        )

        first.refresh_from_db()
        self.assertFalse(first.active)
        self.assertIsNone(first.token_digest)
        self.assertTrue(second.active)

    def test_revoking_session_dissociates_installation(self):
        self.register()
        response = self.client.post(
            reverse("mobile-api:session-revoke", args=[self.session.pk]),
            **self.auth(),
        )

        self.assertEqual(response.status_code, 204)
        installation = PushInstallation.objects.get(session=self.session)
        self.assertFalse(installation.active)
        self.assertIsNone(installation.token_digest)

    def test_delivery_is_created_only_for_an_authorized_active_installation(self):
        installation = self.register()
        stranger = User.objects.create_user("stranger-push", password="Secret!2026")
        stranger_session, _access, _refresh = issue_session_tokens(
            stranger,
            device_id="stranger-phone",
            device_name="Téléphone étranger",
        )
        register_installation(
            session=stranger_session,
            token="stranger-token",
            platform="android",
            permission=PushPermission.GRANTED,
        )

        created = enqueue_push_deliveries(self.event.pk)

        self.assertEqual(created, 1)
        delivery = PushDelivery.objects.get()
        self.assertEqual(delivery.installation, installation)
        self.assertEqual(delivery.recipient, self.user)

    def test_provider_acceptance_and_phone_receipt_are_distinct(self):
        self.register()
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()

        self.assertTrue(dispatch_push_delivery(delivery.pk, provider=AcceptingProvider()))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, PushDeliveryStatus.ACCEPTED)
        self.assertIsNotNone(delivery.provider_accepted_at)
        self.assertIsNone(delivery.received_at)

        response = self.client.post(
            reverse("mobile-api:push-delivery-received", args=[delivery.pk]),
            **self.auth(),
        )
        self.assertEqual(response.status_code, 200)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, PushDeliveryStatus.RECEIVED)
        self.assertIsNotNone(delivery.received_at)

    def test_retries_are_bounded_and_error_is_inspectable(self):
        self.register()
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()

        self.assertFalse(dispatch_push_delivery(delivery.pk, provider=FailingProvider()))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, PushDeliveryStatus.RETRY)
        self.assertEqual(delivery.attempts, 1)
        delivery.next_attempt_at = timezone.now()
        delivery.save(update_fields=("next_attempt_at",))

        self.assertFalse(dispatch_push_delivery(delivery.pk, provider=FailingProvider()))
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, PushDeliveryStatus.FAILED)
        self.assertEqual(delivery.attempts, 2)
        self.assertIn("fournisseur indisponible", delivery.last_error)

    def test_invalid_provider_token_is_removed(self):
        installation = self.register()
        enqueue_push_deliveries(self.event.pk)
        delivery = PushDelivery.objects.get()

        self.assertFalse(dispatch_push_delivery(delivery.pk, provider=InvalidTokenProvider()))

        installation.refresh_from_db()
        delivery.refresh_from_db()
        self.assertFalse(installation.active)
        self.assertIsNone(installation.token_digest)
        self.assertEqual(delivery.status, PushDeliveryStatus.INVALID)

