import base64
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def _capture_key() -> bytes:
    return base64.urlsafe_b64decode(settings.CAPTURE_ENCRYPTION_KEY.encode("ascii"))


def _event_signing_encryption_key() -> bytes:
    return base64.urlsafe_b64decode(settings.EVENT_SIGNING_ENCRYPTION_KEY.encode("ascii"))


def _camera_source_key() -> bytes:
    return base64.urlsafe_b64decode(settings.CAMERA_SOURCE_ENCRYPTION_KEY.encode("ascii"))


def _biometric_key() -> bytes:
    return base64.urlsafe_b64decode(settings.BIOMETRIC_ENCRYPTION_KEY.encode("ascii"))


def encrypt_capture(plaintext: bytes, event_id) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    associated_data = f"sentinelle-capture:{event_id}".encode("ascii")
    ciphertext = AESGCM(_capture_key()).encrypt(nonce, plaintext, associated_data)
    return ciphertext, nonce


def decrypt_capture(ciphertext: bytes, nonce: bytes, event_id) -> bytes:
    associated_data = f"sentinelle-capture:{event_id}".encode("ascii")
    return AESGCM(_capture_key()).decrypt(nonce, ciphertext, associated_data)


def encrypt_event_signing_key(signing_key: str, camera_id) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    associated_data = f"sentinelle-event-signing:{camera_id}".encode("ascii")
    ciphertext = AESGCM(_event_signing_encryption_key()).encrypt(
        nonce, signing_key.encode("utf-8"), associated_data
    )
    return ciphertext, nonce


def decrypt_event_signing_key(ciphertext: bytes, nonce: bytes, camera_id) -> str:
    associated_data = f"sentinelle-event-signing:{camera_id}".encode("ascii")
    plaintext = AESGCM(_event_signing_encryption_key()).decrypt(
        nonce, ciphertext, associated_data
    )
    return plaintext.decode("utf-8")


def encrypt_camera_source_config(config: dict, camera_id) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    associated_data = f"sentinelle-camera-source:{camera_id}".encode("ascii")
    plaintext = json.dumps(config, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(_camera_source_key()).encrypt(nonce, plaintext, associated_data)
    return ciphertext, nonce


def decrypt_camera_source_config(ciphertext: bytes, nonce: bytes, camera_id) -> dict:
    associated_data = f"sentinelle-camera-source:{camera_id}".encode("ascii")
    plaintext = AESGCM(_camera_source_key()).decrypt(nonce, ciphertext, associated_data)
    value = json.loads(plaintext.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Configuration de source caméra invalide.")
    return value


def encrypt_biometric_template(plaintext: bytes, profile_id) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    associated_data = f"sentinelle-biometric-profile:{profile_id}".encode("ascii")
    ciphertext = AESGCM(_biometric_key()).encrypt(nonce, plaintext, associated_data)
    return ciphertext, nonce


def decrypt_biometric_template(ciphertext: bytes, nonce: bytes, profile_id) -> bytes:
    associated_data = f"sentinelle-biometric-profile:{profile_id}".encode("ascii")
    return AESGCM(_biometric_key()).decrypt(nonce, ciphertext, associated_data)
