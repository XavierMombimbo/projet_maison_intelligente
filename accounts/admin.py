from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    MFADevice,
    MFAEmailChallenge,
    MFARecoveryCode,
    MobileAuthChallenge,
    MobileSession,
    User,
)

admin.site.register(User, UserAdmin)


@admin.register(MFADevice)
class MFADeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "confirmed_at", "updated_at")
    readonly_fields = ("user", "confirmed_at", "last_counter", "created_at", "updated_at")
    exclude = ("encrypted_secret", "nonce")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MFARecoveryCode)
class MFARecoveryCodeAdmin(admin.ModelAdmin):
    list_display = ("user", "used_at", "created_at")
    exclude = ("digest",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MFAEmailChallenge)
class MFAEmailChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "expires_at", "used_at", "created_at")
    exclude = ("digest",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MobileSession)
class MobileSessionAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "last_used_at", "revoked_at", "updated_at")
    exclude = ("refresh_digest",)
    readonly_fields = (
        "user",
        "device_id",
        "device_name",
        "refresh_expires_at",
        "last_used_at",
        "revoked_at",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MobileAuthChallenge)
class MobileAuthChallengeAdmin(admin.ModelAdmin):
    list_display = ("user", "device_name", "expires_at", "used_at", "created_at")
    exclude = ("token_digest",)
    readonly_fields = ("user", "device_id", "device_name", "expires_at", "used_at", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
