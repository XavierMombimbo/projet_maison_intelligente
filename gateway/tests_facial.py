import unittest
from types import SimpleNamespace

import numpy as np

from .facial import (
    ARCFACE_TEMPLATE_FORMAT,
    ArcFaceEmbedder,
    FaceQualityError,
    compare_embedding,
    deserialize_embedding,
    serialize_embedding,
)


def vector(value=1.0):
    result = np.zeros(512, dtype=np.float32)
    result[0] = value
    return result


class ArcFaceTemplateTests(unittest.TestCase):
    def test_template_round_trip_is_normalized(self):
        template = serialize_embedding(vector(4.0))
        self.assertEqual(len(template), 2048)
        self.assertAlmostEqual(float(deserialize_embedding(template)[0]), 1.0)

    def test_matching_and_unknown_are_distinct(self):
        profiles = [{"profile_id": "profile-a", "format": ARCFACE_TEMPLATE_FORMAT,
                     "template": serialize_embedding(vector())}]
        matched = compare_embedding(vector(2.0), profiles)
        unknown = compare_embedding(np.eye(1, 512, 1, dtype=np.float32)[0], profiles)
        self.assertEqual(matched.state, "matched")
        self.assertEqual(matched.profile_id, "profile-a")
        self.assertEqual(unknown.state, "unknown")
        self.assertIsNone(unknown.profile_id)

    def test_serialized_query_from_adapter_matches_template(self):
        template = serialize_embedding(vector())
        result = compare_embedding(
            template,
            [{"profile_id": "profile-a", "format": ARCFACE_TEMPLATE_FORMAT, "template": template}],
        )
        self.assertEqual(result.state, "matched")

    def test_missing_compatible_template_is_unavailable(self):
        result = compare_embedding(vector(), [{"profile_id": "profile-a", "format": "other", "template": b""}])
        self.assertEqual(result.state, "unavailable")


class ArcFaceAdapterTests(unittest.TestCase):
    def test_adapter_requires_one_confident_face(self):
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        app = SimpleNamespace(get=lambda image: [SimpleNamespace(det_score=0.95, embedding=vector())])
        self.assertEqual(len(ArcFaceEmbedder(app).embedding_from_bgr(frame)), 2048)

        no_face = SimpleNamespace(get=lambda image: [])
        with self.assertRaises(FaceQualityError):
            ArcFaceEmbedder(no_face).embedding_from_bgr(frame)

        two_faces = SimpleNamespace(get=lambda image: [
            SimpleNamespace(det_score=0.95, embedding=vector()),
            SimpleNamespace(det_score=0.95, embedding=vector()),
        ])
        with self.assertRaises(FaceQualityError):
            ArcFaceEmbedder(two_faces).embedding_from_bgr(frame)
