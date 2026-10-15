from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import authentication, exceptions

from .mobile_security import InvalidMobileToken, decode_access_token
from .models import MobileSession


class MobileJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header:
            return None
        if len(header) != 2 or header[0].decode("ascii", errors="ignore").lower() != "bearer":
            raise exceptions.AuthenticationFailed("En-tête d’autorisation mobile invalide.")
        try:
            payload = decode_access_token(header[1].decode("ascii"))
        except (UnicodeDecodeError, InvalidMobileToken) as exc:
            raise exceptions.AuthenticationFailed("Jeton mobile invalide ou expiré.") from exc
        session = MobileSession.objects.filter(
            pk=payload["session_id"],
            user_id=payload["sub"],
            revoked_at__isnull=True,
            refresh_expires_at__gte=timezone.now(),
        ).first()
        user = get_user_model().objects.filter(pk=payload["sub"], is_active=True).first()
        if session is None or user is None:
            raise exceptions.AuthenticationFailed("Session mobile révoquée ou expirée.")
        request.mobile_session = session
        return user, payload

    def authenticate_header(self, request):
        return self.keyword
