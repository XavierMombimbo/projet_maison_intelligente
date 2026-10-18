from rest_framework import authentication, exceptions
import hmac

from .security import CameraPrincipal, InvalidCameraToken, authenticate_camera_token


class CameraJWTAuthentication(authentication.BaseAuthentication):
    keyword = "Bearer"

    def authenticate(self, request):
        header = authentication.get_authorization_header(request).split()
        if not header:
            return None
        if len(header) != 2 or header[0].decode("ascii", errors="ignore").lower() != self.keyword.lower():
            raise exceptions.AuthenticationFailed("En-tête d’autorisation caméra invalide.")
        try:
            token = header[1].decode("ascii")
            camera, payload = authenticate_camera_token(token)
        except (UnicodeDecodeError, InvalidCameraToken) as exc:
            raise exceptions.AuthenticationFailed("Jeton caméra invalide ou expiré.") from exc
        from .browser_camera import browser_camera_context, is_browser_camera_request
        from .models import Camera
        if "browser_session" in payload or is_browser_camera_request(request):
            session_request = request._request
            current = browser_camera_context(session_request)
            supplied = request.headers.get("X-Sentinelle-Camera-Context", "")
            if (not current or not isinstance(payload.get("browser_session"), str)
                    or not hmac.compare_digest(payload["browser_session"], current)
                    or not hmac.compare_digest(supplied, current)
                    or not Camera.objects.controllable_by(session_request.user).filter(pk=camera.pk).exists()):
                raise exceptions.AuthenticationFailed("Cette caméra n’est pas autorisée pour la session actuelle.")
            authentication.SessionAuthentication().enforce_csrf(request)
            # DRF replaces the underlying request.user with CameraPrincipal
            # after authentication; retain the verified web actor explicitly.
            request.browser_user = session_request.user
        return CameraPrincipal(camera), payload

    def authenticate_header(self, request):
        return self.keyword
