import base64
import hashlib
import hmac
import secrets
import struct
import time
from io import BytesIO
from urllib.parse import quote, urlencode

import qrcode
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone
from qrcode.image.svg import SvgPathImage

PREAUTH_USER_KEY = "mfa_preauth_user_id"
PREAUTH_BACKEND_KEY = "mfa_preauth_backend"
PREAUTH_EXPIRES_KEY = "mfa_preauth_expires_at"
PREAUTH_NEXT_KEY = "mfa_preauth_next"
PREAUTH_EMAIL_SENT_KEY = "mfa_preauth_email_sent"
VERIFIED_USER_KEY = "mfa_verified_user_id"
SETUP_EMAIL_USER_KEY = "mfa_setup_email_user_id"
RECOVERY_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _key():
    return base64.urlsafe_b64decode(settings.MFA_ENCRYPTION_KEY.encode("ascii"))


def encrypt_secret(secret, user_id):
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(_key()).encrypt(nonce, secret.encode("ascii"), f"mfa:{user_id}".encode())
    return ciphertext, nonce


def decrypt_secret(ciphertext, nonce, user_id):
    return AESGCM(_key()).decrypt(nonce, ciphertext, f"mfa:{user_id}".encode()).decode("ascii")


def generate_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def normalize_recovery_code(code):
    return str(code).replace("-", "").replace(" ", "").upper()


def recovery_code_digest(code):
    return hmac.new(
        settings.RECOVERY_CODE_PEPPER.encode("utf-8"),
        normalize_recovery_code(code).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def generate_recovery_codes(user, count=10):
    from .models import MFARecoveryCode

    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(8))
        codes.append(f"{raw[:4]}-{raw[4:]}")
    MFARecoveryCode.objects.filter(user=user).delete()
    MFARecoveryCode.objects.bulk_create(
        [MFARecoveryCode(user=user, digest=recovery_code_digest(code)) for code in codes]
    )
    return codes


def consume_recovery_code(user, code):
    from .models import MFARecoveryCode

    recovery = MFARecoveryCode.objects.select_for_update().filter(
        user=user,
        digest=recovery_code_digest(code),
        used_at__isnull=True,
    ).first()
    if recovery is None:
        return False
    recovery.used_at = timezone.now()
    recovery.save(update_fields=("used_at",))
    return True


def email_code_digest(code):
    return hmac.new(
        settings.EMAIL_OTP_PEPPER.encode("utf-8"),
        str(code).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def issue_email_code(user, *, purpose="login"):
    from datetime import timedelta

    from .models import MFAEmailChallenge

    labels = {"login": "connexion", "setup": "activation"}
    label = labels[purpose]
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = timezone.now() + timedelta(seconds=settings.EMAIL_OTP_TTL_SECONDS)
    challenge = MFAEmailChallenge.objects.create(
        user=user,
        digest=email_code_digest(code),
        expires_at=expires_at,
    )
    try:
        sent = send_mail(
            f"Votre code d'{label} Sentinelle Maison" if purpose == "setup" else "Votre code de connexion Sentinelle Maison",
            (
                f"Votre code d'activation est : {code}\n\n" if purpose == "setup" else f"Votre code de connexion est : {code}\n\n"
            ) + (
                f"Il expire dans {settings.EMAIL_OTP_TTL_SECONDS // 60} minutes et ne peut être utilisé qu'une fois.\n"
                "Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
            ),
            settings.DEFAULT_FROM_EMAIL,
            [user.email],
            fail_silently=False,
        )
        if sent != 1:
            raise RuntimeError("Le service e-mail n'a pas accepte l'envoi.")
    except Exception:
        challenge.delete()
        raise
    MFAEmailChallenge.objects.filter(user=user, used_at__isnull=True).exclude(pk=challenge.pk).delete()
    return challenge


def consume_email_code(user, code):
    from .models import MFAEmailChallenge

    with transaction.atomic():
        challenge = (
            MFAEmailChallenge.objects.select_for_update()
            .filter(user=user, used_at__isnull=True, expires_at__gte=timezone.now())
            .order_by("-created_at")
            .first()
        )
        if challenge is None or not hmac.compare_digest(
            challenge.digest, email_code_digest(code)
        ):
            return False
        challenge.used_at = timezone.now()
        challenge.save(update_fields=("used_at",))
        return True


def consume_mfa_factor(device, user, code):
    """Consume one e-mail, TOTP or recovery factor while the caller owns a DB lock."""
    if str(code).isdigit() and consume_email_code(user, code):
        return "email"
    counter = verify_totp(device.get_secret(), code, last_counter=device.last_counter)
    if counter is not None:
        device.last_counter = counter
        device.save(update_fields=("last_counter", "updated_at"))
        return "totp"
    if consume_recovery_code(user, code):
        return "recovery"
    return None


def mask_email(address):
    local, separator, domain = str(address).partition("@")
    if not separator:
        return "adresse enregistrée"
    visible = local[:2] if len(local) > 2 else local[:1]
    return f"{visible}{'*' * max(2, len(local) - len(visible))}@{domain}"


def email_delivery_configured():
    return (
        settings.EMAIL_BACKEND == "django.core.mail.backends.smtp.EmailBackend"
        and bool(settings.EMAIL_HOST)
    )


def revoke_other_sessions(user, current_session_key):
    from django.contrib.sessions.models import Session
    from django.utils import timezone

    keys = []
    for session in Session.objects.filter(expire_date__gte=timezone.now()).exclude(
        session_key=current_session_key
    ):
        try:
            session_user_id = session.get_decoded().get("_auth_user_id")
        except Exception:
            continue
        if str(session_user_id) == str(user.pk):
            keys.append(session.session_key)
    if keys:
        Session.objects.filter(session_key__in=keys).delete()
    return len(keys)


def provisioning_uri(secret, user):
    label = quote(f"Sentinelle Maison:{user.email or user.username}", safe="")
    query = urlencode({"secret": secret, "issuer": "Sentinelle Maison", "algorithm": "SHA1", "digits": 6, "period": 30})
    return f"otpauth://totp/{label}?{query}"


def qr_svg(uri):
    image = qrcode.make(uri, image_factory=SvgPathImage, box_size=8, border=2)
    output = BytesIO()
    image.save(output)
    return output.getvalue()


def totp_code(secret, *, at_time=None):
    counter = int((time.time() if at_time is None else at_time) // 30)
    padding = "=" * (-len(secret) % 8)
    key = base64.b32decode(secret + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def verify_totp(secret, code, *, last_counter=-1, at_time=None, window=1):
    now_counter = int((time.time() if at_time is None else at_time) // 30)
    for counter in range(now_counter - window, now_counter + window + 1):
        if counter <= last_counter:
            continue
        if hmac.compare_digest(totp_code(secret, at_time=counter * 30), str(code)):
            return counter
    return None


def establish_preauth(request, user, *, backend, next_url):
    request.session.cycle_key()
    request.session[PREAUTH_USER_KEY] = user.pk
    request.session[PREAUTH_BACKEND_KEY] = backend
    request.session[PREAUTH_EXPIRES_KEY] = int(time.time()) + settings.MFA_PREAUTH_TTL_SECONDS
    request.session[PREAUTH_NEXT_KEY] = next_url
    request.session[PREAUTH_EMAIL_SENT_KEY] = False


def clear_preauth(session):
    for key in (
        PREAUTH_USER_KEY,
        PREAUTH_BACKEND_KEY,
        PREAUTH_EXPIRES_KEY,
        PREAUTH_NEXT_KEY,
        PREAUTH_EMAIL_SENT_KEY,
    ):
        session.pop(key, None)


def preauth_is_valid(session):
    return bool(session.get(PREAUTH_USER_KEY)) and int(session.get(PREAUTH_EXPIRES_KEY, 0)) >= int(time.time())
