import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class MaisonQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(
            Q(proprietaire=user)
            | Q(membres__utilisateur=user, membres__statut=StatutInvitation.ACCEPTEE)
        ).distinct()


class Maison(models.Model):
    nom = models.CharField(max_length=120)
    proprietaire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="maisons_possedees",
    )
    utilisateurs = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="MembreMaison",
        related_name="maisons",
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    objects = MaisonQuerySet.as_manager()

    class Meta:
        ordering = ("nom",)

    def __str__(self) -> str:
        return self.nom

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new:
            MembreMaison.objects.get_or_create(
                maison=self,
                utilisateur=self.proprietaire,
                defaults={"role": RoleMaison.PROPRIETAIRE, "statut": StatutInvitation.ACCEPTEE},
            )


class RoleMaison(models.TextChoices):
    PROPRIETAIRE = "owner", "Propriétaire"
    FAMILLE = "family", "Membre de la famille"
    INVITE = "guest", "Invité"


class StatutInvitation(models.TextChoices):
    EN_ATTENTE = "pending", "En attente"
    ACCEPTEE = "accepted", "Acceptée"
    REFUSEE = "refused", "Refusée"


class MembreMaison(models.Model):
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="membres")
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="adhesions_maison",
    )
    role = models.CharField(max_length=12, choices=RoleMaison.choices, default=RoleMaison.INVITE)
    permissions = models.JSONField(default=list, blank=True)
    statut = models.CharField(
        max_length=12,
        choices=StatutInvitation.choices,
        default=StatutInvitation.EN_ATTENTE,
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("maison", "utilisateur"), name="unique_membre_maison")
        ]

    def __str__(self) -> str:
        return f"{self.utilisateur} — {self.maison} ({self.get_role_display()})"


class StatutAppairage(models.TextChoices):
    NON_APPAIREE = "unpaired", "Non appairée"
    APPAIREE = "paired", "Appairée"
    REVOQUEE = "revoked", "Révoquée"


class CameraQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(
            Q(maison__proprietaire=user)
            | Q(
                acces__membre__utilisateur=user,
                acces__membre__statut=StatutInvitation.ACCEPTEE,
                acces__peut_voir=True,
            )
        ).distinct()

    def controllable_by(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(
            Q(maison__proprietaire=user)
            | Q(
                acces__membre__utilisateur=user,
                acces__membre__statut=StatutInvitation.ACCEPTEE,
                acces__peut_controler=True,
            )
        ).distinct()


class Camera(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=120)
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="cameras")
    identifiant_appareil = models.CharField(max_length=255, unique=True, null=True, blank=True)
    secret_appareil_hash = models.CharField(max_length=64, blank=True)
    cle_signature_evenement_chiffree = models.BinaryField(null=True, blank=True)
    nonce_cle_signature_evenement = models.BinaryField(max_length=12, null=True, blank=True)
    version_jeton = models.PositiveIntegerField(default=1)
    statut_appairage = models.CharField(
        max_length=12,
        choices=StatutAppairage.choices,
        default=StatutAppairage.NON_APPAIREE,
    )
    surveillance_active = models.BooleanField(default=False)
    derniere_connexion = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_appairage = models.DateTimeField(null=True, blank=True)
    date_revocation = models.DateTimeField(null=True, blank=True)

    objects = CameraQuerySet.as_manager()

    class Meta:
        ordering = ("nom",)

    def __str__(self) -> str:
        return f"{self.nom} — {self.maison}"

    @property
    def est_connectee(self) -> bool:
        if not self.derniere_connexion:
            return False
        from datetime import timedelta
        from django.utils import timezone

        return self.derniere_connexion >= timezone.now() - timedelta(minutes=2)


class NonceRequeteCamera(models.Model):
    nonce = models.UUIDField(unique=True, editable=False)
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="nonces_requetes")
    horodatage_client = models.DateTimeField()
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-date_creation",)

    def __str__(self) -> str:
        return f"Nonce {self.nonce} — {self.camera}"


class AccesCamera(models.Model):
    membre = models.ForeignKey(MembreMaison, on_delete=models.CASCADE, related_name="acces_cameras")
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="acces")
    peut_voir = models.BooleanField(default=True)
    peut_controler = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("membre", "camera"), name="unique_acces_camera")
        ]


class CodeAppairage(models.Model):
    code_hash = models.CharField(max_length=64, db_index=True)
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="codes_appairage")
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="codes_appairage")
    nom_prevu_camera = models.CharField(max_length=120)
    date_expiration = models.DateTimeField(db_index=True)
    date_utilisation = models.DateTimeField(null=True, blank=True)
    utilise = models.BooleanField(default=False, db_index=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date_creation",)
        constraints = [
            models.CheckConstraint(
                condition=(Q(utilise=False, date_utilisation__isnull=True) | Q(utilise=True, date_utilisation__isnull=False)),
                name="pairing_use_date_consistent",
            )
        ]

    def __str__(self) -> str:
        return f"Code pour {self.nom_prevu_camera} ({self.maison})"


class TypeEvenement(models.TextChoices):
    PERSONNE_DETECTEE = "person_detected", "Personne détectée"
    SIMULATION = "simulation", "Détection simulée"


class StatutEvenement(models.TextChoices):
    NOUVEAU = "new", "Nouveau"
    FAUSSE_ALERTE = "false_alarm", "Fausse alerte"
    INTRUSION_CONFIRMEE = "confirmed", "Intrusion confirmée"


class EvenementQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(camera__in=Camera.objects.visible_to(user)).distinct()

    def controllable_by(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(camera__in=Camera.objects.controllable_by(user)).distinct()


class Evenement(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_event_id = models.UUIDField(unique=True, editable=False)
    camera = models.ForeignKey(Camera, on_delete=models.CASCADE, related_name="evenements")
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="evenements")
    type = models.CharField(max_length=24, choices=TypeEvenement.choices)
    confiance_ia = models.FloatField(
        validators=(MinValueValidator(0.0), MaxValueValidator(1.0))
    )
    horodatage = models.DateTimeField(auto_now_add=True, db_index=True)
    statut = models.CharField(
        max_length=16, choices=StatutEvenement.choices, default=StatutEvenement.NOUVEAU
    )
    simule = models.BooleanField(default=False)
    metadonnees = models.JSONField(default=dict, blank=True)

    objects = EvenementQuerySet.as_manager()

    class Meta:
        ordering = ("-horodatage",)
        indexes = [models.Index(fields=("maison", "-horodatage"), name="event_house_time_idx")]

    def __str__(self) -> str:
        return f"{self.get_type_display()} — {self.camera.nom}"


class CaptureChiffree(models.Model):
    evenement = models.OneToOneField(
        Evenement, on_delete=models.CASCADE, related_name="capture"
    )
    contenu_chiffre = models.BinaryField()
    nonce = models.BinaryField(max_length=12)
    type_mime = models.CharField(max_length=32)
    taille = models.PositiveIntegerField()
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"Capture chiffrée {self.evenement_id}"


class TypeActeurAudit(models.TextChoices):
    UTILISATEUR = "user", "Utilisateur"
    CAMERA = "camera", "Caméra"
    ANONYME = "anonymous", "Anonyme"
    SYSTEME = "system", "Système"


class ResultatAudit(models.TextChoices):
    SUCCES = "success", "Succès"
    REFUS = "denied", "Refus"
    ECHEC = "failure", "Échec"


class JournalAudit(models.Model):
    action = models.CharField(max_length=80, db_index=True)
    resultat = models.CharField(max_length=12, choices=ResultatAudit.choices)
    type_acteur = models.CharField(max_length=12, choices=TypeActeurAudit.choices)
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journaux_audit",
    )
    camera = models.ForeignKey(
        Camera,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journaux_audit",
    )
    maison = models.ForeignKey(
        Maison,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journaux_audit",
    )
    cible_type = models.CharField(max_length=40, blank=True)
    cible_id = models.CharField(max_length=64, blank=True)
    ip_hash = models.CharField(max_length=64, blank=True, db_index=True)
    metadonnees = models.JSONField(default=dict, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-date_creation",)
        indexes = [
            models.Index(fields=("action", "-date_creation"), name="audit_action_time_idx"),
            models.Index(fields=("camera", "-date_creation"), name="audit_camera_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.action} — {self.get_resultat_display()}"
