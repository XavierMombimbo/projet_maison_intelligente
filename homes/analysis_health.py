from django.conf import settings
from django.core.cache import cache
from django.utils import timezone


ANALYSIS_STATES = ("running", "stalled", "failed", "inactive")


def record_analysis_state(camera_id, state):
    if not settings.REDIS_URL:
        return
    try:
        cache.set(
            f"sentinelle:analysis:{camera_id}",
            {"state": state, "at": timezone.now().timestamp()},
            timeout=90,
        )
    except Exception:
        # Camera presence and event delivery must survive diagnostic cache failure.
        pass


def check_analysis_health(camera_ids, now):
    expected = len(camera_ids)
    if not expected or not settings.REDIS_URL:
        return {"status": "unknown", "expected": expected, "reported": 0,
                "message": "Analyse non mesurable sans camera active et cache partage."}
    keys = [f"sentinelle:analysis:{camera_id}" for camera_id in camera_ids]
    try:
        values = {key: cache.get(key) for key in keys}
    except Exception:
        return {"status": "unknown", "expected": expected, "reported": 0,
                "message": "Etats d'analyse indisponibles."}
    reported = running = degraded = 0
    for key in keys:
        value = values.get(key)
        if not isinstance(value, dict) or value.get("state") not in ANALYSIS_STATES:
            continue
        try:
            age = now.timestamp() - float(value["at"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if age < -5 or age > 60:
            continue
        reported += 1
        if value["state"] == "running":
            running += 1
        else:
            degraded += 1
    status = "warning" if degraded else ("ok" if reported == expected else "unknown")
    return {
        "status": status, "expected": expected, "reported": reported,
        "running": running, "degraded": degraded,
        "message": (
            "Analyse active declaree apres inference recente." if status == "ok"
            else "Analyse arretee, bloquee ou modele en echec." if status == "warning"
            else "Rapport d'inference absent ou ancien pour une camera."
        ),
    }
