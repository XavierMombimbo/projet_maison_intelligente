import json
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from homes.models import Evenement
from homes.weapon_messages import PERSON_WEAPON_TITLE, person_weapon_suspected

from .crypto import decrypt_token, encrypt_token, token_digest
from .preferences import allows_push
from .models import (
    CameraPushPreference,
    PushDelivery,
    PushDeliveryStatus,
    PushInstallation,
    PushPermission,
)


class PushProviderError(Exception):
    pass


class PushProviderUnavailable(PushProviderError):
    pass


class PushTokenInvalid(PushProviderError):
    pass


class FirebasePushProvider:
    def _messaging(self):
        if not settings.FCM_ENABLED or not settings.FCM_PROJECT_ID:
            raise PushProviderUnavailable("FCM n’est pas configuré.")
        try:
            import firebase_admin
            from firebase_admin import credentials, exceptions, messaging
        except ImportError as exc:
            raise PushProviderUnavailable("firebase-admin n’est pas installé.") from exc
        try:
            app = firebase_admin.get_app()
        except ValueError:
            credential = None
            if settings.FCM_SERVICE_ACCOUNT_JSON:
                try:
                    credential = credentials.Certificate(
                        json.loads(settings.FCM_SERVICE_ACCOUNT_JSON)
                    )
                except (TypeError, ValueError) as exc:
                    raise PushProviderUnavailable(
                        "Le compte de service Firebase est invalide."
                    ) from exc
            app = firebase_admin.initialize_app(
                credential=credential,
                options={"projectId": settings.FCM_PROJECT_ID},
            )
        return messaging, exceptions, app

    def send(self, delivery: PushDelivery) -> str:
        installation = delivery.installation
        if installation is None or not installation.active:
            raise PushTokenInvalid("Installation push inactive.")
        token = decrypt_token(
            bytes(installation.token_ciphertext),
            bytes(installation.token_nonce),
            installation.session_id,
        )
        messaging, exceptions, app = self._messaging()
        visibility = CameraPushPreference.objects.filter(
            user_id=delivery.recipient_id, camera_id=delivery.event.camera_id,
        ).values_list("lock_screen", flat=True).first() or "private"
        message = messaging.Message(
            token=token,
            notification=messaging.Notification(
                title="Sentinelle Maison",
                body=(PERSON_WEAPON_TITLE if person_weapon_suspected(delivery.event.metadonnees)
                      else "Une nouvelle alerte est disponible."),
            ),
            data={
                "type": "alert.created",
                "event_id": str(delivery.event_id),
                "delivery_id": str(delivery.pk),
                "lock_screen": visibility,
                **({"person_weapon_suspicion": "true"} if person_weapon_suspected(delivery.event.metadonnees) else {}),
            },
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id="sentinelle_alerts",
                    sound="default",
                    default_vibrate_timings=True,
                    tag=str(delivery.pk),
                    visibility=visibility,
                ),
            ),
        )
        try:
            return messaging.send(message, app=app)
        except (messaging.UnregisteredError, exceptions.InvalidArgumentError) as exc:
            raise PushTokenInvalid(str(exc)) from exc
        except Exception as exc:
            raise PushProviderError(str(exc)) from exc


@transaction.atomic
def register_installation(*, session, token, platform, permission):
    now = timezone.now()
    digest = token_digest(token)
    PushInstallation.objects.select_for_update().filter(token_digest=digest).exclude(
        session=session
    ).update(
        active=False,
        token_ciphertext=None,
        token_nonce=None,
        token_digest=None,
        invalidated_at=now,
        last_error="Jeton rattaché à une autre session.",
    )
    installation, _created = PushInstallation.objects.select_for_update().get_or_create(
        session=session,
        defaults={"platform": platform},
    )
    ciphertext, nonce = encrypt_token(token, session.pk)
    installation.provider = "fcm"
    installation.platform = platform
    installation.permission = permission
    installation.token_ciphertext = ciphertext
    installation.token_nonce = nonce
    installation.token_digest = digest
    installation.active = permission in {PushPermission.GRANTED, PushPermission.PROVISIONAL}
    installation.registered_at = now
    installation.last_seen_at = now
    installation.invalidated_at = None
    installation.last_error = ""
    installation.save()
    return installation


@transaction.atomic
def record_denied_permission(*, session, platform):
    installation, _created = PushInstallation.objects.select_for_update().get_or_create(
        session=session,
        defaults={"platform": platform},
    )
    installation.platform = platform
    installation.permission = PushPermission.DENIED
    installation.active = False
    installation.token_ciphertext = None
    installation.token_nonce = None
    installation.token_digest = None
    installation.invalidated_at = timezone.now()
    installation.last_error = "Permission de notification refusée."
    installation.save()
    return installation


def dissociate_session(session):
    now = timezone.now()
    return PushInstallation.objects.filter(session=session).update(
        active=False,
        token_ciphertext=None,
        token_nonce=None,
        token_digest=None,
        invalidated_at=now,
        last_error="Session mobile révoquée.",
    )


def enqueue_push_deliveries(event_id) -> int:
    event = Evenement.objects.select_related("camera", "maison").get(pk=event_id)
    if event.notification_supprimee:
        return 0
    now = timezone.now()
    installations = PushInstallation.objects.select_related("session__user").filter(
        active=True,
        permission__in=(PushPermission.GRANTED, PushPermission.PROVISIONAL),
        session__revoked_at__isnull=True,
        session__refresh_expires_at__gte=now,
    )
    created = 0
    for installation in installations:
        user = installation.session.user
        if not Evenement.objects.visible_to(user).filter(pk=event.pk).exists():
            continue
        if not allows_push(user, event):
            continue
        _delivery, was_created = PushDelivery.objects.get_or_create(
            event=event,
            installation=installation,
            defaults={
                "recipient": user,
                "status": PushDeliveryStatus.PENDING,
                "next_attempt_at": now,
            },
        )
        created += int(was_created)
    return created


def _cancelled_reason(delivery):
    installation = delivery.installation
    if installation is None or not installation.active:
        return "Installation dissociée."
    if installation.session.revoked_at is not None:
        return "Session mobile révoquée."
    if installation.session.refresh_expires_at < timezone.now():
        return "Session mobile expirée."
    if not Evenement.objects.visible_to(delivery.recipient).filter(pk=delivery.event_id).exists():
        return "Le destinataire n’a plus accès à l’événement."
    if not allows_push(delivery.recipient, delivery.event):
        return "Notification désactivée dans les préférences du destinataire."
    return ""


@transaction.atomic
def dispatch_push_delivery(delivery_id, *, provider=None) -> bool:
    delivery = (
        PushDelivery.objects.select_for_update()
        .select_related("installation__session", "recipient", "event")
        .get(pk=delivery_id)
    )
    if delivery.status in {PushDeliveryStatus.ACCEPTED, PushDeliveryStatus.RECEIVED}:
        return True
    if delivery.status in {
        PushDeliveryStatus.CANCELLED,
        PushDeliveryStatus.INVALID,
        PushDeliveryStatus.FAILED,
    }:
        return False
    reason = _cancelled_reason(delivery)
    if reason:
        delivery.status = PushDeliveryStatus.CANCELLED
        delivery.last_error = reason
        delivery.next_attempt_at = None
        delivery.save(update_fields=("status", "last_error", "next_attempt_at"))
        return False

    delivery.attempts += 1
    delivery.last_attempt_at = timezone.now()
    provider = provider or FirebasePushProvider()
    try:
        message_id = provider.send(delivery)
    except PushTokenInvalid as exc:
        installation = delivery.installation
        installation.active = False
        installation.token_ciphertext = None
        installation.token_nonce = None
        installation.token_digest = None
        installation.invalidated_at = timezone.now()
        installation.last_error = str(exc)[:500]
        installation.save()
        delivery.status = PushDeliveryStatus.INVALID
        delivery.last_error = str(exc)[:500]
        delivery.next_attempt_at = None
    except PushProviderError as exc:
        delivery.last_error = str(exc)[:500]
        if delivery.attempts >= settings.PUSH_MAX_ATTEMPTS:
            delivery.status = PushDeliveryStatus.FAILED
            delivery.next_attempt_at = None
        else:
            delay = settings.PUSH_RETRY_BASE_SECONDS * (4 ** (delivery.attempts - 1))
            delivery.status = PushDeliveryStatus.RETRY
            delivery.next_attempt_at = timezone.now() + timedelta(seconds=delay)
    else:
        delivery.status = PushDeliveryStatus.ACCEPTED
        delivery.provider_message_id = str(message_id)[:255]
        delivery.provider_accepted_at = timezone.now()
        delivery.next_attempt_at = None
        delivery.last_error = ""
    delivery.save()
    return delivery.status == PushDeliveryStatus.ACCEPTED


def dispatch_due_push_deliveries(*, limit=100, provider=None) -> tuple[int, int]:
    now = timezone.now()
    ids = list(
        PushDelivery.objects.filter(
            status__in=(PushDeliveryStatus.PENDING, PushDeliveryStatus.RETRY),
            next_attempt_at__lte=now,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )
    accepted = 0
    not_accepted = 0
    for delivery_id in ids:
        if dispatch_push_delivery(delivery_id, provider=provider):
            accepted += 1
        else:
            not_accepted += 1
    return accepted, not_accepted

