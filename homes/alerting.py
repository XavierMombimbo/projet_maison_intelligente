import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from .models import Evenement, NiveauAlerte


@dataclass(frozen=True)
class DecisionAlerte:
    priorite: int
    raison: str
    cle_regroupement: str
    notification_supprimee: bool = False


def _pistes(objects, rule_context):
    rule_tracks = (rule_context or {}).get("track_ids") or []
    object_tracks = [item.get("track_id") for item in objects if item.get("track_id")]
    return sorted(set(rule_tracks or object_tracks))


def _cle_regroupement(camera, objects, rule_context):
    rule_context = rule_context or {}
    tracks = _pistes(objects, rule_context)
    rule_id = rule_context.get("id")
    if not rule_id or not tracks:
        return ""
    material = {
        "camera": str(camera.pk),
        "tracks": tracks,
        "rule": rule_id,
        "version": int(rule_context.get("version") or 0),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def decider_alerte(camera, objects, rule_context):
    qualified_people = [
        item
        for item in objects
        if item.get("label") == "person"
        and float(item.get("confidence") or 0) >= camera.seuil_alerte_personne
    ]
    qualified_animals = [
        item
        for item in objects
        if item.get("label") in {"dog", "cat"}
        and float(item.get("confidence") or 0) >= camera.seuil_alerte_animal
    ]
    rule_type = (rule_context or {}).get("type")
    face_statuses = {
        item.get("face_status")
        for item in qualified_people
        if item.get("face_status") in {"recognized", "unknown", "unavailable"}
    }

    notification_supprimee = False
    if qualified_people and rule_type == "line_crossing":
        priority = NiveauAlerte.URGENTE
        reason = "Personne ayant franchi la ligne configurée."
    elif qualified_people:
        if all(item.get("face_status") == "recognized" for item in qualified_people):
            priority = NiveauAlerte.NORMALE
            reason = "Profil volontaire reconnu ; présence conservée sans notification."
            notification_supprimee = True
        elif "unknown" in face_statuses:
            priority = NiveauAlerte.ELEVEE
            reason = "Personne non reconnue détectée au-dessus du seuil configuré."
        else:
            priority = NiveauAlerte.ELEVEE
            reason = "Personne détectée ; identification locale non déterminée."
    elif qualified_animals and rule_type == "line_crossing":
        priority = NiveauAlerte.NORMALE
        reason = "Animal ayant franchi la ligne configurée."
    elif qualified_animals:
        priority = NiveauAlerte.FAIBLE
        reason = "Animal détecté au-dessus du seuil configuré."
    else:
        priority = NiveauAlerte.NORMALE
        reason = "Événement conservé sans objet dépassant un seuil spécialisé."

    return DecisionAlerte(
        priorite=priority,
        raison=reason,
        cle_regroupement=_cle_regroupement(camera, objects, rule_context),
        notification_supprimee=notification_supprimee,
    )


def trouver_evenement_principal(camera, decision):
    if not decision.cle_regroupement:
        return None
    cutoff = timezone.now() - timedelta(seconds=camera.fenetre_regroupement_secondes)
    latest_matching_event = (
        Evenement.objects.filter(
            camera=camera,
            cle_regroupement=decision.cle_regroupement,
            priorite_alerte__gte=decision.priorite,
            horodatage__gte=cutoff,
        )
        .select_related("evenement_principal")
        .order_by("-horodatage")
        .first()
    )
    if latest_matching_event is None:
        return None
    return latest_matching_event.evenement_principal or latest_matching_event
