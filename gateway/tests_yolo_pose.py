import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import numpy as np

from .pose import Keypoint, PoseModelUnavailable, PosePipeline, PoseState, TrackedPerson
from .yolo_pose import (
    MODEL_BYTES, MODEL_ID, MODEL_NAME, MODEL_SHA256,
    PoseDetection, YoloPoseEstimator, match_estimates, verified_academic_model,
)


def prediction(*, cx=320, cy=320, width=320, height=320, confidence=0.9):
    return np.array([cx, cy, width, height, confidence] + [320, 320, 0.95] * 17, dtype=np.float32)


def session_for(*rows):
    output = np.stack(rows, axis=1)[None]
    return SimpleNamespace(run=lambda *_: [output])


class YoloPoseTests(TestCase):
    def test_letterbox_coordinates_are_restored_and_rgb_is_normalized(self):
        # 640x320 -> 640x640 with 160px vertical padding.
        calls = []
        session = SimpleNamespace(run=lambda _, feed: calls.append(feed) or [prediction()[:, None][None]])
        frame = np.zeros((320, 640, 3), dtype=np.uint8)
        frame[:, :, 2] = 255
        result = YoloPoseEstimator(session).detect(frame)[0]
        self.assertEqual(result.bbox, (160, 0, 480, 320))
        self.assertAlmostEqual(result.keypoints["nose"].x, 320)
        self.assertAlmostEqual(result.keypoints["nose"].y, 160)
        tensor = calls[0]["images"]
        self.assertEqual(tensor.shape, (1, 3, 640, 640))
        self.assertEqual(tensor[0, 0, 200, 0], 1)
        self.assertEqual(tensor[0, 2, 200, 0], 0)

    def test_duplicate_boxes_are_suppressed_but_separate_people_remain(self):
        estimator = YoloPoseEstimator(session_for(
            prediction(cx=120, width=100), prediction(cx=125, width=100, confidence=0.8),
            prediction(cx=520, width=100), prediction(cx=300, confidence=0.2),
        ))
        self.assertEqual(len(estimator.detect(np.zeros((640, 640, 3), dtype=np.uint8))), 2)

    def test_keypoints_in_padding_do_not_claim_visible_legs(self):
        row = prediction()
        row[5 + 15 * 3:5 + 16 * 3] = [320, 600, 0.99]
        result = YoloPoseEstimator(session_for(row)).detect(np.zeros((320, 640, 3), dtype=np.uint8))[0]
        self.assertEqual(result.keypoints["left_ankle"].score, 0)

    def test_nan_and_wrong_output_contract_fail_explicitly(self):
        bad = prediction()
        bad[0] = np.nan
        for output in (bad[:, None][None], np.zeros((1, 55, 1))):
            estimator = YoloPoseEstimator(SimpleNamespace(run=lambda *_: [output]))
            with self.assertRaises(PoseModelUnavailable):
                estimator.detect(np.zeros((640, 640, 3), dtype=np.uint8))

    def test_two_tracks_never_share_one_skeleton(self):
        points = {"nose": Keypoint(20, 20, 0.9)}
        detection = PoseDetection((0, 0, 100, 100), 0.9, points)
        people = [TrackedPerson("one", (0, 0, 100, 100)), TrackedPerson("two", (0, 0, 100, 100))]
        result = match_estimates(people, [detection])
        self.assertEqual(sum(bool(item) for item in result), 1)

    def test_reordered_people_and_detections_keep_their_own_points(self):
        first = PoseDetection((0, 0, 100, 100), 0.9, {"nose": Keypoint(10, 20, 0.9)})
        second = PoseDetection((200, 0, 300, 100), 0.9, {"nose": Keypoint(250, 20, 0.9)})
        people = [TrackedPerson("right", second.bbox), TrackedPerson("left", first.bbox)]
        self.assertEqual(match_estimates(people, [first, second]), [second.keypoints, first.keypoints])

    def test_missing_or_ambiguous_skeleton_is_uncertain(self):
        detection = PoseDetection((0, 0, 100, 100), 0.9, {"nose": Keypoint(10, 20, 0.9)})
        estimator = SimpleNamespace(estimate=lambda _, people: match_estimates(people, [detection, detection]))
        result = PosePipeline(estimator).analyze(None, [TrackedPerson("one", detection.bbox)])
        self.assertEqual(result[0].state, PoseState.UNCERTAIN)

    def test_model_requires_opt_in_and_exact_registry_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / "registry.json"
            registry.write_text(json.dumps({"models": [{
                "id": MODEL_ID, "status": "candidate", "files": [
                    {"name": MODEL_NAME, "bytes": MODEL_BYTES, "sha256": MODEL_SHA256},
                ],
            }]}), encoding="utf-8")
            for opt_in in (False, True):
                with self.assertRaises(PoseModelUnavailable):
                    verified_academic_model(root, registry, academic_use=opt_in)
            data = json.loads(registry.read_text())
            data["models"][0]["status"] = "academic_approved"
            registry.write_text(json.dumps(data), encoding="utf-8")
            (root / MODEL_NAME).write_bytes(b"tampered")
            with self.assertRaises(PoseModelUnavailable):
                verified_academic_model(root, registry, academic_use=True)
            # A correct file length must not bypass the cryptographic check.
            with (root / MODEL_NAME).open("wb") as payload:
                payload.truncate(MODEL_BYTES)
            with self.assertRaises(PoseModelUnavailable):
                verified_academic_model(root, registry, academic_use=True)

    def test_reader_is_closed_if_inference_fails(self):
        from .pose_recipe import run_recipe

        calls = []
        reader = SimpleNamespace(open=lambda: None, close=lambda: calls.append("closed"),
                                 read=lambda: np.zeros((10, 10, 3), dtype=np.uint8))
        estimator = SimpleNamespace(detect=lambda _: (_ for _ in ()).throw(PoseModelUnavailable("failure")))
        with patch("gateway.pose_recipe.time.sleep"), self.assertRaises(PoseModelUnavailable):
            run_recipe(reader, estimator, seconds=2)
        self.assertEqual(calls, ["closed"])
