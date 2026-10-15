import base64
import hashlib
import json
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import ProfilBiometrique, StatutProfilBiometrique


@transaction.atomic
def revoke_biometric_profile(profile: ProfilBiometrique, *, now=None) -> ProfilBiometrique:
    now = now or timezone.now()
    profile = ProfilBiometrique.objects.select_for_update().get(pk=profile.pk)
    if profile.statut == StatutProfilBiometrique.REVOQUE:
        return profile
    profile.statut = StatutProfilBiometrique.REVOQUE
    profile.gabarit_chiffre = None
    profile.nonce_gabarit = None
    profile.format_gabarit = ""
    profile.date_retrait = now
    profile.version += 1
    profile.save(
        update_fields=(
            "statut",
            "gabarit_chiffre",
            "nonce_gabarit",
            "format_gabarit",
            "date_retrait",
            "version",
            "date_modification",
        )
    )
    return profile


def build_biometric_manifest(camera, *, now=None) -> dict:
    now = now or timezone.now()
    profiles = list(
        ProfilBiometrique.objects.filter(maison=camera.maison).order_by("id")
    )
    revision_source = [
        {"id": str(profile.pk), "version": profile.version, "status": profile.statut}
        for profile in profiles
    ]
    generation = hashlib.sha256(
        json.dumps(revision_source, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    active = []
    revoked = []
    for profile in profiles:
        if profile.statut == StatutProfilBiometrique.REVOQUE:
            revoked.append({"profile_id": str(profile.pk), "version": profile.version})
            continue
        template = profile.decrypt_template()
        if template is None:
            continue
        active.append(
            {
                "profile_id": str(profile.pk),
                "version": profile.version,
                "format": profile.format_gabarit,
                "template": base64.b64encode(template).decode("ascii"),
            }
        )
    valid_until = now + timedelta(seconds=settings.BIOMETRIC_CACHE_TTL_SECONDS)
    return {
        "generation": generation,
        "profiles": active,
        "revoked": revoked,
        "valid_until": valid_until.isoformat(),
        "cache_ttl_seconds": settings.BIOMETRIC_CACHE_TTL_SECONDS,
    }
