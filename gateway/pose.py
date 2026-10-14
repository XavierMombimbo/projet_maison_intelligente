import hashlib
import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


COCO_KEYPOINTS = (
    "nose",
    "left_eye",
    "right_eye",
    "left_ear",
    "right_ear",
    "left_shoulder",
    "right_shoulder",
    "left_elbow",
    "right_elbow",
    "left_wrist",
    "right_wrist",
    "left_hip",
    "right_hip",
    "left_knee",
    "right_knee",
    "left_ankle",
    "right_ankle",
)


class PoseModelUnavailable(RuntimeError):
    pass


class PoseState(StrEnum):
    UPRIGHT = "upright"
    LOW = "low"
    HORIZONTAL = "horizontal"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class Keypoint:
    x: float
    y: float
    score: float


@dataclass(frozen=True)
class TrackedPerson:
    track_id: str
    bbox: tuple[float, float, float, float]


@dataclass(frozen=True)
class PoseAssessment:
    track_id: str
    state: PoseState
    quality: float
    visible_keypoints: int
    reason: str


def _midpoint(first: Keypoint, second: Keypoint) -> tuple[float, float]:
    return ((first.x + second.x) / 2, (first.y + second.y) / 2)


def _angle(first: Keypoint, vertex: Keypoint, third: Keypoint) -> float | None:
    left = (first.x - vertex.x, first.y - vertex.y)
    right = (third.x - vertex.x, third.y - vertex.y)
    left_length = math.hypot(*left)
    right_length = math.hypot(*right)
    if left_length == 0 or right_length == 0:
        return None
    cosine = (left[0] * right[0] + left[1] * right[1]) / (
        left_length * right_length
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def assess_pose(
    track_id: str,
    keypoints: dict[str, Keypoint],
    *,
    visibility_threshold: float = 0.45,
) -> PoseAssessment:
    visible = {
        name: point
        for name, point in keypoints.items()
        if point.score >= visibility_threshold
    }
    quality = 0.0
    if keypoints:
        quality = sum(
            max(0.0, min(1.0, point.score)) for point in keypoints.values()
        ) / len(keypoints)

    torso_names = {"left_shoulder", "right_shoulder", "left_hip", "right_hip"}
    if not torso_names.issubset(visible):
        return PoseAssessment(
            track_id,
            PoseState.UNCERTAIN,
            quality,
            len(visible),
            "torso_partially_hidden",
        )

    shoulders = _midpoint(visible["left_shoulder"], visible["right_shoulder"])
    hips = _midpoint(visible["left_hip"], visible["right_hip"])
    torso_dx = hips[0] - shoulders[0]
    torso_dy = hips[1] - shoulders[1]
    if math.hypot(torso_dx, torso_dy) == 0:
        return PoseAssessment(
            track_id,
            PoseState.UNCERTAIN,
            quality,
            len(visible),
            "invalid_torso_geometry",
        )

    xs = [point.x for point in visible.values()]
    ys = [point.y for point in visible.values()]
    span_x = max(xs) - min(xs)
    span_y = max(ys) - min(ys)
    torso_horizontal = abs(torso_dx) >= abs(torso_dy) * 0.9
    body_horizontal = span_y > 0 and span_x >= span_y * 1.25
    if torso_horizontal and body_horizontal:
        return PoseAssessment(
            track_id,
            PoseState.HORIZONTAL,
            quality,
            len(visible),
            "horizontal_body_geometry",
        )

    knee_angles = []
    for side in ("left", "right"):
        names = (f"{side}_hip", f"{side}_knee", f"{side}_ankle")
        if all(name in visible for name in names):
            angle = _angle(*(visible[name] for name in names))
            if angle is not None:
                knee_angles.append(angle)

    if not knee_angles:
        return PoseAssessment(
            track_id,
            PoseState.UNCERTAIN,
            quality,
            len(visible),
            "legs_partially_hidden",
        )

    mean_knee_angle = sum(knee_angles) / len(knee_angles)
    if mean_knee_angle < 135:
        return PoseAssessment(
            track_id,
            PoseState.LOW,
            quality,
            len(visible),
            "bent_knee_geometry",
        )
    if abs(torso_dy) > abs(torso_dx) and mean_knee_angle >= 150:
        return PoseAssessment(
            track_id,
            PoseState.UPRIGHT,
            quality,
            len(visible),
            "vertical_torso_and_extended_leg",
        )
    return PoseAssessment(
        track_id,
        PoseState.UNCERTAIN,
        quality,
        len(visible),
        "ambiguous_geometry",
    )


def _verified_model_artifact(
    registry_path: Path, model_id: str, project_root: Path
) -> tuple[dict, Path]:
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    model = next(
        (entry for entry in registry["models"] if entry["id"] == model_id), None
    )
    if model is None:
        raise PoseModelUnavailable("Le modèle de posture est absent du registre.")
    if model["status"] != "production_approved":
        raise PoseModelUnavailable(
            "Les poids RTMPose ne sont pas approuvés pour ce produit."
        )
    if not model["artifact"] or not model["sha256"] or model["bytes"] is None:
        raise PoseModelUnavailable("Le manifeste du modèle de posture est incomplet.")
    artifact = project_root / model["artifact"]
    try:
        payload = artifact.read_bytes()
    except OSError as exc:
        raise PoseModelUnavailable("Le checkpoint RTMPose approuvé est absent.") from exc
    if len(payload) != model["bytes"]:
        raise PoseModelUnavailable("La taille du checkpoint RTMPose est invalide.")
    if hashlib.sha256(payload).hexdigest() != model["sha256"]:
        raise PoseModelUnavailable("L’empreinte du checkpoint RTMPose est invalide.")
    return model, artifact


class RTMPoseEstimator:
    def __init__(self, model, inference_topdown):
        self.model = model
        self._inference_topdown = inference_topdown

    @classmethod
    def from_registry(
        cls,
        registry_path: Path,
        *,
        project_root: Path,
        model_id: str = "rtmpose-s-256x192",
        device: str = "cpu",
        init_model=None,
        inference_topdown=None,
    ):
        model_spec, checkpoint = _verified_model_artifact(
            registry_path, model_id, project_root
        )
        config_path = project_root / model_spec["config"]
        if not config_path.is_file():
            raise PoseModelUnavailable("La configuration RTMPose approuvée est absente.")
        if init_model is None or inference_topdown is None:
            try:
                from mmpose.apis import inference_topdown as mmpose_inference
                from mmpose.apis import init_model as mmpose_init
            except ImportError as exc:
                raise PoseModelUnavailable(
                    "MMPose n’est pas installé sur la passerelle."
                ) from exc
            init_model = mmpose_init
            inference_topdown = mmpose_inference
        return cls(init_model(str(config_path), str(checkpoint), device=device), inference_topdown)

    def estimate(self, frame, people: list[TrackedPerson]) -> list[dict[str, Keypoint]]:
        if not people:
            return []
        bboxes = [list(person.bbox) for person in people]
        samples = self._inference_topdown(
            self.model, frame, bboxes=bboxes, bbox_format="xyxy"
        )
        results = []
        for sample in samples:
            instances = sample.pred_instances
            coordinates = instances.keypoints[0]
            scores = instances.keypoint_scores[0]
            results.append(
                {
                    name: Keypoint(float(point[0]), float(point[1]), float(score))
                    for name, point, score in zip(COCO_KEYPOINTS, coordinates, scores)
                }
            )
        return results


class PosePipeline:
    def __init__(self, estimator):
        self.estimator = estimator

    def analyze(self, frame, people: list[TrackedPerson]) -> list[PoseAssessment]:
        estimates = self.estimator.estimate(frame, people)
        if len(estimates) != len(people):
            raise PoseModelUnavailable(
                "RTMPose n’a pas renvoyé un résultat pour chaque personne suivie."
            )
        return [
            assess_pose(person.track_id, keypoints)
            for person, keypoints in zip(people, estimates)
        ]
