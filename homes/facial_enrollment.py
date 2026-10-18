"""Bounded, in-memory capture for voluntary web enrolment on this server."""
import base64
import binascii
import io
import threading
import warnings
from functools import lru_cache

from django.conf import settings
from django.views.decorators.debug import sensitive_variables
from PIL import Image, UnidentifiedImageError

from gateway.facial import ArcFaceEmbedder, FaceQualityError, FaceRecognitionError
from gateway.model_policy import ModelApprovalError, require_arcface_academic_approval
from config.facial_body import MAX_CAPTURE_BODY

MAX_IMAGE_BYTES = 384 * 1024
MAX_REQUEST_BYTES = MAX_CAPTURE_BODY
_inference_lock = threading.Lock()


class EnrollmentUnavailable(Exception):
    pass


class EnrollmentBusy(Exception):
    pass


@lru_cache(maxsize=1)
def _embedder(root):
    require_arcface_academic_approval(root)
    return ArcFaceEmbedder.from_model_root(root, allowed_modules=("detection", "recognition"))


@sensitive_variables()
def template_from_capture(encoded):
    if not settings.BIOMETRIC_WEB_ENROLLMENT_ENABLED or not settings.BIOMETRIC_FACE_MODEL_ROOT:
        raise EnrollmentUnavailable
    if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE_BYTES * 4 // 3):
        raise FaceQualityError("La capture est trop volumineuse. Réessayez avec la caméra.")
    try:
        payload = base64.b64decode(encoded, validate=True)
        if not payload or len(payload) > MAX_IMAGE_BYTES:
            raise ValueError
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != "JPEG" or not (160 <= image.width <= 1280 and 120 <= image.height <= 1280):
                    raise ValueError
                image.load()
                import numpy as np
                frame = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()
    except (ValueError, binascii.Error, OSError, UnidentifiedImageError,
            Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise FaceQualityError("Capture illisible. Ouvrez la caméra et réessayez.") from None
    return embedding_from_frame(frame)


@sensitive_variables()
def embedding_from_frame(frame, *, person_bbox=None):
    """Share the bounded model and lock with browser event verification."""
    if not _inference_lock.acquire(blocking=False):
        raise EnrollmentBusy
    try:
        try:
            embedder = _embedder(settings.BIOMETRIC_FACE_MODEL_ROOT)
            return embedder.embedding_from_bgr(frame, **(
                {"person_bbox": person_bbox} if person_bbox is not None else {}
            ))
        except (ModelApprovalError, FaceRecognitionError) as exc:
            if isinstance(exc, FaceQualityError):
                raise
            raise EnrollmentUnavailable from None
    finally:
        _inference_lock.release()
