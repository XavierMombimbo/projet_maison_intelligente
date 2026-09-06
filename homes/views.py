from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, FormView, ListView, TemplateView
from django.views.decorators.cache import patch_cache_control

from .audit import record_audit
from .forms import CameraForm, ConnectCameraForm, MaisonForm
from .crypto import decrypt_capture
from .models import (
    CaptureChiffree,
    Camera,
    Evenement,
    Maison,
    StatutAppairage,
    StatutEvenement,
    ResultatAudit,
)
from .realtime import publish_event
from .services import PairingError, consume_pairing_code, create_pairing_code, revoke_camera
from .throttling import check_rate_limit


class HomeView(TemplateView):
    template_name = "home.html"


class HealthView(View):
    def get(self, request):
        return JsonResponse({"status": "ok"})


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        cameras = Camera.objects.visible_to(self.request.user)
        evenements = Evenement.objects.visible_to(self.request.user)
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
            evenements_recents=evenements.select_related("camera", "maison")[:8],
            alertes_nouvelles=evenements.filter(statut=StatutEvenement.NOUVEAU).count(),
            intrusions_confirmees=evenements.filter(
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
        )[:8]
        return context


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


class ConnectCameraView(FormView):
    form_class = ConnectCameraForm
    template_name = "homes/connect_camera.html"

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
            credentials = consume_pairing_code(form.cleaned_data["code"])
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
                    "deviceId": credentials.device_id,
                    "deviceSecret": credentials.device_secret,
                    "eventSigningKey": credentials.event_signing_key,
                    "accessToken": credentials.access_token,
                },
            )
        )
        patch_cache_control(response, no_store=True, private=True)
        return response


class CameraMonitorView(TemplateView):
    template_name = "homes/camera_monitor.html"


class EvenementListView(LoginRequiredMixin, ListView):
    template_name = "homes/event_list.html"
    context_object_name = "evenements"
    paginate_by = 30

    def get_queryset(self):
        return Evenement.objects.visible_to(self.request.user).select_related("camera", "maison")


class EvenementDetailView(LoginRequiredMixin, DetailView):
    template_name = "homes/event_detail.html"
    context_object_name = "evenement"

    def get_queryset(self):
        return Evenement.objects.visible_to(self.request.user).select_related("camera", "maison")

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

        messages.success(request, f"Alerte classée : {evenement.get_statut_display()}.")
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
