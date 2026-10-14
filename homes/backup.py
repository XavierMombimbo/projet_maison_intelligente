import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings

MAGIC = b"SENTINELLE-BACKUP-V1\0"
ASSOCIATED_DATA = b"sentinelle-backup:v1"


def _key() -> bytes:
    return base64.urlsafe_b64decode(settings.BACKUP_ENCRYPTION_KEY.encode("ascii"))


def encrypt_backup(plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(_key()).encrypt(nonce, plaintext, ASSOCIATED_DATA)


def decrypt_backup(payload: bytes) -> bytes:
    if not payload.startswith(MAGIC) or len(payload) <= len(MAGIC) + 12:
        raise ValueError("Format de sauvegarde Sentinelle invalide.")
    nonce_start = len(MAGIC)
    nonce = payload[nonce_start : nonce_start + 12]
    ciphertext = payload[nonce_start + 12 :]
    return AESGCM(_key()).decrypt(nonce, ciphertext, ASSOCIATED_DATA)
