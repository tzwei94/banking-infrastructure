"""Exercise setup actions with external command boundaries mocked."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('setup_extended', SCRIPTS / 'setup.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.helper = module.Setup(Path(self.temp.name) / 'deployment')
        self.helper.settings.update(account='123456789012', domain='api.example.com', profile='test', region='ap-southeast-1')

    def test_dev_refresh_preserves_release_and_retention(self):
        self.assertTrue(hasattr(self.helper, 'write_dev_config'), 'Extended menu not implemented')
        root = self.helper.deployment / 'infra/environments/dev'
        root.mkdir(parents=True)
        values = {'region':'ap-southeast-1', 'state_bucket':'bucket', 'service_enabled':True, 'bootstrap_enabled':False, 'active_task_definition_arn':'arn:active', 'image':'real-digest', 'db_backup_retention_period':1}
        (root / 'dev.tfvars.json').write_text(json.dumps(values))
        self.helper.settings.update(state_bucket='bucket', state_kms_arn='key')
        self.helper.write_dev_config()
        result = json.loads((root / 'dev.tfvars.json').read_text())
        for key in ['service_enabled', 'active_task_definition_arn', 'image', 'db_backup_retention_period']:
            self.assertEqual(result[key], values[key])

    def test_dev_plan_blocks_runner_replacement(self):
        self.assertTrue(hasattr(self.helper, 'check_dev_changes'), 'Plan guard missing')
        with self.assertRaisesRegex(ValueError, 'replacement|Deletion'):
            self.helper.check_dev_changes({'resource_changes':[{'address':'module.runner.aws_instance.runner','mode':'managed','change':{'actions':['delete','create']}}]})

    def test_secret_write_never_places_value_in_arguments(self):
        self.assertTrue(hasattr(self.helper, 'put_secret'), 'Secret action missing')
        seen = []
        def aws(*args):
            seen.append(args)
            location = args[args.index('--secret-string') + 1]
            self.assertTrue(location.startswith('file://'))
            path = Path(location[7:])
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {'password':'hidden'})
            return {}
        with patch.object(self.helper, 'aws', side_effect=aws):
            self.helper.put_secret('arn:secret', {'password':'hidden'})
        self.assertNotIn('hidden', str(seen))
        self.assertFalse(Path(seen[0][-1][7:]).exists())

    def test_existing_remote_signing_key_is_not_rotated(self):
        self.assertTrue(hasattr(self.helper, 'signing_key'), 'Signing key action missing')
        with patch.object(self.helper, 'contract', return_value={'secret_arns':{'jwt-signing':'arn:key'}}), patch.object(self.helper, 'aws', return_value={'VersionIdsToStages':{'v':['AWSCURRENT']}}), patch.object(self.helper, 'run') as run:
            self.helper.signing_key()
        run.assert_not_called()

    def test_runner_offline_refuses_repair(self):
        self.assertTrue(hasattr(self.helper, 'online_runner'), 'Runner action missing')
        with patch.object(self.helper, 'runner_id', return_value='i-test'), patch.object(self.helper, 'aws', return_value={'InstanceInformationList':[]}):
            with self.assertRaisesRegex(ValueError, 'Online'):
                self.helper.online_runner()

    def test_missing_plugin_does_not_start_session(self):
        self.assertTrue(hasattr(self.helper, 'start_session'), 'Session action missing')
        with patch('shutil.which', return_value=None), patch.object(self.helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'plugin'):
                self.helper.start_session('i-test')
        run.assert_not_called()

    def test_ssm_failure_is_not_reported_as_success(self):
        self.assertTrue(hasattr(self.helper, 'remote'), 'SSM action missing')
        responses = [{'Command':{'CommandId':'cmd'}}, {'CommandInvocations':[{'Status':'Failed','CommandPlugins':[{'Output':'failed command'}]}]}]
        with patch.object(self.helper, 'aws', side_effect=responses):
            with self.assertRaisesRegex(ValueError, 'Failed'):
                self.helper.remote('i-test','false')

    def test_configuration_rejects_credentials_in_url(self):
        self.assertTrue(hasattr(self.helper, 'validate_url'), 'URL validation missing')
        with self.assertRaises(ValueError):
            self.helper.validate_url('https://user:password@example.com/path')

    def test_github_configuration_separates_publisher_variables_from_deploy_environment(self):
        contract = {'build_role_arn': 'arn:build', 'alloy_publish_role_arn': 'arn:alloy',
                    'deploy_role_arn': 'arn:deploy', 'ecr_repositories': {'banking-api': 'ecr/api', 'banking-alloy': 'ecr/alloy'}}
        with patch.object(self.helper, 'contract', return_value=contract), \
             patch.object(self.helper, 'repository_names', return_value={'app': 'example/app', 'deploy': 'example/infra'}), \
             patch.object(self.helper, 'dev_profile', return_value={'state_bucket': 'state'}), \
             patch('setup_actions.approved', side_effect=[True, False]), \
             patch.object(self.helper, 'run') as run:
            self.helper.github_configure()
        writes = [call.args[0] for call in run.call_args_list if call.args[0][:3] == ['gh', 'variable', 'set']]
        self.assertIn(['gh', 'variable', 'set', 'AWS_ALLOY_PUBLISH_ROLE_ARN', '--repo', 'example/infra', '--body', 'arn:alloy'], writes)
        self.assertIn(['gh', 'variable', 'set', 'ALLOY_REPOSITORY', '--repo', 'example/infra', '--body', 'ecr/alloy'], writes)
        self.assertIn(['gh', 'variable', 'set', 'AWS_REGION', '--repo', 'example/infra', '--body', 'ap-southeast-1'], writes)
        self.assertIn(['gh', 'variable', 'set', 'DEPLOYMENT_REPOSITORY', '--repo', 'example/app', '--body', 'example/infra'], writes)
        self.assertIn(['gh', 'variable', 'set', 'AWS_DEPLOY_ROLE_ARN', '--repo', 'example/infra', '--env', 'dev', '--body', 'arn:deploy'], writes)

if __name__ == '__main__':
    unittest.main()
