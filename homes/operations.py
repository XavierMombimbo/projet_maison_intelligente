"""Read-only operational checks; never include identifiers or raw exceptions."""

import asyncio
from datetime import timedelta

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.db import connection
from django.db.models import Count, Min, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from notifications.models import PushDelivery, PushDeliveryStatus
from .analysis_health import check_analysis_health
from .worker_health import check_worker_heartbeats
from .models import Camera, EvenementBoiteEnvoi, StatutAppairage, StatutBoiteEnvoi


async def _probe_channel():
    layer = get_channel_layer()
    if layer is None:
        raise RuntimeError("No channel layer")

    async def roundtrip():
        channel = await layer.new_channel("operations.")
        await layer.send(channel, {"type": "operations.probe"})
        message = await layer.receive(channel)
        if message != {"type": "operations.probe"}:
            raise RuntimeError("Unexpected probe response")

    # This private channel has no group or consumer; no user receives the probe.
    await asyncio.wait_for(roundtrip(), timeout=3)


def _queue_check(queryset, date_field, now, max_age):
    due = queryset.filter(**{f"{date_field}__lte": now})
    stats = due.aggregate(count=Count("pk"), oldest=Min(date_field))
    oldest = stats["oldest"]
    age = max(0, int((now - oldest).total_seconds())) if oldest else 0
    late = due.filter(**{f"{date_field}__lt": now - timedelta(seconds=max_age)}).count()
    return {"status": "warning" if late else "ok", "pending": queryset.count(),
            "due": stats["count"], "overdue": late, "oldest_due_seconds": age,
            "message": "File en retard : verifier le worker." if late else "Pas de retard constate."}


def collect_operations(*, max_queue_age=60, camera_timeout=120):
    now = timezone.now()
    checks = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = {"status": "ok", "message": "Base accessible."}
        checks["event_queue"] = _queue_check(
            EvenementBoiteEnvoi.objects.filter(statut=StatutBoiteEnvoi.EN_ATTENTE),
            "date_creation", now, max_queue_age,
        )
        checks["push_queue"] = _queue_check(
            PushDelivery.objects.filter(status__in=(PushDeliveryStatus.PENDING, PushDeliveryStatus.RETRY))
            .annotate(due_at=Coalesce("next_attempt_at", "created_at")),
            "due_at", now, max_queue_age,
        )
        cameras = Camera.objects.filter(statut_appairage=StatutAppairage.APPAIREE,
                                        surveillance_active=True)
        stale = cameras.filter(Q(derniere_connexion__isnull=True) |
            Q(derniere_connexion__lt=now - timedelta(seconds=camera_timeout))).count()
        checks["camera_presence"] = {"status": "warning" if stale else "ok",
            "expected": cameras.count(), "stale": stale,
            "message": "Presence absente ou ancienne." if stale else "Presence reseau a jour."}
        camera_ids = list(cameras.values_list("pk", flat=True))
    except Exception:
        # Database/schema/driver exceptions may contain credentials or SQL data.
        checks["database"] = {"status": "error", "message": "Base ou schema indisponible : verifier service et migrations."}
        for name in ("event_queue", "push_queue", "camera_presence"):
            checks[name] = {"status": "unknown", "message": "Verification indisponible."}

    try:
        async_to_sync(_probe_channel)()
        backend = settings.CHANNEL_LAYERS.get("default", {}).get("BACKEND", "")
        local = backend == "channels.layers.InMemoryChannelLayer"
        checks["realtime"] = {"status": "warning" if local else "ok",
            "message": "Transport local uniquement : non partage entre processus." if local else "Transport temps reel accessible."}
    except Exception:
        checks["realtime"] = {"status": "error", "message": "Transport temps reel indisponible."}

    configured = bool(settings.FCM_ENABLED and settings.FCM_PROJECT_ID)
    checks["push_configuration"] = {"status": "ok" if configured else "warning",
        "message": "FCM declare actif ; envoi reel non teste." if configured else "FCM inactif ou projet manquant."}
    checks["analysis"] = check_analysis_health(camera_ids, now) if checks["database"]["status"] == "ok" else {
        "status": "unknown", "message": "Analyse non mesurable sans base accessible."
    }
    checks["workers"] = check_worker_heartbeats(now)
    status = "error" if any(c["status"] == "error" for c in checks.values()) else (
        "warning" if any(c["status"] == "warning" for c in checks.values()) else "ok")
    return {"schema_version": 1, "checked_at": now.isoformat(), "status": status,
        "scope": "server_diagnostics_not_pilot_validation",
        "thresholds": {"max_queue_age_seconds": max_queue_age, "camera_timeout_seconds": camera_timeout},
        "checks": checks}
