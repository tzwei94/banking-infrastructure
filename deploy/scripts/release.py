#!/usr/bin/env python3
"""Terraform-owned prepare -> migrate -> promote -> record. No update-service calls."""
import argparse, json, os, re, subprocess, sys, tempfile, time, uuid
from pathlib import Path

def validate_release_plan(plan, allow_bootstrap_changes=False):
    """Reject infrastructure drift or accidental mutations before applying dev state."""
    allowed = {
        'module.ecs_service.aws_ecs_task_definition.app',
        'module.ecs_service.aws_ecs_task_definition.migration',
        'module.ecs_service.aws_ecs_service.app[0]',
    }
    if allow_bootstrap_changes:
        allowed.update({
            'module.ecs_service.aws_ecs_task_definition.bootstrap[0]',
            'module.iam.aws_iam_role.bootstrap[0]',
            'module.iam.aws_iam_role_policy.bootstrap[0]',
        })
    if not isinstance(plan.get('resource_changes'), list):
        raise RuntimeError('Terraform plan did not contain a resource change inventory')
    for change in plan['resource_changes']:
        actions = change.get('change', {}).get('actions', [])
        if actions == ['no-op'] or (change.get('mode') == 'data' and actions == ['read']):
            continue
        if (change.get('mode') != 'managed' or change.get('address') not in allowed
                or not actions or not set(actions) <= {'create', 'update', 'delete'}):
            raise RuntimeError('Release plan changes infrastructure; reconcile dev with an operator plan first: ' + str(change.get('address')))

class Release:
    def __init__(self, config, backend, bucket, first=False):
        self.config=Path(config).resolve(); self.backend=Path(backend).resolve()
        self.values=json.loads(self.config.read_text()); self.bucket=bucket; self.first=first
        self.root=Path(__file__).resolve().parents[2]/'infra/environments/dev'
        self.region=self.values.get('region','ap-southeast-1'); self.name=self.values.get('name','banking-dev')
        self.manifest_key=f'manifests/{self.name}.json'
        self.tmp=tempfile.TemporaryDirectory(prefix='banking-release-'); self.work=Path(self.tmp.name)
    def command(self,args,**kwargs):
        try:
            return subprocess.run(args,check=True,text=True,capture_output=True,**kwargs).stdout
        except subprocess.CalledProcessError as exc:
            if args and (Path(args[0]).name == 'terraform' or
                         (Path(args[0]).name == 'aws' and 'ecs' in args and 'run-task' in args)):
                # Preserve diagnostics beyond TemporaryDirectory cleanup without
                # printing potentially sensitive Terraform output into CI logs.
                directory = Path(__file__).resolve().parents[2] / '.private/setup/diagnostics'
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd, path = tempfile.mkstemp(prefix=Path(args[0]).name+'-', suffix='.log', dir=directory)
                with os.fdopen(fd, 'w') as log:
                    log.write((exc.stdout or '') + '\n' + (exc.stderr or ''))
                print(f'{Path(args[0]).name} failed; private diagnostic log: {path}', file=sys.stderr)
            raise
    def aws(self,*args):
        raw=self.command(['aws','--region',self.region,*args,'--output','json'])
        return json.loads(raw) if raw.strip() else {}
    def manifest(self):
        path=self.work/'manifest.json'
        try: self.aws('s3api','get-object','--bucket',self.bucket,'--key',self.manifest_key,str(path))
        except subprocess.CalledProcessError as e:
            if self.first and ('NoSuchKey' in e.stderr or '(404)' in e.stderr): return None
            raise RuntimeError('Cannot read successful deployment manifest; first release requires --first-release and a missing key') from e
        if self.first: raise RuntimeError('A manifest already exists; refuse first-release mode')
        value=json.loads(path.read_text())
        if not value.get('active_task_definition_arn'): raise RuntimeError('Invalid manifest')
        return value
    def apply(self,active,bootstrap_enabled=False,allow_bootstrap_changes=False):
        variables={**self.values,'service_enabled':bool(active),'active_task_definition_arn':active or '', 'bootstrap_enabled':bootstrap_enabled}
        varfile=self.work/'release.tfvars.json'; varfile.write_text(json.dumps(variables));varfile.chmod(0o600)
        plan=self.work/'release.tfplan'
        self.command(['terraform',f'-chdir={self.root}','plan','-input=false',f'-var-file={varfile}',f'-out={plan}'])
        validate_release_plan(json.loads(self.command(['terraform',f'-chdir={self.root}','show','-json',str(plan)])), allow_bootstrap_changes)
        self.command(['terraform',f'-chdir={self.root}','apply','-input=false','-auto-approve',str(plan)])
        return json.loads(self.command(['terraform',f'-chdir={self.root}','output','-json']))
    def initialize(self):
        self.command(['terraform',f'-chdir={self.root}','init','-input=false',f'-backend-config={self.backend}'])
    def verify_image(self):
        image=self.values['image'];sha=self.values['source_sha']
        if not re.fullmatch(r'[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}',image) or not re.fullmatch('[a-f0-9]{40}',sha): raise ValueError('Invalid digest/source SHA')
        self.command(['docker','pull',image])
        actual=self.command(['docker','image','inspect','--format','{{index .Config.Labels "org.opencontainers.image.revision"}}',image]).strip()
        if actual!=sha: raise RuntimeError('Image source label does not match requested SHA')
    def start_task(self, definition, network, container):
        token = str(uuid.uuid4())
        delays = [5, 10, 20, 40, 40] if container == 'bootstrap' else []
        for attempt in range(len(delays) + 1):
            try:
                return self.aws('ecs','run-task','--cluster',network['cluster'],'--launch-type','FARGATE','--platform-version','1.4.0','--task-definition',definition,
                    '--client-token',token,
                    '--network-configuration',json.dumps({'awsvpcConfiguration':{'subnets':network['subnets'],'securityGroups':network['security_groups'],'assignPublicIp':'DISABLED'}}))
            except subprocess.CalledProcessError as exc:
                # AWS CLI v2 may prefix errors with "aws: [ERROR]:" and ANSI colors.
                stderr = re.sub(r'\x1b\[[0-9;]*m', '', exc.stderr or '')
                match = re.search(r'An error occurred \([^\n]+?\) when calling the RunTask operation:[^\n]*', stderr)
                detail = match.group(0) if match else ''
                # Only retry explicit role-assumption rejection for the freshly
                # created bootstrap role. All other errors fail immediately.
                if 'ECS was unable to assume the role' in detail and attempt < len(delays):
                    print(f'ECS cannot yet assume the new bootstrap role; retrying in {delays[attempt]}s.', flush=True)
                    time.sleep(delays[attempt])
                    continue
                raise RuntimeError('ECS RunTask failed: ' + (detail or
                                   f'AWS CLI exit {exc.returncode}; see the private diagnostic log')) from None

    def run_task(self,definition,network,container='migration'):
        result = self.start_task(definition, network, container)
        if result.get('failures') or len(result.get('tasks',[]))!=1: raise RuntimeError('ECS rejected administrative task')
        arn=result['tasks'][0]['taskArn']
        try: self.aws('ecs','wait','tasks-stopped','--cluster',network['cluster'],'--tasks',arn)
        except subprocess.CalledProcessError:
            self.aws('ecs','stop-task','--cluster',network['cluster'],'--task',arn,'--reason','Release administrative task timed out')
            raise
        task=self.aws('ecs','describe-tasks','--cluster',network['cluster'],'--tasks',arn)['tasks'][0]
        containers=[c for c in task.get('containers',[]) if c['name']==container]
        if len(containers)!=1 or containers[0].get('exitCode')!=0: raise RuntimeError(f'{container} failed; promotion blocked; inspect restricted CloudWatch task logs')
        stream=f'tasks/{container}/{arn.rsplit("/",1)[-1]}'
        return self.migration_version(network['log_group'], stream) if container == 'migration' else None

    def migration_version(self, log_group, stream):
        token = None
        for attempt in range(30):
            args = ['logs','get-log-events','--log-group-name',log_group,
                    '--log-stream-name',stream,'--start-from-head']
            if token:
                args += ['--next-token', token]
            try:
                page = self.aws(*args)
            except subprocess.CalledProcessError as exc:
                if 'ResourceNotFoundException' not in (exc.stderr or ''):
                    raise
                page = {}
            for event in page.get('events', []):
                message = event['message'].strip()
                current = re.fullmatch(r'Liquibase migrate completed; applied changesets: ([0-9]+)', message)
                if current:
                    # This records a changeset count, not a Liquibase version or checksum.
                    return 'liquibase-changesets:' + current.group(1)
                legacy = re.fullmatch(r'Schema version: ([\w.]+)', message)
                if legacy:
                    return legacy.group(1)
            next_token = page.get('nextForwardToken')
            if next_token and next_token != token:
                token = next_token
            elif attempt < 29:
                time.sleep(2)
        raise RuntimeError('Migration succeeded but schema version was not recorded; inspect its CloudWatch log stream')

    def healthy(self,active,network):
        self.aws('ecs','wait','services-stable','--cluster',network['cluster'],'--services',self.name)
        maximum = 4 if self.values.get('autoscaling_enabled', False) else 2

        def snapshot():
            service = self.aws('ecs', 'describe-services', '--cluster', network['cluster'],
                               '--services', self.name)['services'][0]
            if service['taskDefinition'] != active or not 2 <= service['desiredCount'] <= maximum:
                raise RuntimeError('Service has the wrong task definition or capacity outside the approved range')
            return service

        # Scale-out stays active during deployments. Allow up to two minutes for
        # in-range capacity/ALB convergence after the waiter, without rolling back
        # a healthy candidate just because scaling raced with our health reads.
        for attempt in range(13):
            service = snapshot()
            desired = service['desiredCount']
            settled = service['runningCount'] == desired and service['pendingCount'] == 0
            if settled:
                for target in service['loadBalancers']:
                    health = self.aws('elbv2', 'describe-target-health', '--target-group-arn',
                                      target['targetGroupArn'])['TargetHealthDescriptions']
                    if sum(t['TargetHealth']['State'] == 'healthy' for t in health) < desired:
                        settled = False
                if settled:
                    # Ensure the ALB check covered the currently desired capacity.
                    confirmed = snapshot()
                    settled = (confirmed['desiredCount'] == desired
                               and confirmed['runningCount'] == desired and confirmed['pendingCount'] == 0)
            if settled:
                self.command([sys.executable,str(Path(__file__).with_name('smoke.py'))])
                return
            if attempt < 12:
                time.sleep(10)
        raise RuntimeError('Service tasks and ALB targets did not settle at the approved capacity')
    def record(self,manifest):
        path=self.work/'successful.json';path.write_text(json.dumps(manifest,indent=2));path.chmod(0o600)
        self.aws('s3api','put-object','--bucket',self.bucket,'--key',self.manifest_key,'--body',str(path),'--content-type','application/json')
    def deploy(self):
        previous=self.manifest(); active=previous['active_task_definition_arn'] if previous else None
        self.verify_image();self.initialize()
        prepared=self.apply(active)
        candidate=prepared['candidate_app_arn']['value'];migration=prepared['candidate_migration_arn']['value'];network=prepared['run_task']['value']
        version=self.run_task(migration,network)
        try:
            self.apply(candidate);self.healthy(candidate,network)
        except Exception:
            # First failure returns to no service. Later failures reconcile TF to the previous ARN.
            self.apply(active)
            if active: self.healthy(active,network)
            raise
        self.record({'source_sha':self.values['source_sha'],'image':self.values['image'],'alloy_image':self.values['alloy_image'],
            'active_task_definition_arn':candidate,'migration_task_definition_arn':migration,'schema_version':version,
            'prior_active_task_definition_arn':(previous.get('prior_active_task_definition_arn') if previous and active==candidate else active),'workflow_run':os.getenv('GITHUB_RUN_ID','operator')})
        print('Release healthy; versioned successful manifest recorded')
    def rollback(self):
        previous=self.manifest();target=previous.get('prior_active_task_definition_arn')
        if not target: raise RuntimeError('No previous application revision; do not reverse database migrations automatically')
        self.initialize()
        try:
            outputs=self.apply(target);self.healthy(target,outputs['run_task']['value'])
        except Exception:
            restored=self.apply(previous['active_task_definition_arn'])
            self.healthy(previous['active_task_definition_arn'],restored['run_task']['value'])
            raise
        definition=self.aws('ecs','describe-task-definition','--task-definition',target)['taskDefinition']
        app=next(c for c in definition['containerDefinitions'] if c['name']=='app')
        alloy=next(c for c in definition['containerDefinitions'] if c['name']=='alloy')
        previous.update(active_task_definition_arn=target,prior_active_task_definition_arn=previous['active_task_definition_arn'],image=app['image'],alloy_image=alloy['image'],source_sha=next(e['value'] for e in app['environment'] if e['name']=='SOURCE_SHA'))
        self.record(previous);print('Application rollback healthy; database schema retained')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['deploy','rollback']);parser.add_argument('--config',required=True);parser.add_argument('--backend',required=True);parser.add_argument('--manifest-bucket',required=True);parser.add_argument('--first-release',action='store_true')
    args=parser.parse_args()
    release=Release(args.config,args.backend,args.manifest_bucket,args.first_release)
    try: getattr(release,args.action)()
    finally: release.tmp.cleanup()
if __name__=='__main__':
    try: main()
    except (subprocess.CalledProcessError,RuntimeError,ValueError) as e:
        # Do not dump command output/environment. Logs are available in the restricted runner workspace.
        print(f'Release stopped: {type(e).__name__}: '+(str(e) if not isinstance(e,subprocess.CalledProcessError) else 'external command failed'),file=sys.stderr)
        sys.exit(1)
