import uuid

from django.conf import settings
from django.db import models


class PushPlatform(models.TextChoices):
    ANDROID = "android", "Android"
    IOS = "ios", "iOS"
    WEB = "web", "Web"


class CameraPushPreference(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    camera = models.ForeignKey("homes.Camera", on_delete=models.CASCADE)
    enabled = models.BooleanField(default=True)
    people = models.BooleanField(default=True)
    objects_enabled = models.BooleanField(default=True)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)
    urgent_during_quiet = models.BooleanField(default=False)
    lock_screen = models.CharField(max_length=8, default="private", choices=(
        ("private", "Masquer le contenu"),
        ("secret", "Masquer la notification"),
        ("public", "Afficher le message générique"),
    ))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("user", "camera"), name="unique_camera_push_preference")
        ]


class PushPermission(models.TextChoices):
    UNKNOWN = "unknown", "Inconnue"
    GRANTED = "granted", "Accordée"
    PROVISIONAL = "provisional", "Provisoire"
    DENIED = "denied", "Refusée"


class PushInstallation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.OneToOneField(
        "accounts.MobileSession",
        on_delete=models.CASCADE,
        related_name="push_installation",
    )
    provider = models.CharField(max_length=16, default="fcm")
    platform = models.CharField(max_length=12, choices=PushPlatform.choices)
    permission = models.CharField(
        max_length=16,
        choices=PushPermission.choices,
        default=PushPermission.UNKNOWN,
    )
    token_ciphertext = models.BinaryField(null=True, blank=True)
    token_nonce = models.BinaryField(max_length=12, null=True, blank=True)
    token_digest = models.CharField(max_length=64, unique=True, null=True, blank=True)
    active = models.BooleanField(default=False, db_index=True)
    registered_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    invalidated_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(
                        active=True,
                        token_ciphertext__isnull=False,
                        token_nonce__isnull=False,
                        token_digest__isnull=False,
                        invalidated_at__isnull=True,
                    )
                    | models.Q(active=False)
                ),
                name="active_push_installation_has_token",
            )
        ]

    def __str__(self):
        return f"{self.session.device_name} - {self.platform}"


class PushDeliveryStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    RETRY = "retry", "Nouvelle tentative"
    ACCEPTED = "accepted", "Acceptée par le fournisseur"
    RECEIVED = "received", "Reçue par l’application"
    FAILED = "failed", "Échec définitif"
    INVALID = "invalid", "Installation invalide"
    CANCELLED = "cancelled", "Annulée"


class PushDelivery(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event = models.ForeignKey(
        "homes.Evenement",
        on_delete=models.CASCADE,
        related_name="push_deliveries",
    )
    installation = models.ForeignKey(
        PushInstallation,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deliveries",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_deliveries",
    )
    status = models.CharField(
        max_length=16,
        choices=PushDeliveryStatus.choices,
        default=PushDeliveryStatus.PENDING,
        db_index=True,
    )
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(null=True, blank=True, db_index=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    provider_accepted_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("event", "installation"),
                condition=models.Q(installation__isnull=False),
                name="unique_push_delivery_per_installation",
            )
        ]
        indexes = [
            models.Index(
                fields=("status", "next_attempt_at", "created_at"),
                name="push_due_delivery_idx",
            )
        ]

    def __str__(self):
        return f"{self.event_id} - {self.recipient_id} - {self.status}"

