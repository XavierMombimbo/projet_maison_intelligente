"""Django settings loaded from environment variables in production."""

import base64
import hashlib
import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
_env_file = os.getenv("SENTINELLE_ENV_FILE")
load_dotenv(_env_file or BASE_DIR / ".env", override=bool(_env_file))


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", True)
DEVELOPMENT_SECRET = "development-only-change-me-this-is-never-for-production-2026"
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", DEVELOPMENT_SECRET)
if not DEBUG and SECRET_KEY == DEVELOPMENT_SECRET:
    raise RuntimeError("DJANGO_SECRET_KEY must be configured when DEBUG is disabled.")

DEVELOPMENT_MFA_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-mfa:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
MFA_ENCRYPTION_KEY = os.getenv("MFA_ENCRYPTION_KEY", DEVELOPMENT_MFA_KEY)
try:
    if len(base64.urlsafe_b64decode(MFA_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError("MFA_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key.") from exc
if not DEBUG and MFA_ENCRYPTION_KEY == DEVELOPMENT_MFA_KEY:
    raise RuntimeError("A separate MFA_ENCRYPTION_KEY is required in production.")

DEVELOPMENT_PUSH_TOKEN_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-push-token:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
PUSH_TOKEN_ENCRYPTION_KEY = os.getenv(
    "PUSH_TOKEN_ENCRYPTION_KEY", DEVELOPMENT_PUSH_TOKEN_KEY
)
try:
    if len(base64.urlsafe_b64decode(PUSH_TOKEN_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError(
        "PUSH_TOKEN_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key."
    ) from exc
if not DEBUG and PUSH_TOKEN_ENCRYPTION_KEY == DEVELOPMENT_PUSH_TOKEN_KEY:
    raise RuntimeError("A separate PUSH_TOKEN_ENCRYPTION_KEY is required in production.")
PUSH_TOKEN_PEPPER = os.getenv("PUSH_TOKEN_PEPPER", SECRET_KEY)
if not DEBUG and (
    PUSH_TOKEN_PEPPER == SECRET_KEY or len(PUSH_TOKEN_PEPPER.encode("utf-8")) < 32
):
    raise RuntimeError("A separate PUSH_TOKEN_PEPPER of at least 32 bytes is required in production.")
FCM_ENABLED = env_bool("FCM_ENABLED", False)
FCM_PROJECT_ID = os.getenv("FCM_PROJECT_ID", "").strip()
FCM_SERVICE_ACCOUNT_JSON = os.getenv("FCM_SERVICE_ACCOUNT_JSON", "").strip()
PUSH_MAX_ATTEMPTS = int(os.getenv("PUSH_MAX_ATTEMPTS", "5"))
PUSH_RETRY_BASE_SECONDS = int(os.getenv("PUSH_RETRY_BASE_SECONDS", "30"))
if PUSH_MAX_ATTEMPTS < 1 or PUSH_RETRY_BASE_SECONDS < 1:
    raise RuntimeError("Push retry settings must be positive integers.")
DEVELOPMENT_BIOMETRIC_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-biometric:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
BIOMETRIC_ENCRYPTION_KEY = os.getenv(
    "BIOMETRIC_ENCRYPTION_KEY", DEVELOPMENT_BIOMETRIC_KEY
)
try:
    if len(base64.urlsafe_b64decode(BIOMETRIC_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError(
        "BIOMETRIC_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key."
    ) from exc
if not DEBUG and BIOMETRIC_ENCRYPTION_KEY == DEVELOPMENT_BIOMETRIC_KEY:
    raise RuntimeError("A separate BIOMETRIC_ENCRYPTION_KEY is required in production.")
BIOMETRIC_CACHE_TTL_SECONDS = int(os.getenv("BIOMETRIC_CACHE_TTL_SECONDS", "300"))
BIOMETRIC_TEMPLATE_MAX_BYTES = int(os.getenv("BIOMETRIC_TEMPLATE_MAX_BYTES", "65536"))
BIOMETRIC_WEB_ENROLLMENT_ENABLED = env_bool("BIOMETRIC_WEB_ENROLLMENT_ENABLED", False)
BIOMETRIC_FACE_MODEL_ROOT = os.getenv("BIOMETRIC_FACE_MODEL_ROOT", "").strip()
if BIOMETRIC_CACHE_TTL_SECONDS < 30 or BIOMETRIC_TEMPLATE_MAX_BYTES < 1:
    raise RuntimeError("Biometric cache and template limits are invalid.")
MFA_PREAUTH_TTL_SECONDS = int(os.getenv("MFA_PREAUTH_TTL_SECONDS", "300"))
RECOVERY_CODE_PEPPER = os.getenv("RECOVERY_CODE_PEPPER", SECRET_KEY)
if not DEBUG and (
    RECOVERY_CODE_PEPPER == SECRET_KEY or len(RECOVERY_CODE_PEPPER.encode("utf-8")) < 32
):
    raise RuntimeError("A separate RECOVERY_CODE_PEPPER of at least 32 bytes is required in production.")
EMAIL_OTP_PEPPER = os.getenv("EMAIL_OTP_PEPPER", SECRET_KEY)
EMAIL_OTP_TTL_SECONDS = int(os.getenv("EMAIL_OTP_TTL_SECONDS", "600"))
if not DEBUG and (
    EMAIL_OTP_PEPPER == SECRET_KEY or len(EMAIL_OTP_PEPPER.encode("utf-8")) < 32
):
    raise RuntimeError("A separate EMAIL_OTP_PEPPER of at least 32 bytes is required in production.")

EMAIL_BACKEND = os.getenv(
    "EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend"
    if DEBUG
    else "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "10"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", EMAIL_HOST_USER or "no-reply@sentinelle.local")
if not DEBUG and (not EMAIL_HOST or not DEFAULT_FROM_EMAIL):
    raise RuntimeError("EMAIL_HOST and DEFAULT_FROM_EMAIL are required in production.")

PAIRING_CODE_PEPPER = os.getenv("PAIRING_CODE_PEPPER", SECRET_KEY)
CAMERA_CREDENTIAL_PEPPER = os.getenv("CAMERA_CREDENTIAL_PEPPER", SECRET_KEY)
CAMERA_JWT_SECRET = os.getenv("CAMERA_JWT_SECRET", SECRET_KEY)
AUDIT_LOG_PEPPER = os.getenv("AUDIT_LOG_PEPPER", SECRET_KEY)
CAMERA_TOKEN_TTL_SECONDS = int(os.getenv("CAMERA_TOKEN_TTL_SECONDS", "300"))
MOBILE_JWT_SECRET = os.getenv("MOBILE_JWT_SECRET", SECRET_KEY)
MOBILE_CHALLENGE_PEPPER = os.getenv("MOBILE_CHALLENGE_PEPPER", SECRET_KEY)
MOBILE_REFRESH_PEPPER = os.getenv("MOBILE_REFRESH_PEPPER", SECRET_KEY)
MOBILE_ACCESS_TTL_SECONDS = int(os.getenv("MOBILE_ACCESS_TTL_SECONDS", "900"))
MOBILE_REFRESH_TTL_SECONDS = int(os.getenv("MOBILE_REFRESH_TTL_SECONDS", "2592000"))
MOBILE_CHALLENGE_TTL_SECONDS = int(os.getenv("MOBILE_CHALLENGE_TTL_SECONDS", "300"))
if not DEBUG and any(
    value == SECRET_KEY
    for value in (PAIRING_CODE_PEPPER, CAMERA_CREDENTIAL_PEPPER, CAMERA_JWT_SECRET)
):
    raise RuntimeError("Separate pairing, camera credential and JWT secrets are required in production.")
if not DEBUG and any(
    len(value.encode("utf-8")) < 32
    for value in (PAIRING_CODE_PEPPER, CAMERA_CREDENTIAL_PEPPER, CAMERA_JWT_SECRET)
):
    raise RuntimeError("Camera security secrets must each contain at least 32 bytes.")
if not DEBUG and any(
    value == SECRET_KEY
    for value in (MOBILE_JWT_SECRET, MOBILE_CHALLENGE_PEPPER, MOBILE_REFRESH_PEPPER)
):
    raise RuntimeError("Separate mobile JWT, challenge and refresh secrets are required in production.")
if not DEBUG and any(
    len(value.encode("utf-8")) < 32
    for value in (MOBILE_JWT_SECRET, MOBILE_CHALLENGE_PEPPER, MOBILE_REFRESH_PEPPER)
):
    raise RuntimeError("Mobile security secrets must each contain at least 32 bytes.")

DEVELOPMENT_CAPTURE_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-capture:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
CAPTURE_ENCRYPTION_KEY = os.getenv("CAPTURE_ENCRYPTION_KEY", DEVELOPMENT_CAPTURE_KEY)
try:
    if len(base64.urlsafe_b64decode(CAPTURE_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError("CAPTURE_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key.") from exc
if not DEBUG and CAPTURE_ENCRYPTION_KEY == DEVELOPMENT_CAPTURE_KEY:
    raise RuntimeError("A separate CAPTURE_ENCRYPTION_KEY is required in production.")
DEVELOPMENT_BACKUP_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-backup:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
BACKUP_ENCRYPTION_KEY = os.getenv("BACKUP_ENCRYPTION_KEY", DEVELOPMENT_BACKUP_KEY)
try:
    if len(base64.urlsafe_b64decode(BACKUP_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError("BACKUP_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key.") from exc
if not DEBUG and BACKUP_ENCRYPTION_KEY == DEVELOPMENT_BACKUP_KEY:
    raise RuntimeError("A separate BACKUP_ENCRYPTION_KEY is required in production.")
DEVELOPMENT_CAMERA_SOURCE_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-camera-source:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
CAMERA_SOURCE_ENCRYPTION_KEY = os.getenv(
    "CAMERA_SOURCE_ENCRYPTION_KEY", DEVELOPMENT_CAMERA_SOURCE_KEY
)
try:
    if len(base64.urlsafe_b64decode(CAMERA_SOURCE_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError(
        "CAMERA_SOURCE_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key."
    ) from exc
if not DEBUG and CAMERA_SOURCE_ENCRYPTION_KEY == DEVELOPMENT_CAMERA_SOURCE_KEY:
    raise RuntimeError("A separate CAMERA_SOURCE_ENCRYPTION_KEY is required in production.")
DEVELOPMENT_EVENT_SIGNING_KEY = base64.urlsafe_b64encode(
    hashlib.sha256(f"sentinelle-dev-event-signing:{SECRET_KEY}".encode("utf-8")).digest()
).decode("ascii")
EVENT_SIGNING_ENCRYPTION_KEY = os.getenv(
    "EVENT_SIGNING_ENCRYPTION_KEY", DEVELOPMENT_EVENT_SIGNING_KEY
)
try:
    if len(base64.urlsafe_b64decode(EVENT_SIGNING_ENCRYPTION_KEY.encode("ascii"))) != 32:
        raise ValueError
except (ValueError, UnicodeEncodeError) as exc:
    raise RuntimeError(
        "EVENT_SIGNING_ENCRYPTION_KEY must be a URL-safe base64 encoded 32-byte key."
    ) from exc
if not DEBUG and EVENT_SIGNING_ENCRYPTION_KEY == DEVELOPMENT_EVENT_SIGNING_KEY:
    raise RuntimeError("A separate EVENT_SIGNING_ENCRYPTION_KEY is required in production.")
if not DEBUG and (AUDIT_LOG_PEPPER == SECRET_KEY or len(AUDIT_LOG_PEPPER.encode("utf-8")) < 32):
    raise RuntimeError("A separate AUDIT_LOG_PEPPER of at least 32 bytes is required in production.")
MAX_CAPTURE_BYTES = int(os.getenv("MAX_CAPTURE_BYTES", str(2 * 1024 * 1024)))
CAMERA_EVENT_MAX_SKEW_SECONDS = int(os.getenv("CAMERA_EVENT_MAX_SKEW_SECONDS", "60"))
CAPTURE_RETENTION_DAYS = int(os.getenv("CAPTURE_RETENTION_DAYS", "30"))
EVENT_RETENTION_DAYS = int(os.getenv("EVENT_RETENTION_DAYS", "90"))
CAMERA_NONCE_RETENTION_HOURS = int(os.getenv("CAMERA_NONCE_RETENTION_HOURS", "24"))
OUTBOX_RETENTION_DAYS = int(os.getenv("OUTBOX_RETENTION_DAYS", "7"))
AUDIT_RETENTION_DAYS = int(os.getenv("AUDIT_RETENTION_DAYS", "365"))
if min(
    CAPTURE_RETENTION_DAYS,
    EVENT_RETENTION_DAYS,
    CAMERA_NONCE_RETENTION_HOURS,
    OUTBOX_RETENTION_DAYS,
    AUDIT_RETENTION_DAYS,
) < 1:
    raise RuntimeError("Retention periods must be positive integers.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
MOBILE_WEB_ALLOWED_ORIGINS = [
    origin.rstrip("/") for origin in env_list("MOBILE_WEB_ALLOWED_ORIGINS")
]
if DEBUG:
    for origin in ("http://127.0.0.1:8081", "http://localhost:8081"):
        if origin not in MOBILE_WEB_ALLOWED_ORIGINS:
            MOBILE_WEB_ALLOWED_ORIGINS.append(origin)
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if RENDER_EXTERNAL_HOSTNAME:
    if RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    render_origin = f"https://{RENDER_EXTERNAL_HOSTNAME}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "channels",
    "accounts.apps.AccountsConfig",
    "homes.apps.HomesConfig",
    "notifications.apps.NotificationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "accounts.middleware.MobileAPICORSMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "homes.middleware.SecurityHeadersMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "accounts.middleware.MFAEnforcementMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "config.source_code.source_code",
                "homes.browser_camera.browser_camera_template_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Kinshasa"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "home"
LOGIN_URL = "login"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", not DEBUG)
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", not DEBUG)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "0" if DEBUG else "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
X_FRAME_OPTIONS = "DENY"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

RATE_LIMITS = {
    "biometric_enrollment": (5, 300),
    "login": (int(os.getenv("RATE_LIMIT_LOGIN_COUNT", "10")), 300),
    "signup": (int(os.getenv("RATE_LIMIT_SIGNUP_COUNT", "5")), 3600),
    "password_reset": (int(os.getenv("RATE_LIMIT_PASSWORD_RESET_COUNT", "5")), 3600),
    "pairing": (int(os.getenv("RATE_LIMIT_PAIRING_COUNT", "10")), 300),
    "pairing_code": (int(os.getenv("RATE_LIMIT_PAIRING_CODE_COUNT", "10")), 300),
    "camera_token": (int(os.getenv("RATE_LIMIT_CAMERA_TOKEN_COUNT", "30")), 60),
    "camera_detection": (int(os.getenv("RATE_LIMIT_DETECTION_COUNT", "20")), 60),
    "mfa": (int(os.getenv("RATE_LIMIT_MFA_COUNT", "5")), 300),
    "mfa_email": (int(os.getenv("RATE_LIMIT_MFA_EMAIL_COUNT", "3")), 600),
    "mobile_login": (int(os.getenv("RATE_LIMIT_MOBILE_LOGIN_COUNT", "10")), 300),
    "mobile_mfa": (int(os.getenv("RATE_LIMIT_MOBILE_MFA_COUNT", "5")), 300),
    "mobile_refresh": (int(os.getenv("RATE_LIMIT_MOBILE_REFRESH_COUNT", "30")), 60),
}

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "connect-src 'self' ws: wss: https://storage.googleapis.com",
        "font-src 'self'",
        "worker-src 'self' blob:",
    )
)

CACHES = {
    "default": {
        "BACKEND": (
            "django.core.cache.backends.redis.RedisCache"
            if os.getenv("REDIS_URL", "").strip()
            else "django.core.cache.backends.locmem.LocMemCache"
        ),
        "LOCATION": os.getenv("REDIS_URL", "sentinelle-rate-limits").strip()
        or "sentinelle-rate-limits",
    }
}

REDIS_URL = os.getenv("REDIS_URL", "").strip()
CHANNEL_ENCRYPTION_KEY = os.getenv("CHANNEL_ENCRYPTION_KEY", SECRET_KEY)
if REDIS_URL:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [{"address": REDIS_URL, "socket_timeout": 10}],
                "symmetric_encryption_keys": [CHANNEL_ENCRYPTION_KEY],
            },
        }
    }
else:
    CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}

if not DEBUG and not REDIS_URL:
    raise RuntimeError("REDIS_URL is required for WebSocket alerts in production.")
if not DEBUG and len(CHANNEL_ENCRYPTION_KEY.encode("utf-8")) < 32:
    raise RuntimeError("CHANNEL_ENCRYPTION_KEY must contain at least 32 bytes.")
