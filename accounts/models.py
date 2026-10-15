import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    email = models.EmailField("adresse e-mail", unique=True)

    def __str__(self) -> str:
        return self.email or self.username


class MFADevice(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="mfa_device")
    encrypted_secret = models.BinaryField()
    nonce = models.BinaryField(max_length=12)
    pending_encrypted_secret = models.BinaryField(null=True, blank=True)
    pending_nonce = models.BinaryField(max_length=12, null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_counter = models.BigIntegerField(default=-1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def is_confirmed(self):
        return self.confirmed_at is not None

    def set_secret(self, secret):
        from .mfa import encrypt_secret

        self.encrypted_secret, self.nonce = encrypt_secret(secret, self.user_id)

    def get_secret(self):
        from .mfa import decrypt_secret

        return decrypt_secret(bytes(self.encrypted_secret), bytes(self.nonce), self.user_id)

    def set_pending_secret(self, secret):
        from .mfa import encrypt_secret

        self.pending_encrypted_secret, self.pending_nonce = encrypt_secret(secret, self.user_id)

    def get_pending_secret(self):
        from .mfa import decrypt_secret

        if self.pending_encrypted_secret is None or self.pending_nonce is None:
            return None
        return decrypt_secret(
            bytes(self.pending_encrypted_secret), bytes(self.pending_nonce), self.user_id
        )

    def __str__(self):
        return f"MFA TOTP — {self.user}"


class MFARecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfa_recovery_codes")
    digest = models.CharField(max_length=64, unique=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)

    def __str__(self):
        return f"Code de récupération — {self.user}"


class MFAEmailChallenge(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mfa_email_challenges")
    digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"Code MFA e-mail — {self.user}"


class MobileAuthChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mobile_auth_challenges")
    token_digest = models.CharField(max_length=64, unique=True)
    device_id = models.CharField(max_length=255)
    device_name = models.CharField(max_length=120)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)


class MobileSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="mobile_sessions")
    device_id = models.CharField(max_length=255)
    device_name = models.CharField(max_length=120)
    refresh_digest = models.CharField(max_length=64, unique=True)
    refresh_expires_at = models.DateTimeField(db_index=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("user", "device_id"), name="unique_mobile_session_per_device"
            )
        ]
