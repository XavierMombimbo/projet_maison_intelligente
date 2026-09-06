import hashlib
import hmac
import re
import uuid
from datetime import datetime, timezone as datetime_timezone

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .crypto import decrypt_event_signing_key
from .models import NonceRequeteCamera

SIGNATURE_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class InvalidEventSignature(Exception):
    pass


class ReplayedSignedRequest(Exception):
    pass


def capture_sha256(uploaded_file) -> str:
    digest = hashlib.sha256()
    uploaded_file.seek(0)
    for chunk in uploaded_file.chunks():
        digest.update(chunk)
    uploaded_file.seek(0)
    return digest.hexdigest()


def event_signature_payload(
    *, method, path, camera_id, timestamp, nonce, event_id, confidence, simulated, capture_digest
) -> str:
    return "\n".join(
        (
            "sentinelle-event-v1",
            method.upper(),
            path,
            str(camera_id),
            str(int(timestamp)),
            str(nonce),
            str(event_id),
            f"{float(confidence):.6f}",
            "1" if simulated else "0",
            capture_digest.lower(),
        )
    )


def sign_event_payload(signing_key: str, **payload_values) -> str:
    payload = event_signature_payload(**payload_values)
    return hmac.new(
        signing_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def camera_event_signing_key(camera) -> str:
    if not camera.cle_signature_evenement_chiffree or not camera.nonce_cle_signature_evenement:
        raise InvalidEventSignature("Clé de signature caméra absente. Renouvelez l’identité.")
    try:
        return decrypt_event_signing_key(
            bytes(camera.cle_signature_evenement_chiffree),
            bytes(camera.nonce_cle_signature_evenement),
            camera.pk,
        )
    except Exception as exc:
        raise InvalidEventSignature("Clé de signature caméra invalide.") from exc


def verify_detection_signature(*, request, camera, validated_data):
    raw_timestamp = request.headers.get("X-Camera-Timestamp", "")
    raw_nonce = request.headers.get("X-Camera-Nonce", "")
    supplied_signature = request.headers.get("X-Camera-Signature", "").lower()
    try:
        timestamp = int(raw_timestamp)
        nonce = uuid.UUID(raw_nonce)
    except (TypeError, ValueError) as exc:
        raise InvalidEventSignature("En-têtes de signature caméra invalides.") from exc
    if not SIGNATURE_PATTERN.fullmatch(supplied_signature):
        raise InvalidEventSignature("Signature caméra absente ou invalide.")

    now_seconds = int(timezone.now().timestamp())
    if abs(now_seconds - timestamp) > settings.CAMERA_EVENT_MAX_SKEW_SECONDS:
        raise InvalidEventSignature("Horodatage de détection expiré.")

    uploaded_file = validated_data["capture"]
    expected_signature = sign_event_payload(
        camera_event_signing_key(camera),
        method=request.method,
        path=request.path,
        camera_id=camera.pk,
        timestamp=timestamp,
        nonce=nonce,
        event_id=validated_data["event_id"],
        confidence=validated_data["confidence"],
        simulated=validated_data["simulated"],
        capture_digest=capture_sha256(uploaded_file),
    )
    if not hmac.compare_digest(expected_signature, supplied_signature):
        raise InvalidEventSignature("Signature HMAC de détection incorrecte.")

    try:
        with transaction.atomic():
            NonceRequeteCamera.objects.create(
                nonce=nonce,
                camera=camera,
                horodatage_client=datetime.fromtimestamp(timestamp, tz=datetime_timezone.utc),
            )
    except IntegrityError as exc:
        raise ReplayedSignedRequest("Cette requête signée a déjà été utilisée.") from exc
    return nonce, timestamp
