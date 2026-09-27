import importlib.util,json,tempfile,unittest,subprocess
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('release',Path(__file__).parents[1]/'scripts/release.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
class Fake(module.Release):
    def __init__(self,fail=None): self.events=[];self.fail=fail;self.values={'source_sha':'a'*40,'image':'registry/api@sha256:'+'b'*64,'alloy_image':'registry/alloy@sha256:'+'c'*64}
    def manifest(self): return {'active_task_definition_arn':'old'}
    def verify_image(self): self.events.append('verify')
    def initialize(self): self.events.append('init')
    def apply(self,active):
        self.events.append(('apply',active)); return {k:{'value':v} for k,v in {'candidate_app_arn':'candidate','candidate_migration_arn':'migration','run_task':{}}.items()}
    def run_task(self,*args):
        self.events.append('migrate')
        if self.fail=='migration': raise RuntimeError('migration')
        return '1'
    def healthy(self,active,*args):
        self.events.append(('health',active))
        if active=='candidate' and self.fail=='health': raise RuntimeError('health')
    def record(self,manifest): self.events.append(('record',manifest['active_task_definition_arn']))
class ReleaseTests(unittest.TestCase):
    def test_terraform_failure_preserves_private_log_and_original_error(self):
        release = object.__new__(module.Release)
        error = subprocess.CalledProcessError(1, ['terraform'], output='plan output', stderr='underlying error')
        with tempfile.TemporaryDirectory() as directory:
            fake_script = Path(directory) / 'deploy/scripts/release.py'
            with patch.object(module, '__file__', str(fake_script)), patch.object(module.subprocess, 'run', side_effect=error), patch('builtins.print') as output:
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    release.command(['terraform', 'plan'])
            self.assertIs(raised.exception, error)
            logs = list((Path(directory) / '.private/setup/diagnostics').glob('*.log'))
            self.assertEqual(len(logs), 1)
            self.assertIn('underlying error', logs[0].read_text())
            self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
            self.assertNotIn('underlying error', str(output.call_args))

    def test_run_task_surfaces_service_error_without_debug_output(self):
        release = object.__new__(module.Release)
        error = subprocess.CalledProcessError(254, ['aws'], stderr='DEBUG private details\naws: [ERROR]: An error occurred (ClientException) when calling the RunTask operation: Account is blocked\nDEBUG more private details')
        with patch.object(release, 'aws', side_effect=error), self.assertRaises(RuntimeError) as raised:
            release.run_task('task', {'cluster':'cluster','subnets':['subnet'],'security_groups':['sg']})
        self.assertIn('Account is blocked', str(raised.exception))
        self.assertNotIn('private', str(raised.exception))

    def test_run_task_unknown_error_does_not_dump_stderr(self):
        release = object.__new__(module.Release)
        with patch.object(release, 'aws', side_effect=subprocess.CalledProcessError(254, ['aws'], stderr='SENSITIVE_DEBUG_CONTENT')), self.assertRaises(RuntimeError) as raised:
            release.run_task('task', {'cluster':'cluster','subnets':['subnet'],'security_groups':['sg']})
        self.assertIn('AWS CLI exit 254', str(raised.exception))
        self.assertNotIn('SENSITIVE_DEBUG_CONTENT', str(raised.exception))

    def test_bootstrap_role_propagation_retries_with_same_client_token(self):
        release = object.__new__(module.Release)
        error = subprocess.CalledProcessError(254, ['aws'], stderr="aws: [ERROR]: An error occurred (ClientException) when calling the RunTask operation: ECS was unable to assume the role 'bootstrap'")
        with patch.object(release, 'aws', side_effect=[error, {'tasks':[{'taskArn':'task'}]}]) as aws, patch.object(module.time, 'sleep') as sleep:
            result = release.start_task('definition', {'cluster':'cluster','subnets':['subnet'],'security_groups':['sg']}, 'bootstrap')
        self.assertEqual(result['tasks'][0]['taskArn'], 'task')
        self.assertEqual(aws.call_args_list[0], aws.call_args_list[1])
        sleep.assert_called_once_with(5)

    def test_bootstrap_role_retries_are_bounded(self):
        release = object.__new__(module.Release)
        error = subprocess.CalledProcessError(254, ['aws'], stderr="An error occurred (ClientException) when calling the RunTask operation: ECS was unable to assume the role 'bootstrap'")
        with patch.object(release, 'aws', side_effect=error) as aws, patch.object(module.time, 'sleep') as sleep, self.assertRaisesRegex(RuntimeError, 'unable to assume'):
            release.start_task('definition', {'cluster':'cluster','subnets':['subnet'],'security_groups':['sg']}, 'bootstrap')
        self.assertEqual(aws.call_count, 6)
        self.assertEqual(sleep.call_count, 5)

    def test_liquibase_migration_marker_after_empty_and_paginated_logs(self):
        release = object.__new__(module.Release)
        pages = [{'events':[], 'nextForwardToken':'a'},
                 {'events':[{'message':'Update command completed successfully.'}], 'nextForwardToken':'b'},
                 {'events':[{'message':'Liquibase migrate completed; applied changesets: 1'}], 'nextForwardToken':'c'}]
        with patch.object(release, 'aws', side_effect=pages) as aws:
            self.assertEqual(release.migration_version('group','stream'), 'liquibase-changesets:1')
        self.assertIn('--start-from-head', aws.call_args_list[0].args)
        self.assertEqual(aws.call_args_list[2].args[-2:], ('--next-token','b'))

    def test_legacy_schema_marker_is_supported(self):
        release = object.__new__(module.Release)
        with patch.object(release, 'aws', return_value={'events':[{'message':'Schema version: 1.2'}]}):
            self.assertEqual(release.migration_version('group','stream'), '1.2')

    def test_missing_migration_marker_does_not_promote(self):
        release = object.__new__(module.Release)
        with patch.object(release, 'aws', return_value={'events':[{'message':'Liquibase rollback completed; applied changesets: 0'}]}), patch.object(module.time, 'sleep'), self.assertRaisesRegex(RuntimeError, 'not recorded'):
            release.migration_version('group','stream')

    def test_release_plan_allows_only_owned_ecs_changes(self):
        module.validate_release_plan({'resource_changes': [
            {'mode': 'managed', 'address': 'module.ecs_service.aws_ecs_task_definition.app', 'change': {'actions': ['create']}},
            {'mode': 'managed', 'address': 'module.ecs_service.aws_ecs_service.app[0]', 'change': {'actions': ['update']}},
            {'mode': 'managed', 'address': 'module.rds.aws_db_instance.database', 'change': {'actions': ['no-op']}}
        ]})
    def test_release_plan_rejects_infrastructure_mutation(self):
        for address in ['module.rds.aws_db_instance.database', 'module.iam.aws_iam_role.deploy', 'module.other.aws_ecs_service.app']:
            with self.subTest(address=address), self.assertRaises(RuntimeError):
                module.validate_release_plan({'resource_changes': [{'mode': 'managed', 'address': address, 'change': {'actions': ['update']}}]})
    def test_plan_guard_stops_apply_before_infrastructure_change(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.json';path.write_text(json.dumps(Fake().values));r=module.Release(path,path,'bucket')
            commands=[]
            def command(args):
                commands.append(args)
                if 'show' in args:
                    return json.dumps({'resource_changes':[{'mode':'managed','address':'module.rds.aws_db_instance.database','change':{'actions':['delete','create']}}]})
                return '{}'
            r.command=command
            try:
                with self.assertRaises(RuntimeError): r.apply('old')
                self.assertFalse(any('apply' in args for args in commands))
            finally: r.tmp.cleanup()
    def test_bootstrap_permission_is_explicit_and_missing_inventory_fails_closed(self):
        change={'resource_changes':[{'mode':'managed','address':'module.iam.aws_iam_role.bootstrap[0]','change':{'actions':['delete']}}]}
        with self.assertRaises(RuntimeError): module.validate_release_plan(change)
        module.validate_release_plan(change,allow_bootstrap_changes=True)
        with self.assertRaises(RuntimeError): module.validate_release_plan({})
    def test_prepare_retains_active_until_migration(self):
        r=Fake();r.deploy();self.assertEqual(r.events,['verify','init',('apply','old'),'migrate',('apply','candidate'),('health','candidate'),('record','candidate')])
    def test_failed_migration_never_promotes_or_records(self):
        r=Fake('migration')
        with self.assertRaises(RuntimeError):r.deploy()
        self.assertEqual(r.events,['verify','init',('apply','old'),'migrate'])
    def test_failed_health_reconciles_previous_arn(self):
        r=Fake('health')
        with self.assertRaises(RuntimeError):r.deploy()
        self.assertEqual(r.events[-2:],[('apply','old'),('health','old')]);self.assertFalse(any(isinstance(x,tuple) and x[0]=='record' for x in r.events))
    def test_digest_label_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.json';path.write_text(json.dumps(Fake().values));r=module.Release(path,path,'bucket')
            r.command=lambda args:'wrong'
            with self.assertRaises(RuntimeError):r.verify_image()
            r.tmp.cleanup()
    def test_repeated_candidate_preserves_previous_rollback_target(self):
        r=Fake()
        r.manifest=lambda:{'active_task_definition_arn':'candidate','prior_active_task_definition_arn':'previous'}
        recorded=[];r.record=lambda manifest:recorded.append(manifest)
        r.deploy()
        self.assertEqual(recorded[0]['prior_active_task_definition_arn'],'previous')
    def test_failed_rollback_reconciles_pre_rollback_revision(self):
        r=Fake()
        r.manifest=lambda:{'active_task_definition_arn':'candidate','prior_active_task_definition_arn':'old'}
        def healthy(active,*args):
            r.events.append(('health',active))
            if active=='old': raise RuntimeError('rollback smoke failed')
        r.healthy=healthy
        with self.assertRaises(RuntimeError):r.rollback()
        self.assertEqual(r.events[-2:],[('apply','candidate'),('health','candidate')])
    def test_terraform_contract_tests_are_not_ignored(self):
        root=Path(__file__).parents[2]
        self.assertNotEqual(subprocess.run(['git','check-ignore','-q','infra/environments/dev/tests/release.tftest.hcl'],cwd=root).returncode,0)
if __name__=='__main__':unittest.main()
