from django import forms
from datetime import datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, available_timezones

from .crypto import encrypt_camera_source_config
from .models import (
    AnnotationClasseEvaluation,
    CampagneEvaluation,
    Camera,
    ClasseEvaluation,
    ExceptionSurveillance,
    Maison,
    PlageSurveillance,
    SensFranchissement,
    TypeSourceCamera,
)


class CampagneEvaluationForm(forms.ModelForm):
    class Meta:
        model = CampagneEvaluation
        fields = ("partition", "condition", "notes")
        labels = {
            "partition": "Utilisation des données",
            "condition": "Condition principale",
            "notes": "Note courte",
        }
        help_texts = {
            "partition": "Une campagne d’évaluation ne doit pas servir à modifier les seuils.",
            "notes": "Exemple : contre-jour, éclairage faible ou personne partiellement masquée.",
        }


class AnnotationEvaluationForm(forms.Form):
    classes = ClasseEvaluation.choices
    cpu_moyen_pourcent = forms.FloatField(
        label="CPU moyen du navigateur (%)",
        min_value=0,
        max_value=100,
        required=False,
        help_text="Valeur observée dans le gestionnaire des tâches pendant la campagne.",
    )
    ram_pic_mo = forms.IntegerField(
        label="Pic mémoire du navigateur (Mo)",
        min_value=0,
        required=False,
        help_text="Plus grande valeur mémoire observée pendant la campagne.",
    )

    def __init__(self, *args, campagne, **kwargs):
        super().__init__(*args, **kwargs)
        self.campagne = campagne
        self.fields["cpu_moyen_pourcent"].initial = campagne.cpu_moyen_pourcent
        self.fields["ram_pic_mo"].initial = campagne.ram_pic_mo
        existing = {item.classe: item for item in campagne.annotations_classes.all()}
        for code, label in self.classes:
            annotation = existing.get(code)
            values = {
                "attendues": annotation.occurrences_attendues if annotation else 0,
                "correctes": annotation.vrais_positifs if annotation else 0,
                "fausses": annotation.faux_positifs if annotation else 0,
            }
            self.fields[f"{code}_attendues"] = forms.IntegerField(
                label=f"{label} — présences attendues", min_value=0, initial=values["attendues"]
            )
            self.fields[f"{code}_correctes"] = forms.IntegerField(
                label=f"{label} — détections correctes", min_value=0, initial=values["correctes"]
            )
            self.fields[f"{code}_fausses"] = forms.IntegerField(
                label=f"{label} — fausses détections", min_value=0, initial=values["fausses"]
            )

    def clean(self):
        cleaned = super().clean()
        for code, label in self.classes:
            expected = cleaned.get(f"{code}_attendues")
            correct = cleaned.get(f"{code}_correctes")
            if expected is not None and correct is not None and correct > expected:
                self.add_error(
                    f"{code}_correctes",
                    f"Les détections correctes de {label.lower()} ne peuvent pas dépasser les présences attendues.",
                )
        return cleaned

    def save(self, user):
        self.campagne.cpu_moyen_pourcent = self.cleaned_data["cpu_moyen_pourcent"]
        self.campagne.ram_pic_mo = self.cleaned_data["ram_pic_mo"]
        self.campagne.save(update_fields=("cpu_moyen_pourcent", "ram_pic_mo"))
        annotations = []
        for code, _label in self.classes:
            annotation, _created = AnnotationClasseEvaluation.objects.update_or_create(
                campagne=self.campagne,
                classe=code,
                defaults={
                    "occurrences_attendues": self.cleaned_data[f"{code}_attendues"],
                    "vrais_positifs": self.cleaned_data[f"{code}_correctes"],
                    "faux_positifs": self.cleaned_data[f"{code}_fausses"],
                    "annotee_par": user,
                },
            )
            annotations.append(annotation)
        return annotations


class MaisonForm(forms.ModelForm):
    class Meta:
        model = Maison
        fields = ("nom",)


class ProfilBiometriqueConsentementForm(forms.Form):
    libelle = forms.CharField(
        label="Nom du profil",
        max_length=80,
        help_text="Exemple : Mon profil. Ce nom reste limité aux membres autorisés.",
    )
    consentement = forms.BooleanField(
        label=(
            "Je demande volontairement la création de mon profil biométrique pour cette maison "
            "et je comprends que je peux le retirer à tout moment."
        )
    )

    def clean_libelle(self):
        value = self.cleaned_data["libelle"].strip()
        if not value:
            raise forms.ValidationError("Saisissez un nom de profil.")
        return value


class MaisonFuseauHoraireForm(forms.ModelForm):
    fuseau_horaire = forms.ChoiceField(
        label="Fuseau horaire",
        choices=[(name, name) for name in sorted(available_timezones())],
    )

    class Meta:
        model = Maison
        fields = ("fuseau_horaire",)


class PlageSurveillanceForm(forms.ModelForm):
    class Meta:
        model = PlageSurveillance
        fields = ("nom", "jour", "heure_debut", "heure_fin", "active")
        widgets = {
            "heure_debut": forms.TimeInput(attrs={"type": "time"}),
            "heure_fin": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("heure_debut") == cleaned.get("heure_fin"):
            self.add_error("heure_fin", "L’heure de fin doit différer de l’heure de début.")
        return cleaned


class PlanningQuotidienForm(forms.Form):
    heure_activation = forms.TimeField(
        label="Heure d’activation",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    heure_arret = forms.TimeField(
        label="Heure d’arrêt",
        widget=forms.TimeInput(attrs={"type": "time"}),
    )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("heure_activation") == cleaned.get("heure_arret"):
            self.add_error(
                "heure_arret",
                "L’heure d’arrêt doit différer de l’heure d’activation.",
            )
        return cleaned


class ExceptionSurveillanceForm(forms.ModelForm):
    class Meta:
        model = ExceptionSurveillance
        fields = ("nom", "date_debut", "date_fin", "surveillance_active", "priorite")
        widgets = {
            "date_debut": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
            "date_fin": forms.DateTimeInput(
                attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"
            ),
        }

    def __init__(self, *args, house_timezone="Africa/Kinshasa", **kwargs):
        self.house_timezone = ZoneInfo(house_timezone)
        super().__init__(*args, **kwargs)
        self.fields["date_debut"].input_formats = ["%Y-%m-%dT%H:%M"]
        self.fields["date_fin"].input_formats = ["%Y-%m-%dT%H:%M"]
        if self.instance and self.instance.pk:
            self.initial["date_debut"] = self.instance.date_debut.astimezone(
                self.house_timezone
            ).replace(tzinfo=None)
            self.initial["date_fin"] = self.instance.date_fin.astimezone(
                self.house_timezone
            ).replace(tzinfo=None)

    def clean(self):
        cleaned = super().clean()
        for field_name in ("date_debut", "date_fin"):
            raw_value = self.data.get(field_name)
            if raw_value and field_name not in self.errors:
                try:
                    local_value = datetime.strptime(raw_value, "%Y-%m-%dT%H:%M")
                    cleaned[field_name] = local_value.replace(tzinfo=self.house_timezone)
                except ValueError:
                    self.add_error(field_name, "Date et heure invalides.")
        start = cleaned.get("date_debut")
        end = cleaned.get("date_fin")
        if start and end and end <= start:
            self.add_error("date_fin", "La fin doit être postérieure au début.")
        return cleaned


class DerogationSurveillanceForm(forms.Form):
    surveillance_active = forms.TypedChoiceField(
        label="État prioritaire",
        choices=((True, "Activer"), (False, "Désactiver")),
        coerce=lambda value: value == "True",
    )
    duree_minutes = forms.TypedChoiceField(
        label="Durée",
        choices=((15, "15 minutes"), (30, "30 minutes"), (60, "1 heure"), (120, "2 heures"), (480, "8 heures"), (1440, "24 heures")),
        coerce=int,
    )


class CameraForm(forms.ModelForm):
    adresse_rtsp = forms.CharField(
        required=False,
        label="Adresse RTSP",
        help_text="Exemple : rtsp://192.168.1.20:554/stream1. Les identifiants ont leurs champs séparés.",
        widget=forms.TextInput(attrs={"placeholder": "rtsp://camera.local:554/stream1"}),
    )
    utilisateur_rtsp = forms.CharField(
        required=False,
        label="Utilisateur RTSP",
        widget=forms.TextInput(attrs={"autocomplete": "off"}),
    )
    mot_de_passe_rtsp = forms.CharField(
        required=False,
        label="Mot de passe RTSP",
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )

    class Meta:
        model = Camera
        fields = ("maison", "nom", "type_source")

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["maison"].queryset = Maison.objects.filter(proprietaire=user)
        self.fields["type_source"].choices = [
            (TypeSourceCamera.WEBCAM, "Webcam d’un ordinateur"),
            (TypeSourceCamera.RTSP, "Caméra réseau (RTSP)"),
        ]

    def clean(self):
        cleaned = super().clean()
        source_type = cleaned.get("type_source")
        url = (cleaned.get("adresse_rtsp") or "").strip()
        username = (cleaned.get("utilisateur_rtsp") or "").strip()
        password = cleaned.get("mot_de_passe_rtsp") or ""

        if source_type == TypeSourceCamera.WEBCAM:
            if url or username or password:
                self.add_error(
                    "type_source",
                    "Choisissez RTSP pour enregistrer une adresse ou des identifiants réseau.",
                )
            return cleaned

        if source_type != TypeSourceCamera.RTSP:
            return cleaned
        if not url:
            self.add_error("adresse_rtsp", "L’adresse RTSP est obligatoire.")
            return cleaned

        try:
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in {"rtsp", "rtsps"} or not parsed.hostname:
                raise ValueError
            parsed.port
        except ValueError:
            self.add_error("adresse_rtsp", "Saisissez une adresse rtsp:// ou rtsps:// valide.")
            return cleaned
        if parsed.username is not None or parsed.password is not None:
            self.add_error(
                "adresse_rtsp",
                "Retirez les identifiants de l’adresse et utilisez les champs dédiés.",
            )
        if password and not username:
            self.add_error("utilisateur_rtsp", "Un utilisateur est requis avec le mot de passe.")
        cleaned["adresse_rtsp"] = url
        cleaned["utilisateur_rtsp"] = username
        cleaned["mot_de_passe_rtsp"] = password
        return cleaned

    def save(self, commit=True):
        camera = super().save(commit=False)
        if camera.type_source == TypeSourceCamera.RTSP:
            config = {
                "url": self.cleaned_data["adresse_rtsp"],
                "username": self.cleaned_data["utilisateur_rtsp"],
                "password": self.cleaned_data["mot_de_passe_rtsp"],
            }
            ciphertext, nonce = encrypt_camera_source_config(config, camera.pk)
            camera.configuration_source_chiffree = ciphertext
            camera.nonce_configuration_source = nonce
        else:
            camera.configuration_source_chiffree = None
            camera.nonce_configuration_source = None
        if commit:
            camera.save()
        return camera


class CameraAnalysisForm(forms.Form):
    zone_x = forms.DecimalField(label="Zone — gauche (%)", min_value=0, max_value=99, decimal_places=1)
    zone_y = forms.DecimalField(label="Zone — haut (%)", min_value=0, max_value=99, decimal_places=1)
    zone_width = forms.DecimalField(label="Zone — largeur (%)", min_value=1, max_value=100, decimal_places=1)
    zone_height = forms.DecimalField(label="Zone — hauteur (%)", min_value=1, max_value=100, decimal_places=1)
    duree_presence_secondes = forms.DecimalField(
        label="Durée avant événement (secondes)",
        min_value=0.5,
        max_value=30,
        decimal_places=1,
        help_text="La durée est mesurée par l’horloge, indépendamment du nombre d’images analysées.",
    )
    seuil_alerte_personne_pourcent = forms.DecimalField(
        label="Seuil personne (%)",
        min_value=1,
        max_value=100,
        decimal_places=0,
        help_text="Une personne sous ce score reste visible localement mais ne rend pas l’alerte prioritaire.",
    )
    seuil_alerte_animal_pourcent = forms.DecimalField(
        label="Seuil chien et chat (%)",
        min_value=1,
        max_value=100,
        decimal_places=0,
    )
    fenetre_regroupement_secondes = forms.IntegerField(
        label="Regrouper les répétitions pendant (secondes)",
        min_value=1,
        max_value=300,
        help_text="Même caméra, même piste et même règle : une seule notification est envoyée pendant cette durée.",
    )
    ligne_active = forms.BooleanField(label="Afficher une ligne de référence", required=False)
    sens_franchissement_interdit = forms.ChoiceField(
        label="Sens de franchissement interdit",
        choices=SensFranchissement.choices,
    )
    ligne_x1 = forms.DecimalField(label="Ligne — départ X (%)", min_value=0, max_value=100, decimal_places=1, required=False)
    ligne_y1 = forms.DecimalField(label="Ligne — départ Y (%)", min_value=0, max_value=100, decimal_places=1, required=False)
    ligne_x2 = forms.DecimalField(label="Ligne — arrivée X (%)", min_value=0, max_value=100, decimal_places=1, required=False)
    ligne_y2 = forms.DecimalField(label="Ligne — arrivée Y (%)", min_value=0, max_value=100, decimal_places=1, required=False)

    def __init__(self, *args, camera, **kwargs):
        self.camera = camera
        if not args and "data" not in kwargs:
            zone = camera.zone_analyse
            line = camera.ligne_analyse
            kwargs.setdefault("initial", {}).update({
                "zone_x": zone["x"] * 100,
                "zone_y": zone["y"] * 100,
                "zone_width": zone["width"] * 100,
                "zone_height": zone["height"] * 100,
                "duree_presence_secondes": camera.duree_presence_secondes,
                "seuil_alerte_personne_pourcent": camera.seuil_alerte_personne * 100,
                "seuil_alerte_animal_pourcent": camera.seuil_alerte_animal * 100,
                "fenetre_regroupement_secondes": camera.fenetre_regroupement_secondes,
                "ligne_active": line is not None,
                "sens_franchissement_interdit": camera.sens_franchissement_interdit,
                "ligne_x1": line["x1"] * 100 if line else 50,
                "ligne_y1": line["y1"] * 100 if line else 0,
                "ligne_x2": line["x2"] * 100 if line else 50,
                "ligne_y2": line["y2"] * 100 if line else 100,
            })
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        x = cleaned.get("zone_x")
        y = cleaned.get("zone_y")
        width = cleaned.get("zone_width")
        height = cleaned.get("zone_height")
        if x is not None and width is not None and x + width > 100:
            self.add_error("zone_width", "La zone dépasse le bord droit de l’image.")
        if y is not None and height is not None and y + height > 100:
            self.add_error("zone_height", "La zone dépasse le bord inférieur de l’image.")
        if cleaned.get("ligne_active"):
            names = ("ligne_x1", "ligne_y1", "ligne_x2", "ligne_y2")
            if any(cleaned.get(name) is None for name in names):
                for name in names:
                    if cleaned.get(name) is None:
                        self.add_error(name, "Coordonnée obligatoire lorsque la ligne est active.")
            elif cleaned["ligne_x1"] == cleaned["ligne_x2"] and cleaned["ligne_y1"] == cleaned["ligne_y2"]:
                self.add_error("ligne_x2", "Les deux extrémités doivent être différentes.")
        return cleaned

    def save(self):
        data = self.cleaned_data
        self.camera.zone_analyse = {
            "x": float(data["zone_x"] / 100),
            "y": float(data["zone_y"] / 100),
            "width": float(data["zone_width"] / 100),
            "height": float(data["zone_height"] / 100),
        }
        self.camera.duree_presence_secondes = float(data["duree_presence_secondes"])
        self.camera.seuil_alerte_personne = float(data["seuil_alerte_personne_pourcent"] / 100)
        self.camera.seuil_alerte_animal = float(data["seuil_alerte_animal_pourcent"] / 100)
        self.camera.fenetre_regroupement_secondes = data["fenetre_regroupement_secondes"]
        self.camera.ligne_analyse = None
        self.camera.sens_franchissement_interdit = data["sens_franchissement_interdit"]
        if data["ligne_active"]:
            self.camera.ligne_analyse = {
                key.removeprefix("ligne_"): float(data[key] / 100)
                for key in ("ligne_x1", "ligne_y1", "ligne_x2", "ligne_y2")
            }
        self.camera.full_clean()
        self.camera.save(update_fields=(
            "zone_analyse",
            "ligne_analyse",
            "duree_presence_secondes",
            "seuil_alerte_personne",
            "seuil_alerte_animal",
            "fenetre_regroupement_secondes",
            "sens_franchissement_interdit",
        ))
        return self.camera


class ConnectCameraForm(forms.Form):
    code = forms.RegexField(
        regex=r"^\d{6}$",
        min_length=6,
        max_length=6,
        label="Code d’appairage",
        error_messages={"invalid": "Saisissez exactement six chiffres."},
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "placeholder": "000000",
                "class": "pairing-input",
            }
        ),
    )
