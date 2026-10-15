import hashlib
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from .model_policy import MODEL_BYTES, MODEL_SHA256, ModelApprovalError, require_webcam_approval
from .client import GatewayAPIError
from .startup import StartupError, read_configuration, verify_release, write_status, launch, main


class StartupTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = {'id': 'yolo11n-320', 'status': 'production_approved',
                      'sha256': MODEL_SHA256, 'bytes': MODEL_BYTES,
                      'artifact': 'static/vendor/yolo/yolo11n.onnx'}
        self.registry = self.root / 'registry.json'
        self.registry.write_text(json.dumps({'models': [self.model]}))

    def test_unapproved_model_and_missing_source_revision_are_refused(self):
        for revision in ('', 'abc', 'A' * 40):
            with self.assertRaises(ModelApprovalError):
                require_webcam_approval(registry_path=self.registry, source_revision=revision)
        self.model['status'] = 'development_only'
        self.registry.write_text(json.dumps({'models': [self.model]}))
        with self.assertRaises(ModelApprovalError):
            require_webcam_approval(registry_path=self.registry, source_revision='a' * 40)

    def test_approved_source_cannot_substitute_another_artifact(self):
        require_webcam_approval(registry_path=self.registry, source_revision='a' * 40)
        self.model['sha256'] = 'b' * 64
        self.registry.write_text(json.dumps({'models': [self.model]}))
        with self.assertRaises(ModelApprovalError):
            require_webcam_approval(registry_path=self.registry, source_revision='a' * 40)

    def make_receipt(self):
        files = {}
        for name in ('gateway/webcam.py', 'gateway/startup.py', 'config/settings.py', 'config/model_registry.json'):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(name)
            files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt = {'revision': 'a' * 40, 'anonymous_archive_verified': True, 'files': files}
        target = self.root / 'receipt.json'
        target.write_text(json.dumps(receipt))
        return target, receipt

    def test_unpublished_or_modified_source_is_refused(self):
        path, receipt = self.make_receipt()
        self.assertEqual(verify_release(path, self.root), 'a' * 40)
        (self.root / 'gateway/webcam.py').write_text('changed locally')
        with self.assertRaises(StartupError):
            verify_release(path, self.root)

    def test_receipt_rejects_traversal_and_incomplete_manifest(self):
        path, receipt = self.make_receipt()
        receipt['files']['../escape.py'] = 'b' * 64
        path.write_text(json.dumps(receipt))
        with self.assertRaises(StartupError):
            verify_release(path, self.root)
        del receipt['files']['../escape.py']
        del receipt['files']['config/settings.py']
        path.write_text(json.dumps(receipt))
        with self.assertRaises(StartupError):
            verify_release(path, self.root)

    def configuration(self):
        return {'credentials_file': str(self.root / 'credentials'), 'cache_root': str(self.root / 'cache'),
                'env_file': '', 'status_file': str(self.root / 'status.json'),
                'mode': 'webcam', 'index': 0, 'recipe': True}

    def test_permanent_configuration_cannot_bypass_release_gate(self):
        config = self.configuration()
        path = self.root / 'config.json'
        path.write_text(json.dumps(config))
        self.assertTrue(read_configuration(path)['recipe'])
        config['recipe'] = False
        path.write_text(json.dumps(config))
        with self.assertRaises(StartupError):
            read_configuration(path)
        config['recipe'] = True
        config['cache_root'] = '../outside'
        path.write_text(json.dumps(config))
        with self.assertRaises(StartupError):
            read_configuration(path)

    def test_status_does_not_contain_credentials_or_configuration(self):
        config = self.configuration()
        write_status(config, 'running')
        result = json.loads(Path(config['status_file']).read_text())
        self.assertEqual(set(result), {'state', 'pid', 'updated_at'})

    @patch('gateway.startup.load_credentials', return_value=object())
    @patch('gateway.startup.watch_webcam', return_value=0)
    def test_recipe_is_once_and_isolated_from_production(self, watch, credentials):
        config = self.configuration()
        with patch.dict('os.environ', {}, clear=False):
            self.assertEqual(launch(config), 0)
            import os
            self.assertEqual(os.environ['FCM_ENABLED'], '0')
            self.assertEqual(os.environ['REDIS_URL'], '')
        options = watch.call_args.kwargs
        self.assertTrue(options['once'])
        self.assertTrue(options['allow_development_model'])
        schedule = options['schedule_cache_factory']('00000000-0000-0000-0000-000000000001', 'key')
        self.assertEqual(schedule.path.parent, Path(config['cache_root']) / 'schedules')
        self.assertEqual(json.loads(Path(config['status_file']).read_text())['state'], 'completed_recipe')

    @patch('gateway.startup.load_credentials', return_value=object())
    @patch('gateway.startup.watch_webcam', side_effect=[GatewayAPIError('offline'), 0])
    def test_recipe_waits_for_local_server_at_startup(self, watch, credentials):
        config = self.configuration()
        from unittest.mock import Mock
        wait = Mock()
        with patch('builtins.print'):
            self.assertEqual(launch(config, sleep=wait), 0)
        self.assertEqual(wait.call_args_list, [((10,),)])
        self.assertEqual(watch.call_count, 2)
        self.assertEqual(json.loads(Path(config['status_file']).read_text())['state'], 'completed_recipe')

    @patch('gateway.startup.launch', side_effect=StartupError('sensitive-content'))
    def test_fatal_failure_returns_terminal_code_without_logging_secret(self, launch):
        config = self.configuration()
        path = self.root / 'config.json'
        path.write_text(json.dumps(config))
        with patch('builtins.print') as output:
            self.assertEqual(main(['--config', str(path)]), 2)
        self.assertNotIn('sensitive-content', str(output.call_args))
        self.assertEqual(json.loads(Path(config['status_file']).read_text())['state'], 'configuration_refused')

    @patch('gateway.startup.launch', side_effect=GatewayAPIError('sensitive-content'))
    def test_temporary_server_failure_is_reported_without_leaking_detail(self, launch):
        config = self.configuration()
        path = self.root / 'config.json'
        path.write_text(json.dumps(config))
        with patch('builtins.print') as output:
            self.assertEqual(main(['--config', str(path)]), 1)
        self.assertNotIn('sensitive-content', str(output.call_args))
        self.assertEqual(json.loads(Path(config['status_file']).read_text())['state'], 'unavailable')
