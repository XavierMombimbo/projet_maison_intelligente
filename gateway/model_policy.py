"""Deployment approval for the pinned webcam model."""
import hashlib
import json
import os
import re
from pathlib import Path

MODEL_SHA256 = "ed25687f7f3176a041bcdd0173501629afcaaddf37711f2294ced377f249fd65"
MODEL_BYTES = 10594049
ARCFACE_MODEL_ID = "insightface-arcface-buffalo-l"


class ModelApprovalError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
        from django.conf import settings
        # Load the configured dotenv before looking up the deployment revision.
        _ = settings.DEBUG
        source_revision = os.environ.get('SENTINELLE_SOURCE_REVISION', '')
    if not re.fullmatch(r'[0-9a-f]{40}', source_revision or ''):
        raise ModelApprovalError('Revision du code source publie absente ou invalide.')


def require_arcface_academic_approval(model_root, *, registry_path=None):
    """Verify the reviewed academic package before local face embedding."""
    root = Path(__file__).resolve().parents[1]
    try:
        registry = json.loads(Path(registry_path or root / 'config/model_registry.json').read_text(encoding='utf-8'))
        model = next(item for item in registry['models'] if item['id'] == ARCFACE_MODEL_ID)
        files = model['files']
    except (OSError, ValueError, KeyError, StopIteration, TypeError) as exc:
        raise ModelApprovalError('Registre ArcFace indisponible.') from exc
    if model.get('status') != 'academic_approved':
        raise ModelApprovalError('ArcFace n’est pas approuvé pour cette recette académique.')
    package = Path(model_root) / 'models' / 'buffalo_l'
    if not package.is_dir() or not isinstance(files, list) or not files:
        raise ModelApprovalError('Paquet ArcFace absent ou manifeste invalide.')
    for item in files:
        try:
            path = package / item['name']
            valid = path.is_file() and path.stat().st_size == item['bytes']
            valid = valid and _sha256_file(path) == item['sha256']
        except (KeyError, TypeError):
            raise ModelApprovalError('Manifeste ArcFace invalide.') from None
        if not valid:
            raise ModelApprovalError('Poids ArcFace absent ou empreinte invalide.')

