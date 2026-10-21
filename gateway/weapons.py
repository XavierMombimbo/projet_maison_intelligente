"""Local weapon candidates and temporal confirmation, never an identity or intent.

The pinned candidate is evaluation-only: its training provenance is unresolved.
No download, camera acquisition, notification or persistence happens here.
"""
import ast
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

MODEL_ID = "ece-weapon-640-review"
MODEL_SHA256 = "d300e36bb5c1939e0ca0717e7523fcee93d8a4cb502ec407e21f596d26935068"
MODEL_BYTES = 12268102
MODEL_SIZE = 640
MODEL_CLASSES = {0: "Gun", 1: "explosion", 2: "grenade", 3: "knife"}
WEAPON_CLASSES = {0: "firearm", 3: "knife"}
# Development operating points, NOT measured acceptance thresholds.
THRESHOLDS = {"firearm": 0.65, "knife": 0.70}


class WeaponUnavailable(ValueError):
    pass


@dataclass(frozen=True)
class WeaponDetection:
    label: str
    confidence: float
    bbox: tuple[float, float, float, float]  # normalized x, y, width, height

    def public(self):
        return {"label": self.label, "confidence": self.confidence, "bbox": list(self.bbox)}


def box_iou(a, b):
    width = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    height = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    intersection = width * height
    union = a[2] * a[3] + b[2] * b[3] - intersection
    return intersection / union if union > 0 else 0.0


def verified_model(model_root, *, registry_path=None, mode="review"):
    if mode not in {"review", "alerts"}:
        raise WeaponUnavailable("Module de suspicion d’arme désactivé.")
    try:
        path = Path(model_root) / "model.onnx"
        registry = Path(registry_path or Path(__file__).resolve().parents[1] / "config/model_registry.json")
        spec = next(m for m in json.loads(registry.read_text(encoding="utf-8"))["models"] if m["id"] == MODEL_ID)
        allowed = {"evaluation_only", "production_approved"} if mode == "review" else {"production_approved"}
        expected = {"name": "model.onnx", "bytes": MODEL_BYTES, "sha256": MODEL_SHA256}
        if spec["status"] not in allowed or spec["files"] != [expected]:
            raise ValueError("Unapproved artifact")
        if path.stat().st_size != MODEL_BYTES:
            raise ValueError("Invalid size")
        with path.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != MODEL_SHA256:
                raise ValueError("Invalid digest")
    except (OSError, KeyError, ValueError, TypeError, StopIteration) as exc:
        raise WeaponUnavailable("Modèle d’arme absent, altéré ou non qualifié pour ce mode.") from exc
    return path


class WeaponDetector:
    def __init__(self, session):
        self.session = session

    @classmethod
    def from_registry(cls, model_root, *, mode="review", registry_path=None):
        path = verified_model(model_root, mode=mode, registry_path=registry_path)
        import onnxruntime as ort
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        session = ort.InferenceSession(str(path), sess_options=options, providers=["CPUExecutionProvider"])
        inputs, outputs = session.get_inputs(), session.get_outputs()
        if (len(inputs) != 1 or inputs[0].name != "images" or inputs[0].type != "tensor(float)"
                or inputs[0].shape != [1, 3, 640, 640] or len(outputs) != 1
                or outputs[0].shape != [1, 8, 8400]):
            raise WeaponUnavailable("Contrat ONNX d’arme inattendu.")
        try:
            names = ast.literal_eval(session.get_modelmeta().custom_metadata_map["names"])
            if names != MODEL_CLASSES:
                raise ValueError("Class mapping mismatch")
        except (KeyError, ValueError, SyntaxError) as exc:
            raise WeaponUnavailable("Classes du modèle d’arme inattendues.") from exc
        return cls(session)

    def detect(self, frame):
        if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8 or frame.ndim != 3
                or frame.shape[2] != 3 or min(frame.shape[:2]) < 2):
            raise WeaponUnavailable("Image BGR d’arme invalide.")
        height, width = frame.shape[:2]
        scale = min(MODEL_SIZE / width, MODEL_SIZE / height)
        resized_width, resized_height = max(1, round(width * scale)), max(1, round(height * scale))
        left, top = (MODEL_SIZE - resized_width) // 2, (MODEL_SIZE - resized_height) // 2
        canvas = np.full((MODEL_SIZE, MODEL_SIZE, 3), 114, dtype=np.uint8)
        canvas[top:top + resized_height, left:left + resized_width] = cv2.resize(frame, (resized_width, resized_height))
        tensor = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None], dtype=np.float32) / 255
        try:
            output = self.session.run(None, {"images": tensor})[0]
        except Exception as exc:
            raise WeaponUnavailable("Inférence d’arme indisponible.") from exc
        if output.shape != (1, 8, 8400) or not np.isfinite(output).all():
            raise WeaponUnavailable("Sortie ONNX d’arme invalide.")
        rows = output[0].T
        if (rows[:, 4:] < 0).any() or (rows[:, 4:] > 1).any():
            raise WeaponUnavailable("Scores ONNX d’arme invalides.")
        found = []
        for row in rows:
            index = int(np.argmax(row[4:]))
            label = WEAPON_CLASSES.get(index)
            if label is None or row[4 + index] < THRESHOLDS[label]:
                continue
            cx, cy, w, h = map(float, row[:4])
            if min(w, h) <= 0:
                continue
            x1 = max(0.0, (cx - w / 2 - left) / scale / width)
            y1 = max(0.0, (cy - h / 2 - top) / scale / height)
            x2 = min(1.0, (cx + w / 2 - left) / scale / width)
            y2 = min(1.0, (cy + h / 2 - top) / scale / height)
            if x2 <= x1 or y2 <= y1:
                continue
            found.append(WeaponDetection(label, float(row[4 + index]), (x1, y1, x2 - x1, y2 - y1)))
        kept = []
        for item in sorted(found, key=lambda x: x.confidence, reverse=True):
            if all(item.label != old.label or box_iou(item.bbox, old.bbox) <= 0.45 for old in kept):
                kept.append(item)
            if len(kept) >= 64:
                break
        return kept


def observe(detections, previous, now):
    """Three distinct samples spanning >=2s, gap <=3s, same class and IoU.

    State contains only boxes/times, never images. Caller serializes updates and
    supplies server time. Missing detections and long gaps reset confirmation.
    """
    if not math.isfinite(now) or now < 0:
        raise ValueError("Invalid observation time")
    previous = previous or {}
    last = previous.get("at", -10.0)
    if now <= last:
        raise ValueError("Observations must be ordered")
    old_tracks = previous.get("tracks", []) if now - last <= 3.0 else []
    used, tracks, confirmed = set(), [], []
    next_id = int(previous.get("next_id", 0))
    for item in sorted(detections, key=lambda d: d.confidence, reverse=True)[:64]:
        if item.label not in THRESHOLDS or not THRESHOLDS[item.label] <= item.confidence <= 1:
            continue
        candidates = [(box_iou(item.bbox, old["bbox"]), i, old) for i, old in enumerate(old_tracks)
                      if i not in used and old["label"] == item.label]
        match = max(candidates, key=lambda row: row[0], default=None)
        if match and match[0] >= 0.30:
            _, index, old = match
            used.add(index)
            # Request bursts cannot manufacture a sustained detection.
            count = old["count"] + int(now - last >= 0.4)
            track_id, since = old["id"], old["since"]
        else:
            next_id += 1
            track_id, since, count = str(next_id), now, 1
        track = {"id": track_id, "label": item.label, "bbox": list(item.bbox),
                 "since": since, "count": count, "confidence": item.confidence}
        tracks.append(track)
        if count >= 3 and now - since >= 2:
            confirmed.append({**item.public(), "track_id": f"weapon-{track_id}"})
    return {"at": now, "tracks": tracks, "next_id": next_id}, confirmed
