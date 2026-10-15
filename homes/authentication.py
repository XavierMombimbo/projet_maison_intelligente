from rest_framework import authentication, exceptions

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
        return CameraPrincipal(camera), payload

    def authenticate_header(self, request):
        return self.keyword
