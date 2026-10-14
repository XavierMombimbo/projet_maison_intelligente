"""Deployment approval for the pinned webcam model."""
import json
import os
import re
from pathlib import Path

MODEL_SHA256 = "ed25687f7f3176a041bcdd0173501629afcaaddf37711f2294ced377f249fd65"
MODEL_BYTES = 10594049


class ModelApprovalError(ValueError):
    pass


def require_webcam_approval(*, registry_path=None, source_revision=None):
    root = Path(__file__).resolve().parents[1]
    try:
        registry = json.loads(Path(registry_path or root / 'config/model_registry.json').read_text(encoding='utf-8'))
        model = next(item for item in registry['models'] if item['id'] == 'yolo11n-320')
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        raise ModelApprovalError('Registre du modele indisponible.') from exc
    if model.get('status') != 'production_approved':
        raise ModelApprovalError('Modele non approuve pour un service permanent.')
    if (model.get('sha256') != MODEL_SHA256 or model.get('bytes') != MODEL_BYTES
            or model.get('artifact') != 'static/vendor/yolo/yolo11n.onnx'):
        raise ModelApprovalError('Artefact approuve different du modele webcam integre.')
    if source_revision is None:
        from django.conf import settings
        # Load the configured dotenv before looking up the deployment revision.
        _ = settings.DEBUG
        source_revision = os.environ.get('SENTINELLE_SOURCE_REVISION', '')
    if not re.fullmatch(r'[0-9a-f]{40}', source_revision or ''):
        raise ModelApprovalError('Revision du code source publie absente ou invalide.')

