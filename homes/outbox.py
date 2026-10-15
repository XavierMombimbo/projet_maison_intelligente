import logging

from django.db import transaction
from django.utils import timezone

from . import realtime
from .models import EvenementBoiteEnvoi, StatutBoiteEnvoi

logger = logging.getLogger(__name__)


def dispatch_outbox_entry(entry_id) -> bool:
    error = None
    event_id = None
    with transaction.atomic():
        entry = (
            EvenementBoiteEnvoi.objects.select_for_update()
            .select_related("evenement")
            .get(pk=entry_id)
        )
        if entry.statut == StatutBoiteEnvoi.ENVOYE:
            event_id = entry.evenement_id
        else:
            entry.tentatives += 1
            entry.date_derniere_tentative = timezone.now()
            try:
                realtime.publish_event(entry.evenement_id, message_type=entry.type_message)
            except Exception as exc:  # La ligne durable doit survivre à toute panne de transport.
                error = exc
                entry.derniere_erreur = str(exc)[:500]
            else:
                entry.statut = StatutBoiteEnvoi.ENVOYE
                entry.date_envoi = timezone.now()
                entry.derniere_erreur = ""
                event_id = entry.evenement_id
            entry.save(
                update_fields=(
                    "tentatives",
                    "date_derniere_tentative",
                    "derniere_erreur",
                    "statut",
                    "date_envoi",
                )
            )

    if error is not None:
        raise error
    if event_id is not None:
        try:
            from notifications.services import enqueue_push_deliveries

            enqueue_push_deliveries(event_id)
        except Exception:
            logger.exception("Échec de création des livraisons push pour %s", event_id)
    return True


def try_dispatch_outbox_entry(entry_id) -> bool:
    try:
        return dispatch_outbox_entry(entry_id)
    except Exception:
        logger.exception("Échec de livraison de la boîte d’envoi %s", entry_id)
        return False


def dispatch_pending_outbox(*, limit=100) -> tuple[int, int]:
    entry_ids = list(
        EvenementBoiteEnvoi.objects.filter(statut=StatutBoiteEnvoi.EN_ATTENTE)
        .order_by("date_creation")
        .values_list("pk", flat=True)[:limit]
    )
    sent = 0
    failed = 0
    for entry_id in entry_ids:
        if try_dispatch_outbox_entry(entry_id):
            sent += 1
        else:
            failed += 1
    return sent, failed
