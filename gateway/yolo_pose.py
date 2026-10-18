"""Pinned YOLO11 pose adapter for the isolated academic recipe only."""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .pose import COCO_KEYPOINTS, Keypoint, PoseModelUnavailable

MODEL_ID = "yolo11n-pose-640"
MODEL_NAME = "yolo11n-pose.onnx"
MODEL_BYTES = 11853451
MODEL_SHA256 = "93e2866b0ce678f99b4dd88af0c12e9ea2edf079a361dc2ecbc6226b77ff6408"
MODEL_SIZE = 640


@dataclass(frozen=True)
class PoseDetection:
    bbox: tuple[float, float, float, float]
    confidence: float
    keypoints: dict[str, Keypoint]


def verified_academic_model(model_root, registry_path, *, academic_use=False):
    if not academic_use:
        raise PoseModelUnavailable("La recette de posture doit etre explicitement activee.")
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
        spec = next(item for item in registry["models"] if item["id"] == MODEL_ID)
        expected = {"name": MODEL_NAME, "bytes": MODEL_BYTES, "sha256": MODEL_SHA256}
        if spec["status"] != "academic_approved" or spec["files"] != [expected]:
            raise ValueError("Unapproved manifest")
        path = Path(model_root) / MODEL_NAME
        if path.stat().st_size != MODEL_BYTES:
            raise ValueError("Wrong size")
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != MODEL_SHA256:
            raise ValueError("Wrong digest")
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise PoseModelUnavailable("Poids de posture absents, non approuves ou alteres.") from exc
    return path


def box_iou(first, second):
    x1, y1 = max(first[0], second[0]), max(first[1], second[1])
    x2, y2 = min(first[2], second[2]), min(first[3], second[3])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area_a = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    area_b = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def match_estimates(people, detections, *, minimum_iou=0.30):
    """Never reuse one skeleton for two tracks; ambiguous matches stay unknown."""
    candidates = []
    for person_index, person in enumerate(people):
        scores = sorted(
            ((box_iou(person.bbox, detection.bbox), index)
             for index, detection in enumerate(detections)), reverse=True,
        )
        if not scores or scores[0][0] < minimum_iou:
            continue
        if len(scores) > 1 and scores[0][0] - scores[1][0] < 0.10:
            continue
        candidates.append((scores[0][0], person_index, scores[0][1]))
    results = [{} for _ in people]
    used = set()
    for _, person_index, detection_index in sorted(candidates, reverse=True):
        if detection_index not in used:
            used.add(detection_index)
            results[person_index] = detections[detection_index].keypoints
    return results


class YoloPoseEstimator:
    def __init__(self, session, *, confidence=0.45, nms_iou=0.45):
        self.session = session
        self.confidence = confidence
        self.nms_iou = nms_iou

    @classmethod
    def from_registry(cls, model_root, *, registry_path=None, academic_use=False):
        root = Path(__file__).resolve().parents[1]
        path = verified_academic_model(
            model_root, registry_path or root / "config/model_registry.json",
            academic_use=academic_use,
        )
        import onnxruntime as ort

        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(
            str(path), sess_options=options, providers=["CPUExecutionProvider"],
        )
        inputs, outputs = session.get_inputs(), session.get_outputs()
        if (len(inputs) != 1 or inputs[0].name != "images"
                or inputs[0].shape != [1, 3, 640, 640]
                or len(outputs) != 1 or outputs[0].shape != [1, 56, 8400]):
            raise PoseModelUnavailable("Contrat ONNX de posture inattendu.")
        return cls(session)

    def detect(self, frame):
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise PoseModelUnavailable("Image BGR de posture invalide.")
        height, width = frame.shape[:2]
        if min(height, width) < 2:
            raise PoseModelUnavailable("Image BGR de posture trop petite.")
        scale = min(MODEL_SIZE / width, MODEL_SIZE / height)
        resized_width, resized_height = round(width * scale), round(height * scale)
        left, top = (MODEL_SIZE - resized_width) // 2, (MODEL_SIZE - resized_height) // 2
        canvas = np.full((MODEL_SIZE, MODEL_SIZE, 3), 114, dtype=np.uint8)
        canvas[top:top + resized_height, left:left + resized_width] = cv2.resize(
            frame, (resized_width, resized_height),
        )
        tensor = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255
        output = self.session.run(None, {"images": tensor})[0]
        if output.ndim != 3 or output.shape[:2] != (1, 56) or not np.isfinite(output).all():
            raise PoseModelUnavailable("Sortie ONNX de posture invalide.")
        # YOLO11 pose: cx, cy, width, height, person confidence, 17 * (x, y, score).
        rows = output[0].T
        rows = rows[rows[:, 4] >= self.confidence]
        detections = []
        for row in rows:
            cx, cy, box_width, box_height = map(float, row[:4])
            if box_width <= 0 or box_height <= 0 or not 0 <= row[4] <= 1:
                continue
            bbox = (
                max(0.0, (cx - box_width / 2 - left) / scale),
                max(0.0, (cy - box_height / 2 - top) / scale),
                min(float(width), (cx + box_width / 2 - left) / scale),
                min(float(height), (cy + box_height / 2 - top) / scale),
            )
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            keypoints = {}
            for name, (x, y, score) in zip(COCO_KEYPOINTS, row[5:].reshape(17, 3)):
                x, y = (float(x) - left) / scale, (float(y) - top) / scale
                visible = 0 <= x < width and 0 <= y < height and 0 <= score <= 1
                keypoints[name] = Keypoint(x, y, float(score) if visible else 0.0)
            detections.append(PoseDetection(bbox, float(row[4]), keypoints))
        kept = []
        for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
            if all(box_iou(detection.bbox, item.bbox) <= self.nms_iou for item in kept):
                kept.append(detection)
            if len(kept) >= 64:
                break
        return kept

    def estimate(self, frame, people):
        if not people:
            return []
        return match_estimates(people, self.detect(frame))
