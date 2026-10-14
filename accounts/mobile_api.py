import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from homes.audit import fingerprint, record_audit
from homes.models import ResultatAudit
from homes.throttling import check_rate_limit

from .authentication import MobileJWTAuthentication
from .mfa import consume_mfa_factor, email_delivery_configured, issue_email_code, mask_email
from .mobile_security import (
    InvalidMobileToken,
    challenge_digest,
    issue_auth_challenge,
    issue_session_tokens,
    rotate_refresh_token,
)
from .mobile_serializers import LoginSerializer, MFAVerifySerializer, RefreshSerializer
from .models import MFADevice, MobileAuthChallenge, MobileSession

logger = logging.getLogger(__name__)


def _no_store(response):
    response["Cache-Control"] = "no-store, private"
    return response


def _rate_limited(rate):
    response = Response(
        {"detail": "Trop de tentatives. Réessayez plus tard."},
        status=status.HTTP_429_TOO_MANY_REQUESTS,
    )
    response["Retry-After"] = str(rate.retry_after)
    return _no_store(response)


def _token_response(session, access_token, refresh_token):
    return _no_store(
        Response(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
                "expires_in": settings.MOBILE_ACCESS_TTL_SECONDS,
                "session_id": str(session.pk),
            }
        )
    )


class MobileLoginAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rate = check_rate_limit(
            "mobile_login", request, identifier=fingerprint(data["identifier"].lower())
        )
        if not rate.allowed:
            return _rate_limited(rate)
        user = get_user_model().objects.filter(
            Q(username__iexact=data["identifier"]) | Q(email__iexact=data["identifier"])
        ).first()
        if user is None or not user.is_active or not user.check_password(data["password"]):
            record_audit("mobile.login.failure", ResultatAudit.REFUS, request=request)
            return _no_store(
                Response({"detail": "Identifiants invalides."}, status=status.HTTP_401_UNAUTHORIZED)
            )
        if not MFADevice.objects.filter(user=user, confirmed_at__isnull=False).exists():
            return _no_store(
                Response(
                    {"detail": "Activez d’abord l’authentification multifacteur sur le site web."},
                    status=status.HTTP_403_FORBIDDEN,
                )
            )
        _challenge, raw = issue_auth_challenge(
            user, device_id=data["device_id"], device_name=data["device_name"]
        )
        email_sent = True
        try:
            issue_email_code(user)
        except Exception:
            logger.exception("Échec d’envoi du code MFA mobile par e-mail.")
            email_sent = False
        else:
            email_sent = email_delivery_configured()
        record_audit("mobile.login.password_verified", request=request, user=user)
        return _no_store(
            Response(
                {
                    "challenge": raw,
                    "expires_in": settings.MOBILE_CHALLENGE_TTL_SECONDS,
                    "email": mask_email(user.email),
                    "email_sent": email_sent,
                    "detail": "Saisissez le code MFA envoyé par e-mail.",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        )


class MobileMFAVerifyAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = MFAVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        rate = check_rate_limit("mobile_mfa", request, identifier=fingerprint(data["challenge"]))
        if not rate.allowed:
            return _rate_limited(rate)
        with transaction.atomic():
            challenge = (
                MobileAuthChallenge.objects.select_for_update()
                .select_related("user")
                .filter(
                    token_digest=challenge_digest(data["challenge"]),
                    used_at__isnull=True,
                    expires_at__gte=timezone.now(),
                )
                .first()
            )
            if challenge is None:
                return _no_store(
                    Response(
                        {"detail": "Défi MFA invalide ou expiré."},
                        status=status.HTTP_401_UNAUTHORIZED,
                    )
                )
            device = MFADevice.objects.select_for_update().filter(
                user=challenge.user, confirmed_at__isnull=False
            ).first()
            factor = device and consume_mfa_factor(device, challenge.user, data["code"])
            if not factor:
                record_audit(
                    "mobile.mfa.failure", ResultatAudit.REFUS, request=request, user=challenge.user
                )
                return _no_store(
                    Response({"detail": "Code MFA invalide."}, status=status.HTTP_401_UNAUTHORIZED)
                )
            challenge.used_at = timezone.now()
            challenge.save(update_fields=("used_at",))
            session, access, refresh = issue_session_tokens(
                challenge.user,
                device_id=challenge.device_id,
                device_name=challenge.device_name,
            )
        record_audit(
            "mobile.mfa.success",
            request=request,
            user=challenge.user,
            metadata={"factor": factor, "session_id": str(session.pk)},
        )
        return _token_response(session, access, refresh)


class MobileRefreshAPIView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = RefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        raw = serializer.validated_data["refresh_token"]
        rate = check_rate_limit("mobile_refresh", request, identifier=fingerprint(raw[:36]))
        if not rate.allowed:
            return _rate_limited(rate)
        try:
            session, access, refresh = rotate_refresh_token(raw)
        except InvalidMobileToken as exc:
            return _no_store(Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED))
        return _token_response(session, access, refresh)


class MobileMeAPIView(APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "id": request.user.pk,
                "username": request.user.username,
                "email": request.user.email,
                "session_id": str(request.mobile_session.pk),
            }
        )


class MobileSessionListAPIView(APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        sessions = MobileSession.objects.filter(user=request.user).order_by("-updated_at")
        return Response(
            [
                {
                    "id": str(item.pk),
                    "device_id": item.device_id,
                    "device_name": item.device_name,
                    "current": item.pk == request.mobile_session.pk,
                    "last_used_at": item.last_used_at,
                    "revoked_at": item.revoked_at,
                    "created_at": item.created_at,
                }
                for item in sessions
            ]
        )


class MobileSessionRevokeAPIView(APIView):
    authentication_classes = [MobileJWTAuthentication]
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, session_id):
        session = MobileSession.objects.filter(user=request.user, pk=session_id).first()
        if session is None:
            return Response({"detail": "Session introuvable."}, status=status.HTTP_404_NOT_FOUND)
        if session.revoked_at is None:
            session.revoked_at = timezone.now()
            session.save(update_fields=("revoked_at", "updated_at"))
        from notifications.services import dissociate_session

        dissociate_session(session)
        return Response(status=status.HTTP_204_NO_CONTENT)
