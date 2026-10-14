import base64
import binascii

from django.utils import timezone
from django.urls import reverse
from cryptography.exceptions import InvalidTag
from django.db import transaction
from rest_framework import mixins, parsers, permissions, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import fingerprint, record_audit
from .analysis_health import ANALYSIS_STATES, record_analysis_state
from .authentication import CameraJWTAuthentication
from .biometrics import build_biometric_manifest
from .detection import ConflictingEventError, DetectionError, create_detection_event
from .crypto import decrypt_camera_source_config
from .models import (
    AccusePurgeBiometrique,
    Camera,
    ProfilBiometrique,
    ResultatAudit,
    StatutProfilBiometrique,
    TypeSourceCamera,
)
from .outbox import dispatch_pending_outbox
from .request_signing import (
    InvalidEventSignature,
    ReplayedSignedRequest,
    verify_detection_signature,
)
from .scheduling import build_schedule_manifest, effective_camera_monitoring
from .serializers import (
    CameraSerializer,
    DetectionEventSerializer,
    DeviceCredentialsSerializer,
    PairingRequestSerializer,
)
from .services import PairingError, consume_pairing_code, renew_camera_token
from .throttling import check_rate_limit


def rate_limited_response(rate):
    response = Response(
        {"detail": "Trop de requêtes. Réessayez plus tard."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(rate.retry_after)
    return response


class CameraClockMixin:
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["X-Sentinelle-Time"] = str(int(timezone.now().timestamp() * 1000))
        return response


class BiometricPurgeItemSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()
    version = serializers.IntegerField(min_value=1)


class BiometricPurgeAckSerializer(serializers.Serializer):
    purges = BiometricPurgeItemSerializer(many=True, allow_empty=False)


class BiometricEnrollmentSerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=("arcface-f32le-v1",))
    template = serializers.CharField(max_length=4096, trim_whitespace=True)

    def validate_template(self, value):
        try:
            payload = base64.b64decode(value.encode("ascii"), validate=True)
        except (UnicodeEncodeError, binascii.Error) as exc:
            raise serializers.ValidationError("Gabarit ArcFace invalide.") from exc
        if len(payload) != 512 * 4:
            raise serializers.ValidationError("Taille de gabarit ArcFace invalide.")
        return payload


class CameraViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CameraSerializer

    def get_queryset(self):
        return Camera.objects.visible_to(self.request.user).select_related("maison")


class PairCameraAPIView(CameraClockMixin, APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        rate = check_rate_limit("pairing", request)
        if not rate.allowed:
            record_audit(
                "camera.pairing_api.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                metadata={"retry_after": rate.retry_after},
            )
            return rate_limited_response(rate)
        serializer = PairingRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            credentials = consume_pairing_code(serializer.validated_data["code"])
        except PairingError as exc:
            record_audit("camera.pairing_api.failure", ResultatAudit.REFUS, request=request)
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(
            "camera.pairing_api.success",
            request=request,
            camera=credentials.camera,
            target=credentials.camera,
        )
        response = Response(
            {
                "camera_id": str(credentials.camera.pk),
                "camera_name": credentials.camera.nom,
                "house_name": credentials.camera.maison.nom,
                "device_id": credentials.device_id,
                "device_secret": credentials.device_secret,
                "event_signing_key": credentials.event_signing_key,
                "access_token": credentials.access_token,
                "token_type": "Bearer",
            },
            status=status.HTTP_201_CREATED,
        )
        response["Cache-Control"] = "no-store, private"
        return response


class CameraTokenAPIView(CameraClockMixin, APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = DeviceCredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        device_id = serializer.validated_data["device_id"]
        rate = check_rate_limit("camera_token", request, identifier=fingerprint(device_id))
        if not rate.allowed:
            record_audit(
                "camera.token.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                metadata={"retry_after": rate.retry_after, "device_id_hash": fingerprint(device_id)},
            )
            return rate_limited_response(rate)
        try:
            camera, token, event_signing_key = renew_camera_token(**serializer.validated_data)
        except PairingError as exc:
            record_audit(
                "camera.token.failure",
                ResultatAudit.REFUS,
                request=request,
                metadata={"device_id_hash": fingerprint(device_id)},
            )
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
        record_audit("camera.token.success", request=request, camera=camera, target=camera)
        response = Response(
            {
                "camera_id": str(camera.pk),
                "access_token": token,
                "event_signing_key": event_signing_key,
                "token_type": "Bearer",
            }
        )
        response["Cache-Control"] = "no-store, private"
        return response


class CameraStateAPIView(CameraClockMixin, APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        camera = request.user.camera
        monitoring_active, monitoring_source = effective_camera_monitoring(camera)
        return Response(
            {
                "camera_id": str(camera.pk),
                "name": camera.nom,
                "house_id": camera.maison_id,
                "monitoring_active": monitoring_active,
                "monitoring_source": monitoring_source,
                "schedule": build_schedule_manifest(camera),
                "analysis": {
                    "zone": camera.zone_analyse,
                    "line": camera.ligne_analyse,
                    "forbidden_crossing_direction": camera.sens_franchissement_interdit,
                    "presence_seconds": camera.duree_presence_secondes,
                    "alert_thresholds": {
                        "person": camera.seuil_alerte_personne,
                        "dog": camera.seuil_alerte_animal,
                        "cat": camera.seuil_alerte_animal,
                    },
                    "grouping_window_seconds": camera.fenetre_regroupement_secondes,
                },
                "analysis_settings_url": reverse("camera-analysis-update", kwargs={"pk": camera.pk}),
                "monitoring_toggle_url": reverse("camera-toggle", kwargs={"pk": camera.pk}),
                "revoked": False,
            }
        )


class CameraSourceAPIView(APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        camera = request.user.camera
        if camera.type_source != TypeSourceCamera.RTSP:
            return Response(
                {"detail": "Cette caméra n’utilise pas une source RTSP."},
                status=status.HTTP_409_CONFLICT,
            )
        if not camera.configuration_source_chiffree or not camera.nonce_configuration_source:
            return Response(
                {"detail": "La configuration RTSP n’est pas disponible."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            source = decrypt_camera_source_config(
                bytes(camera.configuration_source_chiffree),
                bytes(camera.nonce_configuration_source),
                camera.pk,
            )
        except (InvalidTag, KeyError, TypeError, ValueError, UnicodeDecodeError):
            return Response(
                {"detail": "La configuration RTSP est illisible."},
                status=status.HTTP_409_CONFLICT,
            )
        response = Response(
            {
                "camera_id": str(camera.pk),
                "endpoint": camera.endpoint_source_expurge,
                "url": source.get("url", ""),
                "username": source.get("username", ""),
                "password": source.get("password", ""),
            }
        )
        response["Cache-Control"] = "no-store, private"
        return response


class CameraBiometricProfilesAPIView(APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        camera = request.user.camera
        try:
            payload = build_biometric_manifest(camera)
        except InvalidTag:
            record_audit(
                "biometric.sync.read",
                ResultatAudit.ECHEC,
                request=request,
                camera=camera,
                target=camera,
            )
            return Response(
                {"detail": "Un profil biométrique est illisible."},
                status=status.HTTP_409_CONFLICT,
            )
        record_audit(
            "biometric.sync.read",
            request=request,
            camera=camera,
            target=camera,
            metadata={
                "generation": payload["generation"],
                "profile_count": len(payload["profiles"]),
                "revoked_count": len(payload["revoked"]),
            },
        )
        response = Response(payload)
        response["Cache-Control"] = "no-store, private"
        return response


class CameraBiometricPurgeAckAPIView(APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        camera = request.user.camera
        serializer = BiometricPurgeAckSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        items = serializer.validated_data["purges"]
        profiles = []
        for item in items:
            profile = ProfilBiometrique.objects.filter(
                pk=item["profile_id"],
                maison=camera.maison,
                statut=StatutProfilBiometrique.REVOQUE,
                version=item["version"],
            ).first()
            if profile is None:
                return Response(
                    {"detail": "Accusé de purge biométrique invalide."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            profiles.append(profile)
        confirmed = []
        with transaction.atomic():
            for profile in profiles:
                AccusePurgeBiometrique.objects.update_or_create(
                    camera=camera,
                    profil=profile,
                    version=profile.version,
                )
                confirmed.append(
                    {"profile_id": str(profile.pk), "version": profile.version}
                )
        record_audit(
            "biometric.purge.confirmed",
            request=request,
            camera=camera,
            target=camera,
            metadata={"count": len(confirmed)},
        )
        return Response({"confirmed": confirmed})


class CameraBiometricEnrollmentAPIView(APIView):
    """Trusted local gateways enrol only active, consenting house profiles."""

    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, profile_id):
        camera = request.user.camera
        profile = ProfilBiometrique.objects.filter(
            pk=profile_id,
            maison=camera.maison,
            statut=StatutProfilBiometrique.ACTIF,
        ).first()
        if profile is None:
            return Response({"detail": "Profil biométrique indisponible."}, status=status.HTTP_404_NOT_FOUND)
        serializer = BiometricEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        template = serializer.validated_data["template"]
        profile.set_template(template, serializer.validated_data["format"])
        record_audit(
            "biometric.profile.enroll",
            request=request,
            camera=camera,
            maison=camera.maison,
            target=profile,
            metadata={"format": profile.format_gabarit, "bytes": len(template)},
        )
        return Response({"profile_id": str(profile.pk), "version": profile.version, "status": "enrolled"})


class CameraHeartbeatAPIView(CameraClockMixin, APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        camera = request.user.camera
        now = timezone.now()
        analysis_state = None
        if "analysis_state" in request.data:
            analysis_state = serializers.ChoiceField(choices=ANALYSIS_STATES).run_validation(
                request.data["analysis_state"]
            )
        has_applied = "monitoring_active" in request.data
        applied = None
        if has_applied:
            applied = serializers.BooleanField().run_validation(
                request.data["monitoring_active"]
            )
        schedule_version = None
        if "schedule_version" in request.data:
            schedule_version = serializers.RegexField(r"^[0-9a-f]{64}$").run_validation(
                request.data["schedule_version"]
            )
            if not has_applied or schedule_version != build_schedule_manifest(camera)["version"]:
                return Response(
                    {"detail": "Version de planning obsolete ou sans etat applique."},
                    status=status.HTTP_409_CONFLICT,
                )
        camera.derniere_connexion = now
        update_fields = ["derniere_connexion"]
        if has_applied:
            camera.surveillance_appliquee = applied
            camera.surveillance_appliquee_le = now
            update_fields.extend(("surveillance_appliquee", "surveillance_appliquee_le"))
        if schedule_version is not None:
            camera.version_planning_appliquee = schedule_version
            update_fields.append("version_planning_appliquee")
        camera.save(update_fields=update_fields)
        if analysis_state is not None:
            record_analysis_state(camera.pk, analysis_state)
        dispatch_pending_outbox(limit=20)
        return Response(
            {
                "status": "online",
                "last_seen": camera.derniere_connexion,
                "monitoring_active": camera.surveillance_appliquee,
                "monitoring_applied_at": camera.surveillance_appliquee_le,
                "schedule_version": camera.version_planning_appliquee,
            }
        )


class CameraDetectionAPIView(CameraClockMixin, APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [parsers.MultiPartParser, parsers.FormParser]

    def post(self, request):
        camera = request.user.camera
        rate = check_rate_limit("camera_detection", request, identifier=str(camera.pk))
        if not rate.allowed:
            record_audit(
                "camera.detection.rate_limited",
                ResultatAudit.REFUS,
                request=request,
                camera=camera,
                metadata={"retry_after": rate.retry_after},
            )
            return rate_limited_response(rate)
        serializer = DetectionEventSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request_nonce, request_timestamp = verify_detection_signature(
                request=request,
                camera=request.user.camera,
                validated_data=serializer.validated_data,
            )
            event, created = create_detection_event(
                camera=request.user.camera,
                client_event_id=serializer.validated_data["event_id"],
                confidence=serializer.validated_data.get("confidence"),
                simulated=serializer.validated_data["simulated"],
                uploaded_file=serializer.validated_data["capture"],
                request_nonce=request_nonce,
                request_timestamp=request_timestamp,
                contract_version=serializer.validated_data["contract_version"],
                observed_at=serializer.validated_data.get("observed_at"),
                model_name=serializer.validated_data.get("model_name", ""),
                model_version=serializer.validated_data.get("model_version", ""),
                objects=serializer.validated_data.get("objects", []),
                rule_context=serializer.validated_data.get("rule_context"),
            )
        except InvalidEventSignature as exc:
            record_audit(
                "camera.detection.invalid_signature",
                ResultatAudit.REFUS,
                request=request,
                camera=camera,
            )
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)
        except ReplayedSignedRequest as exc:
            record_audit(
                "camera.detection.replay",
                ResultatAudit.REFUS,
                request=request,
                camera=camera,
            )
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except ConflictingEventError as exc:
            record_audit(
                "camera.detection.idempotency_conflict",
                ResultatAudit.REFUS,
                request=request,
                camera=camera,
            )
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        except DetectionError as exc:
            record_audit(
                "camera.detection.failure",
                ResultatAudit.REFUS,
                request=request,
                camera=camera,
            )
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        record_audit(
            "camera.detection.accepted" if created else "camera.detection.deduplicated",
            request=request,
            camera=camera,
            target=event,
            metadata={"simulated": event.simule, "created": created},
        )
        return Response(
            {
                "event_id": str(event.pk),
                "status": event.statut,
                "simulated": event.simule,
                "contract_version": event.version_contrat,
                "observed_at": event.horodatage_observation,
                "received_at": event.horodatage,
                "created_at": event.horodatage,
                "deduplicated": not created,
                "alert_priority": event.priorite_alerte,
                "alert_priority_label": event.get_priorite_alerte_display(),
                "notification_sent": not event.notification_supprimee,
                "grouped_under": (
                    str(event.evenement_principal_id)
                    if event.evenement_principal_id
                    else None
                ),
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
