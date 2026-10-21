import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import MagicMock

import numpy as np

from .weapons import (MODEL_ID, THRESHOLDS, WeaponDetection, WeaponDetector,
                      WeaponUnavailable, observe, verified_model)
from .weapon_evaluation import score_frame, evaluate


class WeaponTests(TestCase):
    def setUp(self):
        self.session = MagicMock()
        self.output = np.zeros((1, 8, 8400), dtype=np.float32)
        self.session.run.return_value = [self.output]
        self.detector = WeaponDetector(self.session)
        self.frame = np.zeros((360, 640, 3), dtype=np.uint8)

    def row(self, index, label, score, box=(320, 320, 100, 80)):
        self.output[0, :4, index] = box
        self.output[0, 4 + label, index] = score

    def test_no_detection_is_distinct_from_model_failure(self):
        self.assertEqual(self.detector.detect(self.frame), [])
        self.session.run.side_effect = RuntimeError("unavailable")
        with self.assertRaises(WeaponUnavailable):
            self.detector.detect(self.frame)

    def test_exact_class_mapping_and_letterboxing(self):
        for index, label in enumerate(range(4)):
            self.row(index, label, .9, (120 + index * 110, 320, 60, 80))
        result = self.detector.detect(self.frame)
        self.assertEqual([d.label for d in result], ["firearm", "knife"])
        self.assertAlmostEqual(result[0].bbox[1], 140 / 360)
        self.assertAlmostEqual(result[0].bbox[3], 80 / 360)
        tensor = self.session.run.call_args.args[1]["images"]
        self.assertEqual(tensor.shape, (1, 3, 640, 640))
        self.assertEqual(tensor.dtype, np.float32)

    def test_non_weapon_winner_is_not_relabeled(self):
        self.row(0, 0, .8)
        self.row(0, 1, .9)
        self.assertEqual(self.detector.detect(self.frame), [])

    def test_nms_is_per_class_and_boxes_stay_in_frame(self):
        self.row(0, 0, .95)
        self.row(1, 0, .9)
        self.row(2, 3, .8)
        result = self.detector.detect(self.frame)
        self.assertEqual(len(result), 2)
        for item in result:
            x, y, w, h = item.bbox
            self.assertTrue(0 <= x < x + w <= 1)
            self.assertTrue(0 <= y < y + h <= 1)

    def test_invalid_scores_shapes_and_images_fail_closed(self):
        for value in (np.nan, np.inf, -1, 1.1):
            self.output[0, 4, 0] = value
            with self.subTest(value=value), self.assertRaises(WeaponUnavailable):
                self.detector.detect(self.frame)
        self.session.run.return_value = [np.zeros((1, 84, 8400))]
        with self.assertRaises(WeaponUnavailable):
            self.detector.detect(self.frame)
        for frame in (None, np.zeros((1, 1, 3), np.uint8), np.zeros((2, 2, 3), np.float32)):
            with self.assertRaises(WeaponUnavailable):
                self.detector.detect(frame)

    def test_temporal_confirmation_requires_three_samples_and_duration(self):
        item = WeaponDetection("firearm", .9, (.1, .1, .3, .3))
        state = None
        for at in (0, 1):
            state, confirmed = observe([item], state, at)
            self.assertEqual(confirmed, [])
        state, confirmed = observe([item], state, 2)
        self.assertEqual(confirmed[0]["label"], "firearm")

    def test_missing_frame_gap_different_class_or_location_resets_evidence(self):
        item = WeaponDetection("firearm", .9, (.1, .1, .2, .2))
        for middle, at in (([], 2), ([item], 5),
                           ([WeaponDetection("knife", .9, item.bbox)], 2),
                           ([WeaponDetection("firearm", .9, (.7, .7, .2, .2))], 2)):
            with self.subTest(middle=middle, at=at):
                state, _ = observe([item], None, 0)
                state, _ = observe([item], state, 1)
                state, _ = observe(middle, state, at)
                _, confirmed = observe([item], state, at + 1)
                self.assertEqual(confirmed, [])

    def test_one_old_box_cannot_confirm_two_new_objects(self):
        item = WeaponDetection("firearm", .9, (.1, .1, .2, .2))
        state, _ = observe([item], None, 0)
        state, _ = observe([item], state, 1)
        _, confirmed = observe([item, item], state, 2)
        self.assertEqual(len(confirmed), 1)

    def test_bursts_and_reversed_time_never_confirm(self):
        item = WeaponDetection("knife", .9, (.1, .1, .2, .2))
        state = None
        for at in (0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1, 1.1, 1.2, 1.3, 1.4, 2):
            state, confirmed = observe([item], state, at)
            self.assertEqual(confirmed, [])
        for at in (2, 1, float("nan")):
            with self.assertRaises(ValueError):
                observe([item], state, at)

    def test_model_cannot_load_with_missing_or_unapproved_weights(self):
        with TemporaryDirectory() as folder:
            registry = Path(folder) / "registry.json"
            registry.write_text(json.dumps({"models": [{"id": MODEL_ID, "status": "evaluation_only", "files": []}]}))
            for mode in ("disabled", "review", "alerts"):
                with self.subTest(mode=mode), self.assertRaises(WeaponUnavailable):
                    verified_model(folder, registry_path=registry, mode=mode)

    def test_subthreshold_candidate_does_not_advance_confirmation(self):
        item = WeaponDetection("knife", THRESHOLDS["knife"] - .01, (.1, .1, .2, .2))
        state = None
        for at in range(5):
            state, confirmed = observe([item], state, at)
            self.assertEqual(confirmed, [])
            self.assertEqual(state["tracks"], [])

    def test_evaluation_matching_is_one_to_one_and_per_class(self):
        item = WeaponDetection("firearm", .9, (.1, .1, .2, .2))
        truth = [{"label": "firearm", "bbox": list(item.bbox)},
                 {"label": "knife", "bbox": [.7, .7, .1, .1]}]
        counts = score_frame([item, item], truth)
        self.assertEqual(counts[("firearm", "tp")], 1)
        self.assertEqual(counts[("firearm", "fp")], 1)
        self.assertEqual(counts[("knife", "fn")], 1)

    def test_evaluation_rejects_scene_leakage_and_keeps_household_context_distinct(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            import cv2
            cv2.imwrite(str(root / "fixture.png"), self.frame)
            spec = {"protocol_id": "fixture-only", "training_source_groups": ["other-scene"], "images": [
                {"file": "fixture.png", "source_group": "test-scene", "context": "household_knife",
                 "alert_expected": False, "objects": [{"label": "knife", "bbox": [.1, .1, .2, .2]}]}]}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(spec))
            detector = MagicMock()
            detector.detect.return_value = [WeaponDetection("knife", .9, (.1, .1, .2, .2))]
            result = evaluate(manifest, detector)
            self.assertEqual(result["detection_metrics"]["knife"]["tp"], 1)
            self.assertEqual(result["negative_images_with_candidates"], {"household_knife": 1})
            self.assertFalse(result["production_qualified"])
            self.assertFalse(result["independence_verified"])
            self.assertEqual(len(result["manifest_sha256"]), 64)
            self.assertEqual(len(result["image_fingerprints"]), 1)
            self.assertEqual(result["latency_ms"]["samples"], 1)
            self.assertGreaterEqual(result["latency_ms"]["mean"], 0)
            self.assertIn("phone", result["missing_negative_contexts"])
            spec["training_source_groups"] = ["test-scene"]
            manifest.write_text(json.dumps(spec))
            with self.assertRaises(ValueError):
                evaluate(manifest, detector)

    def test_evaluation_unknown_class_never_passes_as_measured(self):
        item = WeaponDetection("firearm", .9, (.1, .1, .2, .2))
        counts = score_frame([item], [{"label": "knife", "bbox": list(item.bbox)}])
        self.assertEqual(counts[("firearm", "tp")], 0)
        self.assertEqual(counts[("firearm", "fp")], 1)
        self.assertEqual(counts[("knife", "fn")], 1)

    def test_evaluation_rejects_same_pixels_under_a_different_name_and_format(self):
        with TemporaryDirectory() as folder:
            import cv2
            root = Path(folder)
            cv2.imwrite(str(root / "one.png"), self.frame)
            cv2.imwrite(str(root / "two.bmp"), self.frame)
            spec = {"protocol_id": "synthetic-only", "training_source_groups": [], "images": [
                {"file": name, "source_group": "scene-" + name, "context": "clean",
                 "alert_expected": False, "objects": []} for name in ("one.png", "two.bmp")]}
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps(spec))
            detector = MagicMock()
            detector.detect.return_value = []
            with self.assertRaisesRegex(ValueError, "dupliquée après décodage"):
                evaluate(manifest, detector)
            self.assertEqual(detector.detect.call_count, 1)

    def test_report_changes_fingerprint_when_source_pixels_change(self):
        with TemporaryDirectory() as folder:
            import cv2
            root = Path(folder)
            image = root / "one.png"
            cv2.imwrite(str(image), self.frame)
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"protocol_id": "synthetic-only",
                "training_source_groups": [], "images": [{"file": "one.png",
                    "source_group": "scene", "context": "clean", "alert_expected": False,
                    "objects": []}]}))
            detector = MagicMock()
            detector.detect.return_value = []
            first = evaluate(manifest, detector)
            cv2.imwrite(str(image), np.full_like(self.frame, 100))
            second = evaluate(manifest, detector)
            self.assertEqual(first["manifest_sha256"], second["manifest_sha256"])
            self.assertNotEqual(first["image_fingerprints"], second["image_fingerprints"])
            self.assertFalse(second["production_qualified"])
