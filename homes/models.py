import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
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
    fuseau_horaire = models.CharField(max_length=64, default="Africa/Kinshasa")
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


class TypeSourceCamera(models.TextChoices):
    WEBCAM = "webcam", "Webcam de la passerelle"
    RTSP = "rtsp", "Caméra réseau RTSP"


class SensFranchissement(models.TextChoices):
    TOUS = "any", "Dans les deux sens"
    NEGATIF_VERS_POSITIF = "negative_to_positive", "Gauche vers droite avec la ligne verticale proposée"
    POSITIF_VERS_NEGATIF = "positive_to_negative", "Droite vers gauche avec la ligne verticale proposée"


class PartitionEvaluation(models.TextChoices):
    AJUSTEMENT = "calibration", "Ajustement des seuils"
    EVALUATION = "evaluation", "Évaluation indépendante"


class ConditionEvaluation(models.TextChoices):
    JOUR = "day", "Jour"
    NUIT = "night", "Nuit"
    OMBRES = "shadows", "Ombres"
    PLUIE = "rain", "Pluie"
    OCCLUSION = "occlusion", "Occlusion"


class ClasseEvaluation(models.TextChoices):
    PERSONNE = "person", "Personne"
    CHIEN = "dog", "Chien"
    CHAT = "cat", "Chat"


class JourSemaine(models.IntegerChoices):
    LUNDI = 0, "Lundi"
    MARDI = 1, "Mardi"
    MERCREDI = 2, "Mercredi"
    JEUDI = 3, "Jeudi"
    VENDREDI = 4, "Vendredi"
    SAMEDI = 5, "Samedi"
    DIMANCHE = 6, "Dimanche"


class PlageSurveillance(models.Model):
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="plages_surveillance")
    nom = models.CharField(max_length=80)
    jour = models.PositiveSmallIntegerField(choices=JourSemaine.choices)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    active = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("jour", "heure_debut", "nom")
        constraints = [
            models.CheckConstraint(
                condition=~Q(heure_debut=models.F("heure_fin")),
                name="schedule_start_differs_from_end",
            ),
            models.UniqueConstraint(
                fields=("maison", "jour", "heure_debut", "heure_fin"),
                name="unique_house_schedule_window",
            ),
        ]

    def __str__(self):
        return f"{self.nom} — {self.get_jour_display()}"


class ExceptionSurveillance(models.Model):
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="exceptions_surveillance")
    nom = models.CharField(max_length=120)
    date_debut = models.DateTimeField()
    date_fin = models.DateTimeField()
    surveillance_active = models.BooleanField(default=False)
    priorite = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(100)])
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date_debut", "-priorite", "-date_creation")
        constraints = [
            models.CheckConstraint(
                condition=Q(date_fin__gt=models.F("date_debut")),
                name="schedule_exception_end_after_start",
            )
        ]

    def __str__(self):
        return self.nom


class DerogationSurveillance(models.Model):
    maison = models.OneToOneField(
        Maison,
        on_delete=models.CASCADE,
        related_name="derogation_surveillance",
    )
    surveillance_active = models.BooleanField()
    expire_le = models.DateTimeField()
    creee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="derogations_surveillance",
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-date_creation",)

    def __str__(self):
        return f"Dérogation {self.maison} jusqu’au {self.expire_le}"


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


def zone_analyse_par_defaut():
    return {"x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0}


def valider_zone_normalisee(value):
    if not isinstance(value, dict) or set(value) != {"x", "y", "width", "height"}:
        raise ValidationError("La zone doit contenir x, y, width et height.")
    try:
        x, y, width, height = (float(value[key]) for key in ("x", "y", "width", "height"))
    except (TypeError, ValueError):
        raise ValidationError("Les coordonnées de la zone doivent être numériques.")
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1.000001 or y + height > 1.000001:
        raise ValidationError("La zone normalisée doit rester entièrement dans l’image.")


def valider_ligne_normalisee(value):
    if value is None:
        return
    if not isinstance(value, dict) or set(value) != {"x1", "y1", "x2", "y2"}:
        raise ValidationError("La ligne doit contenir x1, y1, x2 et y2.")
    try:
        coordinates = [float(value[key]) for key in ("x1", "y1", "x2", "y2")]
    except (TypeError, ValueError):
        raise ValidationError("Les coordonnées de la ligne doivent être numériques.")
    if any(coordinate < 0 or coordinate > 1 for coordinate in coordinates):
        raise ValidationError("La ligne normalisée doit rester dans l’image.")
    if coordinates[:2] == coordinates[2:]:
        raise ValidationError("Les deux extrémités de la ligne doivent être différentes.")


class Camera(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    nom = models.CharField(max_length=120)
    maison = models.ForeignKey(Maison, on_delete=models.CASCADE, related_name="cameras")
    type_source = models.CharField(
        max_length=12,
        choices=TypeSourceCamera.choices,
        default=TypeSourceCamera.WEBCAM,
    )
    configuration_source_chiffree = models.BinaryField(null=True, blank=True)
    nonce_configuration_source = models.BinaryField(max_length=12, null=True, blank=True)
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
    surveillance_appliquee = models.BooleanField(null=True, blank=True)
    surveillance_appliquee_le = models.DateTimeField(null=True, blank=True)
    version_planning_appliquee = models.CharField(max_length=64, blank=True, default="")
    zone_analyse = models.JSONField(
        default=zone_analyse_par_defaut,
        validators=(valider_zone_normalisee,),
    )
    ligne_analyse = models.JSONField(
        null=True,
        blank=True,
        validators=(valider_ligne_normalisee,),
    )
    duree_presence_secondes = models.FloatField(
        default=1.0,
        validators=(MinValueValidator(0.5), MaxValueValidator(30.0)),
    )
    seuil_alerte_personne = models.FloatField(
        default=0.45,
        validators=(MinValueValidator(0.01), MaxValueValidator(1.0)),
    )
    seuil_alerte_animal = models.FloatField(
        default=0.50,
        validators=(MinValueValidator(0.01), MaxValueValidator(1.0)),
    )
    fenetre_regroupement_secondes = models.PositiveSmallIntegerField(
        default=30,
        validators=(MinValueValidator(1), MaxValueValidator(300)),
    )
    sens_franchissement_interdit = models.CharField(
        max_length=24,
        choices=SensFranchissement.choices,
        default=SensFranchissement.TOUS,
    )
    derniere_connexion = models.DateTimeField(null=True, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_appairage = models.DateTimeField(null=True, blank=True)
    date_revocation = models.DateTimeField(null=True, blank=True)

    objects = CameraQuerySet.as_manager()

    class Meta:
        ordering = ("nom",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        type_source=TypeSourceCamera.WEBCAM,
                        configuration_source_chiffree__isnull=True,
                        nonce_configuration_source__isnull=True,
                    )
                    | Q(
                        type_source=TypeSourceCamera.RTSP,
                        configuration_source_chiffree__isnull=False,
                        nonce_configuration_source__isnull=False,
                    )
                    | Q(
                        type_source=TypeSourceCamera.RTSP,
                        statut_appairage=StatutAppairage.REVOQUEE,
                        configuration_source_chiffree__isnull=True,
                        nonce_configuration_source__isnull=True,
                    )
                ),
                name="camera_source_configuration_consistent",
            )
        ]

    def __str__(self) -> str:
        return f"{self.nom} — {self.maison}"

    @property
    def endpoint_source_expurge(self) -> str:
        if self.type_source != TypeSourceCamera.RTSP:
            return "Webcam locale"
        if not self.configuration_source_chiffree or not self.nonce_configuration_source:
            return "Configuration RTSP absente"
        try:
            from urllib.parse import urlsplit, urlunsplit

            from cryptography.exceptions import InvalidTag

            from .crypto import decrypt_camera_source_config

            config = decrypt_camera_source_config(
                bytes(self.configuration_source_chiffree),
                bytes(self.nonce_configuration_source),
                self.pk,
            )
            parsed = urlsplit(config["url"])
            hostname = parsed.hostname or ""
            if ":" in hostname and not hostname.startswith("["):
                hostname = f"[{hostname}]"
            netloc = hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunsplit((parsed.scheme, netloc, parsed.path or "/", "", ""))
        except (InvalidTag, KeyError, TypeError, ValueError, UnicodeDecodeError):
            return "Configuration RTSP illisible"

    @property
    def est_connectee(self) -> bool:
        if not self.derniere_connexion:
            return False
        from datetime import timedelta
        from django.utils import timezone

        return self.derniere_connexion >= timezone.now() - timedelta(minutes=2)


class StatutProfilBiometrique(models.TextChoices):
    ACTIF = "active", "Actif"
    REVOQUE = "revoked", "Retiré"


class ProfilBiometriqueQuerySet(models.QuerySet):
    def visible_to(self, user):
        if not user.is_authenticated:
            return self.none()
        return self.filter(Q(utilisateur=user) | Q(maison__proprietaire=user)).distinct()


class ProfilBiometrique(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    maison = models.ForeignKey(
        Maison,
        on_delete=models.CASCADE,
        related_name="profils_biometriques",
    )
    utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profils_biometriques",
    )
    libelle = models.CharField(max_length=80)
    statut = models.CharField(
        max_length=12,
        choices=StatutProfilBiometrique.choices,
        default=StatutProfilBiometrique.ACTIF,
        db_index=True,
    )
    format_gabarit = models.CharField(max_length=80, blank=True)
    gabarit_chiffre = models.BinaryField(null=True, blank=True)
    nonce_gabarit = models.BinaryField(max_length=12, null=True, blank=True)
    version = models.PositiveIntegerField(default=1)
    version_consentement = models.CharField(max_length=24, default="face-profile-v1")
    date_consentement = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    date_retrait = models.DateTimeField(null=True, blank=True)

    objects = ProfilBiometriqueQuerySet.as_manager()

    class Meta:
        ordering = ("libelle", "date_consentement")
        constraints = [
            models.UniqueConstraint(
                fields=("maison", "utilisateur"),
                condition=Q(statut=StatutProfilBiometrique.ACTIF),
                name="one_active_biometric_profile_per_house_user",
            ),
            models.CheckConstraint(
                condition=(
                    Q(gabarit_chiffre__isnull=True, nonce_gabarit__isnull=True)
                    | Q(gabarit_chiffre__isnull=False, nonce_gabarit__isnull=False)
                ),
                name="biometric_template_ciphertext_nonce_pair",
            ),
            models.CheckConstraint(
                condition=(
                    Q(statut=StatutProfilBiometrique.ACTIF)
                    | Q(
                        statut=StatutProfilBiometrique.REVOQUE,
                        gabarit_chiffre__isnull=True,
                        nonce_gabarit__isnull=True,
                    )
                ),
                name="revoked_biometric_profile_has_no_template",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.libelle} — {self.maison}"

    @property
    def est_enrole(self) -> bool:
        return bool(self.gabarit_chiffre and self.nonce_gabarit)

    def clean(self):
        super().clean()
        if self.maison_id and self.utilisateur_id:
            accepted = MembreMaison.objects.filter(
                maison_id=self.maison_id,
                utilisateur_id=self.utilisateur_id,
                statut=StatutInvitation.ACCEPTEE,
            ).exists()
            if not accepted:
                raise ValidationError(
                    "Le profil biométrique exige une adhésion acceptée à la maison."
                )

    def set_template(self, payload: bytes, template_format: str):
        if self.statut != StatutProfilBiometrique.ACTIF:
            raise ValidationError("Un profil retiré ne peut pas être enrôlé.")
        if not payload or len(payload) > settings.BIOMETRIC_TEMPLATE_MAX_BYTES:
            raise ValidationError("La taille du gabarit biométrique est invalide.")
        normalized_format = template_format.strip()
        if not normalized_format or len(normalized_format) > 80:
            raise ValidationError("Le format du gabarit biométrique est invalide.")
        from .crypto import encrypt_biometric_template

        ciphertext, nonce = encrypt_biometric_template(payload, self.pk)
        self.gabarit_chiffre = ciphertext
        self.nonce_gabarit = nonce
        self.format_gabarit = normalized_format
        self.version += 1
        self.save(
            update_fields=(
                "gabarit_chiffre",
                "nonce_gabarit",
                "format_gabarit",
                "version",
                "date_modification",
            )
        )

    def decrypt_template(self) -> bytes | None:
        if not self.est_enrole:
            return None
        from .crypto import decrypt_biometric_template

        return decrypt_biometric_template(
            bytes(self.gabarit_chiffre),
            bytes(self.nonce_gabarit),
            self.pk,
        )


class AccusePurgeBiometrique(models.Model):
    camera = models.ForeignKey(
        Camera,
        on_delete=models.CASCADE,
        related_name="accuses_purge_biometrique",
    )
    profil = models.ForeignKey(
        ProfilBiometrique,
        on_delete=models.CASCADE,
        related_name="accuses_purge",
    )
    version = models.PositiveIntegerField()
    date_confirmation = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-date_confirmation",)
        constraints = [
            models.UniqueConstraint(
                fields=("camera", "profil", "version"),
                name="unique_biometric_purge_receipt",
            )
        ]

    def __str__(self) -> str:
        return f"Purge {self.profil_id} v{self.version} — {self.camera}"


class CampagneEvaluation(models.Model):
    camera = models.ForeignKey(
        Camera,
        on_delete=models.CASCADE,
        related_name="campagnes_evaluation",
    )
    partition = models.CharField(max_length=16, choices=PartitionEvaluation.choices)
    condition = models.CharField(max_length=16, choices=ConditionEvaluation.choices)
    notes = models.CharField(max_length=240, blank=True)
    cpu_moyen_pourcent = models.FloatField(
        null=True,
        blank=True,
        validators=(MinValueValidator(0.0), MaxValueValidator(100.0)),
    )
    ram_pic_mo = models.PositiveIntegerField(null=True, blank=True)
    date_debut = models.DateTimeField(auto_now_add=True, db_index=True)
    date_fin = models.DateTimeField(null=True, blank=True, db_index=True)
    creee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="campagnes_evaluation",
    )

    class Meta:
        ordering = ("-date_debut",)
        constraints = [
            models.UniqueConstraint(
                fields=("camera",),
                condition=Q(date_fin__isnull=True),
                name="one_active_evaluation_per_camera",
            )
        ]

    @property
    def active(self):
        return self.date_fin is None

    @property
    def duree_secondes(self):
        from django.utils import timezone

        end = self.date_fin or timezone.now()
        return max(0.0, (end - self.date_debut).total_seconds())

    @property
    def nombre_evenements(self):
        end = self.date_fin
        events = self.camera.evenements.filter(
            horodatage_observation__gte=self.date_debut,
            simule=False,
        )
        if end is not None:
            events = events.filter(horodatage_observation__lt=end)
        return events.count()

    @property
    def annotation_complete(self):
        return self.annotations_classes.count() == len(ClasseEvaluation.choices)

    @property
    def performance_complete(self):
        return self.cpu_moyen_pourcent is not None and self.ram_pic_mo is not None

    def __str__(self):
        return f"{self.camera.nom} — {self.get_partition_display()} — {self.get_condition_display()}"


class AnnotationClasseEvaluation(models.Model):
    campagne = models.ForeignKey(
        CampagneEvaluation,
        on_delete=models.CASCADE,
        related_name="annotations_classes",
    )
    classe = models.CharField(max_length=16, choices=ClasseEvaluation.choices)
    occurrences_attendues = models.PositiveIntegerField(default=0)
    vrais_positifs = models.PositiveIntegerField(default=0)
    faux_positifs = models.PositiveIntegerField(default=0)
    annotee_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="annotations_evaluation",
    )
    modifiee_le = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("classe",)
        constraints = [
            models.UniqueConstraint(
                fields=("campagne", "classe"),
                name="one_annotation_per_campaign_class",
            ),
            models.CheckConstraint(
                condition=models.Q(vrais_positifs__lte=models.F("occurrences_attendues")),
                name="evaluation_true_positives_lte_expected",
            ),
        ]

    @property
    def faux_negatifs(self):
        return self.occurrences_attendues - self.vrais_positifs

    @property
    def precision(self):
        denominator = self.vrais_positifs + self.faux_positifs
        return None if denominator == 0 else self.vrais_positifs / denominator

    @property
    def rappel(self):
        return None if self.occurrences_attendues == 0 else self.vrais_positifs / self.occurrences_attendues

    def __str__(self):
        return f"{self.campagne} — {self.get_classe_display()}"


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
    OBJETS_DETECTES = "objects_detected", "Objets détectés"
    SIMULATION = "simulation", "Détection simulée"


class StatutEvenement(models.TextChoices):
    NOUVEAU = "new", "Nouveau"
    FAUSSE_ALERTE = "false_alarm", "Fausse alerte"
    INTRUSION_CONFIRMEE = "confirmed", "Intrusion confirmée"


class NiveauAlerte(models.IntegerChoices):
    FAIBLE = 10, "Faible"
    NORMALE = 50, "Normale"
    ELEVEE = 80, "Élevée"
    URGENTE = 100, "Urgente"


class EvenementQuerySet(models.QuerySet):
    def operationnels(self):
        return self.filter(simule=False)

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
    version_contrat = models.PositiveSmallIntegerField(default=1, db_index=True)
    horodatage_observation = models.DateTimeField(null=True, blank=True, db_index=True)
    nom_modele = models.CharField(max_length=80, blank=True)
    version_modele = models.CharField(max_length=80, blank=True)
    empreinte_charge_utile = models.CharField(max_length=64, blank=True, db_index=True)
    horodatage = models.DateTimeField(auto_now_add=True, db_index=True)
    statut = models.CharField(
        max_length=16, choices=StatutEvenement.choices, default=StatutEvenement.NOUVEAU
    )
    simule = models.BooleanField(default=False)
    metadonnees = models.JSONField(default=dict, blank=True)
    priorite_alerte = models.PositiveSmallIntegerField(
        choices=NiveauAlerte.choices,
        default=NiveauAlerte.NORMALE,
        db_index=True,
    )
    raison_priorite = models.CharField(max_length=180, blank=True)
    cle_regroupement = models.CharField(max_length=64, blank=True, db_index=True)
    evenement_principal = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="evenements_regroupes",
    )
    notification_supprimee = models.BooleanField(default=False)

    objects = EvenementQuerySet.as_manager()

    class Meta:
        ordering = ("-priorite_alerte", "-horodatage")
        indexes = [
            models.Index(fields=("maison", "-horodatage"), name="event_house_time_idx"),
            models.Index(
                fields=("camera", "cle_regroupement", "-horodatage"),
                name="event_group_window_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_type_display()} — {self.camera.nom}"

    @property
    def nombre_evenements_regroupes(self):
        if self.evenement_principal_id:
            return self.evenement_principal.evenements_regroupes.count() + 1
        return self.evenements_regroupes.count() + 1

    @property
    def identite_locale(self):
        """Human-readable, non-identifying state attached by contract v3."""
        statuses = set((self.metadonnees.get("identite_locale") or {}).get("statuts") or [])
        if "recognized" in statuses:
            return "Profil volontaire reconnu. Cette indication ne désarme pas la surveillance."
        if "unknown" in statuses:
            return "Personne non reconnue : vérifiez la capture avant toute décision."
        if "unavailable" in statuses:
            return "Identification non déterminée."
        return ""


class ObjetDetecte(models.Model):
    evenement = models.ForeignKey(Evenement, on_delete=models.CASCADE, related_name="objets")
    classe = models.CharField(max_length=64, db_index=True)
    confiance = models.FloatField(validators=(MinValueValidator(0.0), MaxValueValidator(1.0)))
    boite = models.JSONField()
    identifiant_suivi = models.CharField(max_length=64, blank=True)

    class Meta:
        ordering = ("id",)
        indexes = [models.Index(fields=("classe", "-confiance"), name="object_class_score_idx")]

    def __str__(self) -> str:
        return f"{self.classe} ({self.confiance:.2f}) — {self.evenement_id}"


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


class StatutBoiteEnvoi(models.TextChoices):
    EN_ATTENTE = "pending", "En attente"
    ENVOYE = "sent", "Envoyé"


class EvenementBoiteEnvoi(models.Model):
    evenement = models.OneToOneField(
        Evenement, on_delete=models.CASCADE, related_name="boite_envoi"
    )
    type_message = models.CharField(max_length=40, default="alert.created")
    statut = models.CharField(
        max_length=12,
        choices=StatutBoiteEnvoi.choices,
        default=StatutBoiteEnvoi.EN_ATTENTE,
        db_index=True,
    )
    tentatives = models.PositiveIntegerField(default=0)
    derniere_erreur = models.CharField(max_length=500, blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_derniere_tentative = models.DateTimeField(null=True, blank=True)
    date_envoi = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("date_creation",)
        indexes = [
            models.Index(fields=("statut", "date_creation"), name="outbox_status_time_idx")
        ]

    def __str__(self) -> str:
        return f"{self.type_message} — {self.evenement_id} — {self.statut}"


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
