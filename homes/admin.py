from django.contrib import admin

from .models import (
    AccesCamera,
    Camera,
    CaptureChiffree,
    CodeAppairage,
    Evenement,
    JournalAudit,
    Maison,
    MembreMaison,
    NonceRequeteCamera,
)


class MembreMaisonInline(admin.TabularInline):
    model = MembreMaison
    extra = 0


@admin.register(Maison)
class MaisonAdmin(admin.ModelAdmin):
    list_display = ("nom", "proprietaire", "date_creation")
    inlines = (MembreMaisonInline,)


@admin.register(Camera)
class CameraAdmin(admin.ModelAdmin):
    list_display = ("nom", "maison", "statut_appairage", "surveillance_active")
    list_filter = ("statut_appairage", "surveillance_active")


admin.site.register(MembreMaison)
admin.site.register(AccesCamera)


@admin.register(CodeAppairage)
class CodeAppairageAdmin(admin.ModelAdmin):
    list_display = ("nom_prevu_camera", "maison", "date_expiration", "utilise")
    list_filter = ("utilise",)
    readonly_fields = ("code_hash", "date_creation", "date_utilisation")


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display = ("type", "camera", "maison", "confiance_ia", "simule", "horodatage")
    list_filter = ("type", "statut", "simule")
    readonly_fields = ("client_event_id", "horodatage")


@admin.register(CaptureChiffree)
class CaptureChiffreeAdmin(admin.ModelAdmin):
    list_display = ("evenement", "type_mime", "taille", "date_creation")
    readonly_fields = ("contenu_chiffre", "nonce", "date_creation")


@admin.register(NonceRequeteCamera)
class NonceRequeteCameraAdmin(admin.ModelAdmin):
    list_display = ("nonce", "camera", "horodatage_client", "date_creation")
    search_fields = ("nonce", "camera__nom")
    readonly_fields = ("nonce", "camera", "horodatage_client", "date_creation")


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    list_display = ("date_creation", "action", "resultat", "type_acteur", "camera", "maison")
    list_filter = ("resultat", "type_acteur", "action")
    search_fields = ("action", "cible_id", "camera__nom", "maison__nom")
    readonly_fields = (
        "action",
        "resultat",
        "type_acteur",
        "utilisateur",
        "camera",
        "maison",
        "cible_type",
        "cible_id",
        "ip_hash",
        "metadonnees",
        "date_creation",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
