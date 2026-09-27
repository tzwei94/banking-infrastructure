"""Setup workflow tests; AWS and Terraform processes are replaced at the boundary."""
import importlib.util
import json
from pathlib import Path
import tempfile
import sys
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / 'scripts/setup.py'
sys.path.insert(0, str(SCRIPT.parent))

class SetupTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'The setup menu helper has not been implemented')
        spec = importlib.util.spec_from_file_location('setup_helper', SCRIPT)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.helper = self.module.Setup(Path(self.temp.name))
        self.helper.settings.update(profile='test', region='ap-southeast-1', account='123456789012', domain='api.example.com')

    def test_settings_persist_privately_without_credentials(self):
        self.helper.save()
        path = self.helper.settings_path
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.module.Setup(Path(self.temp.name)).settings['profile'], 'test')
        self.assertNotIn('credentials', json.loads(path.read_text()))

    def test_certificate_reuses_existing_issued_certificate(self):
        calls = []
        def aws(*args):
            calls.append(args)
            if args[1] == 'list-certificates':
                return {'CertificateSummaryList': [{'CertificateArn': 'arn:existing', 'DomainName': 'api.example.com'}]}
            return {'Certificate': {'DomainName': 'api.example.com', 'Status': 'ISSUED', 'DomainValidationOptions': []}}
        with patch.object(self.helper, 'aws', side_effect=aws), patch('builtins.input', side_effect=AssertionError('Should reuse without prompting')):
            self.helper.certificate()
        self.assertEqual(self.helper.settings['certificate_arn'], 'arn:existing')
        self.assertFalse(any('request-certificate' in c for c in calls))

    def test_account_change_is_rejected(self):
        with patch.object(self.helper, 'aws', return_value={'Account': '999999999999', 'Arn': 'different'}):
            with self.assertRaisesRegex(ValueError, 'account'):
                self.helper.identity()

    def test_apply_without_reviewed_plan_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'plan'):
            self.helper.apply('backend')

    def test_apply_rejects_tampered_plan(self):
        self.helper.private.mkdir(parents=True)
        plan = self.helper.private / 'backend.tfplan'
        plan.write_bytes(b'original')
        self.helper.record_plan('backend', plan)
        plan.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'plan'):
            self.helper.apply('backend')

    def test_apply_cancellation_does_not_execute_terraform(self):
        self.helper.private.mkdir(parents=True)
        plan = self.helper.private / 'backend.tfplan'
        plan.write_bytes(b'original')
        self.helper.record_plan('backend', plan)
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'tf') as tf, patch('builtins.input', return_value='no'):
            self.helper.apply('backend')
        tf.assert_called_once_with('backend', 'show', str(plan))

    def test_outputs_are_loaded(self):
        with patch.object(self.helper, 'tf', return_value={'bucket': {'value': 'my-bucket'}, 'kms_key_arn': {'value': 'my-key'}}):
            self.helper.outputs('backend')
        self.assertEqual(self.helper.settings['state_bucket'], 'my-bucket')
        self.assertEqual(self.helper.settings['state_kms_arn'], 'my-key')

    def test_aws_environment_uses_selected_profile_without_local_endpoint(self):
        with patch.dict('os.environ', {'AWS_ACCESS_KEY_ID': 'stale', 'AWS_ENDPOINT_URL': 'http://localhost:4566', 'TF_CLI_ARGS_apply': '-destroy'}):
            env = self.helper.env()
        self.assertNotIn('AWS_ACCESS_KEY_ID', env)
        self.assertNotIn('AWS_ENDPOINT_URL', env)
        self.assertNotIn('TF_CLI_ARGS_apply', env)
        self.assertEqual(env['AWS_PROFILE'], 'test')

    def test_oidc_already_tracked_is_not_imported(self):
        arn = 'arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com'
        state = {'values': {'root_module': {'resources': [{'address': 'aws_iam_openid_connect_provider.github', 'values': {'arn': arn}}]}}}
        with patch.object(self.helper, 'aws', return_value={'OpenIDConnectProviderList': [{'Arn': arn}]}), patch.object(self.helper, 'tf', side_effect=[None, state]) as tf, patch.object(self.helper, 'outputs'):
            self.helper.oidc_import()
        self.assertFalse(any('import' in call.args for call in tf.call_args_list))

    def test_failed_apply_consumes_saved_plan(self):
        self.helper.private.mkdir(parents=True)
        plan = self.helper.private / 'backend.tfplan'
        plan.write_bytes(b'original')
        self.helper.record_plan('backend', plan)
        with patch.object(self.helper, 'identity'), patch.object(self.helper, 'tf', side_effect=[None, OSError('failed')]), patch('builtins.input', return_value='yes'):
            with self.assertRaises(OSError):
                self.helper.apply('backend')
        self.assertNotIn('backend', self.helper.settings['plans'])

    def test_discovery_filters_numeric_version_prefix_as_string(self):
        results = [
            {'Parameter': {'Value': 'ami-test'}},
            {'Images': [{'ImageId': 'ami-test', 'Name': 'al2023', 'Architecture': 'x86_64', 'State': 'available', 'OwnerId': 'amazon'}]},
            [{'Type': 't3.small'}],
            {'OrderableDBInstanceOptions': [{'EngineVersion': '17.11', 'StorageType': 'gp3'}, {'EngineVersion': '16.1', 'StorageType': 'gp3'}]},
        ]
        with patch.object(self.helper, 'aws', side_effect=results), patch('builtins.print') as output:
            self.helper.discover()
        self.assertEqual(self.helper.settings['runner_ami_id'], 'ami-test')
        self.assertIn(('PostgreSQL 17.11: gp3',), [call.args for call in output.call_args_list])
        self.assertNotIn(('PostgreSQL 16.1: gp3',), [call.args for call in output.call_args_list])

    def test_terminal_certificate_can_be_replaced(self):
        self.helper.settings['certificate_arn'] = 'arn:expired'
        responses = [
            {'Certificate': {'DomainName': 'api.example.com', 'Status': 'EXPIRED'}},
            {'CertificateSummaryList': []},
            {'CertificateArn': 'arn:new'},
            {'Certificate': {'DomainName': 'api.example.com', 'Status': 'PENDING_VALIDATION'}},
        ]
        with patch.object(self.helper, 'aws', side_effect=responses), patch('builtins.input', return_value='yes'):
            self.helper.certificate()
        self.assertEqual(self.helper.settings['certificate_arn'], 'arn:new')

    def test_existing_dev_profile_keeps_release_fields(self):
        folder = self.helper.deployment / 'infra/environments/dev'
        folder.mkdir(parents=True)
        original = {'service_enabled': True, 'bootstrap_enabled': False, 'active_task_definition_arn': 'live-task', 'image': 'real-digest', 'db_backup_retention_period': 1, 'region': 'ap-southeast-1'}
        (folder / 'dev.tfvars.json').write_text(json.dumps(original))
        self.helper.settings.update(alarm_email='ops@example.com')
        self.helper.write_dev_config()
        result = json.loads((folder / 'dev.tfvars.json').read_text())
        self.assertTrue(result['service_enabled'])
        self.assertEqual(result['active_task_definition_arn'], 'live-task')
        self.assertEqual(result['db_backup_retention_period'], 1)
        self.assertEqual(result['image'], 'real-digest')

    def test_dev_plan_replacement_is_blocked(self):
        plan = {'resource_changes': [{'mode': 'managed', 'address': 'module.runner.aws_instance.runner', 'change': {'actions': ['delete', 'create']}}]}
        with self.assertRaisesRegex(ValueError, 'replacement'):
            self.helper.check_dev_changes(plan)

    def test_secret_value_only_goes_into_private_temporary_file(self):
        paths = []
        def aws(*args):
            self.assertNotIn('test-password', ' '.join(args))
            path = Path(args[args.index('--secret-string') + 1].removeprefix('file://'))
            paths.append(path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())['password'], 'test-password')
            return {}
        with patch.object(self.helper, 'aws', side_effect=aws):
            self.helper.put_secret('arn:test', {'password': 'test-password'})
        self.assertFalse(paths[0].exists())
        self.assertNotIn('test-password', json.dumps(self.helper.settings))

    def test_existing_signing_secret_is_not_overwritten(self):
        with patch.object(self.helper, 'contract', return_value={'secret_arns': {'jwt-signing': 'arn:test'}}), patch.object(self.helper, 'aws', return_value={'VersionIdsToStages': {'version': ['AWSCURRENT']}}), patch.object(self.helper, 'put_secret') as put, patch.object(self.helper, 'run') as run:
            self.helper.signing_key()
        put.assert_not_called()
        run.assert_not_called()

    def test_runner_target_must_match_tag(self):
        response = {'Reservations': [{'Instances': [{'InstanceId': 'i-test', 'State': {'Name': 'running'}, 'Tags': [{'Key': 'Name', 'Value': 'other'}]}]}]}
        with patch.object(self.helper, 'contract', return_value={'runner_instance_id': 'i-test'}), patch.object(self.helper, 'aws', return_value=response):
            with self.assertRaisesRegex(ValueError, 'runner'):
                self.helper.runner_id()

    def test_cancelled_repair_sends_no_command(self):
        with patch.object(self.helper, 'online_runner', return_value='i-test'), patch('builtins.input', return_value='no'), patch.object(self.helper, 'remote') as remote:
            self.helper.repair_runner()
        remote.assert_not_called()

    def test_ssm_poll_preserves_failed_status(self):
        result = {'CommandInvocations': [{'Status': 'Failed', 'CommandPlugins': [{'Output': 'package failed'}]}]}
        with patch.object(self.helper, 'aws', return_value=result), patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'Failed'):
                self.helper.command_result('cmd', 'i-test')

    def test_http_503_is_not_reported_as_deployment_success(self):
        with patch.object(self.helper, 'contract', return_value={'alb_dns_name': 'test.elb.amazonaws.com', 'alarm_topic_arn': 'arn:topic'}), patch.object(self.helper, 'run', return_value='503'), patch.object(self.helper, 'aws', return_value={'Subscriptions': []}), patch('builtins.input', return_value='yes'), patch('builtins.print') as out:
            self.helper.dns_check()
        text = ' '.join(str(c.args) for c in out.call_args_list)
        self.assertIn('not ready', text)

    def test_dev_apply_rejects_changed_input_files(self):
        with patch.object(self.helper, 'dev_fingerprint', return_value={'profile': 'new'}):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.helper.check_dev_plan({'inputs': {'profile': 'old'}}, Path('plan'))

    def test_registration_upload_never_contains_token(self):
        self.helper.settings['runner_command'] = {'id': 'cmd', 'instance': 'i-test'}
        script = self.helper.deployment / 'deploy/provisioning/register-runner.sh'
        script.parent.mkdir(parents=True)
        script.write_text('read -rsp token token\n')
        replies = ['app', '2.329.0', 'a'*64, 'yes']
        with patch.object(self.helper, 'repository_names', return_value={'app': 'owner/app', 'deploy': 'owner/deploy'}), patch.object(self.helper, 'online_runner', return_value='i-test'), patch('setup_actions.shutil.which', return_value='/plugin'), patch.object(self.helper, 'remote_busy', return_value=False), patch.object(self.helper, 'remote') as remote, patch.object(self.helper, 'aws', return_value={'CommandInvocations': [{'Status': 'Success'}]}), patch.object(self.helper, 'start_session') as session, patch('builtins.input', side_effect=replies):
            self.helper.registration()
        self.assertIn('register-runner.sh owner/app app 2.329.0', session.call_args.args[1])
        self.assertIn('base64 -d', ' '.join(remote.call_args.args[1]))

    def test_new_profile_requires_bootstrap_values(self):
        root = self.helper.dev_root
        root.mkdir(parents=True)
        (root / 'dev.tfvars.json.example').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Missing'):
            self.helper.write_dev_config()
        self.assertFalse((root / 'dev.tfvars.json').exists())

    def test_pending_ssm_command_does_not_report_success(self):
        with patch.object(self.helper, 'aws', return_value={'CommandInvocations': [{'Status': 'InProgress'}]}), patch('setup_actions.time.sleep'), patch('builtins.print') as out:
            self.helper.command_result('cmd', 'i-test')
        self.assertIn('do not resend', ' '.join(str(c.args) for c in out.call_args_list))

    def test_existing_secret_can_be_kept_without_password_prompt(self):
        with patch.object(self.helper, 'contract', return_value={'secret_arns': {'telemetry': 'arn:test'}}), patch.object(self.helper, 'aws', return_value={'VersionIdsToStages': {'v': ['AWSCURRENT']}}), patch('builtins.input', side_effect=['1', 'no']), patch('setup_actions.getpass.getpass') as password, patch.object(self.helper, 'put_secret') as put:
            self.helper.credentials_menu()
        password.assert_not_called()
        put.assert_not_called()

    def test_menu_progress_and_exit_are_usable(self):
        with patch('builtins.input', side_effect=['15', '0']), patch('builtins.print'):
            self.helper.menu()

    def test_diagnosis_cannot_overwrite_running_repair(self):
        original = {'id': 'running-repair', 'instance': 'i-test'}
        self.helper.settings['runner_command'] = original.copy()
        with patch.object(self.helper, 'remote_busy', return_value=True), patch.object(self.helper, 'aws') as aws:
            with self.assertRaisesRegex(ValueError, 'still active'):
                self.helper.remote('i-test', ['cloud-init status'])
        aws.assert_not_called()
        self.assertEqual(self.helper.settings['runner_command'], original)

    def test_github_rejects_environment_mismatched_with_workflow(self):
        with patch.object(self.helper, 'contract', return_value={}), patch.object(self.helper, 'repository_names', return_value={'app': 'owner/app', 'deploy': 'owner/deployment'}), patch.object(self.helper, 'dev_profile', return_value={'github_environment': 'production'}), patch.object(self.helper, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'dev'):
                self.helper.github_configure()
        run.assert_not_called()

if __name__ == '__main__':
    unittest.main()
