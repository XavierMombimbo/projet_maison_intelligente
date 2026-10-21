"""Offline detection metrics for an independently annotated local image set.

No activation decision is inferred from an uploader's advertised mAP. Input
images remain local. This report measures boxes, not real-world alert precision.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time

import cv2

from .weapons import MODEL_ID, MODEL_SHA256, THRESHOLDS, WeaponDetector, box_iou

NEGATIVE_CONTEXTS = {"phone", "tool", "toy", "household_knife", "clean"}


def score_frame(predicted, expected, *, minimum_iou=.5):
    used, counts = set(), Counter()
    for item in sorted(predicted, key=lambda x: x.confidence, reverse=True):
        candidates = [(box_iou(item.bbox, truth["bbox"]), index)
                      for index, truth in enumerate(expected)
                      if index not in used and truth["label"] == item.label]
        overlap, index = max(candidates, default=(0, -1))
        if overlap >= minimum_iou:
            used.add(index)
            counts[(item.label, "tp")] += 1
        else:
            counts[(item.label, "fp")] += 1
    for index, truth in enumerate(expected):
        if index not in used:
            counts[(truth["label"], "fn")] += 1
    return counts


def evaluate(manifest, detector):
    path = Path(manifest).resolve()
    manifest_bytes = path.read_bytes()
    spec = json.loads(manifest_bytes.decode("utf-8"))
    # A source group is a video/scene, never an individual adjacent frame.
    training_groups = set(spec["training_source_groups"])
    declared_groups = [item["source_group"] for item in spec["images"]]
    if training_groups.intersection(declared_groups):
        raise ValueError("Le jeu d’évaluation partage des scènes avec l’entraînement.")
    if not spec["images"] or not spec.get("protocol_id"):
        raise ValueError("Protocole ou images d’évaluation absents.")
    counts, contexts, negative_candidates = Counter(), Counter(), Counter()
    seen_paths, seen_pixels, fingerprints, timings = set(), set(), [], []
    for item in spec["images"]:
        if (not isinstance(item["alert_expected"], bool) or not item["source_group"]
                or item["context"] not in NEGATIVE_CONTEXTS | {"firearm", "knife"}):
            raise ValueError("Contexte d’évaluation invalide.")
        image_path = (path.parent / item["file"]).resolve()
        if not image_path.is_relative_to(path.parent) or image_path in seen_paths:
            raise ValueError("Image dupliquée ou hors du dossier d’évaluation.")
        seen_paths.add(image_path)
        if any(truth["label"] not in THRESHOLDS or len(truth["bbox"]) != 4
               or any(not 0 <= v <= 1 for v in truth["bbox"])
               or truth["bbox"][2] <= 0 or truth["bbox"][3] <= 0
               or truth["bbox"][0] + truth["bbox"][2] > 1
               or truth["bbox"][1] + truth["bbox"][3] > 1 for truth in item["objects"]):
            raise ValueError("Annotation d’évaluation invalide.")
        frame = cv2.imread(str(image_path))
        if frame is None:
            raise ValueError("Image d’évaluation illisible.")
        # Renaming or re-encoding a duplicate must not inflate the sample count.
        pixels_digest = hashlib.sha256(str(frame.shape).encode() + frame.tobytes()).hexdigest()
        if pixels_digest in seen_pixels:
            raise ValueError("Image d’évaluation dupliquée après décodage.")
        seen_pixels.add(pixels_digest)
        fingerprints.append({"file": item["file"], "source_group": item["source_group"],
                             "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                             "decoded_sha256": pixels_digest})
        started = time.perf_counter()
        predicted = detector.detect(frame)
        timings.append((time.perf_counter() - started) * 1000)
        counts.update(score_frame(predicted, item["objects"]))
        context = item["context"]
        contexts[context] += 1
        if not item["alert_expected"] and predicted:
            negative_candidates[context] += 1
    metrics = {}
    for label in THRESHOLDS:
        tp, fp, fn = (counts[(label, name)] for name in ("tp", "fp", "fn"))
        metrics[label] = {"tp": tp, "fp": fp, "fn": fn,
                          "precision": tp / (tp + fp) if tp + fp else None,
                          "recall": tp / (tp + fn) if tp + fn else None}
    return {"protocol_id": spec["protocol_id"], "model_id": MODEL_ID, "sha256": MODEL_SHA256,
            "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            "image_fingerprints": fingerprints,
            "operating_thresholds": THRESHOLDS, "images": len(spec["images"]),
            "detection_metrics": metrics, "contexts": dict(contexts),
            "negative_images_with_candidates": dict(negative_candidates),
            "missing_negative_contexts": sorted(NEGATIVE_CONTEXTS - contexts.keys()),
            "training_provenance_declared": bool(training_groups),
            # A caller's source-group list is not evidence about this model's training.
            "independence_verified": False,
            "latency_ms": {"samples": len(timings), "mean": sum(timings) / len(timings),
                           "max": max(timings), "includes_first_inference": True,
                           "scope": "detector_only_not_camera_or_network"},
            "production_qualified": False,
            "remaining": ["Vérifier les droits et la provenance des données et poids.",
                          "Fixer les seuils d’acceptation avant l’évaluation finale.",
                          "Mesurer rappels temporels et fausses alertes par caméra-heure sur vidéos indépendantes."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    result = evaluate(args.manifest, WeaponDetector.from_registry(args.model_root, mode="review"))
    with Path(args.output).open("x", encoding="utf-8") as destination:
        json.dump(result, destination, ensure_ascii=False, indent=2)
    print("Rapport de détection créé ; qualification de production non accordée.")


if __name__ == "__main__":
    main()
