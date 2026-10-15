from io import BytesIO
from datetime import timedelta
from math import isclose

from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .alerting import decider_alerte, trouver_evenement_principal
from .crypto import encrypt_capture
from .models import (
    CaptureChiffree,
    Evenement,
    EvenementBoiteEnvoi,
    ObjetDetecte,
    TypeEvenement,
)
from .outbox import try_dispatch_outbox_entry
from .request_signing import capture_sha256, event_content_fingerprint

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 12_000_000
NORMALIZED_MAX_SIZE = (1280, 720)
DELAYED_ALERT_SECONDS = 60


class DetectionError(Exception):
    pass


class CaptureValidationError(DetectionError):
    pass


class ConflictingEventError(DetectionError):
    pass


def _same_geometry(left, right, keys):
    return bool(left and right) and all(
        isclose(float(left[key]), float(right[key]), abs_tol=0.000001) for key in keys
    )


def validate_rule_context(camera, rule_context, objects):
    if not rule_context:
        return
    if int(rule_context["version"]) != 1:
        raise DetectionError("Version de règle non prise en charge.")
    if not _same_geometry(
        rule_context["zone"], camera.zone_analyse, ("x", "y", "width", "height")
    ):
        raise DetectionError("La zone de la règle ne correspond pas à la caméra.")
    object_track_ids = {item.get("track_id") for item in objects if item.get("track_id")}
    if not set(rule_context["track_ids"]).issubset(object_track_ids):
        raise DetectionError("Une piste de la règle est absente des objets détectés.")

    if rule_context["type"] == "presence_prolonged":
        if rule_context["id"] != "presence-zone":
            raise DetectionError("Identifiant de règle de présence invalide.")
        if float(rule_context["duration_seconds"]) < camera.duree_presence_secondes:
            raise DetectionError("La durée minimale de présence n’est pas atteinte.")
        if rule_context.get("line") or rule_context.get("direction"):
            raise DetectionError("Une règle de présence ne doit pas déclarer de franchissement.")
        return

    if rule_context["id"] != "line-crossing" or not camera.ligne_analyse:
        raise DetectionError("La règle de franchissement n’est pas configurée.")
    if not _same_geometry(
        rule_context.get("line"), camera.ligne_analyse, ("x1", "y1", "x2", "y2")
    ):
        raise DetectionError("La ligne de la règle ne correspond pas à la caméra.")
    configured_direction = camera.sens_franchissement_interdit
    if configured_direction != "any" and rule_context.get("direction") != configured_direction:
        raise DetectionError("Ce sens de franchissement est autorisé.")


def validate_and_normalize_capture(uploaded_file) -> tuple[bytes, str, dict]:
    if uploaded_file is None:
        raise CaptureValidationError("Une capture est obligatoire.")
    if uploaded_file.size <= 0 or uploaded_file.size > settings.MAX_CAPTURE_BYTES:
        raise CaptureValidationError("La capture dépasse la taille autorisée.")
    declared_type = (uploaded_file.content_type or "").lower()
    expected_format = ALLOWED_IMAGE_TYPES.get(declared_type)
    if expected_format is None:
        raise CaptureValidationError("Type MIME de capture non autorisé.")

    raw_data = uploaded_file.read(settings.MAX_CAPTURE_BYTES + 1)
    if len(raw_data) > settings.MAX_CAPTURE_BYTES:
        raise CaptureValidationError("La capture dépasse la taille autorisée.")
    try:
        with Image.open(BytesIO(raw_data)) as probe:
            actual_format = probe.format
            probe.verify()
        with Image.open(BytesIO(raw_data)) as image:
            width, height = image.size
            if (
                width < 1
                or height < 1
                or width > MAX_IMAGE_DIMENSION
                or height > MAX_IMAGE_DIMENSION
                or width * height > MAX_IMAGE_PIXELS
            ):
                raise CaptureValidationError("Dimensions de capture non autorisées.")
            if actual_format != expected_format:
                raise CaptureValidationError("Le contenu ne correspond pas au type MIME annoncé.")
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            image.thumbnail(NORMALIZED_MAX_SIZE, Image.Resampling.LANCZOS)
            normalized_width, normalized_height = image.size
            output = BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=True)
    except CaptureValidationError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise CaptureValidationError("Le fichier transmis n’est pas une image valide.") from exc

    normalized = output.getvalue()
    return normalized, "image/jpeg", {
        "largeur": normalized_width,
        "hauteur": normalized_height,
        "format_source": actual_format,
    }


def create_detection_event(
    *,
    camera,
    client_event_id,
    confidence: float,
    simulated: bool,
    uploaded_file,
    request_nonce=None,
    request_timestamp=None,
    contract_version=1,
    observed_at=None,
    model_name="",
    model_version="",
    objects=None,
    rule_context=None,
) -> tuple[Evenement, bool]:
    if not camera.surveillance_active:
        raise DetectionError("La surveillance de cette caméra est désactivée.")
    if simulated:
        raise DetectionError("La simulation n’est plus prise en charge.")
    objects = objects or []
    validate_rule_context(camera, rule_context, objects)
    payload_fingerprint = event_content_fingerprint(
        contract_version=contract_version,
        camera_id=camera.pk,
        event_id=client_event_id,
        confidence=confidence,
        simulated=simulated,
        observed_at=observed_at,
        model_name=model_name,
        model_version=model_version,
        objects=objects,
        rule_context=rule_context,
        capture_type=uploaded_file.content_type or "",
        capture_digest=capture_sha256(uploaded_file),
    )
    existing = Evenement.objects.filter(client_event_id=client_event_id).first()
    if existing is not None:
        if (
            existing.camera_id == camera.pk
            and existing.empreinte_charge_utile
            and existing.empreinte_charge_utile == payload_fingerprint
        ):
            if hasattr(existing, "boite_envoi"):
                transaction.on_commit(
                    lambda entry_id=existing.boite_envoi.pk: try_dispatch_outbox_entry(entry_id)
                )
            return existing, False
        raise ConflictingEventError(
            "Cet identifiant d’événement existe avec un contenu différent."
        )

    normalized, mime_type, image_metadata = validate_and_normalize_capture(uploaded_file)
    event_confidence = max((item["confidence"] for item in objects), default=confidence or 0.0)
    delayed = bool(
        contract_version == 2 and observed_at
        and observed_at < timezone.now() - timedelta(seconds=DELAYED_ALERT_SECONDS)
    )

    try:
        with transaction.atomic():
            locked_camera = type(camera).objects.select_for_update().get(pk=camera.pk)
            alert_decision = decider_alerte(locked_camera, objects, rule_context)
            principal_event = trouver_evenement_principal(locked_camera, alert_decision)
            event = Evenement.objects.create(
                client_event_id=client_event_id,
                camera=camera,
                maison=camera.maison,
                type=(
                    TypeEvenement.OBJETS_DETECTES
                    if contract_version == 2
                    else TypeEvenement.PERSONNE_DETECTEE
                ),
                confiance_ia=event_confidence,
                version_contrat=contract_version,
                horodatage_observation=observed_at,
                nom_modele=model_name,
                version_modele=model_version,
                empreinte_charge_utile=payload_fingerprint,
                simule=False,
                priorite_alerte=alert_decision.priorite,
                raison_priorite=alert_decision.raison,
                cle_regroupement="" if delayed else alert_decision.cle_regroupement,
                evenement_principal=principal_event,
                notification_supprimee=(
                    principal_event is not None or delayed or alert_decision.notification_supprimee
                ),
                metadonnees={
                    "capture": image_metadata,
                    "analyse_locale": True,
                    "regle": rule_context,
                    "identite_locale": {
                        "statuts": sorted({
                            item["face_status"] for item in objects
                            if item.get("label") == "person" and item.get("face_status")
                        }),
                    },
                    "signature_hmac": f"HMAC-SHA256/v{contract_version}",
                    "nonce_requete": str(request_nonce) if request_nonce else None,
                    "horodatage_requete": request_timestamp,
                    "alerte": {
                        "priorite": alert_decision.priorite,
                        "raison": alert_decision.raison,
                        "regroupee": principal_event is not None,
                        "retardee": delayed,
                        "notification_supprimee": alert_decision.notification_supprimee,
                    },
                },
            )
            if objects:
                ObjetDetecte.objects.bulk_create(
                    [
                        ObjetDetecte(
                            evenement=event,
                            classe=item["label"],
                            confiance=item["confidence"],
                            boite=item["bbox"],
                            identifiant_suivi=item.get("track_id", ""),
                        )
                        for item in objects
                    ]
                )
            ciphertext, nonce = encrypt_capture(normalized, event.pk)
            CaptureChiffree.objects.create(
                evenement=event,
                contenu_chiffre=ciphertext,
                nonce=nonce,
                type_mime=mime_type,
                taille=len(normalized),
            )
            if principal_event is None and not delayed:
                outbox_entry = EvenementBoiteEnvoi.objects.create(evenement=event)
                transaction.on_commit(
                    lambda entry_id=outbox_entry.pk: try_dispatch_outbox_entry(entry_id)
                )
    except IntegrityError as exc:
        existing = Evenement.objects.filter(client_event_id=client_event_id).first()
        if (
            existing is not None
            and existing.camera_id == camera.pk
            and existing.empreinte_charge_utile == payload_fingerprint
        ):
            if hasattr(existing, "boite_envoi"):
                transaction.on_commit(
                    lambda entry_id=existing.boite_envoi.pk: try_dispatch_outbox_entry(entry_id)
                )
            return existing, False
        raise ConflictingEventError(
            "Cet identifiant d’événement existe avec un contenu différent."
        ) from exc
    return event, True
