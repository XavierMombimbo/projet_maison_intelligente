from django.contrib import admin

from .models import PushDelivery, PushInstallation


@admin.register(PushInstallation)
class PushInstallationAdmin(admin.ModelAdmin):
    list_display = ("session", "platform", "permission", "active", "last_seen_at", "invalidated_at")
    list_filter = ("platform", "permission", "active")
    exclude = ("token_ciphertext", "token_nonce", "token_digest")
    readonly_fields = (
        "session",
        "provider",
        "platform",
        "permission",
        "active",
        "registered_at",
        "last_seen_at",
        "invalidated_at",
        "last_error",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(PushDelivery)
class PushDeliveryAdmin(admin.ModelAdmin):
    list_display = ("event", "recipient", "status", "attempts", "provider_accepted_at", "received_at")
    list_filter = ("status",)
    search_fields = ("provider_message_id", "event__id", "recipient__username")
    readonly_fields = [field.name for field in PushDelivery._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

