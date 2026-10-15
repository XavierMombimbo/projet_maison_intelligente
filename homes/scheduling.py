from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.utils import timezone

from gateway.schedule import sign_schedule

from .services import ensure_event_signing_key


@dataclass(frozen=True)
class DecisionSurveillance:
    active: bool
    source: str
    libelle: str
    evaluee_le: datetime


def _house_timezone(maison):
    try:
        return ZoneInfo(maison.fuseau_horaire)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def effective_camera_monitoring(camera, *, at=None):
    if not camera.surveillance_active:
        return False, "camera"

    maison = camera.maison
    configured = (
        maison.plages_surveillance.exists()
        or maison.exceptions_surveillance.exists()
        or getattr(maison, "derogation_surveillance", None) is not None
    )
    if not configured:
        return True, "camera"

    decision = evaluate_surveillance(maison, at=at)
    return decision.active, decision.source


def build_schedule_manifest(camera):
    maison = camera.maison
    override = getattr(maison, "derogation_surveillance", None)
    payload = {
        "camera_id": str(camera.pk),
        "camera_enabled": camera.surveillance_active,
        "timezone": maison.fuseau_horaire,
        "windows": [
            {
                "id": item.pk, "day": item.jour,
                "starts_at": item.heure_debut.isoformat(timespec="seconds"),
                "ends_at": item.heure_fin.isoformat(timespec="seconds"),
                "active": item.active,
            }
            for item in maison.plages_surveillance.order_by("pk")
        ],
        "exceptions": [
            {
                "id": item.pk,
                "starts_at": item.date_debut.isoformat(),
                "ends_at": item.date_fin.isoformat(),
                "active": item.surveillance_active,
                "priority": item.priorite,
                "created_at": item.date_creation.isoformat(),
            }
            for item in maison.exceptions_surveillance.order_by("pk")
        ],
        "override": (
            {"active": override.surveillance_active,
             "expires_at": override.expire_le.isoformat()}
            if override is not None else None
        ),
        "analysis": {
            "zone": camera.zone_analyse,
            "line": camera.ligne_analyse,
            "presence_seconds": camera.duree_presence_secondes,
            "alert_thresholds": {
                "person": camera.seuil_alerte_personne,
                "dog": camera.seuil_alerte_animal,
                "cat": camera.seuil_alerte_animal,
            },
        },
    }
    return sign_schedule(payload, ensure_event_signing_key(camera))


def evaluate_surveillance(maison, *, at=None) -> DecisionSurveillance:
    at = at or timezone.now()
    if timezone.is_naive(at):
        at = timezone.make_aware(at, timezone=datetime_timezone.utc)

    override = getattr(maison, "derogation_surveillance", None)
    if override is not None and override.expire_le > at:
        return DecisionSurveillance(
            active=override.surveillance_active,
            source="manual",
            libelle=f"Priorité manuelle jusqu’au {override.expire_le.isoformat()}",
            evaluee_le=at,
        )

    exception = (
        maison.exceptions_surveillance.filter(date_debut__lte=at, date_fin__gt=at)
        .order_by("-priorite", "-date_creation", "-pk")
        .first()
    )
    if exception is not None:
        return DecisionSurveillance(
            active=exception.surveillance_active,
            source="exception",
            libelle=exception.nom,
            evaluee_le=at,
        )

    local = at.astimezone(_house_timezone(maison))
    weekday = local.weekday()
    local_time = local.time().replace(tzinfo=None)
    for window in maison.plages_surveillance.filter(active=True):
        if window.heure_debut < window.heure_fin:
            matches = (
                window.jour == weekday
                and window.heure_debut <= local_time < window.heure_fin
            )
        else:
            matches = (
                (window.jour == weekday and local_time >= window.heure_debut)
                or ((window.jour + 1) % 7 == weekday and local_time < window.heure_fin)
            )
        if matches:
            return DecisionSurveillance(
                active=True,
                source="schedule",
                libelle=window.nom,
                evaluee_le=at,
            )

    return DecisionSurveillance(
        active=False,
        source="default",
        libelle="Hors plage planifiée",
        evaluee_le=at,
    )
