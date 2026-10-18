"""Short-lived browser camera grants, tied to the current web session."""
import hmac
import uuid

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.crypto import salted_hmac
from django.views import View

from .models import Camera, StatutAppairage, TypeSourceCamera
from .security import issue_camera_token
from .services import ensure_event_signing_key
from .throttling import check_rate_limit


def browser_camera_context(request):
    session_key = getattr(getattr(request, "session", None), "session_key", None)
    if not request.user.is_authenticated or not session_key:
        return ""
    return salted_hmac("browser-camera-session", f"{request.user.pk}:{session_key}",
                       secret=settings.SECRET_KEY, algorithm="sha256").hexdigest()


def is_browser_camera_request(request):
    return bool(request.headers.get("Sec-Fetch-Site") or request.headers.get("Origin"))


def browser_camera_template_context(request):
    return {"camera_session_context": browser_camera_context(request)}


class BrowserCameraContextView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    def get(self, request):
        context = browser_camera_context(request)
        supplied = request.headers.get("X-Sentinelle-Camera-Context", "")
        if not context or not hmac.compare_digest(supplied, context):
            return JsonResponse({"detail": "Le compte ou la session a changé. Rechargez la page."}, status=409)
        cameras = Camera.objects.controllable_by(request.user).filter(
            statut_appairage=StatutAppairage.APPAIREE, date_revocation__isnull=True,
            type_source=TypeSourceCamera.WEBCAM)
        camera_id = request.GET.get("camera", "")
        if not camera_id:
            response = JsonResponse({"camera_ids": [str(pk) for pk in cameras.values_list("pk", flat=True)]})
        else:
            try:
                uuid.UUID(camera_id)
            except ValueError:
                return JsonResponse({"detail": "Caméra non autorisée."}, status=404)
            camera = get_object_or_404(cameras, pk=camera_id)
            rate = check_rate_limit("camera_token", request, identifier=context)
            if not rate.allowed:
                response = JsonResponse({"detail": "Trop de renouvellements. Réessayez dans un instant."}, status=429)
                response["Retry-After"] = str(rate.retry_after)
                return response
            response = JsonResponse({
                "camera_id": str(camera.pk),
                "access_token": issue_camera_token(camera, browser_session=context),
                "event_signing_key": ensure_event_signing_key(camera),
            })
        response["Cache-Control"] = "no-store, private"
        return response
