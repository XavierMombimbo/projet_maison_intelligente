"""Prepare a reviewable source snapshot, never publish or change the main checkout."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
SOURCE_ROOTS = {'accounts', 'homes', 'notifications', 'config', 'gateway', 'templates', 'static', 'tests_js', 'mobile', 'tools'}
ROOT_FILES = {'README.md', 'requirements.txt', 'manage.py', '.env.example', '.gitignore', 'render.yaml', 'Procfile', 'Dockerfile'}
EXTENSIONS = {'.py', '.html', '.css', '.js', '.cjs', '.mjs', '.json', '.yaml', '.yml', '.md', '.txt', '.ps1',
              '.dart', '.kt', '.kts', '.xml', '.gradle', '.properties', '.sh', '.bat', '.xcconfig', '.plist',
              '.swift', '.storyboard', '.pbxproj', '.xcscheme', '.xcworkspacedata', '.png', '.ico', '.svg',
              '.webmanifest', '.lock', '.ttf', '.otf', '.woff', '.woff2', '.wasm', '.onnx', '.jar', '.xcworkspacedata'}
EXCLUDED_PARTS = {'.git', '.codex', '.agents', '.idea', '.venv', '.dart_tool', '.gradle', 'build', '__pycache__', 'tmp', 'node_modules', 'Pods', 'ephemeral', '.symlinks'}
EXCLUDED_FILES = {'local.properties', 'Generated.xcconfig', 'flutter_export_environment.sh',
                  'cloudflared-sentinelle.yml', 'build_academic_report.py', 'export_docx_pdf.ps1'}
PRIVATE_DOCS = {'ETAT_ACTUEL.md', 'RELAIS_AGENTS.md'}
PATTERNS = {
    'private_key': re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider_token': re.compile(rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{25,}|AKIA[A-Z0-9]{16}|GOCSPX-[A-Za-z0-9_-]{20,})'),
    'service_account': re.compile(rb'"type"\s*:\s*"service_account"'),
}


def is_source(name):
    path = Path(name)
    if any(part in EXCLUDED_PARTS for part in path.parts) or path.name in EXCLUDED_FILES:
        return False
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    if len(path.parts) == 1:
        return path.name in ROOT_FILES
    if path.parts[:2] == ('docs', 'produit'):
        return path.suffix == '.md' and path.name not in PRIVATE_DOCS
    return path.parts[0] in SOURCE_ROOTS and (path.suffix in EXTENSIONS or path.name in {'gradlew', 'NOTICES', 'LICENSE', 'NOTICE', '.metadata', '.gitignore'})


def findings(data, secrets=()):
    result = [name for name, pattern in PATTERNS.items() if pattern.search(data)]
    if data.startswith(b'SQLite format 3\x00'):
        result.append('runtime_database')
    if any(value in data for value in secrets):
        result.append('known_local_secret')
    return result


def known_secrets():
    result = set()
    examples = set(value for value in dotenv_values(ROOT / '.env.example').values() if value)
    paths = [('development', ROOT / '.env'), ('production', Path(os.environ['LOCALAPPDATA']) / 'Sentinelle/production/current/.env.production')]
    for scope, path in paths:
        if path.is_file():
            for key, value in dotenv_values(path).items():
                if value and len(value) >= 16 and re.search(r'(SECRET|PEPPER|PASSWORD|TOKEN|ENCRYPTION_KEY|PRIVATE_KEY)', key):
                    if scope == 'development' and value in examples and (value.startswith('change-me') or not value.strip('A=')):
                        continue
                    result.add(value.encode('utf-8'))
    return result


def audit_history(secrets):
    objects = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=ROOT).decode().splitlines()
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    issues = []
    scanned = 0
    try:
        for entry in objects:
            oid, _, name = entry.partition(' ')
            if not name:
                continue
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().split()
            if len(header) != 3:
                raise RuntimeError('Objet Git illisible.')
            kind, size = header[1], int(header[2])
            data = process.stdout.read(size)
            process.stdout.read(1)
            if kind != 'blob':
                continue
            scanned += 1
            types = findings(data, secrets)
            if types:
                issues.append({'path': name, 'object': oid, 'types': types})
    finally:
        process.stdin.close()
        process.wait()
    return {'blobs_scanned': scanned, 'findings': issues}


def prepare(destination, *, notice_dir, propose_model_approval=False, authors_consent_confirmed=False):
    destination = Path(destination).resolve()
    if destination == ROOT or destination.is_relative_to(ROOT):
        raise ValueError('La publication doit etre preparee hors du depot principal.')
    destination.mkdir(parents=True, exist_ok=False)
    secrets = known_secrets()
    files = {}
    issues = []
    for directory, subdirs, names in os.walk(ROOT):
        base = Path(directory)
        subdirs[:] = [name for name in subdirs if name not in EXCLUDED_PARTS
                      and not (base / name).is_symlink()
                      and (base != ROOT or name in SOURCE_ROOTS | {'docs'})]
        if base == ROOT / 'docs':
            subdirs[:] = [name for name in subdirs if name == 'produit']
        for basename in names:
            path = base / basename
            name = path.relative_to(ROOT).as_posix()
            if not is_source(name) or path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                continue
            data = path.read_bytes()
            kinds = findings(data, secrets)
            if kinds:
                issues.append({'path': name, 'types': kinds})
            else:
                files[name] = data
    history = audit_history(secrets)
    report = {'status': 'blocked' if issues or history['findings'] else 'prepared',
              'source_findings': issues, 'history': history, 'candidate_files': len(files),
              'authors_consent_confirmed': authors_consent_confirmed, 'published': False}
    (destination / 'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if issues or history['findings']:
        print(json.dumps({'status': 'blocked', 'source_findings': issues, 'history_findings': history['findings']}))
        return 2
    if propose_model_approval:
        registry = json.loads(files['config/model_registry.json'])
        model = next(item for item in registry['models'] if item['id'] == 'yolo11n-320')
        from gateway.model_policy import MODEL_SHA256, MODEL_BYTES
        if model['sha256'] != MODEL_SHA256 or model['bytes'] != MODEL_BYTES:
            raise ValueError('Modele propose different de l artefact qualifie.')
        model['status'] = 'production_approved'
        model['classes'] = 'COCO-80; gateway currently decodes person, cat and dog'
        files['config/model_registry.json'] = (json.dumps(registry, indent=2) + '\n').encode()
    # Licenses remain a proposal until the authors' confirmation; nothing is pushed here.
    notices = Path(notice_dir)
    for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md'):
        files[name] = (notices / name).read_bytes()
    for path in (notices / 'licenses').glob('*'):
        files['licenses/' + path.name] = path.read_bytes()
    snapshot = destination / 'source'
    snapshot.mkdir()
    manifest = {}
    for name, data in files.items():
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest[name] = hashlib.sha256(data).hexdigest()
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    with zipfile.ZipFile(destination / 'source-review.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            archive.writestr('sentinelle-source/' + name, files[name])
    model_note = ('La proposition approuve le modele webcam ; le registre principal reste development_only jusqu a publication verifiee.\n'
                  if propose_model_approval else 'Le registre modele reste development_only.\n')
    consent_note = ('L accord des auteurs cites dans README a ete confirme avant cette preparation.\n\n'
                    if authors_consent_confirmed else
                    'Publication proposee sous AGPL-3.0, apres accord des auteurs.\n\n')
    summary = (
        '# Source preparee pour revue\n\n'
        + consent_note
        + f'{len(files)} fichiers ; {history["blobs_scanned"]} blobs Git historiques audites.\n'
        + 'Aucune correspondance aux secrets locaux connus ni aux motifs recherches.\n'
        + 'Ce scan automatise ne constitue pas une preuve exhaustive d absence de secret.\n\n'
        + 'Exclus : .env reels, bases, identites DPAPI, caches, journaux, captures, rapports academiques, '
        + 'passations privees et configuration locale Cloudflare. Les exemples de configuration et scripts de construction sont inclus.\n\n'
        + model_note
        + 'Aucun service permanent active et aucune publication effectuee.\n'
    )
    (destination / 'REVIEW.md').write_text(summary, encoding='utf-8')
    print(json.dumps({'status': 'prepared', 'files': len(files), 'history_blobs': history['blobs_scanned'],
                      'archive_bytes': (destination / 'source-review.zip').stat().st_size, 'published': False}))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--notice-dir', type=Path, required=True)
    parser.add_argument('--propose-model-approval', action='store_true')
    parser.add_argument('--authors-consent-confirmed', action='store_true')
    args = parser.parse_args()
    raise SystemExit(prepare(args.destination, notice_dir=args.notice_dir,
                             propose_model_approval=args.propose_model_approval,
                             authors_consent_confirmed=args.authors_consent_confirmed))
