"""Explicit browser weapon review; signed snapshots, no continuous recording."""
import hashlib
from io import BytesIO
import threading
import uuid

import numpy as np
from PIL import Image
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.debug import sensitive_variables
from rest_framework import parsers, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from gateway.weapons import MODEL_ID, MODEL_SHA256, WeaponDetector, WeaponUnavailable, observe
from .authentication import CameraJWTAuthentication
from .detection import ConflictingEventError, DetectionError, create_detection_event, validate_and_normalize_capture
from .models import Camera
from .request_signing import InvalidEventSignature, ReplayedSignedRequest, capture_sha256, verify_detection_signature
from .serializers import DetectionEventSerializer
from .throttling import check_rate_limit
from .weapon_demo import academic_demo_enabled, record_demo

_inference_lock = threading.Lock()
_detector = None
_detector_config = None
SCENE = [{"label": "scene", "confidence": 1.0, "bbox": [0.0, 0.0, 1.0, 1.0]}]


@sensitive_variables()
def infer(capture, mode):
    global _detector, _detector_config
    if not _inference_lock.acquire(blocking=False):
        raise WeaponUnavailable("Analyse d’arme occupée. Réessayez.")
    try:
        config = (settings.WEAPON_MODEL_ROOT, mode)
        if _detector is None or _detector_config != config:
            try:
                _detector = WeaponDetector.from_registry(config[0], mode=mode)
            except Exception as exc:
                raise WeaponUnavailable("Chargement du modèle d’arme indisponible.") from exc
            _detector_config = config
        with Image.open(BytesIO(capture)) as image:
            frame = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        return _detector.detect(frame)
    finally:
        _inference_lock.release()


class WeaponObservationAPIView(APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store, private"
        return response

    @sensitive_variables()
    def post(self, request):
        actor = getattr(request, "browser_user", None)
        if actor is None:
            return Response({"detail": "Une session web caméra est requise."}, status=403)
        mode = settings.WEAPON_DETECTION_MODE
        if mode not in {"review", "alerts"}:
            return Response({"state": "disabled", "detail": "Module d’arme non activé."}, status=409)
        camera = request.user.camera
        received_at = timezone.now().timestamp()
        if not camera.surveillance_active:
            return Response({"detail": "La surveillance est désactivée."}, status=403)
        rate = check_rate_limit("weapon_observation", request, identifier=str(camera.pk))
        if not rate.allowed:
            return Response({"state": "unavailable", "detail": "Analyse trop fréquente."}, status=429,
                            headers={"Retry-After": str(rate.retry_after)})
        serializer = DetectionEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        demo_requested = data.get("model_name") == "weapon-observation-academic-demo"
        if settings.WEAPON_ACADEMIC_SITE_ENABLED and not demo_requested:
            return Response({"detail": "Cette caméra utilise la démonstration académique explicite."}, status=403)
        if demo_requested and not academic_demo_enabled(request, camera.pk):
            return Response({"detail": "Démonstration académique locale indisponible."}, status=403)
        try:
            uuid.UUID(data.get("model_version", ""))  # one browser run, reset on every stop
        except ValueError:
            return Response({"detail": "Session d’analyse invalide."}, status=400)
        if (data["contract_version"] != 2 or data.get("model_name") not in {"weapon-observation", "weapon-observation-academic-demo"}
                or data.get("objects") != SCENE or data.get("rule_context")):
            return Response({"detail": "Le résultat d’arme est exclusivement calculé par le serveur."}, status=400)
        if abs((timezone.now() - data["observed_at"]).total_seconds()) > 5:
            return Response({"detail": "Observation expirée."}, status=400)
        try:
            nonce, timestamp = verify_detection_signature(request=request, camera=camera, validated_data=data)
            normalized, _, _ = validate_and_normalize_capture(data["capture"])
        except InvalidEventSignature as exc:
            return Response({"detail": str(exc)}, status=401)
        except ReplayedSignedRequest as exc:
            return Response({"detail": str(exc)}, status=409)
        except DetectionError as exc:
            return Response({"detail": str(exc)}, status=400)
        # Session + camera + run isolate houses, accounts and webcam restarts.
        context = request.auth["browser_session"]
        key_material = f"{camera.pk}:{context}:{data['model_version']}:{data['model_name']}"
        state_key = "weapon-review:" + hashlib.sha256(key_material.encode()).hexdigest()
        observation_id = str(data["event_id"])
        digest = capture_sha256(data["capture"])
        try:
            found = infer(normalized, mode)
        except (WeaponUnavailable, OSError, ValueError):
            # Discard old temporal evidence after a failed inference.
            with transaction.atomic():
                Camera.objects.select_for_update().get(pk=camera.pk)
                cache.delete(state_key)
            return Response({"state": "unavailable", "detail": "Analyse d’arme indisponible ; la surveillance habituelle continue."}, status=503)
        with transaction.atomic():
            current = Camera.objects.select_for_update().get(pk=camera.pk)
            if (current.date_revocation or not current.surveillance_active
                    or not Camera.objects.controllable_by(actor).filter(pk=camera.pk).exists()
                    or settings.WEAPON_DETECTION_MODE != mode):
                cache.delete(state_key)
                return Response({"detail": "La surveillance ou les droits caméra ont changé."}, status=403)
            if ((settings.WEAPON_ACADEMIC_SITE_ENABLED and not demo_requested)
                    or (demo_requested and not academic_demo_enabled(request, current.pk))):
                cache.delete(state_key)
                return Response({"detail": "Démonstration académique arrêtée."}, status=403)
            previous = cache.get(state_key) or {}
            seen = previous.get("seen", {})
            if observation_id in seen:
                saved = seen[observation_id]
                if saved["digest"] != digest:
                    return Response({"detail": "Identifiant d’observation réutilisé."}, status=409)
                return Response(saved["response"])
            now = received_at
            if now <= previous.get("at", -1):
                return Response({"state": "unavailable", "detail": "Observation simultanée ignorée."}, status=409)
            new_state, confirmed = observe(found, previous, now)
            result = {"state": "suspected" if confirmed else "candidate" if found else "clear",
                      "mode": mode, "model_id": MODEL_ID, "detections": [item.public() for item in found],
                      "confirmed": confirmed, "event_id": None, "notification_requested": False}
            # Only a qualified registry artifact can reach this branch: infer()
            # validates the mode before loading it. Client labels are ignored.
            last_alert = previous.get("last_alert", -1000)
            if demo_requested and confirmed and now - last_alert >= 30:
                try:
                    event = record_demo(camera=current, data=data, confirmed=confirmed, digest=digest)
                except ConflictingEventError as exc:
                    return Response({"detail": str(exc)}, status=409)
                result.update(academic_demo=True, event_id=str(event.pk),
                              detail_url=reverse("event-detail", kwargs={"pk": event.pk}))
                last_alert = now
            if mode == "alerts" and confirmed and now - last_alert >= 30:
                evidence = {"state": "suspected", "source": "server", "model_id": MODEL_ID,
                            "sha256": MODEL_SHA256, "objects": confirmed,
                            "group": hashlib.sha256((key_material + ":" + ",".join(sorted(x["track_id"] for x in confirmed))).encode()).hexdigest()}
                data["capture"].seek(0)
                try:
                    event, _ = create_detection_event(
                        camera=current, client_event_id=data["event_id"], confidence=None, simulated=False,
                        uploaded_file=data["capture"], request_nonce=nonce, request_timestamp=timestamp,
                        contract_version=2, observed_at=data["observed_at"], model_name=data["model_name"],
                        model_version=data["model_version"], objects=data["objects"], browser_user=actor,
                        verified_weapon=evidence,
                    )
                except ConflictingEventError as exc:
                    return Response({"detail": str(exc)}, status=409)
                except DetectionError as exc:
                    return Response({"detail": str(exc)}, status=400)
                result["event_id"] = str(event.pk)
                result["notification_requested"] = not event.notification_supprimee
                last_alert = now
            new_state["last_alert"] = last_alert
            seen[observation_id] = {"digest": digest, "response": result}
            new_state["seen"] = dict(list(seen.items())[-64:])
            cache.set(state_key, new_state, timeout=90)
        return Response(result, status=status.HTTP_200_OK)
