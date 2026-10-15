import hashlib
import hmac
import secrets
from datetime import timedelta

import jwt
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import MobileAuthChallenge, MobileSession


class InvalidMobileToken(Exception):
    pass


def _digest(secret, value):
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


@transaction.atomic
def issue_auth_challenge(user, *, device_id, device_name):
    raw = secrets.token_urlsafe(32)
    MobileAuthChallenge.objects.filter(
        user=user, device_id=device_id, used_at__isnull=True
    ).delete()
    challenge = MobileAuthChallenge.objects.create(
        user=user,
        token_digest=_digest(settings.MOBILE_CHALLENGE_PEPPER, raw),
        device_id=device_id,
        device_name=device_name,
        expires_at=timezone.now() + timedelta(seconds=settings.MOBILE_CHALLENGE_TTL_SECONDS),
    )
    return challenge, raw


def challenge_digest(raw):
    return _digest(settings.MOBILE_CHALLENGE_PEPPER, raw)


def _access_token(session):
    now = timezone.now()
    payload = {
        "iss": "sentinelle-maison",
        "aud": "sentinelle-mobile-api",
        "sub": str(session.user_id),
        "session_id": str(session.pk),
        "iat": now,
        "exp": now + timedelta(seconds=settings.MOBILE_ACCESS_TTL_SECONDS),
    }
    return jwt.encode(payload, settings.MOBILE_JWT_SECRET, algorithm="HS256")


def _new_refresh_token(session):
    raw = f"{session.pk}.{secrets.token_urlsafe(48)}"
    return raw, _digest(settings.MOBILE_REFRESH_PEPPER, raw)


@transaction.atomic
def issue_session_tokens(user, *, device_id, device_name):
    session = MobileSession.objects.select_for_update().filter(
        user=user, device_id=device_id
    ).first()
    expires_at = timezone.now() + timedelta(seconds=settings.MOBILE_REFRESH_TTL_SECONDS)
    if session is None:
        session = MobileSession(
            user=user,
            device_id=device_id,
            device_name=device_name,
            refresh_digest=secrets.token_hex(32),
            refresh_expires_at=expires_at,
        )
        session.save()
    session.device_name = device_name
    session.refresh_expires_at = expires_at
    session.revoked_at = None
    session.last_used_at = timezone.now()
    refresh, session.refresh_digest = _new_refresh_token(session)
    session.save(
        update_fields=(
            "device_name",
            "refresh_expires_at",
            "revoked_at",
            "last_used_at",
            "refresh_digest",
            "updated_at",
        )
    )
    return session, _access_token(session), refresh


def _refresh_session_id(raw):
    try:
        value, _secret = raw.split(".", 1)
        return value
    except (AttributeError, ValueError) as exc:
        raise InvalidMobileToken("Jeton de renouvellement invalide.") from exc


@transaction.atomic
def rotate_refresh_token(raw):
    now = timezone.now()
    session = MobileSession.objects.select_for_update().select_related("user").filter(
        pk=_refresh_session_id(raw)
    ).first()
    if (
        session is None
        or session.revoked_at is not None
        or session.refresh_expires_at < now
        or not session.user.is_active
        or not hmac.compare_digest(
            session.refresh_digest, _digest(settings.MOBILE_REFRESH_PEPPER, raw)
        )
    ):
        raise InvalidMobileToken("Jeton de renouvellement invalide ou expiré.")
    refresh, session.refresh_digest = _new_refresh_token(session)
    session.last_used_at = now
    session.save(update_fields=("refresh_digest", "last_used_at", "updated_at"))
    return session, _access_token(session), refresh


def decode_access_token(token):
    try:
        return jwt.decode(
            token,
            settings.MOBILE_JWT_SECRET,
            algorithms=["HS256"],
            audience="sentinelle-mobile-api",
            issuer="sentinelle-maison",
            options={"require": ["exp", "iat", "sub", "session_id"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidMobileToken("Jeton mobile invalide ou expiré.") from exc
