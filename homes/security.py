import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import timedelta

import jwt
from django.conf import settings
from django.utils import timezone

from .models import Camera, StatutAppairage

CAMERA_TOKEN_ISSUER = "sentinelle-maison"
CAMERA_TOKEN_AUDIENCE = "sentinelle-camera-api"


class InvalidCameraCredential(Exception):
    pass


class InvalidCameraToken(Exception):
    pass


def _hmac_hex(value: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_pairing_code(code: str) -> str:
    return _hmac_hex(code, settings.PAIRING_CODE_PEPPER)


def hash_device_secret(secret: str) -> str:
    return _hmac_hex(secret, settings.CAMERA_CREDENTIAL_PEPPER)


def device_secret_matches(secret: str, expected_hash: str) -> bool:
    return hmac.compare_digest(hash_device_secret(secret), expected_hash)


def issue_camera_token(camera: Camera, *, now=None, ttl_seconds: int | None = None) -> str:
    now = now or timezone.now()
    ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.CAMERA_TOKEN_TTL_SECONDS
    payload = {
        "iss": CAMERA_TOKEN_ISSUER,
        "aud": CAMERA_TOKEN_AUDIENCE,
        "sub": str(camera.pk),
        "device_id": camera.identifiant_appareil,
        "token_version": camera.version_jeton,
        "iat": now,
        "nbf": now,
        "exp": now + timedelta(seconds=ttl_seconds),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.CAMERA_JWT_SECRET, algorithm="HS256")


def authenticate_camera_token(token: str, *, expected_camera_id=None) -> tuple[Camera, dict]:
    try:
        payload = jwt.decode(
            token,
            settings.CAMERA_JWT_SECRET,
            algorithms=["HS256"],
            audience=CAMERA_TOKEN_AUDIENCE,
            issuer=CAMERA_TOKEN_ISSUER,
            options={
                "require": [
                    "iss",
                    "aud",
                    "sub",
                    "device_id",
                    "token_version",
                    "iat",
                    "nbf",
                    "exp",
                    "jti",
                ]
            },
        )
    except jwt.PyJWTError as exc:
        raise InvalidCameraToken("Jeton caméra invalide ou expiré.") from exc

    if expected_camera_id is not None and payload["sub"] != str(expected_camera_id):
        raise InvalidCameraToken("Ce jeton appartient à une autre caméra.")

    try:
        camera = Camera.objects.get(pk=payload["sub"])
    except (Camera.DoesNotExist, ValueError) as exc:
        raise InvalidCameraToken("Caméra inconnue.") from exc

    valid = (
        camera.statut_appairage == StatutAppairage.APPAIREE
        and camera.date_revocation is None
        and camera.identifiant_appareil == payload["device_id"]
        and camera.version_jeton == payload["token_version"]
    )
    if not valid:
        raise InvalidCameraToken("Identité caméra révoquée ou incohérente.")
    return camera, payload


@dataclass(frozen=True)
class CameraPrincipal:
    camera: Camera

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def pk(self):
        return self.camera.pk

    def __str__(self) -> str:
        return f"camera:{self.camera.pk}"

