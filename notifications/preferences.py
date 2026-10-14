from zoneinfo import ZoneInfo

from django.utils import timezone

from homes.models import NiveauAlerte, TypeEvenement

from .models import CameraPushPreference


def allows_push(user, event, *, now=None):
    preference = CameraPushPreference.objects.filter(user=user, camera_id=event.camera_id).first()
    if preference is None:
        return True
    if not preference.enabled:
        return False
    if event.type == TypeEvenement.PERSONNE_DETECTEE and not preference.people:
        return False
    if event.type == TypeEvenement.OBJETS_DETECTES:
        has_person = event.objets.filter(classe="person").exists()
        has_other_objects = event.objets.exclude(classe="person").exists()
        if not (
            (has_person and preference.people)
            or (has_other_objects and preference.objects_enabled)
            or (not has_person and not has_other_objects and preference.objects_enabled)
        ):
            return False
    if preference.quiet_start is not None and preference.quiet_end is not None:
        local_time = timezone.localtime(
            now or timezone.now(), ZoneInfo(event.maison.fuseau_horaire),
        ).time()
        start, end = preference.quiet_start, preference.quiet_end
        quiet = start <= local_time < end if start < end else local_time >= start or local_time < end
        if quiet:
            return preference.urgent_during_quiet and event.priorite_alerte == NiveauAlerte.URGENTE
    return True
