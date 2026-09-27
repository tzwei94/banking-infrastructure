"""Destructive workflow tests: all external operations are mocked."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('destroy_setup', SCRIPTS / 'setup.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def plan(actions, before=None, after=None, address='module.rds.aws_db_instance.database'):
    return {'resource_changes': [{'mode': 'managed', 'address': address,
        'change': {'actions': actions, 'before': before or {}, 'after': after}}]}


class DestroyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.helper = module.Setup(Path(self.temp.name) / 'deployment')
        self.helper.settings.update(account='123456789012', region='ap-southeast-1')
        self.helper.save()

    def test_destroy_rejects_replacement(self):
        with self.assertRaisesRegex(ValueError, 'delete-only'):
            self.helper.validate_teardown(plan(['delete', 'create']), 'destroy')

    def test_destroy_requires_protection_disabled(self):
        with self.assertRaisesRegex(ValueError, 'protection'):
            self.helper.validate_teardown(plan(['delete'], {'deletion_protection': True}), 'destroy')

    def test_destroy_requires_final_snapshot(self):
        with self.assertRaisesRegex(ValueError, 'snapshot'):
            self.helper.validate_teardown(plan(['delete'], {'skip_final_snapshot': True}), 'destroy')

    def test_protection_plan_rejects_other_changes(self):
        before = {'deletion_protection': True, 'instance_class': 'db.t4g.micro'}
        after = {'deletion_protection': False, 'instance_class': 'db.t4g.small'}
        with self.assertRaisesRegex(ValueError, 'protection-only'):
            self.helper.validate_teardown(plan(['update'], before, after), 'unprotect')

    def test_protection_plan_accepts_only_protection_change(self):
        self.helper.validate_teardown(plan(['update'], {'deletion_protection': True}, {'deletion_protection': False}), 'unprotect')

    def saved(self):
        path = self.helper.private / 'dev-destroy.tfplan'
        path.write_bytes(b'reviewed plan')
        self.helper.record_plan('dev-destroy', path)
        self.helper.settings['plans']['dev-destroy']['inputs'] = {'config': 'same'}
        return path

    def test_cancel_does_not_apply(self):
        self.saved()
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'dev_fingerprint', return_value={'config': 'same'}), patch.object(self.helper, 'validate_teardown'), patch.object(self.helper, 'tf') as tf, patch('builtins.input', return_value='no'):
            self.helper.teardown_apply('destroy')
        self.assertFalse(any(c.args[1] == 'apply' for c in tf.call_args_list))
        self.assertIn('dev-destroy', self.helper.settings['plans'])

    def test_changed_plan_is_rejected(self):
        self.saved().write_bytes(b'changed')
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'tf') as tf:
            with self.assertRaisesRegex(ValueError, 'matching'):
                self.helper.teardown_apply('destroy')
        tf.assert_not_called()

    def test_failed_apply_consumes_plan(self):
        self.saved()
        def tf(root, command, *args, **kwargs):
            self.assertEqual(root, 'dev')
            if command == 'apply':
                raise OSError('partial apply')
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'dev_fingerprint', return_value={'config': 'same'}), patch.object(self.helper, 'validate_teardown'), patch.object(self.helper, 'tf', side_effect=tf), patch('builtins.input', return_value='DESTROY dev 123456789012 ap-southeast-1'):
            with self.assertRaises(OSError):
                self.helper.teardown_apply('destroy')
        self.assertNotIn('dev-destroy', self.helper.settings['plans'])

    def test_nonempty_ecr_blocks_before_apply(self):
        data = plan(['delete'], {'name': 'banking-api'}, address='module.ecr.aws_ecr_repository.this["api"]')
        data['resource_changes'][0]['type'] = 'aws_ecr_repository'
        with patch.object(self.helper, 'aws', return_value={'imageIds': [{'imageDigest': 'sha256:test'}]}):
            with self.assertRaisesRegex(ValueError, 'contains images'):
                self.helper.validate_teardown(data, 'destroy')

    def test_configuration_change_rejects_saved_plan(self):
        self.saved()
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'dev_fingerprint', return_value={'config': 'changed'}), patch.object(self.helper, 'tf') as tf:
            with self.assertRaisesRegex(ValueError, 'Configuration changed'):
                self.helper.teardown_apply('destroy')
        tf.assert_not_called()

    def test_plan_only_uses_dev_destroy_and_never_applies(self):
        profile = {'region': 'ap-southeast-1', 'state_bucket': 'bucket', 'state_kms_arn': 'key'}
        self.helper.settings.update(profile)
        calls = []
        def tf(root, command, *args, **kwargs):
            calls.append((root, command, args))
            self.assertEqual(root, 'dev')
            if command == 'plan':
                self.assertIn('-destroy', args)
                Path(next(a[5:] for a in args if a.startswith('-out='))).write_bytes(b'plan')
            return {'resource_changes': []}
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'dev_profile', return_value=profile), patch.object(self.helper, 'dev_fingerprint', return_value={}), patch.object(self.helper, 'tf', side_effect=tf):
            self.helper.teardown_plan('destroy')
        self.assertFalse(any(command == 'apply' for _, command, _ in calls))
        self.assertIn('dev-destroy', self.helper.settings['plans'])


if __name__ == '__main__':
    unittest.main()
