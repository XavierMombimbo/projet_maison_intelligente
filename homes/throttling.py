import hashlib
import hmac
import logging
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.core.cache.backends.locmem import LocMemCache


logger = logging.getLogger(__name__)
fallback_cache = LocMemCache("sentinelle-rate-limit-fallback", {})


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    retry_after: int
    limit: int
    count: int


def _identity_digest(request, identifier="") -> str:
    address = request.META.get("REMOTE_ADDR", "unknown")
    raw_identity = f"{address}|{identifier}".encode("utf-8")
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), raw_identity, hashlib.sha256
    ).hexdigest()


def _increment_counter(cache_backend, key, retry_after):
    if cache_backend.add(key, 1, timeout=retry_after + 1):
        return 1
    try:
        return cache_backend.incr(key)
    except ValueError:
        cache_backend.set(key, 1, timeout=retry_after + 1)
        return 1


def check_rate_limit(scope, request, *, identifier="") -> RateLimitResult:
    limit, window = settings.RATE_LIMITS[scope]
    now = int(time.time())
    bucket = now // window
    retry_after = max(1, window - (now % window))
    key = f"sentinelle:rate:{scope}:{_identity_digest(request, identifier)}:{bucket}"
    try:
        count = _increment_counter(cache, key, retry_after)
    except Exception:
        # Le cache Redis est une protection supplémentaire, pas une raison de
        # rendre l'authentification indisponible. Le repli local conserve une
        # limitation par processus pendant une panne temporaire de Redis.
        logger.exception(
            "Cache de limitation indisponible pour %s ; utilisation du repli local.",
            scope,
        )
        count = _increment_counter(fallback_cache, key, retry_after)
    return RateLimitResult(count <= limit, retry_after, limit, count)
