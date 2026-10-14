from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.authentication import MobileJWTAuthentication
from homes.audit import record_audit

from .models import PushDelivery, PushDeliveryStatus, PushInstallation, PushPermission, PushPlatform
from .services import dissociate_session, record_denied_permission, register_installation


def _installation_payload(installation):
    if installation is None:
        return {
            "registered": False,
            "active": False,
            "permission": PushPermission.UNKNOWN,
        }
    return {
        "registered": installation.token_digest is not None,
        "active": installation.active,
        "provider": installation.provider,
        "platform": installation.platform,
        "permission": installation.permission,
        "registered_at": installation.registered_at,
        "last_seen_at": installation.last_seen_at,
        "invalidated_at": installation.invalidated_at,
        "last_error": installation.last_error,
    }


class MobilePushInstallationAPIView(APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        installation = PushInstallation.objects.filter(session=request.mobile_session).first()
        return Response(_installation_payload(installation))

    def put(self, request):
        platform = str(request.data.get("platform", "")).strip().lower()
        permission = str(request.data.get("permission", "")).strip().lower()
        token = str(request.data.get("token", "")).strip()
        if platform not in PushPlatform.values:
            return Response(
                {"platform": "Plateforme push invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if permission not in PushPermission.values:
            return Response(
                {"permission": "État de permission invalide."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if permission == PushPermission.DENIED:
            installation = record_denied_permission(
                session=request.mobile_session,
                platform=platform,
            )
        else:
            if permission not in {PushPermission.GRANTED, PushPermission.PROVISIONAL}:
                return Response(
                    {"permission": "La permission doit être accordée, provisoire ou refusée."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not token or len(token) > 4096:
                return Response(
                    {"token": "Jeton push requis et limité à 4096 caractères."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            installation = register_installation(
                session=request.mobile_session,
                token=token,
                platform=platform,
                permission=permission,
            )
        record_audit(
            "mobile.push.installation.updated",
            request=request,
            user=request.user,
            target=installation,
            metadata={"platform": platform, "permission": permission},
        )
        return Response(_installation_payload(installation))

    def delete(self, request):
        dissociate_session(request.mobile_session)
        record_audit(
            "mobile.push.installation.removed",
            request=request,
            user=request.user,
            target=request.mobile_session,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class MobilePushDeliveryReceiptAPIView(APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, delivery_id):
        delivery = PushDelivery.objects.filter(
            pk=delivery_id,
            recipient=request.user,
            installation__session=request.mobile_session,
        ).first()
        if delivery is None:
            return Response({"detail": "Livraison introuvable."}, status=status.HTTP_404_NOT_FOUND)
        if delivery.status not in {PushDeliveryStatus.ACCEPTED, PushDeliveryStatus.RECEIVED}:
            return Response(
                {"detail": "Cette livraison n’a pas été acceptée par le fournisseur."},
                status=status.HTTP_409_CONFLICT,
            )
        if delivery.received_at is None:
            delivery.status = PushDeliveryStatus.RECEIVED
            delivery.received_at = timezone.now()
            delivery.save(update_fields=("status", "received_at"))
        return Response({"received_at": delivery.received_at})

