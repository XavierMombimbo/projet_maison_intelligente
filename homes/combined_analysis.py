"""One signed frame for presence and server weapon review, one event pipeline."""
import hashlib
import json

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.urls import reverse
from rest_framework.response import Response

from gateway.weapons import MODEL_ID, MODEL_SHA256, WeaponUnavailable, observe
from .detection import ConflictingEventError, DetectionError, create_detection_event, validate_rule_context
from .models import Camera
from .scheduling import effective_camera_monitoring
from .weapon_demo import academic_demo_enabled
from .weapon_messages import PERSON_WEAPON_TITLE

COMBINED_MODELS = {"camera-combined", "camera-combined-academic"}


def associated_weapons(camera, objects, detections):
    """Spatial proximity is tentative, never proof of possession or intent."""
    zone = camera.zone_analyse
    people = []
    for person in objects:
        if person["label"] != "person" or person["confidence"] < camera.seuil_alerte_personne:
            continue
        x, y, w, h = person["bbox"]
        cx, cy = x + w / 2, y + h / 2
        if zone["x"] <= cx <= zone["x"] + zone["width"] and zone["y"] <= cy <= zone["y"] + zone["height"]:
            people.append(person)
    result = []
    for weapon in detections:
        x, y, w, h = weapon.bbox
        for person in people:
            px, py, pw, ph = person["bbox"]
            # A small extension covers a hand just outside the person box.
            left, top = px - pw * .12, py - ph * .08
            right, bottom = px + pw * 1.12, py + ph * 1.08
            overlap = max(0, min(x + w, right) - max(x, left)) * max(0, min(y + h, bottom) - max(y, top))
            if w * h > 0 and overlap / (w * h) >= .60:
                result.append(weapon)
                break
    return result


def process_observation(*, request, camera, data, normalized, state_key, nonce, timestamp, mode, received_at):
    from .weapon_analysis import infer
    actor = request.browser_user
    academic = data["model_name"] == "camera-combined-academic"
    digest = hashlib.sha256(normalized).hexdigest()
    fingerprint = hashlib.sha256(json.dumps({"image": digest, "objects": data["objects"],
        "rule": data.get("rule_context")}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    try:
        validate_rule_context(camera, data.get("rule_context"), data["objects"])
    except DetectionError as exc:
        return Response({"detail": str(exc)}, status=400)
    unavailable = False
    try:
        found = infer(normalized, mode)
    except (WeaponUnavailable, OSError, ValueError):
        found, unavailable = [], True
    with transaction.atomic():
        current = Camera.objects.select_for_update().get(pk=camera.pk)
        if (not settings.WEAPON_COMBINED_ENABLED or settings.WEAPON_DETECTION_MODE != mode
                or current.date_revocation or not effective_camera_monitoring(current)[0]
                or not Camera.objects.controllable_by(actor).filter(pk=camera.pk).exists()
                or (settings.WEAPON_ACADEMIC_SITE_ENABLED and not academic)
                or (academic and not academic_demo_enabled(request, current.pk))):
            cache.delete(state_key)
            return Response({"detail": "La surveillance ou les droits caméra ont changé."}, status=403)
        previous = cache.get(state_key) or {}
        seen = previous.get("seen", {})
        saved = seen.get(str(data["event_id"]))
        if saved:
            if saved["fingerprint"] != fingerprint:
                return Response({"detail": "Identifiant d’observation réutilisé."}, status=409)
            return Response(saved["response"])
        now = received_at
        if now <= previous.get("at", -1):
            return Response({"detail": "Observation simultanée ignorée."}, status=409)
        paired = associated_weapons(current, data["objects"], found)
        new_state, confirmed = observe(found, {} if unavailable else previous, now)
        association, associated = observe(paired, {} if unavailable else previous.get("association"), now)
        new_state["association"] = association
        z = current.zone_analyse
        standalone = [x for x in confirmed if z["x"] <= x["bbox"][0] + x["bbox"][2] / 2 <= z["x"] + z["width"]
                      and z["y"] <= x["bbox"][1] + x["bbox"][3] / 2 <= z["y"] + z["height"]] if not paired else []
        pending_since = previous.get("pending_since", now) if paired and not associated else now
        new_state["pending_since"] = pending_since
        result = {"state": "unavailable" if unavailable else "suspected" if confirmed else "candidate" if found else "clear",
                  "combined": True, "mode": mode, "evaluation_only": mode == "review",
                  "person_weapon_suspicion": bool(associated),
                  "detections": [x.public() for x in found], "confirmed": confirmed,
                  "event_id": None, "notification_requested": False}
        last_event = previous.get("last_event", -1000)
        last_weapon = previous.get("last_weapon", -1000)
        rule = data.get("rule_context")
        crossing = rule and rule["type"] == "line_crossing"
        # Give a nearby tentative object up to 4.5s to be confirmed. A crossing
        # is never held, and weapon failure leaves ordinary intrusion working.
        pending = paired and not associated and now - pending_since < 4.5 and not crossing
        weapon_due = (associated or standalone) and (now - last_weapon >= 30
                      or associated and not previous.get("last_weapon_person", False))
        ordinary_due = rule and not pending and now - last_event >= 15
        last_weapon_person = previous.get("last_weapon_person", False)
        if weapon_due or (ordinary_due and not associated and not standalone):
            evidence = None
            confirmed_objects = associated or standalone
            if confirmed_objects:
                kind = ":person-weapon:" if associated else ":weapon-only:"
                group = hashlib.sha256((state_key + kind + ",".join(sorted(x["track_id"] for x in confirmed_objects))).encode()).hexdigest()
                evidence = {"state": "suspected", "source": "server", "person_associated": bool(associated),
                            "evaluation_only": mode == "review", "model_id": MODEL_ID,
                            "sha256": MODEL_SHA256,
                            "objects": [x for x in data["objects"] if x["label"] != "scene"] + confirmed_objects,
                            "group": group}
            data["capture"].seek(0)
            try:
                event, created = create_detection_event(camera=current, client_event_id=data["event_id"],
                    confidence=None, simulated=False, uploaded_file=data["capture"], request_nonce=nonce,
                    request_timestamp=timestamp, contract_version=2, observed_at=data["observed_at"],
                    model_name=data["model_name"], model_version=data["model_version"], objects=data["objects"],
                    rule_context=rule, browser_user=actor, verified_weapon=evidence)
            except ConflictingEventError as exc:
                return Response({"detail": str(exc)}, status=409)
            except DetectionError as exc:
                return Response({"detail": str(exc)}, status=400)
            title = PERSON_WEAPON_TITLE if associated else "Suspicion d’arme" if evidence else "Personne détectée" if any(x["label"] == "person" for x in data["objects"]) else "Présence détectée"
            result.update(event_id=str(event.pk), detail_url=reverse("event-detail", kwargs={"pk": event.pk}),
                          alert_title=title, notification_requested=not event.notification_supprimee,
                          face_verification=event.metadonnees.get("face_verification"),
                          notification_sent=not event.notification_supprimee, deduplicated=not created)
            last_event = now
            if evidence:
                last_weapon = now
                last_weapon_person = bool(associated)
        new_state.update(last_event=last_event, last_weapon=last_weapon, last_weapon_person=last_weapon_person)
        seen[str(data["event_id"])] = {"fingerprint": fingerprint, "response": result}
        new_state["seen"] = dict(list(seen.items())[-64:])
        cache.set(state_key, new_state, timeout=90)
        return Response(result)
