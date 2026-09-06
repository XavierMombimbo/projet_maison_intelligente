from django.utils import timezone
from rest_framework import mixins, parsers, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import fingerprint, record_audit
from .authentication import CameraJWTAuthentication
from .detection import DetectionError, ReplayedEventError, create_detection_event
from .models import Camera, ResultatAudit
from .request_signing import (
    InvalidEventSignature,
    ReplayedSignedRequest,
    verify_detection_signature,
)
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


class CameraViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CameraSerializer

    def get_queryset(self):
        return Camera.objects.visible_to(self.request.user).select_related("maison")


class PairCameraAPIView(APIView):
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


class CameraTokenAPIView(APIView):
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


class CameraStateAPIView(APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        camera = request.user.camera
        return Response(
            {
                "camera_id": str(camera.pk),
                "name": camera.nom,
                "house_id": camera.maison_id,
                "monitoring_active": camera.surveillance_active,
                "revoked": False,
            }
        )


class CameraHeartbeatAPIView(APIView):
    authentication_classes = [CameraJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        camera = request.user.camera
        camera.derniere_connexion = timezone.now()
        camera.save(update_fields=("derniere_connexion",))
        return Response({"status": "online", "last_seen": camera.derniere_connexion})


class CameraDetectionAPIView(APIView):
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
            event = create_detection_event(
                camera=request.user.camera,
                client_event_id=serializer.validated_data["event_id"],
                confidence=serializer.validated_data["confidence"],
                simulated=serializer.validated_data["simulated"],
                uploaded_file=serializer.validated_data["capture"],
                request_nonce=request_nonce,
                request_timestamp=request_timestamp,
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
        except ReplayedEventError as exc:
            record_audit(
                "camera.detection.replay",
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
            "camera.detection.accepted",
            request=request,
            camera=camera,
            target=event,
            metadata={"simulated": event.simule},
        )
        return Response(
            {
                "event_id": str(event.pk),
                "status": event.statut,
                "simulated": event.simule,
                "created_at": event.horodatage,
            },
            status=status.HTTP_201_CREATED,
        )
