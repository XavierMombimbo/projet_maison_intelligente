import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from .pose import (
    COCO_KEYPOINTS,
    Keypoint,
    PoseModelUnavailable,
    PosePipeline,
    PoseState,
    RTMPoseEstimator,
    TrackedPerson,
    assess_pose,
)


def point(x, y, score=0.95):
    return Keypoint(x, y, score)


def upright_keypoints():
    return {
        "left_shoulder": point(40, 20),
        "right_shoulder": point(60, 20),
        "left_hip": point(43, 50),
        "right_hip": point(57, 50),
        "left_knee": point(44, 75),
        "right_knee": point(56, 75),
        "left_ankle": point(45, 100),
        "right_ankle": point(55, 100),
    }


class PoseAssessmentTests(TestCase):
    def test_recognizes_neutral_upright_geometry(self):
        result = assess_pose("track-1", upright_keypoints())

        self.assertEqual(result.state, PoseState.UPRIGHT)
        self.assertEqual(result.track_id, "track-1")

    def test_recognizes_low_geometry_from_bent_knees(self):
        keypoints = upright_keypoints()
        keypoints.update(
            left_knee=point(45, 65),
            left_ankle=point(70, 60),
            right_knee=point(55, 65),
            right_ankle=point(30, 60),
        )

        result = assess_pose("track-2", keypoints)

        self.assertEqual(result.state, PoseState.LOW)

    def test_recognizes_horizontal_geometry_without_calling_it_a_fall(self):
        keypoints = {
            "left_shoulder": point(20, 40),
            "right_shoulder": point(20, 60),
            "left_hip": point(55, 42),
            "right_hip": point(55, 58),
            "left_knee": point(75, 43),
            "right_knee": point(75, 57),
            "left_ankle": point(100, 44),
            "right_ankle": point(100, 56),
        }

        result = assess_pose("track-3", keypoints)

        self.assertEqual(result.state, PoseState.HORIZONTAL)
        self.assertEqual(result.reason, "horizontal_body_geometry")

    def test_hidden_torso_is_explicitly_uncertain(self):
        keypoints = upright_keypoints()
        keypoints["right_shoulder"] = point(60, 20, score=0.1)

        result = assess_pose("track-4", keypoints)

        self.assertEqual(result.state, PoseState.UNCERTAIN)
        self.assertEqual(result.reason, "torso_partially_hidden")

    def test_pipeline_preserves_person_tracking_identity(self):
        estimator = SimpleNamespace(
            estimate=lambda frame, people: [upright_keypoints() for _ in people]
        )
        people = [
            TrackedPerson("track-a", (0, 0, 100, 120)),
            TrackedPerson("track-b", (100, 0, 200, 120)),
        ]

        results = PosePipeline(estimator).analyze(object(), people)

        self.assertEqual([result.track_id for result in results], ["track-a", "track-b"])

    def test_pipeline_rejects_missing_person_result(self):
        estimator = SimpleNamespace(estimate=lambda frame, people: [])

        with self.assertRaises(PoseModelUnavailable):
            PosePipeline(estimator).analyze(
                object(), [TrackedPerson("track-a", (0, 0, 100, 120))]
            )


class RTMPoseAdapterTests(TestCase):
    def test_registry_blocks_unapproved_checkpoint_before_import(self):
        registry = {
            "models": [
                {
                    "id": "rtmpose-s-256x192",
                    "status": "blocked_weight_license",
                    "artifact": None,
                    "bytes": None,
                    "sha256": None,
                    "config": "config/pose.py",
                }
            ]
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry_path = root / "registry.json"
            registry_path.write_text(json.dumps(registry), encoding="utf-8")

            with self.assertRaisesRegex(PoseModelUnavailable, "pas approuvés"):
                RTMPoseEstimator.from_registry(registry_path, project_root=root)

    def test_adapter_maps_coco_keypoints_for_each_person(self):
        coordinates = [[float(index), float(index + 1)] for index in range(17)]
        scores = [0.9] * 17
        sample = SimpleNamespace(
            pred_instances=SimpleNamespace(
                keypoints=[coordinates], keypoint_scores=[scores]
            )
        )
        calls = []

        def inference(model, frame, *, bboxes, bbox_format):
            calls.append((model, frame, bboxes, bbox_format))
            return [sample]

        estimator = RTMPoseEstimator("model", inference)
        frame = object()
        result = estimator.estimate(
            frame, [TrackedPerson("track-1", (1, 2, 30, 40))]
        )

        self.assertEqual(set(result[0]), set(COCO_KEYPOINTS))
        self.assertEqual(result[0]["nose"], Keypoint(0.0, 1.0, 0.9))
        self.assertEqual(calls, [("model", frame, [[1, 2, 30, 40]], "xyxy")])
