import hashlib
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class ModelRegistryTests(SimpleTestCase):
    def test_registry_is_complete_and_local_artifacts_match(self):
        registry_path = Path(settings.BASE_DIR) / "config" / "model_registry.json"
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
        models = registry["models"]
        self.assertEqual(len({model["id"] for model in models}), len(models))

        required = {
            "id",
            "status",
            "task",
            "version",
            "source",
            "license",
            "classes",
            "artifact",
            "bytes",
            "sha256",
            "hardware",
        }
        for model in models:
            self.assertTrue(required.issubset(model), model["id"])
            self.assertLessEqual(set(model) - required, {"config"}, model["id"])
            if model["artifact"] is None:
                self.assertIsNone(model["bytes"])
                self.assertIsNone(model["sha256"])
                self.assertNotEqual(model["status"], "production_approved")
                continue

            artifact = Path(settings.BASE_DIR) / model["artifact"]
            payload = artifact.read_bytes()
            self.assertEqual(len(payload), model["bytes"], model["id"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), model["sha256"], model["id"])
