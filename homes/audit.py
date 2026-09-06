import hashlib
import hmac
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import DatabaseError

from .models import JournalAudit, ResultatAudit, TypeActeurAudit

logger = logging.getLogger(__name__)
SENSITIVE_FRAGMENTS = ("password", "secret", "token", "code", "signature", "authorization")


def _redact(value, key=""):
    if any(fragment in key.lower() for fragment in SENSITIVE_FRAGMENTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def request_ip_hash(request) -> str:
    if request is None:
        return ""
    address = request.META.get("REMOTE_ADDR", "")
    if not address:
        return ""
    return hmac.new(
        settings.AUDIT_LOG_PEPPER.encode("utf-8"),
        address.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def fingerprint(value: str) -> str:
    return hmac.new(
        settings.AUDIT_LOG_PEPPER.encode("utf-8"),
        value.strip().lower().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def record_audit(
    action,
    resultat=ResultatAudit.SUCCES,
    *,
    request=None,
    user=None,
    camera=None,
    maison=None,
    target=None,
    metadata=None,
):
    if user is None and request is not None and getattr(request, "user", None):
        request_user = request.user
        if isinstance(request_user, get_user_model()) and request_user.is_authenticated:
            user = request_user
    if camera is not None:
        maison = maison or camera.maison
    if user is not None:
        actor_type = TypeActeurAudit.UTILISATEUR
    elif camera is not None:
        actor_type = TypeActeurAudit.CAMERA
    elif request is not None:
        actor_type = TypeActeurAudit.ANONYME
    else:
        actor_type = TypeActeurAudit.SYSTEME

    target_type = ""
    target_id = ""
    if target is not None:
        target_type = target.__class__.__name__[:40]
        target_id = str(getattr(target, "pk", ""))[:64]
    try:
        return JournalAudit.objects.create(
            action=str(action)[:80],
            resultat=resultat,
            type_acteur=actor_type,
            utilisateur=user,
            camera=camera,
            maison=maison,
            cible_type=target_type,
            cible_id=target_id,
            ip_hash=request_ip_hash(request),
            metadonnees=_redact(metadata or {}),
        )
    except DatabaseError:
        logger.exception("Impossible d’enregistrer l’événement d’audit %s", action)
        return None
