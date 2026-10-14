import hashlib
import hmac
import json
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


def event_signature_payload_v1(
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


def canonical_observed_at(value) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime_timezone.utc)
    return value.astimezone(datetime_timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def canonical_v2_objects(objects) -> str:
    normalized = [
        {
            "bbox": [f"{float(value):.6f}" for value in item["bbox"]],
            "confidence": f"{float(item['confidence']):.6f}",
            "label": item["label"],
            "track_id": item.get("track_id", ""),
        }
        for item in objects
    ]
    normalized.sort(
        key=lambda item: (
            item["label"],
            item["track_id"],
            item["bbox"],
            item["confidence"],
        )
    )
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def canonical_rule_context(rule_context) -> str:
    if not rule_context:
        return ""
    zone = rule_context["zone"]
    line = rule_context.get("line")
    normalized = {
        "duration_seconds": f"{float(rule_context['duration_seconds']):.6f}",
        "direction": rule_context.get("direction"),
        "id": rule_context["id"],
        "line": (
            {key: f"{float(line[key]):.6f}" for key in ("x1", "y1", "x2", "y2")}
            if line else None
        ),
        "track_ids": sorted(rule_context["track_ids"]),
        "type": rule_context["type"],
        "version": int(rule_context["version"]),
        "zone": {key: f"{float(zone[key]):.6f}" for key in ("x", "y", "width", "height")},
    }
    return json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))


def event_signature_payload_v2(
    *,
    method,
    path,
    camera_id,
    timestamp,
    nonce,
    event_id,
    observed_at,
    model_name,
    model_version,
    objects,
    simulated,
    capture_type,
    capture_digest,
    rule_context=None,
) -> str:
    parts = [
            "sentinelle-event-v2",
            method.upper(),
            path,
            str(camera_id),
            str(int(timestamp)),
            str(nonce),
            str(event_id),
            canonical_observed_at(observed_at),
            model_name,
            model_version,
            canonical_v2_objects(objects),
            "1" if simulated else "0",
            capture_type.lower(),
            capture_digest.lower(),
    ]
    if rule_context:
        parts.extend(("sentinelle-rule-context-v1", canonical_rule_context(rule_context)))
    return "\n".join(parts)


def event_content_fingerprint(
    *,
    contract_version,
    camera_id,
    event_id,
    simulated,
    capture_digest,
    confidence=None,
    observed_at=None,
    model_name="",
    model_version="",
    objects=None,
    capture_type="",
    rule_context=None,
) -> str:
    if int(contract_version) == 2:
        parts = [
                "sentinelle-event-content-v2",
                str(camera_id),
                str(event_id),
                canonical_observed_at(observed_at),
                model_name,
                model_version,
                canonical_v2_objects(objects or []),
                "1" if simulated else "0",
                capture_type.lower(),
                capture_digest.lower(),
        ]
        if rule_context:
            parts.extend(("sentinelle-rule-context-v1", canonical_rule_context(rule_context)))
        payload = "\n".join(parts)
    else:
        payload = "\n".join(
            (
                "sentinelle-event-content-v1",
                str(camera_id),
                str(event_id),
                f"{float(confidence):.6f}",
                "1" if simulated else "0",
                capture_digest.lower(),
            )
        )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


event_signature_payload = event_signature_payload_v1


def sign_event_payload(signing_key: str, **payload_values) -> str:
    contract_version = int(payload_values.pop("contract_version", 1))
    payload = (
        event_signature_payload_v2(**payload_values)
        if contract_version == 2
        else event_signature_payload_v1(**payload_values)
    )
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
    payload_values = {
        "method": request.method,
        "path": request.path,
        "camera_id": camera.pk,
        "timestamp": timestamp,
        "nonce": nonce,
        "event_id": validated_data["event_id"],
        "simulated": validated_data["simulated"],
        "capture_digest": capture_sha256(uploaded_file),
    }
    contract_version = validated_data["contract_version"]
    if contract_version == 2:
        payload_values.update(
            {
                "contract_version": 2,
                "observed_at": validated_data["observed_at"],
                "model_name": validated_data["model_name"],
                "model_version": validated_data["model_version"],
                "objects": validated_data["objects"],
                "capture_type": uploaded_file.content_type or "",
                "rule_context": validated_data.get("rule_context"),
            }
        )
    else:
        payload_values["confidence"] = validated_data["confidence"]
    expected_signature = sign_event_payload(camera_event_signing_key(camera), **payload_values)
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
