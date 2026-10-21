"""Opt-in academic demonstration for explicitly configured cameras.

Demo records have no capture or outbox and are excluded from operational events.
This does not qualify a model or enable the production alerts mode.
"""
import uuid

from django.conf import settings
from django.db import connection

from .detection import ConflictingEventError
from .models import Camera, Evenement, NiveauAlerte, ObjetDetecte, TypeEvenement


def academic_site_demo_cameras(actor):
    if (not settings.WEAPON_ACADEMIC_SITE_ENABLED or settings.WEAPON_DETECTION_MODE != "review"
            or not settings.WEAPON_MODEL_ROOT or not actor or not actor.is_authenticated):
        return Camera.objects.none()
    ids = []
    for value in settings.WEAPON_ACADEMIC_SITE_CAMERA_IDS:
        try:
            ids.append(uuid.UUID(str(value)))
        except (ValueError, TypeError, AttributeError):
            continue
    return Camera.objects.controllable_by(actor).filter(
        pk__in=ids, date_revocation__isnull=True, type_source="webcam").order_by("nom", "pk")


def academic_demo_enabled(request, camera_id):
    if settings.WEAPON_DETECTION_MODE != "review":
        return False
    try:
        camera_id = str(uuid.UUID(str(camera_id)))
    except (ValueError, TypeError, AttributeError):
        return False
    if settings.WEAPON_ACADEMIC_SITE_ENABLED:
        actor = getattr(request, "browser_user", None) or getattr(request, "user", None)
        return academic_site_demo_cameras(actor).filter(pk=camera_id).exists()
    return bool(
        settings.DEBUG
        and not settings.FCM_ENABLED and connection.vendor == "sqlite"
        and request.META.get("REMOTE_ADDR") in {"127.0.0.1", "::1"}
        and str(camera_id) in getattr(settings, "WEAPON_ACADEMIC_DEMO_CAMERA_IDS", ())
    )


def record_demo(*, camera, data, confirmed, digest):
    """Called inside the observation transaction, after server confirmation."""
    event, created = Evenement.objects.get_or_create(
        client_event_id=data["event_id"],
        defaults={
            "camera": camera, "maison": camera.maison,
            "type": TypeEvenement.OBJETS_DETECTES, "version_contrat": 2,
            "horodatage_observation": data["observed_at"],
            "nom_modele": data["model_name"], "version_modele": data["model_version"],
            "confiance_ia": max(item["confidence"] for item in confirmed),
            "simule": True, "notification_supprimee": True,
            "priorite_alerte": NiveauAlerte.NORMALE,
            "raison_priorite": "Démonstration académique expérimentale, aucune alerte de sécurité réelle.",
            "metadonnees": {"academic_weapon_demo": True,
                "observation_sha256": digest,
                "weapon_verification": {"state": "suspected", "source": "server",
                                        "objects": confirmed, "evaluation_only": True}},
        },
    )
    if (event.camera_id != camera.pk or not event.metadonnees.get("academic_weapon_demo")
            or event.metadonnees.get("observation_sha256") != digest
            or event.version_modele != data["model_version"]):
        raise ConflictingEventError("Identifiant d’essai déjà utilisé pour un autre contenu.")
    if created:
        ObjetDetecte.objects.bulk_create([
            ObjetDetecte(evenement=event, classe=item["label"], confiance=item["confidence"],
                         boite=item["bbox"], identifiant_suivi=item["track_id"])
            for item in confirmed
        ])
    return event
