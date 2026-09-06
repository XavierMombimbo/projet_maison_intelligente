from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.urls import reverse

from .models import Evenement


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
        "simulated": event.simule,
        "status": event.statut,
        "created_at": event.horodatage.isoformat(),
        "detail_url": reverse("event-detail", kwargs={"pk": event.pk}),
    }


def publish_event(event_id, *, message_type: str = "alert.created") -> None:
    event = Evenement.objects.select_related("camera", "maison").get(pk=event_id)
    async_to_sync(get_channel_layer().group_send)(
        alert_group_name(event.maison_id),
        {"type": message_type, "payload": _event_payload(event)},
    )

