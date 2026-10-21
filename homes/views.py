import base64
import json
from datetime import timedelta

from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView, UpdateView
from django.views.decorators.cache import patch_cache_control

from .audit import record_audit
from .forms import (
    AnnotationEvaluationForm,
    CampagneEvaluationForm,
    CameraForm,
    CameraAnalysisForm,
    ConnectCameraForm,
    DerogationSurveillanceForm,
    ExceptionSurveillanceForm,
    MaisonForm,
    MaisonFuseauHoraireForm,
    ProfilBiometriqueConsentementForm,
    PlanningQuotidienForm,
    PlageSurveillanceForm,
)
from .crypto import decrypt_capture
from .models import (
    AnnotationClasseEvaluation,
    CampagneEvaluation,
    CaptureChiffree,
    Camera,
    ClasseEvaluation,
    DerogationSurveillance,
    Evenement,
    ExceptionSurveillance,
    Maison,
    MembreMaison,
    PlageSurveillance,
    ProfilBiometrique,
    StatutAppairage,
    StatutEvenement,
    ResultatAudit,
    StatutInvitation,
    StatutProfilBiometrique,
)
from .biometrics import revoke_biometric_profile
from .realtime import publish_event
from .scheduling import evaluate_surveillance
from .services import PairingError, consume_pairing_code, create_pairing_code, revoke_camera
from .throttling import check_rate_limit


class HomeView(TemplateView):
    template_name = "home.html"


class HealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"})


class MyProfileView(LoginRequiredMixin, TemplateView):
    template_name = "homes/my_profile.html"

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        houses = list(Maison.objects.visible_to(self.request.user).filter(
            membres__utilisateur=self.request.user,
            membres__statut=StatutInvitation.ACCEPTEE,
        ).distinct().order_by("nom", "pk"))
        profiles = {profile.maison_id: profile for profile in ProfilBiometrique.objects.filter(
            utilisateur=self.request.user, maison__in=houses,
            statut=StatutProfilBiometrique.ACTIF,
        )}
        context["face_houses"] = [{"maison": house, "profil": profiles.get(house.pk)} for house in houses]
        context["web_enrollment"] = (settings.BIOMETRIC_WEB_ENROLLMENT_ENABLED
                                      and bool(settings.BIOMETRIC_FACE_MODEL_ROOT))
        return context


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cameras = Camera.objects.visible_to(self.request.user)
        evenements = Evenement.objects.visible_to(self.request.user)
        evenements_operationnels = evenements.operationnels()
        limite_connexion = timezone.now() - timedelta(minutes=2)
        context.update(
            maisons=Maison.objects.visible_to(self.request.user),
            cameras=cameras[:6],
            nombre_cameras=cameras.count(),
            cameras_actives=cameras.filter(surveillance_active=True).count(),
            cameras_connectees=cameras.filter(
                derniere_connexion__gte=limite_connexion
            ).count(),
            cameras_hors_ligne=cameras.filter(
                Q(derniere_connexion__lt=limite_connexion)
                | Q(derniere_connexion__isnull=True)
            ).count(),
            cameras_revoquees=cameras.filter(statut_appairage=StatutAppairage.REVOQUEE).count(),
            evenements_recents=evenements.select_related("camera", "maison").order_by("-horodatage")[:8],
            alertes_nouvelles=evenements_operationnels.filter(
                statut=StatutEvenement.NOUVEAU, notification_supprimee=False
            ).count(),
            intrusions_confirmees=evenements_operationnels.filter(
                statut=StatutEvenement.INTRUSION_CONFIRMEE
            ).count(),
        )
        return context


class MaisonListView(LoginRequiredMixin, ListView):
    template_name = "homes/maison_list.html"
    context_object_name = "maisons"

    def get_queryset(self):
        return Maison.objects.visible_to(self.request.user).annotate(
            nombre_cameras=Count("cameras", distinct=True)
        )


class MaisonCreateView(LoginRequiredMixin, CreateView):
    form_class = MaisonForm
    template_name = "homes/form.html"
    success_url = reverse_lazy("maison-list")
    extra_context = {
        "form_eyebrow": "Nouvel espace",
        "form_title": "Créer une maison",
        "form_intro": "Commencez par nommer l’espace que vous souhaitez protéger.",
        "submit_label": "Créer la maison",
    }

    def form_valid(self, form):
        form.instance.proprietaire = self.request.user
        response = super().form_valid(form)
        record_audit(
            "house.create", request=self.request, user=self.request.user, maison=self.object, target=self.object
        )
        return response


class MaisonDetailView(LoginRequiredMixin, DetailView):
    template_name = "homes/maison_detail.html"
    context_object_name = "maison"

    def get_queryset(self):
        return Maison.objects.visible_to(self.request.user).prefetch_related("membres__utilisateur")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["cameras"] = Camera.objects.visible_to(self.request.user).filter(maison=self.object)
        return context


class ProfilBiometriqueListCreateView(LoginRequiredMixin, View):
    template_name = "homes/biometric_profiles.html"

    def dispatch(self, request, *args, **kwargs):
        self.maison = get_object_or_404(
            Maison.objects.visible_to(request.user), pk=kwargs["maison_pk"]
        )
        self.membership = MembreMaison.objects.filter(
            maison=self.maison,
            utilisateur=request.user,
            statut=StatutInvitation.ACCEPTEE,
        ).first()
        return super().dispatch(request, *args, **kwargs)

    def _context(self, form=None):
        own_active = ProfilBiometrique.objects.filter(
            maison=self.maison,
            utilisateur=self.request.user,
            statut=StatutProfilBiometrique.ACTIF,
        ).first()
        return {
            "maison": self.maison,
            "mon_profil": own_active,
            "web_enrollment": (settings.BIOMETRIC_WEB_ENROLLMENT_ENABLED
                               and bool(settings.BIOMETRIC_FACE_MODEL_ROOT)),
            "profils": ProfilBiometrique.objects.visible_to(self.request.user).filter(
                maison=self.maison
            ),
            "form": form or ProfilBiometriqueConsentementForm(),
            "peut_creer": self.membership is not None and not own_active,
        }

    def get(self, request, maison_pk):
        return render(request, self.template_name, self._context())

    def post(self, request, maison_pk):
        if self.membership is None:
            raise PermissionDenied
        if ProfilBiometrique.objects.filter(
            maison=self.maison,
            utilisateur=request.user,
            statut=StatutProfilBiometrique.ACTIF,
        ).exists():
            messages.error(request, "Vous avez déjà un profil actif dans cette maison.")
            return redirect("biometric-profile-list", maison_pk=self.maison.pk)
        form = ProfilBiometriqueConsentementForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form), status=400)
        profile = ProfilBiometrique(
            maison=self.maison,
            utilisateur=request.user,
            libelle=form.cleaned_data["libelle"],
        )
        profile.full_clean()
        profile.save()
        record_audit(
            "biometric.profile.consent",
            request=request,
            maison=self.maison,
            target=profile,
            metadata={"consent_version": profile.version_consentement},
        )
        messages.success(
            request,
            "Votre accord est enregistré. Vous pouvez maintenant enregistrer votre visage.",
        )
        if settings.BIOMETRIC_WEB_ENROLLMENT_ENABLED and settings.BIOMETRIC_FACE_MODEL_ROOT:
            return redirect("biometric-profile-enroll", maison_pk=self.maison.pk, profile_pk=profile.pk)
        return redirect("biometric-profile-list", maison_pk=self.maison.pk)


class ProfilBiometriqueExportView(LoginRequiredMixin, View):
    def get(self, request, maison_pk, profile_pk):
        maison = get_object_or_404(Maison.objects.visible_to(request.user), pk=maison_pk)
        profile = get_object_or_404(
            ProfilBiometrique,
            pk=profile_pk,
            maison=maison,
            utilisateur=request.user,
        )
        template = None
        try:
            decrypted = profile.decrypt_template()
            if decrypted is not None:
                template = base64.b64encode(decrypted).decode("ascii")
        except InvalidTag:
            record_audit(
                "biometric.profile.export",
                ResultatAudit.ECHEC,
                request=request,
                maison=maison,
                target=profile,
            )
            return HttpResponse("Le profil biométrique est illisible.", status=409)
        payload = {
            "profile_id": str(profile.pk),
            "house_id": profile.maison_id,
            "label": profile.libelle,
            "status": profile.statut,
            "consent_version": profile.version_consentement,
            "consented_at": profile.date_consentement.isoformat(),
            "withdrawn_at": profile.date_retrait.isoformat() if profile.date_retrait else None,
            "template_format": profile.format_gabarit or None,
            "template_base64": template,
        }
        response = HttpResponse(
            json.dumps(payload, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="profil-{profile.pk}.json"'
        response["Cache-Control"] = "no-store, private"
        record_audit(
            "biometric.profile.export",
            request=request,
            maison=maison,
            target=profile,
        )
        return response


class ProfilBiometriqueRevokeView(LoginRequiredMixin, View):
    def post(self, request, maison_pk, profile_pk):
        maison = get_object_or_404(Maison.objects.visible_to(request.user), pk=maison_pk)
        profile = get_object_or_404(
            ProfilBiometrique.objects.visible_to(request.user),
            pk=profile_pk,
            maison=maison,
        )
        profile = revoke_biometric_profile(profile)
        record_audit(
            "biometric.profile.withdraw",
            request=request,
            maison=maison,
            target=profile,
            metadata={"version": profile.version},
        )
        messages.success(
            request,
            "Le profil est retiré et son gabarit a été effacé du serveur.",
        )
        return redirect("biometric-profile-list", maison_pk=maison.pk)


class PlanningMaisonView(LoginRequiredMixin, DetailView):
    model = Maison
    template_name = "homes/planning_detail.html"
    context_object_name = "maison"

    def get_queryset(self):
        return Maison.objects.visible_to(self.request.user).prefetch_related(
            "plages_surveillance", "exceptions_surveillance"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["decision"] = evaluate_surveillance(self.object)
        context["est_proprietaire"] = self.object.proprietaire_id == self.request.user.id
        try:
            override = self.object.derogation_surveillance
        except DerogationSurveillance.DoesNotExist:
            override = None
        context["derogation"] = override if override and override.expire_le > timezone.now() else None
        context["fuseau_form"] = MaisonFuseauHoraireForm(instance=self.object)
        context["derogation_form"] = DerogationSurveillanceForm()
        daily_window = self.object.plages_surveillance.filter(
            nom="Planning quotidien", active=True
        ).first()
        context["planning_quotidien"] = daily_window
        context["plages_avancees"] = self.object.plages_surveillance.exclude(
            nom="Planning quotidien"
        )
        context["planning_quotidien_form"] = PlanningQuotidienForm(
            initial={
                "heure_activation": daily_window.heure_debut if daily_window else None,
                "heure_arret": daily_window.heure_fin if daily_window else None,
            }
        )
        return context


class OwnerHouseMixin(LoginRequiredMixin):
    maison = None

    def dispatch(self, request, *args, **kwargs):
        self.maison = get_object_or_404(
            Maison, pk=kwargs["maison_pk"], proprietaire=request.user
        )
        return super().dispatch(request, *args, **kwargs)

    def get_success_url(self):
        return reverse("planning-detail", kwargs={"pk": self.maison.pk})


class PlanningQuotidienUpdateView(OwnerHouseMixin, View):
    def post(self, request, maison_pk):
        form = PlanningQuotidienForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Saisissez deux heures différentes.")
            return redirect("planning-detail", pk=self.maison.pk)
        start = form.cleaned_data["heure_activation"]
        end = form.cleaned_data["heure_arret"]
        with transaction.atomic():
            self.maison.plages_surveillance.filter(nom="Planning quotidien").delete()
            PlageSurveillance.objects.bulk_create(
                [
                    PlageSurveillance(
                        maison=self.maison,
                        nom="Planning quotidien",
                        jour=day,
                        heure_debut=start,
                        heure_fin=end,
                        active=True,
                    )
                    for day in range(7)
                ]
            )
        record_audit(
            "schedule.daily.update",
            request=request,
            maison=self.maison,
            target=self.maison,
            metadata={"start": start.isoformat(), "end": end.isoformat()},
        )
        messages.success(request, "Le démarrage et l’arrêt automatiques sont enregistrés.")
        return redirect("planning-detail", pk=self.maison.pk)


class PlageSurveillanceCreateView(OwnerHouseMixin, CreateView):
    form_class = PlageSurveillanceForm
    template_name = "homes/form.html"
    extra_context = {
        "form_eyebrow": "Planning",
        "form_title": "Ajouter une plage",
        "form_intro": "Une plage traversant minuit continue automatiquement le jour suivant.",
        "submit_label": "Ajouter la plage",
    }

    def form_valid(self, form):
        form.instance.maison = self.maison
        response = super().form_valid(form)
        record_audit(
            "schedule.window.create",
            request=self.request,
            maison=self.maison,
            target=self.object,
            metadata={"day": self.object.jour},
        )
        return response


class PlageSurveillanceUpdateView(OwnerHouseMixin, UpdateView):
    form_class = PlageSurveillanceForm
    template_name = "homes/form.html"
    pk_url_kwarg = "plage_pk"
    extra_context = {
        "form_eyebrow": "Planning",
        "form_title": "Modifier la plage",
        "submit_label": "Enregistrer",
    }

    def get_queryset(self):
        return PlageSurveillance.objects.filter(maison=self.maison)

    def form_valid(self, form):
        response = super().form_valid(form)
        record_audit(
            "schedule.window.update",
            request=self.request,
            maison=self.maison,
            target=self.object,
        )
        return response


class PlageSurveillanceDeleteView(OwnerHouseMixin, View):
    def post(self, request, maison_pk, plage_pk):
        window = get_object_or_404(
            PlageSurveillance, pk=plage_pk, maison=self.maison
        )
        record_audit(
            "schedule.window.delete",
            request=request,
            maison=self.maison,
            target=window,
        )
        window.delete()
        return redirect("planning-detail", pk=self.maison.pk)


class ExceptionSurveillanceCreateView(OwnerHouseMixin, CreateView):
    form_class = ExceptionSurveillanceForm
    template_name = "homes/form.html"
    extra_context = {
        "form_eyebrow": "Exception",
        "form_title": "Ajouter une exception",
        "form_intro": "Une priorité plus élevée gagne si deux exceptions se chevauchent.",
        "submit_label": "Ajouter l’exception",
    }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["house_timezone"] = self.maison.fuseau_horaire
        return kwargs

    def form_valid(self, form):
        form.instance.maison = self.maison
        response = super().form_valid(form)
        record_audit(
            "schedule.exception.create",
            request=self.request,
            maison=self.maison,
            target=self.object,
            metadata={"priority": self.object.priorite},
        )
        return response


class ExceptionSurveillanceUpdateView(OwnerHouseMixin, UpdateView):
    form_class = ExceptionSurveillanceForm
    template_name = "homes/form.html"
    pk_url_kwarg = "exception_pk"
    extra_context = {
        "form_eyebrow": "Exception",
        "form_title": "Modifier l’exception",
        "submit_label": "Enregistrer",
    }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["house_timezone"] = self.maison.fuseau_horaire
        return kwargs

    def get_queryset(self):
        return ExceptionSurveillance.objects.filter(maison=self.maison)

    def form_valid(self, form):
        response = super().form_valid(form)
        record_audit(
            "schedule.exception.update",
            request=self.request,
            maison=self.maison,
            target=self.object,
        )
        return response


class ExceptionSurveillanceDeleteView(OwnerHouseMixin, View):
    def post(self, request, maison_pk, exception_pk):
        exception = get_object_or_404(
            ExceptionSurveillance, pk=exception_pk, maison=self.maison
        )
        record_audit(
            "schedule.exception.delete",
            request=request,
            maison=self.maison,
            target=exception,
        )
        exception.delete()
        return redirect("planning-detail", pk=self.maison.pk)


class MaisonFuseauHoraireUpdateView(OwnerHouseMixin, View):
    def post(self, request, maison_pk):
        form = MaisonFuseauHoraireForm(request.POST, instance=self.maison)
        if not form.is_valid():
            messages.error(request, "Fuseau horaire invalide.")
            return redirect("planning-detail", pk=self.maison.pk)
        form.save()
        record_audit(
            "schedule.timezone.update",
            request=request,
            maison=self.maison,
            target=self.maison,
            metadata={"timezone": self.maison.fuseau_horaire},
        )
        return redirect("planning-detail", pk=self.maison.pk)


class DerogationSurveillanceUpdateView(OwnerHouseMixin, View):
    def post(self, request, maison_pk):
        form = DerogationSurveillanceForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Dérogation invalide.")
            return redirect("planning-detail", pk=self.maison.pk)
        expires = timezone.now() + timedelta(minutes=form.cleaned_data["duree_minutes"])
        override, _ = DerogationSurveillance.objects.update_or_create(
            maison=self.maison,
            defaults={
                "surveillance_active": form.cleaned_data["surveillance_active"],
                "expire_le": expires,
                "creee_par": request.user,
            },
        )
        record_audit(
            "schedule.override.set",
            request=request,
            maison=self.maison,
            target=override,
            metadata={
                "monitoring_active": override.surveillance_active,
                "expires_at": expires.isoformat(),
            },
        )
        return redirect("planning-detail", pk=self.maison.pk)


class DerogationSurveillanceDeleteView(OwnerHouseMixin, View):
    def post(self, request, maison_pk):
        override = DerogationSurveillance.objects.filter(maison=self.maison).first()
        if override:
            record_audit(
                "schedule.override.clear",
                request=request,
                maison=self.maison,
                target=override,
            )
            override.delete()
        return redirect("planning-detail", pk=self.maison.pk)


class CameraListView(LoginRequiredMixin, ListView):
    template_name = "homes/camera_list.html"
    context_object_name = "cameras"

    def get_queryset(self):
        return Camera.objects.visible_to(self.request.user).select_related("maison")


class CameraCreateView(LoginRequiredMixin, CreateView):
    form_class = CameraForm
    template_name = "homes/form.html"
    extra_context = {
        "form_eyebrow": "Nouvel équipement",
        "form_title": "Ajouter une caméra",
        "form_intro": "Choisissez sa maison et un nom facile à reconnaître lors d’une alerte.",
        "submit_label": "Ajouter la caméra",
    }

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["user"] = self.request.user
        return kwargs

    def get_success_url(self):
        return reverse_lazy("camera-detail", kwargs={"pk": self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        record_audit(
            "camera.create",
            request=self.request,
            user=self.request.user,
            camera=self.object,
            target=self.object,
        )
        return response


class CameraDetailView(LoginRequiredMixin, DetailView):
    template_name = "homes/camera_detail.html"
    context_object_name = "camera"

    def get_queryset(self):
        return Camera.objects.visible_to(self.request.user).select_related("maison")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["evenements"] = Evenement.objects.visible_to(self.request.user).filter(
            camera=self.object
        ).order_by("-horodatage")[:8]
        return context


class CameraEvaluationView(LoginRequiredMixin, DetailView):
    model = Camera
    template_name = "homes/camera_evaluation.html"
    context_object_name = "camera"

    def get_queryset(self):
        return Camera.objects.filter(maison__proprietaire=self.request.user).select_related("maison")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        campaigns = self.object.campagnes_evaluation.select_related("creee_par").prefetch_related("annotations_classes")
        context["campagne_active"] = campaigns.filter(date_fin__isnull=True).first()
        completed = list(campaigns.filter(date_fin__isnull=False))
        context["campagnes_terminees"] = completed[:12]
        context["form"] = CampagneEvaluationForm()
        annotations = AnnotationClasseEvaluation.objects.filter(
            campagne__camera=self.object,
            campagne__date_fin__isnull=False,
        ).select_related("campagne")
        reports = []
        for partition, partition_label in (("calibration", "Ajustement des seuils"), ("evaluation", "Évaluation indépendante")):
            metrics = []
            partition_campaigns = [
                campaign for campaign in completed
                if campaign.partition == partition and campaign.annotation_complete
            ]
            partition_campaign_ids = {campaign.pk for campaign in partition_campaigns}
            partition_annotations = [item for item in annotations if item.campagne_id in partition_campaign_ids]
            for class_code, class_label in ClasseEvaluation.choices:
                class_annotations = [item for item in partition_annotations if item.classe == class_code]
                expected = sum(item.occurrences_attendues for item in class_annotations)
                true_positives = sum(item.vrais_positifs for item in class_annotations)
                false_positives = sum(item.faux_positifs for item in class_annotations)
                precision_denominator = true_positives + false_positives
                metrics.append({
                    "label": class_label,
                    "expected": expected,
                    "true_positives": true_positives,
                    "false_positives": false_positives,
                    "precision": None if precision_denominator == 0 else 100 * true_positives / precision_denominator,
                    "recall": None if expected == 0 else 100 * true_positives / expected,
                })
            duration_seconds = sum(campaign.duree_secondes for campaign in partition_campaigns)
            false_alerts = sum(item.faux_positifs for item in partition_annotations)
            cpu_campaigns = [campaign for campaign in partition_campaigns if campaign.cpu_moyen_pourcent is not None]
            cpu_duration = sum(campaign.duree_secondes for campaign in cpu_campaigns)
            cpu_average = None
            if cpu_duration:
                cpu_average = sum(
                    campaign.cpu_moyen_pourcent * campaign.duree_secondes
                    for campaign in cpu_campaigns
                ) / cpu_duration
            ram_values = [campaign.ram_pic_mo for campaign in partition_campaigns if campaign.ram_pic_mo is not None]
            reports.append({
                "label": partition_label,
                "metrics": metrics,
                "duration_hours": duration_seconds / 3600,
                "false_alerts": false_alerts,
                "false_alerts_per_hour": None if duration_seconds == 0 else false_alerts * 3600 / duration_seconds,
                "cpu_average": cpu_average,
                "ram_peak": max(ram_values) if ram_values else None,
            })
        context["rapports"] = reports
        return context


class CameraEvaluationAnnotationView(LoginRequiredMixin, View):
    template_name = "homes/camera_evaluation_annotation.html"

    def get_campaign(self, request, pk, campagne_pk):
        camera = get_object_or_404(Camera, pk=pk, maison__proprietaire=request.user)
        campaign = get_object_or_404(
            CampagneEvaluation.objects.prefetch_related("annotations_classes"),
            pk=campagne_pk,
            camera=camera,
            date_fin__isnull=False,
        )
        return camera, campaign

    def render_form(self, request, camera, campaign, form):
        rows = []
        for code, label in ClasseEvaluation.choices:
            rows.append({
                "label": label,
                "expected": form[f"{code}_attendues"],
                "correct": form[f"{code}_correctes"],
                "false": form[f"{code}_fausses"],
            })
        events = camera.evenements.filter(
            horodatage_observation__gte=campaign.date_debut,
            horodatage_observation__lt=campaign.date_fin,
            simule=False,
        ).prefetch_related("objets")
        return render(request, self.template_name, {
            "camera": camera,
            "campagne": campaign,
            "form": form,
            "annotation_rows": rows,
            "evenements": events,
        })

    def get(self, request, pk, campagne_pk):
        camera, campaign = self.get_campaign(request, pk, campagne_pk)
        form = AnnotationEvaluationForm(campagne=campaign)
        return self.render_form(request, camera, campaign, form)

    def post(self, request, pk, campagne_pk):
        camera, campaign = self.get_campaign(request, pk, campagne_pk)
        form = AnnotationEvaluationForm(request.POST, campagne=campaign)
        if not form.is_valid():
            return self.render_form(request, camera, campaign, form)
        with transaction.atomic():
            annotations = form.save(request.user)
            record_audit(
                "evaluation.campaign.annotate",
                request=request,
                user=request.user,
                camera=camera,
                target=campaign,
                metadata={
                    item.classe: {
                        "expected": item.occurrences_attendues,
                        "true_positives": item.vrais_positifs,
                        "false_positives": item.faux_positifs,
                    }
                    for item in annotations
                },
            )
        messages.success(request, "Annotations enregistrées et rapport recalculé.")
        return redirect("camera-evaluation", pk=camera.pk)


class CameraEvaluationStartView(LoginRequiredMixin, View):
    def post(self, request, pk):
        camera = get_object_or_404(Camera, pk=pk, maison__proprietaire=request.user)
        if camera.campagnes_evaluation.filter(date_fin__isnull=True).exists():
            messages.error(request, "Une campagne est déjà active pour cette caméra.")
            return redirect("camera-evaluation", pk=camera.pk)
        form = CampagneEvaluationForm(request.POST)
        if not form.is_valid():
            campaigns = camera.campagnes_evaluation.select_related("creee_par")
            return render(request, "homes/camera_evaluation.html", {
                "camera": camera,
                "campagne_active": campaigns.filter(date_fin__isnull=True).first(),
                "campagnes_terminees": campaigns.filter(date_fin__isnull=False)[:12],
                "form": form,
            })
        campaign = form.save(commit=False)
        campaign.camera = camera
        campaign.creee_par = request.user
        campaign.save()
        record_audit(
            "evaluation.campaign.start",
            request=request,
            user=request.user,
            camera=camera,
            target=campaign,
            metadata={"partition": campaign.partition, "condition": campaign.condition},
        )
        messages.success(request, "Campagne terrain démarrée.")
        return redirect("camera-evaluation", pk=camera.pk)


class CameraEvaluationStopView(LoginRequiredMixin, View):
    def post(self, request, pk, campagne_pk):
        camera = get_object_or_404(Camera, pk=pk, maison__proprietaire=request.user)
        campaign = get_object_or_404(
            CampagneEvaluation,
            pk=campagne_pk,
            camera=camera,
            date_fin__isnull=True,
        )
        campaign.date_fin = timezone.now()
        campaign.save(update_fields=("date_fin",))
        record_audit(
            "evaluation.campaign.stop",
            request=request,
            user=request.user,
            camera=camera,
            target=campaign,
            metadata={
                "duration_seconds": campaign.duree_secondes,
                "event_count": campaign.nombre_evenements,
            },
        )
        messages.success(request, "Campagne terrain arrêtée et durée enregistrée.")
        return redirect("camera-evaluation", pk=camera.pk)


class CameraAnalysisUpdateView(LoginRequiredMixin, FormView):
    form_class = CameraAnalysisForm
    template_name = "homes/form.html"
    extra_context = {
        "form_eyebrow": "Analyse locale",
        "form_title": "Configurer les règles de détection",
        "form_intro": "Réglez la zone, les seuils, la durée et le regroupement des alertes.",
        "submit_label": "Enregistrer les règles",
    }

    def dispatch(self, request, *args, **kwargs):
        self.camera = get_object_or_404(
            Camera.objects.select_related("maison"),
            pk=kwargs["pk"],
            maison__proprietaire=request.user,
        )
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["camera"] = self.camera
        return kwargs

    def form_valid(self, form):
        form.save()
        record_audit(
            "camera.analysis.update",
            request=self.request,
            user=self.request.user,
            camera=self.camera,
            target=self.camera,
            metadata={
                "zone": self.camera.zone_analyse,
                "line_enabled": self.camera.ligne_analyse is not None,
                "presence_seconds": self.camera.duree_presence_secondes,
                "person_threshold": self.camera.seuil_alerte_personne,
                "animal_threshold": self.camera.seuil_alerte_animal,
                "grouping_window_seconds": self.camera.fenetre_regroupement_secondes,
            },
        )
        messages.success(self.request, "Règles, seuils et regroupement des alertes enregistrés.")
        return redirect("camera-detail", pk=self.camera.pk)


class CameraToggleView(LoginRequiredMixin, View):
    def post(self, request, pk):
        camera = Camera.objects.visible_to(request.user).filter(pk=pk).first()
        if not camera:
            raise PermissionDenied
        if camera.maison.proprietaire_id != request.user.id:
            raise PermissionDenied
        if camera.statut_appairage == StatutAppairage.REVOQUEE:
            raise PermissionDenied
        camera.surveillance_active = not camera.surveillance_active
        camera.save(update_fields=("surveillance_active",))
        record_audit(
            "camera.monitoring.toggle",
            request=request,
            user=request.user,
            camera=camera,
            target=camera,
            metadata={"monitoring_active": camera.surveillance_active},
        )
        if request.POST.get("return_to") == "monitor":
            return redirect("camera-monitor")
        return redirect("camera-detail", pk=camera.pk)


class PairingCodeCreateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        camera = get_object_or_404(
            Camera.objects.select_related("maison"), pk=pk, maison__proprietaire=request.user
        )
        rate = check_rate_limit(
            "pairing_code", request, identifier=f"{request.user.pk}:{camera.pk}"
        )
        if not rate.allowed:
            record_audit(
                "camera.pairing_code.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                user=request.user,
                camera=camera,
                target=camera,
                metadata={"retry_after": rate.retry_after},
            )
            response = HttpResponse("Trop de codes demandés. Réessayez plus tard.", status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        try:
            pairing_code, plain_code = create_pairing_code(camera)
        except PairingError as exc:
            record_audit(
                "camera.pairing_code.failure",
                ResultatAudit.REFUS,
                request=request,
                user=request.user,
                camera=camera,
                target=camera,
            )
            messages.error(request, str(exc))
            return redirect("camera-detail", pk=camera.pk)
        record_audit(
            "camera.pairing_code.created",
            request=request,
            user=request.user,
            camera=camera,
            target=camera,
            metadata={"expires_at": pairing_code.date_expiration.isoformat()},
        )
        response = render(
            request,
            "homes/pairing_code.html",
            {"camera": camera, "pairing_code": pairing_code, "plain_code": plain_code},
        )
        patch_cache_control(response, no_store=True, private=True)
        return response


class ConnectCameraView(LoginRequiredMixin, FormView):
    form_class = ConnectCameraForm
    template_name = "homes/connect_camera.html"

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, no_store=True, private=True)
        return response

    def post(self, request, *args, **kwargs):
        rate = check_rate_limit("pairing", request)
        if not rate.allowed:
            form = self.get_form()
            form.add_error(None, "Trop de tentatives d’appairage. Réessayez plus tard.")
            record_audit(
                "camera.pairing.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                metadata={"retry_after": rate.retry_after},
            )
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            credentials = consume_pairing_code(form.cleaned_data["code"], user=self.request.user)
        except PairingError as exc:
            record_audit("camera.pairing.failure", ResultatAudit.REFUS, request=self.request)
            form.add_error("code", str(exc))
            return self.form_invalid(form)
        record_audit(
            "camera.pairing.success",
            request=self.request,
            camera=credentials.camera,
            target=credentials.camera,
        )
        response = self.render_to_response(
            self.get_context_data(
                form=form,
                paired=True,
                camera=credentials.camera,
                device_credentials={
                    "cameraId": str(credentials.camera.pk),
                },
            )
        )
        patch_cache_control(response, no_store=True, private=True)
        return response


class CameraMonitorView(LoginRequiredMixin, TemplateView):
    template_name = "homes/camera_monitor.html"

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        patch_cache_control(response, no_store=True, private=True)
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from .browser_camera import browser_camera_context
        context["browser_camera_context"] = browser_camera_context(self.request)
        context["requested_camera_id"] = self.request.GET.get("camera", "")
        context["web_face_recognition"] = (settings.BIOMETRIC_WEB_RECOGNITION_ENABLED
                                            and bool(settings.BIOMETRIC_FACE_MODEL_ROOT))
        context["weapon_mode"] = settings.WEAPON_DETECTION_MODE
        from .weapon_demo import academic_demo_enabled, academic_site_demo_cameras
        context["weapon_academic_demo"] = academic_demo_enabled(self.request, context["requested_camera_id"])
        context["weapon_available"] = (settings.WEAPON_DETECTION_MODE in {"review", "alerts"}
                                       and bool(settings.WEAPON_MODEL_ROOT))
        if settings.WEAPON_ACADEMIC_SITE_ENABLED:
            context["weapon_available"] = context["weapon_available"] and context["weapon_academic_demo"]
            if not context["requested_camera_id"]:
                context["weapon_demo_cameras"] = academic_site_demo_cameras(self.request.user)
        return context


class EvenementListView(LoginRequiredMixin, ListView):
    template_name = "homes/event_list.html"
    context_object_name = "evenements"
    paginate_by = 30

    def get_queryset(self):
        return (
            Evenement.objects.visible_to(self.request.user)
            .select_related("camera", "maison", "boite_envoi", "evenement_principal")
            .prefetch_related("objets", "evenements_regroupes")
            .order_by("-horodatage")
        )


class EvenementDetailView(LoginRequiredMixin, DetailView):
    template_name = "homes/event_detail.html"
    context_object_name = "evenement"

    def get_queryset(self):
        return (
            Evenement.objects.visible_to(self.request.user)
            .select_related("camera", "maison", "boite_envoi", "evenement_principal")
            .prefetch_related("objets", "evenements_regroupes")
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["peut_decider"] = Evenement.objects.controllable_by(
            self.request.user
        ).filter(pk=self.object.pk).exists()
        return context


class EvenementDecisionView(LoginRequiredMixin, View):
    decisions = {
        "false_alarm": StatutEvenement.FAUSSE_ALERTE,
        "confirmed": StatutEvenement.INTRUSION_CONFIRMEE,
    }

    def post(self, request, pk):
        decision = request.POST.get("decision", "")
        nouveau_statut = self.decisions.get(decision)
        if nouveau_statut is None:
            return HttpResponseBadRequest("Décision invalide.")

        with transaction.atomic():
            evenement = get_object_or_404(
                Evenement.objects.controllable_by(request.user).select_for_update(), pk=pk
            )
            if evenement.statut != StatutEvenement.NOUVEAU:
                return HttpResponse("Cette alerte a déjà été traitée.", status=409)
            evenement.statut = nouveau_statut
            evenement.save(update_fields=("statut",))
            record_audit(
                "event.decision",
                request=request,
                user=request.user,
                camera=evenement.camera,
                maison=evenement.maison,
                target=evenement,
                metadata={"decision": nouveau_statut},
            )
            transaction.on_commit(
                lambda: publish_event(evenement.pk, message_type="alert.updated")
            )

        decision_label = evenement.get_statut_display()
        if (evenement.metadonnees.get("weapon_verification") or {}).get("state") == "suspected" and nouveau_statut == StatutEvenement.INTRUSION_CONFIRMEE:
            decision_label = "Signalement confirmé"
        messages.success(request, f"Alerte classée : {decision_label}.")
        return redirect("event-detail", pk=evenement.pk)


class CaptureView(LoginRequiredMixin, View):
    def get(self, request, pk):
        capture = get_object_or_404(
            CaptureChiffree.objects.select_related("evenement"),
            evenement__in=Evenement.objects.visible_to(request.user),
            evenement_id=pk,
        )
        plaintext = decrypt_capture(
            bytes(capture.contenu_chiffre), bytes(capture.nonce), capture.evenement_id
        )
        response = HttpResponse(plaintext, content_type=capture.type_mime)
        response["Content-Disposition"] = f'inline; filename="capture-{capture.evenement_id}.jpg"'
        response["X-Content-Type-Options"] = "nosniff"
        patch_cache_control(response, no_store=True, private=True)
        return response


class CameraRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        camera = get_object_or_404(
            Camera.objects.select_related("maison"), pk=pk, maison__proprietaire=request.user
        )
        revoke_camera(camera)
        record_audit(
            "camera.revoke",
            request=request,
            user=request.user,
            camera=camera,
            target=camera,
        )
        messages.success(request, f"La caméra « {camera.nom} » a été révoquée.")
        return redirect("camera-detail", pk=camera.pk)


def error_403(request, exception=None):
    return render(request, "errors/403.html", status=403)


def error_404(request, exception=None):
    return render(request, "errors/404.html", status=404)


def error_500(request):
    return render(request, "errors/500.html", status=500)
