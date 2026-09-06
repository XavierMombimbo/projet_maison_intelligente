import hashlib
import hmac
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache


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


def check_rate_limit(scope, request, *, identifier="") -> RateLimitResult:
    limit, window = settings.RATE_LIMITS[scope]
    now = int(time.time())
    bucket = now // window
    retry_after = max(1, window - (now % window))
    key = f"sentinelle:rate:{scope}:{_identity_digest(request, identifier)}:{bucket}"
    if cache.add(key, 1, timeout=retry_after + 1):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=retry_after + 1)
            count = 1
    return RateLimitResult(count <= limit, retry_after, limit, count)
