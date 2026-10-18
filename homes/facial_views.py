import json

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import RequestDataTooBig
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.decorators.debug import sensitive_variables

from gateway.facial import ARCFACE_TEMPLATE_FORMAT, FaceQualityError
from .audit import record_audit
from .facial_enrollment import (
    MAX_REQUEST_BYTES, EnrollmentBusy, EnrollmentUnavailable, template_from_capture,
)
from .models import Maison, MembreMaison, ProfilBiometrique, StatutInvitation, StatutProfilBiometrique
from .throttling import check_rate_limit


class FacialEnrollmentView(LoginRequiredMixin, View):
    """An accepted member may enrol only their own, consenting pending profile."""

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    def _profile(self, request, maison_pk, profile_pk):
        maison = get_object_or_404(Maison.objects.visible_to(request.user), pk=maison_pk)
        get_object_or_404(MembreMaison, maison=maison, utilisateur=request.user,
                          statut=StatutInvitation.ACCEPTEE)
        return get_object_or_404(ProfilBiometrique, pk=profile_pk, maison=maison,
                                utilisateur=request.user, statut=StatutProfilBiometrique.ACTIF)

    def get(self, request, maison_pk, profile_pk):
        profile = self._profile(request, maison_pk, profile_pk)
        return render(request, "homes/facial_enrollment.html", {
            "profil": profile, "maison": profile.maison,
            "enrollment_available": (settings.BIOMETRIC_WEB_ENROLLMENT_ENABLED
                                     and bool(settings.BIOMETRIC_FACE_MODEL_ROOT)),
        })

    @sensitive_variables()
    def post(self, request, maison_pk, profile_pk):
        profile = self._profile(request, maison_pk, profile_pk)
        if profile.est_enrole:
            return JsonResponse({"detail": "Votre visage est déjà enregistré."}, status=409)
        if not settings.BIOMETRIC_WEB_ENROLLMENT_ENABLED or not settings.BIOMETRIC_FACE_MODEL_ROOT:
            return JsonResponse({"detail": "L’enregistrement du visage est temporairement indisponible."}, status=503)
        rate = check_rate_limit("biometric_enrollment", request, identifier=str(request.user.pk))
        if not rate.allowed:
            response = JsonResponse({"detail": "Trop d’essais. Réessayez dans quelques minutes."}, status=429)
            response["Retry-After"] = str(rate.retry_after)
            return response
        try:
            if request.content_type != "application/json":
                raise ValueError
            if int(request.META.get("CONTENT_LENGTH") or 0) > MAX_REQUEST_BYTES:
                raise RequestDataTooBig
            body = request.body
            if len(body) > MAX_REQUEST_BYTES:
                raise RequestDataTooBig
            payload = json.loads(body)
            if not isinstance(payload, dict) or payload.get("consent") is not True:
                return JsonResponse({"detail": "Confirmez votre accord avant d’enregistrer votre visage."}, status=400)
            template = template_from_capture(payload.get("image"))
        except RequestDataTooBig:
            return JsonResponse({"detail": "Capture trop volumineuse. Réessayez avec la caméra."}, status=413)
        except (ValueError, UnicodeError):
            return JsonResponse({"detail": "Capture invalide. Ouvrez la caméra et réessayez."}, status=400)
        except FaceQualityError as exc:
            return JsonResponse({"detail": str(exc)}, status=422)
        except EnrollmentBusy:
            return JsonResponse({"detail": "Un enregistrement est en cours. Réessayez dans un instant."}, status=409)
        except EnrollmentUnavailable:
            return JsonResponse({"detail": "L’enregistrement du visage est temporairement indisponible."}, status=503)
        # Recheck all rights after inference: consent or membership may have
        # been withdrawn while the face model was processing the capture.
        with transaction.atomic():
            get_object_or_404(Maison.objects.select_for_update(), pk=maison_pk)
            get_object_or_404(MembreMaison.objects.select_for_update(), maison_id=maison_pk,
                              utilisateur=request.user, statut=StatutInvitation.ACCEPTEE)
            locked = get_object_or_404(ProfilBiometrique.objects.select_for_update(),
                pk=profile.pk, maison_id=maison_pk, utilisateur=request.user,
                statut=StatutProfilBiometrique.ACTIF)
            if locked.est_enrole:
                return JsonResponse({"detail": "Votre visage est déjà enregistré."}, status=409)
            locked.set_template(template, ARCFACE_TEMPLATE_FORMAT)
            record_audit("biometric.profile.enroll", request=request, maison=locked.maison,
                         target=locked, metadata={"format": ARCFACE_TEMPLATE_FORMAT, "source": "web"})
        return JsonResponse({"status": "enrolled", "detail": "Votre visage est enregistré."})
