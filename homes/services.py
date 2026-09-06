import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .crypto import decrypt_event_signing_key, encrypt_event_signing_key
from .models import Camera, CodeAppairage, StatutAppairage
from .security import device_secret_matches, hash_device_secret, hash_pairing_code, issue_camera_token

PAIRING_CODE_TTL = timedelta(minutes=5)
PAIRING_CODE_PATTERN = re.compile(r"^\d{6}$")


class PairingError(Exception):
    pass


@dataclass(frozen=True)
class PairingCredentials:
    camera: Camera
    device_id: str
    device_secret: str
    event_signing_key: str
    access_token: str


def ensure_event_signing_key(camera: Camera) -> str:
    with transaction.atomic():
        camera = Camera.objects.select_for_update().get(pk=camera.pk)
        if camera.cle_signature_evenement_chiffree and camera.nonce_cle_signature_evenement:
            return decrypt_event_signing_key(
                bytes(camera.cle_signature_evenement_chiffree),
                bytes(camera.nonce_cle_signature_evenement),
                camera.pk,
            )
        signing_key = secrets.token_urlsafe(32)
        ciphertext, nonce = encrypt_event_signing_key(signing_key, camera.pk)
        camera.cle_signature_evenement_chiffree = ciphertext
        camera.nonce_cle_signature_evenement = nonce
        camera.save(
            update_fields=(
                "cle_signature_evenement_chiffree",
                "nonce_cle_signature_evenement",
            )
        )
        return signing_key


def create_pairing_code(camera: Camera, *, now=None) -> tuple[CodeAppairage, str]:
    now = now or timezone.now()
    with transaction.atomic():
        camera = Camera.objects.select_for_update().select_related("maison").get(pk=camera.pk)
        if camera.statut_appairage == StatutAppairage.REVOQUEE:
            raise PairingError("Une caméra révoquée ne peut pas être appairée de nouveau.")
        if camera.statut_appairage == StatutAppairage.APPAIREE:
            raise PairingError("Cette caméra est déjà appairée.")

        CodeAppairage.objects.filter(
            camera=camera, utilise=False, date_expiration__gt=now
        ).update(utilise=True, date_utilisation=now)

        for _ in range(20):
            plain_code = f"{secrets.randbelow(1_000_000):06d}"
            code_hash = hash_pairing_code(plain_code)
            collision = CodeAppairage.objects.filter(
                code_hash=code_hash, utilise=False, date_expiration__gt=now
            ).exists()
            if not collision:
                break
        else:
            raise PairingError("Impossible de générer un code unique pour le moment.")

        pairing_code = CodeAppairage.objects.create(
            code_hash=code_hash,
            maison=camera.maison,
            camera=camera,
            nom_prevu_camera=camera.nom,
            date_expiration=now + PAIRING_CODE_TTL,
        )
    return pairing_code, plain_code


def consume_pairing_code(code: str, *, now=None) -> PairingCredentials:
    now = now or timezone.now()
    normalized_code = code.strip()
    if not PAIRING_CODE_PATTERN.fullmatch(normalized_code):
        raise PairingError("Code invalide ou expiré.")

    code_hash = hash_pairing_code(normalized_code)
    with transaction.atomic():
        pairing_code = (
            CodeAppairage.objects.select_for_update()
            .select_related("camera", "maison")
            .filter(code_hash=code_hash, utilise=False, date_expiration__gt=now)
            .first()
        )
        if pairing_code is None:
            raise PairingError("Code invalide ou expiré.")

        claimed = CodeAppairage.objects.filter(
            pk=pairing_code.pk, utilise=False, date_expiration__gt=now
        ).update(utilise=True, date_utilisation=now)
        if claimed != 1:
            raise PairingError("Ce code vient d’être utilisé.")

        camera = Camera.objects.select_for_update().get(pk=pairing_code.camera_id)
        if camera.maison_id != pairing_code.maison_id:
            raise PairingError("Appairage incohérent.")
        if camera.statut_appairage != StatutAppairage.NON_APPAIREE:
            raise PairingError("Cette caméra ne peut plus être appairée.")

        device_id = uuid.uuid4().hex
        device_secret = secrets.token_urlsafe(32)
        event_signing_key = secrets.token_urlsafe(32)
        signing_key_ciphertext, signing_key_nonce = encrypt_event_signing_key(
            event_signing_key, camera.pk
        )
        camera.identifiant_appareil = device_id
        camera.secret_appareil_hash = hash_device_secret(device_secret)
        camera.cle_signature_evenement_chiffree = signing_key_ciphertext
        camera.nonce_cle_signature_evenement = signing_key_nonce
        camera.statut_appairage = StatutAppairage.APPAIREE
        camera.date_appairage = now
        camera.date_revocation = None
        camera.save(
            update_fields=(
                "identifiant_appareil",
                "secret_appareil_hash",
                "cle_signature_evenement_chiffree",
                "nonce_cle_signature_evenement",
                "statut_appairage",
                "date_appairage",
                "date_revocation",
            )
        )

    return PairingCredentials(
        camera=camera,
        device_id=device_id,
        device_secret=device_secret,
        event_signing_key=event_signing_key,
        access_token=issue_camera_token(camera, now=now),
    )


def renew_camera_token(device_id: str, device_secret: str) -> tuple[Camera, str, str]:
    camera = Camera.objects.filter(
        identifiant_appareil=device_id,
        statut_appairage=StatutAppairage.APPAIREE,
        date_revocation__isnull=True,
    ).first()
    if camera is None or not device_secret_matches(device_secret, camera.secret_appareil_hash):
        raise PairingError("Identifiants caméra invalides.")
    event_signing_key = ensure_event_signing_key(camera)
    return camera, issue_camera_token(camera), event_signing_key


def revoke_camera(camera: Camera, *, now=None) -> Camera:
    now = now or timezone.now()
    with transaction.atomic():
        camera = Camera.objects.select_for_update().get(pk=camera.pk)
        camera.statut_appairage = StatutAppairage.REVOQUEE
        camera.date_revocation = now
        camera.surveillance_active = False
        camera.version_jeton += 1
        camera.secret_appareil_hash = ""
        camera.cle_signature_evenement_chiffree = None
        camera.nonce_cle_signature_evenement = None
        camera.save(
            update_fields=(
                "statut_appairage",
                "date_revocation",
                "surveillance_active",
                "version_jeton",
                "secret_appareil_hash",
                "cle_signature_evenement_chiffree",
                "nonce_cle_signature_evenement",
            )
        )
        CodeAppairage.objects.filter(camera=camera, utilise=False).update(
            utilise=True, date_utilisation=now
        )
    return camera
