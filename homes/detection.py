from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError
from django.conf import settings
from django.db import IntegrityError, transaction

from .crypto import encrypt_capture
from .models import CaptureChiffree, Evenement, TypeEvenement

ALLOWED_IMAGE_TYPES = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
MAX_IMAGE_DIMENSION = 4096
MAX_IMAGE_PIXELS = 12_000_000
NORMALIZED_MAX_SIZE = (1280, 720)


class DetectionError(Exception):
    pass


class CaptureValidationError(DetectionError):
    pass


class ReplayedEventError(DetectionError):
    pass


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
) -> Evenement:
    if not camera.surveillance_active:
        raise DetectionError("La surveillance de cette caméra est désactivée.")
    normalized, mime_type, image_metadata = validate_and_normalize_capture(uploaded_file)

    try:
        with transaction.atomic():
            event = Evenement.objects.create(
                client_event_id=client_event_id,
                camera=camera,
                maison=camera.maison,
                type=(TypeEvenement.SIMULATION if simulated else TypeEvenement.PERSONNE_DETECTEE),
                confiance_ia=confidence,
                simule=simulated,
                metadonnees={
                    "capture": image_metadata,
                    "analyse_locale": True,
                    "stabilite_images": 3 if not simulated else 0,
                    "signature_hmac": "HMAC-SHA256/v1",
                    "nonce_requete": str(request_nonce) if request_nonce else None,
                    "horodatage_requete": request_timestamp,
                },
            )
            ciphertext, nonce = encrypt_capture(normalized, event.pk)
            CaptureChiffree.objects.create(
                evenement=event,
                contenu_chiffre=ciphertext,
                nonce=nonce,
                type_mime=mime_type,
                taille=len(normalized),
            )
            from .realtime import publish_event

            transaction.on_commit(lambda event_id=event.pk: publish_event(event_id))
    except IntegrityError as exc:
        raise ReplayedEventError("Cet événement a déjà été transmis.") from exc
    return event
