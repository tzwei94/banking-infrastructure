import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
spec = importlib.util.spec_from_file_location('bootstrap_database', Path(__file__).parents[1] / 'scripts/bootstrap-database.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeRelease:
    root = '/dev'
    def __init__(self, fail=None):
        self.events = []
        self.fail = fail
    def manifest(self):
        if self.fail == 'manifest':
            raise RuntimeError('manifest unavailable')
    def verify_image(self):
        pass
    def initialize(self):
        pass
    def command(self, args):
        return '{"active_task_definition_arn":{"value":"active"}}' if self.fail == 'active' else '{}'
    def apply(self, active, **kwargs):
        self.events.append(kwargs)
        return {'bootstrap_arn': {'value': 'bootstrap'}, 'run_task': {'value': {}}}
    def run_task(self, *args):
        if self.fail == 'database':
            raise RuntimeError('database failed')


class BootstrapTests(unittest.TestCase):
    def test_failed_database_task_still_revokes_bootstrap_capability(self):
        release = FakeRelease('database')
        with self.assertRaises(RuntimeError):
            module.bootstrap(release)
        self.assertEqual(release.events, [
            {'bootstrap_enabled': True, 'allow_bootstrap_changes': True},
            {'allow_bootstrap_changes': True},
        ])
    def test_failed_preflight_or_active_service_never_mutates(self):
        for reason in ['manifest', 'active']:
            with self.subTest(reason=reason):
                release = FakeRelease(reason)
                with self.assertRaises(RuntimeError):
                    module.bootstrap(release)
                self.assertEqual(release.events, [])
