from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


WORKERS = ("event_outbox", "push")


def record_worker_heartbeat(worker, interval):
    if not settings.REDIS_URL or worker not in WORKERS:
        return
    try:
        cache.set(
            f"sentinelle:worker:{worker}",
            {"at": timezone.now().timestamp(), "interval": interval},
            timeout=max(30, interval * 3 + 15),
        )
    except Exception:
        # Delivery must not stop merely because the diagnostic cache failed.
        pass


def check_worker_heartbeats(now):
    if not settings.REDIS_URL:
        return {"status": "unknown", "message": "Transport partage absent : workers non mesurables."}
    try:
        values = {
            f"sentinelle:worker:{name}": cache.get(f"sentinelle:worker:{name}")
            for name in WORKERS
        }
    except Exception:
        return {"status": "unknown", "message": "Battements des workers indisponibles."}
    ages = {}
    for name in WORKERS:
        value = values.get(f"sentinelle:worker:{name}")
        if not isinstance(value, dict):
            ages[name] = None
            continue
        try:
            interval = int(value["interval"])
            age = max(0, int(now.timestamp() - float(value["at"])))
            ages[name] = age if interval > 0 and age <= max(30, interval * 3) else None
        except (KeyError, TypeError, ValueError, OverflowError):
            ages[name] = None
    healthy = all(age is not None for age in ages.values())
    return {
        "status": "ok" if healthy else "warning",
        "message": "Workers actifs." if healthy else "Worker absent ou sans cycle recent.",
        "event_outbox_age_seconds": ages["event_outbox"],
        "push_age_seconds": ages["push"],
    }
