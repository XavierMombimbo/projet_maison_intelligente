from django.contrib import admin

from .models import (
    AccesCamera,
    AccusePurgeBiometrique,
    AnnotationClasseEvaluation,
    CampagneEvaluation,
    Camera,
    CaptureChiffree,
    CodeAppairage,
    Evenement,
    EvenementBoiteEnvoi,
    JournalAudit,
    Maison,
    MembreMaison,
    NonceRequeteCamera,
    ObjetDetecte,
    ProfilBiometrique,
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
    list_display = ("nom", "maison", "type_source", "statut_appairage", "surveillance_active")
    list_filter = ("type_source", "statut_appairage", "surveillance_active")
    readonly_fields = (
        "configuration_source_chiffree",
        "nonce_configuration_source",
        "secret_appareil_hash",
        "cle_signature_evenement_chiffree",
        "nonce_cle_signature_evenement",
    )


admin.site.register(MembreMaison)
admin.site.register(AccesCamera)
admin.site.register(CampagneEvaluation)
admin.site.register(AnnotationClasseEvaluation)


@admin.register(CodeAppairage)
class CodeAppairageAdmin(admin.ModelAdmin):
    list_display = ("nom_prevu_camera", "maison", "date_expiration", "utilise")
    list_filter = ("utilise",)
    readonly_fields = ("code_hash", "date_creation", "date_utilisation")


class ObjetDetecteInline(admin.TabularInline):
    model = ObjetDetecte
    extra = 0
    readonly_fields = ("classe", "confiance", "boite", "identifiant_suivi")
    can_delete = False


@admin.register(Evenement)
class EvenementAdmin(admin.ModelAdmin):
    list_display = (
        "type",
        "camera",
        "maison",
        "version_contrat",
        "confiance_ia",
        "simule",
        "horodatage",
    )
    list_filter = ("version_contrat", "type", "statut", "simule")
    readonly_fields = (
        "client_event_id",
        "version_contrat",
        "horodatage_observation",
        "nom_modele",
        "version_modele",
        "empreinte_charge_utile",
        "horodatage",
    )
    inlines = (ObjetDetecteInline,)


@admin.register(CaptureChiffree)
class CaptureChiffreeAdmin(admin.ModelAdmin):
    list_display = ("evenement", "type_mime", "taille", "date_creation")
    readonly_fields = ("contenu_chiffre", "nonce", "date_creation")


@admin.register(EvenementBoiteEnvoi)
class EvenementBoiteEnvoiAdmin(admin.ModelAdmin):
    list_display = (
        "evenement",
        "type_message",
        "statut",
        "tentatives",
        "date_derniere_tentative",
        "date_envoi",
    )
    list_filter = ("statut", "type_message")
    readonly_fields = (
        "evenement",
        "type_message",
        "statut",
        "tentatives",
        "derniere_erreur",
        "date_creation",
        "date_derniere_tentative",
        "date_envoi",
    )


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


@admin.register(ProfilBiometrique)
class ProfilBiometriqueAdmin(admin.ModelAdmin):
    list_display = (
        "libelle",
        "maison",
        "utilisateur",
        "statut",
        "version",
        "date_consentement",
        "date_retrait",
    )
    list_filter = ("statut", "maison")
    search_fields = ("libelle", "utilisateur__username", "maison__nom")
    fields = (
        "id",
        "libelle",
        "maison",
        "utilisateur",
        "statut",
        "format_gabarit",
        "version",
        "version_consentement",
        "date_consentement",
        "date_modification",
        "date_retrait",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AccusePurgeBiometrique)
class AccusePurgeBiometriqueAdmin(admin.ModelAdmin):
    list_display = ("camera", "profil", "version", "date_confirmation")
    readonly_fields = ("camera", "profil", "version", "date_confirmation")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
