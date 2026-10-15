"""Local ArcFace embedding and comparison primitives.

This module deliberately does not save source images.  It only accepts an
already decoded BGR frame, produces a normalized embedding, and compares that
embedding with the encrypted templates supplied for explicitly enrolled
profiles.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np


ARCFACE_TEMPLATE_FORMAT = "arcface-f32le-v1"
ARCFACE_EMBEDDING_SIZE = 512
DEFAULT_MATCH_THRESHOLD = 0.45
MIN_FACE_DETECTION_CONFIDENCE = 0.65


class FaceRecognitionError(RuntimeError):
    """A local face-recognition operation cannot safely return a result."""


class FaceQualityError(FaceRecognitionError):
    """The frame has no single, sufficiently clear face for a comparison."""


@dataclass(frozen=True)
class FaceComparison:
    state: str
    score: float | None = None
    profile_id: str | None = None


def _normalized_embedding(value: object) -> np.ndarray:
    # ``ArcFaceEmbedder.embedding_from_bgr`` deliberately returns the stable
    # serialized representation used for enrolment.  Accept that same
    # representation for a query so the capture and comparison paths compose
    # without ever expanding a template beyond process memory.
    if isinstance(value, (bytes, bytearray, memoryview)):
        payload = bytes(value)
        if len(payload) != ARCFACE_EMBEDDING_SIZE * 4:
            raise FaceRecognitionError("Gabarit ArcFace invalide.")
        value = np.frombuffer(payload, dtype="<f4")
    try:
        embedding = np.asarray(value, dtype=np.float32).reshape(-1)
    except (TypeError, ValueError) as exc:
        raise FaceRecognitionError("Vecteur facial invalide.") from exc
    if embedding.size != ARCFACE_EMBEDDING_SIZE or not np.isfinite(embedding).all():
        raise FaceRecognitionError("Vecteur facial invalide.")
    norm = float(np.linalg.norm(embedding))
    if not np.isfinite(norm) or norm <= 1e-9:
        raise FaceRecognitionError("Vecteur facial sans information exploitable.")
    return embedding / norm


def serialize_embedding(value: object) -> bytes:
    """Return the stable, normalized binary template stored by the server."""
    return _normalized_embedding(value).astype("<f4", copy=False).tobytes()


def deserialize_embedding(payload: bytes) -> np.ndarray:
    if not isinstance(payload, bytes) or len(payload) != ARCFACE_EMBEDDING_SIZE * 4:
        raise FaceRecognitionError("Gabarit ArcFace invalide.")
    return _normalized_embedding(np.frombuffer(payload, dtype="<f4"))


def compare_embedding(
    query: object,
    profiles: Iterable[dict],
    *,
    threshold: float = DEFAULT_MATCH_THRESHOLD,
) -> FaceComparison:
    """Compare one query locally and make unknown distinct from bad input.

    Profile labels and images are intentionally not part of the return value.
    The caller may use ``profile_id`` only for a local, consent-scoped result.
    """
    if not 0.0 < float(threshold) <= 1.0:
        raise FaceRecognitionError("Seuil de comparaison facial invalide.")
    vector = _normalized_embedding(query)
    best_id = None
    best_score = -1.0
    for profile in profiles:
        if not isinstance(profile, dict) or not isinstance(profile.get("profile_id"), str):
            raise FaceRecognitionError("Profil biométrique local invalide.")
        if profile.get("format") != ARCFACE_TEMPLATE_FORMAT:
            continue
        score = float(np.dot(vector, deserialize_embedding(profile.get("template"))))
        if score > best_score:
            best_score = score
            best_id = profile["profile_id"]
    if best_id is None:
        return FaceComparison("unavailable")
    if best_score >= threshold:
        return FaceComparison("matched", score=best_score, profile_id=best_id)
    return FaceComparison("unknown", score=best_score)


class ArcFaceEmbedder:
    """Thin InsightFace adapter, imported only when the feature is requested."""

    def __init__(self, application, *, minimum_confidence=MIN_FACE_DETECTION_CONFIDENCE):
        self.application = application
        self.minimum_confidence = float(minimum_confidence)
        if not 0.0 < self.minimum_confidence <= 1.0:
            raise FaceRecognitionError("Seuil de détection faciale invalide.")

    @classmethod
    def from_model_root(cls, root: str | Path):
        root = Path(root)
        if not root.is_dir():
            raise FaceRecognitionError("Répertoire ArcFace absent.")
        try:
            from insightface.app import FaceAnalysis
        except ImportError as exc:
            raise FaceRecognitionError("InsightFace n’est pas installé.") from exc
        try:
            application = FaceAnalysis(
                name="buffalo_l", root=str(root), providers=["CPUExecutionProvider"]
            )
            application.prepare(ctx_id=-1, det_size=(640, 640))
        except Exception as exc:
            raise FaceRecognitionError("Modèle ArcFace indisponible ou illisible.") from exc
        return cls(application)

    def embedding_from_bgr(self, frame: np.ndarray) -> bytes:
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.size == 0:
            raise FaceQualityError("Image faciale invalide.")
        try:
            faces = list(self.application.get(frame))
        except Exception as exc:
            raise FaceRecognitionError("Inférence ArcFace indisponible.") from exc
        faces = [face for face in faces if float(getattr(face, "det_score", 0.0)) >= self.minimum_confidence]
        if not faces:
            raise FaceQualityError("Aucun visage suffisamment net n’est visible.")
        if len(faces) != 1:
            raise FaceQualityError("Un seul visage doit être visible pendant l’enrôlement.")
        return serialize_embedding(getattr(faces[0], "embedding", None))
