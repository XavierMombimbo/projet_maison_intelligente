"""Verify an event capture against consenting profiles, never export templates."""
from dataclasses import dataclass
from io import BytesIO

import numpy as np
from cryptography.exceptions import InvalidTag
from django.conf import settings
from django.views.decorators.debug import sensitive_variables
from PIL import Image

from gateway.facial import ARCFACE_TEMPLATE_FORMAT, FaceQualityError, FaceRecognitionError, compare_embedding
from .facial_enrollment import EnrollmentBusy, EnrollmentUnavailable, embedding_from_frame
from .models import MembreMaison, ProfilBiometrique, StatutInvitation, StatutProfilBiometrique


@dataclass(frozen=True)
class BrowserFaceResult:
    state: str
    reason: str
    profile_id: str | None = None
    profile_version: int | None = None

    def public(self):
        return {"state": self.state, "reason": self.reason, "source": "server"}


def eligible_profiles(camera):
    members = MembreMaison.objects.filter(
        maison_id=camera.maison_id, statut=StatutInvitation.ACCEPTEE,
        utilisateur__is_active=True,
    ).values("utilisateur_id")
    return ProfilBiometrique.objects.filter(
        maison_id=camera.maison_id, statut=StatutProfilBiometrique.ACTIF,
        date_retrait__isnull=True, utilisateur_id__in=members,
        format_gabarit=ARCFACE_TEMPLATE_FORMAT, gabarit_chiffre__isnull=False,
        nonce_gabarit__isnull=False,
    )


@sensitive_variables()
def verify_browser_face(camera, capture, objects):
    if not settings.BIOMETRIC_WEB_RECOGNITION_ENABLED or not settings.BIOMETRIC_FACE_MODEL_ROOT:
        return BrowserFaceResult("unavailable", "disabled")
    people = [item for item in objects if item["label"] == "person"]
    if not people:
        return BrowserFaceResult("unavailable", "no_person")
    if len(people) != 1:
        return BrowserFaceResult("unavailable", "multiple_people")
    profiles = list(eligible_profiles(camera).order_by("pk")[:129])
    if not profiles:
        return BrowserFaceResult("unavailable", "no_profiles")
    if len(profiles) > 128:
        return BrowserFaceResult("unavailable", "capacity")
    try:
        with Image.open(BytesIO(capture)) as image:
            frame = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
        query = embedding_from_frame(frame, person_bbox=people[0]["bbox"])
        result = compare_embedding(query, [
            {"profile_id": str(p.pk), "format": p.format_gabarit, "template": p.decrypt_template()}
            for p in profiles
        ])
    except FaceQualityError:
        return BrowserFaceResult("unavailable", "quality")
    except EnrollmentBusy:
        return BrowserFaceResult("unavailable", "busy")
    except (EnrollmentUnavailable, FaceRecognitionError, InvalidTag, OSError, ValueError):
        return BrowserFaceResult("unavailable", "service")
    if result.state == "matched":
        matched = next(p for p in profiles if str(p.pk) == result.profile_id)
        return BrowserFaceResult("recognized", "matched", str(matched.pk), matched.version)
    return BrowserFaceResult("unknown", "not_matched")


def confirm_browser_face(camera, result):
    """Called inside the event transaction after inference; withdrawal wins."""
    if result.state != "recognized":
        return result
    profile = eligible_profiles(camera).select_for_update().filter(
        pk=result.profile_id, version=result.profile_version,
    ).first()
    if profile is not None:
        member = MembreMaison.objects.select_for_update().filter(
            maison_id=camera.maison_id, utilisateur_id=profile.utilisateur_id,
            statut=StatutInvitation.ACCEPTEE,
        ).first()
        if member is not None:
            return result
    return BrowserFaceResult("unavailable", "profile_changed")
