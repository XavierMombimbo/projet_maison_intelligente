from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .models import Evenement
from .weapon_messages import person_weapon_suspected


def alert_group_name(house_id) -> str:
    return f"house.{house_id}.alerts"


def _event_payload(event: Evenement) -> dict:
    return {
        "event_id": str(event.pk),
        "camera_id": str(event.camera_id),
        "camera_name": event.camera.nom,
        "house_id": event.maison_id,
        "house_name": event.maison.nom,
        "confidence": event.confiance_ia,
        "contract_version": event.version_contrat,
        "observed_at": (
            event.horodatage_observation.isoformat() if event.horodatage_observation else None
        ),
        "received_at": event.horodatage.isoformat(),
        "model": {
            "name": event.nom_modele,
            "version": event.version_modele,
        },
        "objects": [
            {
                "label": item.classe,
                "confidence": item.confiance,
                "bbox": item.boite,
                "track_id": item.identifiant_suivi or None,
            }
            for item in event.objets.all()
        ],
        "simulated": event.simule,
        "status": event.statut,
        "alert_priority": event.priorite_alerte,
        "alert_priority_label": event.get_priorite_alerte_display(),
        "alert_reason": event.raison_priorite,
        "weapon_suspicion": (event.metadonnees.get("weapon_verification") or {}).get("state") == "suspected",
        "person_weapon_suspicion": person_weapon_suspected(event.metadonnees),
        "notification_suppressed": event.notification_supprimee,
        "created_at": event.horodatage.isoformat(),
        "detail_url": reverse("event-detail", kwargs={"pk": event.pk}),
    }


def publish_event(event_id, *, message_type: str = "alert.created") -> None:
    event = (
        Evenement.objects.operationnels()
        .select_related("camera", "maison")
        .prefetch_related("objets")
        .filter(pk=event_id)
        .first()
    )
    # The outbox also records silent presences. It must never turn one into
    # a browser alert (toast/siren), including when an old entry is retried.
    if event is None or (message_type == "alert.created" and event.notification_supprimee):
        return
    async_to_sync(get_channel_layer().group_send)(
        alert_group_name(event.maison_id),
        {"type": message_type, "payload": _event_payload(event)},
    )
