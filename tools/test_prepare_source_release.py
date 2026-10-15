import unittest
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch
from tools.prepare_source_release import is_source, findings
from tools import prepare_source_release as release


class SourceReleaseTests(unittest.TestCase):
    def test_corresponding_sources_include_scripts_and_untracked_mobile_modules(self):
        for name in ('gateway/startup.py', 'mobile/lib/screens/gestures.dart',
                     'mobile/pubspec.lock', 'mobile/android/gradlew', 'static/mobile/assets/NOTICES',
                     'tools/run_local_production.ps1', '.env.example'):
            self.assertTrue(is_source(name), name)

    def test_runtime_secrets_reports_and_generated_local_configuration_are_excluded(self):
        for name in ('.env', '.env.production', 'db.sqlite3', 'tmp/recipe.credentials',
                     'docs/produit/ETAT_ACTUEL.md', 'docs/rapport_academique.docx',
                     'mobile/android/local.properties', 'tools/cloudflared-sentinelle.yml',
                     'gateway/__pycache__/credentials.pyc', 'mobile/tmp/token.json',
                     'mobile/build/app.json'):
            self.assertFalse(is_source(name), name)

    def test_known_credentials_and_runtime_database_are_blocked(self):
        self.assertEqual(findings(b'prefix-private-value-suffix', [b'private-value']), ['known_local_secret'])
        self.assertEqual(findings(b'SQLite format 3\x00more'), ['runtime_database'])
        self.assertEqual(findings(b'ordinary source file'), [])

    def test_snapshot_preserves_current_untracked_source_without_runtime_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = (base / 'project').resolve()
            (root / 'gateway').mkdir(parents=True)
            (root / 'gateway/untracked.py').write_bytes(b'new_code = True\n')
            (root / '.env').write_text('secret = do-not-publish\n')
            notices = base / 'notices'
            (notices / 'licenses').mkdir(parents=True)
            (notices / 'LICENSE').write_text('test license')
            (notices / 'THIRD_PARTY_NOTICES.md').write_text('test notice')
            destination = base / 'review'
            with patch.object(release, 'ROOT', root), patch.object(release, 'known_secrets', return_value=[]), \
                    patch.object(release, 'audit_history', return_value={'blobs_scanned': 1, 'findings': []}), patch('builtins.print'):
                self.assertEqual(release.prepare(destination, notice_dir=notices), 0)
            with zipfile.ZipFile(destination / 'source-review.zip') as archive:
                self.assertEqual(archive.read('sentinelle-source/gateway/untracked.py'), b'new_code = True\n')
                self.assertFalse(any(name.endswith('/.env') for name in archive.namelist()))
            manifest = json.loads((destination / 'manifest.json').read_text())
            self.assertEqual(set(manifest), {'gateway/untracked.py', 'LICENSE', 'THIRD_PARTY_NOTICES.md'})


if __name__ == '__main__':
    unittest.main()
