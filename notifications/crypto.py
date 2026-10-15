import base64
import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


def _key() -> bytes:
    return base64.urlsafe_b64decode(settings.PUSH_TOKEN_ENCRYPTION_KEY.encode("ascii"))


def token_digest(token: str) -> str:
    return hmac.new(
        settings.PUSH_TOKEN_PEPPER.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def encrypt_token(token: str, session_id) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    associated_data = f"push-token:{session_id}".encode("ascii")
    ciphertext = AESGCM(_key()).encrypt(nonce, token.encode("utf-8"), associated_data)
    return ciphertext, nonce


def decrypt_token(ciphertext: bytes, nonce: bytes, session_id) -> str:
    associated_data = f"push-token:{session_id}".encode("ascii")
    return AESGCM(_key()).decrypt(nonce, ciphertext, associated_data).decode("utf-8")

