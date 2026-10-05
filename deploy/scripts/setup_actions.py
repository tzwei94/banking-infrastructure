"""Deployment menu actions. AWS/GitHub mutations are explicit interactive choices."""
import base64
from contextlib import contextmanager
import datetime
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urlsplit


def prompt(label, default=''):
    return input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip() or default


def approved(message):
    return input(message + ' Type yes to continue: ').strip() == 'yes'


def private_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
        os.chmod(stream.name, 0o600)
        stream.write(content)
        temporary = Path(stream.name)
    temporary.replace(path)


@contextmanager
def private_json(value):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as stream:
        os.chmod(stream.name, 0o600)
        json.dump(value, stream)
        stream.flush()
        yield 'file://' + stream.name


class DeploymentActions:
    @property
    def dev_root(self):
        return self.deployment / 'infra/environments/dev'

    def dev_profile(self):
        return json.loads((self.dev_root / 'dev.tfvars.json').read_text())

    @staticmethod
    def validate_url(value):
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Use an HTTPS URL without embedded credentials, query or fragment.')
        return value

    def configure_deployment(self):
        existing = self.dev_profile() if (self.dev_root / 'dev.tfvars.json').exists() else {}
        updates = {}
        labels = {'alarm_email': 'Alarm email', 'loki_url': 'Loki push HTTPS URL',
                  'metrics_url': 'Prometheus remote-write HTTPS URL', 'traces_base_url': 'Tempo HTTPS base URL',
                  'github_owner': 'GitHub owner', 'app_repository': 'App repository name',
                  'deployment_repository': 'Deployment repository name'}
        for key, label in labels.items():
            value = prompt(label, self.settings.get(key, existing.get(key, '')))
            if key.endswith('url'):
                self.validate_url(value)
            elif key == 'alarm_email':
                if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
                    raise ValueError('Enter a valid alarm email.')
            elif not re.fullmatch(r'[A-Za-z0-9_.-]+', value):
                raise ValueError('Invalid GitHub owner/repository name.')
            updates[key] = value
        days = int(prompt('RDS backup retention days (1 for restricted account retry)', str(existing.get('db_backup_retention_period', 7))))
        if not 1 <= days <= 35:
            raise ValueError('Choose 1 to 35 days.')
        updates['db_backup_retention_period'] = days
        self.settings.update(updates)
        self.save()
        print('Settings saved locally. Choose dev infrastructure to write/review its configuration.')

    def write_dev_config(self):
        path = self.dev_root / 'dev.tfvars.json'
        exists = path.exists()
        values = self.dev_profile() if exists else json.loads((self.dev_root / 'dev.tfvars.json.example').read_text())
        keys = ['region', 'alarm_email', 'loki_url', 'metrics_url', 'traces_base_url', 'github_owner',
                'app_repository', 'deployment_repository', 'github_oidc_arn', 'state_bucket',
                'state_kms_arn', 'certificate_arn', 'runner_ami_id', 'db_backup_retention_period']
        for key in keys:
            if key in self.settings:
                values[key] = self.settings[key]
            elif not exists and key != 'db_backup_retention_period':
                raise ValueError(f'Missing {key}; complete bootstrap and configuration menus first.')
        if not exists:
            host = f"{self.settings['account']}.dkr.ecr.{self.settings['region']}.amazonaws.com"
            values.update(name='banking-dev', service_enabled=False, bootstrap_enabled=False,
                          active_task_definition_arn='', runner_instance_type='t3.small', seed_synthetic=True,
                          image=host+'/banking-dev/banking-api@sha256:'+'0'*64,
                          alloy_image=host+'/banking-dev/banking-alloy@sha256:'+'0'*64, source_sha='0'*40,
                          final_snapshot_identifier='banking-dev-final-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S'))
        private_write(path, json.dumps(values, indent=2)+'\n')
        if 'state_bucket' in values and 'state_kms_arn' in values:
            backend = dict(bucket=values['state_bucket'], key='dev/terraform.tfstate', region=values['region'],
                           encrypt=True, use_lockfile=True, kms_key_id=values['state_kms_arn'])
            backend_path = self.dev_root / 'backend.hcl'
            # Preserve existing backend wiring; changing state locations needs explicit migration.
            if not backend_path.exists():
                private_write(backend_path, '\n'.join(f'{k} = {json.dumps(v)}' for k, v in backend.items())+'\n')
        self.settings['plans'].pop('dev', None)
        self.save()
        print('Private dev profile saved; existing image, service and task settings preserved.')

    def dev_fingerprint(self):
        paths = [self.dev_root / name for name in ['dev.tfvars.json', 'backend.hcl']]
        paths += sorted((self.deployment / 'infra').rglob('*.tf'))
        paths += [self.deployment / 'deploy/provisioning/runner-init.sh']
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}

    def check_dev_changes(self, plan):
        unsafe = [r['address'] for r in plan.get('resource_changes', [])
                  if r['mode'] == 'managed' and 'delete' in r['change']['actions']]
        if unsafe:
            raise ValueError('Deletion/replacement blocked by setup menu: '+', '.join(unsafe)+
                             '. Review separately; a runner user-data change can cause replacement.')

    def dev_plan(self):
        self.settings['plans'].pop('dev', None)
        self.save()
        profile = self.dev_profile()
        for key in ['region', 'state_bucket', 'state_kms_arn']:
            if profile[key] != self.settings[key]:
                raise ValueError(f'Dev profile {key} differs from saved bootstrap settings.')
        print('For an already deployed service, synchronize the operator profile with its successful release manifest first (SETUP.md section 11).')
        self.tf('dev', 'init', '-input=false', f'-backend-config={self.dev_root}/backend.hcl')
        path = self.private / 'dev.tfplan'
        self.tf('dev', 'plan', '-input=false', f'-var-file={self.dev_root}/dev.tfvars.json', f'-out={path}')
        self.check_dev_changes(self.tf('dev', 'show', '-json', str(path), capture=True))
        self.record_plan('dev', path)
        self.settings['plans']['dev']['inputs'] = self.dev_fingerprint()
        self.save()
        print('Plan saved. Choose review/apply separately.')

    def check_dev_plan(self, saved, path):
        if saved.get('inputs') != self.dev_fingerprint():
            raise ValueError('Dev configuration changed after planning; generate a new plan.')
        self.check_dev_changes(self.tf('dev', 'show', '-json', str(path), capture=True))

    def contract(self):
        data = self.tf('dev', 'output', '-json', 'contract', capture=True)
        if not data.get('runner_instance_id') or not data.get('secret_arns'):
            raise ValueError('Dev outputs incomplete. Finish the infrastructure apply first.')
        private_write(self.private / 'contract.json', json.dumps(data, indent=2)+'\n')
        # Keep the main guide's contract location in sync when used in assignment.
        if (self.deployment.parent / 'SETUP.md').exists():
            private_write(self.deployment.parent / '.private/setup/contract.json', json.dumps(data, indent=2)+'\n')
        return data

    def dev_menu(self):
        print('1. Write/update private configuration\n2. Plan\n3. Review/apply saved plan\n4. Reload/save outputs')
        choice = prompt('Selection (0 back)', '0')
        actions = {'1': self.write_dev_config, '2': self.dev_plan, '3': lambda: self.apply('dev'), '4': self.contract}
        if choice in actions:
            actions[choice]()

    def dns_check(self):
        contract = self.contract()
        host = self.settings['domain']
        if not host:
            raise ValueError('Set the API hostname first.')
        print(f"DNS CNAME: {host} -> {contract['alb_dns_name']}\nCloudflare: DNS only. Keep the ACM validation CNAME.")
        print('Confirm the SNS email subscription in your inbox.')
        subscriptions = self.aws('sns', 'list-subscriptions-by-topic', '--topic-arn', contract['alarm_topic_arn'])
        for subscription in subscriptions.get('Subscriptions', []):
            print(subscription['Protocol'], subscription['Endpoint'], subscription['SubscriptionArn'])
        if approved('Test public HTTPS readiness now?'):
            code = self.run(['curl', '--silent', '--show-error', '--connect-timeout', '10', '--max-time', '20',
                             '--output', '/dev/null', '--write-out', '%{http_code}', f'https://{host}/readyz'], True).strip()
            if code == '200':
                print('HTTPS readiness returned 200; authenticated API checks still run during deployment.')
            elif code == '503':
                print('HTTPS works, but application is not ready (503); expected before first deployment.')
            else:
                raise ValueError(f'Unexpected readiness HTTP {code}; check DNS, listener and application.')

    def put_secret(self, arn, value):
        with private_json(value) as file:
            self.aws('secretsmanager', 'put-secret-value', '--secret-id', arn, '--secret-string', file)
        print('Secret version stored.')

    def credentials_menu(self):
        secrets = self.contract()['secret_arns']
        choice = prompt('1 telemetry credentials, 2 API token-login credentials, 0 back', '0')
        if choice not in {'1', '2'}:
            return
        name = 'telemetry' if choice == '1' else 'token-auth'
        metadata = self.aws('secretsmanager', 'describe-secret', '--secret-id', secrets[name])
        if metadata.get('VersionIdsToStages') and not approved(f'{name} already has a value. Store a new version? Running tasks need replacement to use it.'):
            return
        print('Use existing homelab ingestion credentials.' if name == 'telemetry' else 'Choose API-login credentials and retain them in your password manager.')
        username = prompt('Username')
        password = getpass.getpass('Password: ')
        if not username or not password:
            raise ValueError('Username and password must not be empty.')
        if approved(f'Store {name} in AWS Secrets Manager?'):
            self.put_secret(secrets[name], dict(username=username, password=password))

    def signing_key(self):
        arn = self.contract()['secret_arns']['jwt-signing']
        if self.aws('secretsmanager', 'describe-secret', '--secret-id', arn).get('VersionIdsToStages'):
            print('Signing secret already populated; keeping the existing key. Rotation is a separate operation.')
            return
        if not approved('Generate/reuse a local RSA key and store it in the empty signing secret?'):
            return
        self.private.mkdir(parents=True, exist_ok=True)
        key = self.private / 'demo-signing.key'
        legacy = self.deployment.parent / '.private/setup/demo-signing.key'
        if not key.exists() and legacy.exists():
            key = legacy
        if not key.exists():
            with tempfile.TemporaryDirectory(dir=self.private) as temp:
                candidate = Path(temp) / 'signing.key'
                self.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(candidate)])
                self.run(['openssl', 'pkey', '-in', str(candidate), '-check', '-noout'], True)
                private_write(key, candidate.read_text())
        self.run(['openssl', 'pkey', '-in', str(key), '-check', '-noout'], True)
        self.put_secret(arn, {'private_key': key.read_text()})

    def runner_id(self):
        instance = self.contract()['runner_instance_id']
        response = self.aws('ec2', 'describe-instances', '--instance-ids', instance)
        instances = [i for r in response['Reservations'] for i in r['Instances']]
        expected = self.dev_profile().get('name', 'banking-dev') if (self.dev_root / 'dev.tfvars.json').exists() else 'banking-dev'
        if len(instances) != 1 or {t['Key']: t['Value'] for t in instances[0].get('Tags', [])}.get('Name') != expected+'-runner':
            raise ValueError('Instance does not match the expected runner tag.')
        print('Runner:', instance, 'state:', instances[0]['State']['Name'])
        if instances[0]['State']['Name'] != 'running':
            raise ValueError('Start the runner instance before continuing.')
        return instance

    def online_runner(self):
        instance = self.runner_id()
        info = self.aws('ssm', 'describe-instance-information', '--filters', f'Key=InstanceIds,Values={instance}')
        if not any(x.get('InstanceId') == instance and x.get('PingStatus') == 'Online' for x in info.get('InstanceInformationList', [])):
            raise ValueError('Runner must be Online in SSM before this action.')
        return instance

    def command_result(self, command, instance):
        for _ in range(30):
            response = self.aws('ssm', 'list-command-invocations', '--command-id', command, '--instance-id', instance, '--details')
            invocations = response.get('CommandInvocations', [])
            if invocations and invocations[0]['Status'] not in {'Pending', 'InProgress', 'Delayed', 'Cancelling'}:
                invocation = invocations[0]
                for plugin in invocation.get('CommandPlugins', []):
                    print(plugin.get('Output', ''))
                print('SSM command:', command, invocation['Status'])
                if invocation['Status'] != 'Success':
                    raise ValueError('Remote command '+invocation['Status'])
                return
            time.sleep(2)
        print(f'Command {command} is still pending/running. Use runner menu status; do not resend the repair.')

    def remote(self, instance, commands):
        if self.remote_busy():
            raise ValueError('Previous runner command is still active; inspect its status first.')
        with private_json({'commands': commands, 'executionTimeout': ['1200']}) as parameters:
            command = self.aws('ssm', 'send-command', '--instance-ids', instance, '--document-name', 'AWS-RunShellScript',
                               '--parameters', parameters)['Command']['CommandId']
        self.settings['runner_command'] = {'id': command, 'instance': instance}
        self.save()
        print('Submitted SSM command:', command)
        self.command_result(command, instance)

    def remote_busy(self):
        previous = self.settings.get('runner_command')
        if not previous:
            return False
        status = self.aws('ssm', 'list-command-invocations', '--command-id', previous['id'], '--instance-id', previous['instance'])
        invocations = status.get('CommandInvocations', [])
        return not invocations or invocations[0]['Status'] in {'Pending', 'InProgress', 'Delayed', 'Cancelling'}

    def repair_runner(self):
        instance = self.online_runner()
        if not approved(f'Run the reviewed provisioning script on existing runner {instance}? Installs packages, starts Docker and ensures runner users exist.'):
            return
        if self.remote_busy():
            raise ValueError('Previous runner command is still active; inspect its status first.')
        script = (self.deployment / 'deploy/provisioning/runner-init.sh').read_bytes()
        encoded = base64.b64encode(script).decode()
        self.remote(instance, ['set -eu', 'install -d -m 700 /root/banking-setup',
                              f"printf %s {shlex.quote(encoded)} | base64 -d > /root/banking-setup/runner-init.sh",
                              'bash /root/banking-setup/runner-init.sh',
                              'systemctl is-active docker', 'aws --version', 'java -version', 'id runner-app', 'id runner-deploy'])
        print('Historical cloud-init status may remain error after manual repair. Use command result and service checks.')

    def start_session(self, instance, command=None):
        if not shutil.which('session-manager-plugin'):
            raise ValueError('Install the Session Manager plugin on this computer first: https://docs.aws.amazon.com/systems-manager/latest/userguide/install-plugin-macos-overview.html')
        args = ['aws', '--profile', self.settings['profile'], '--region', self.settings['region'], 'ssm', 'start-session', '--target', instance]
        if command:
            with private_json({'command': [command]}) as parameters:
                self.run(args+['--document-name', 'AWS-StartInteractiveCommand', '--parameters', parameters])
        else:
            self.run(args)

    def runner_menu(self):
        print('1. Check SSM status\n2. Connect interactively\n3. Diagnose cloud-init/Docker\n4. Repair existing runner\n5. Poll last command')
        choice = prompt('Selection (0 back)', '0')
        if choice == '0':
            return
        if choice == '4':
            return self.repair_runner()
        if choice == '5':
            command = self.settings.get('runner_command')
            if not command:
                raise ValueError('No saved SSM command.')
            return self.command_result(command['id'], command['instance'])
        instance = self.runner_id()
        if choice == '1':
            print(json.dumps(self.aws('ssm', 'describe-instance-information', '--filters', f'Key=InstanceIds,Values={instance}',
                                      '--query', 'InstanceInformationList[].{Id:InstanceId,Status:PingStatus}'), indent=2))
        elif choice == '2':
            self.start_session(instance)
        elif choice == '3':
            self.remote(instance, ['cloud-init status --long || true', 'tail -n 100 /var/log/cloud-init-output.log',
                                   'systemctl is-active docker || true', 'aws --version || true', 'java -version || true',
                                   'id runner-app || true', 'id runner-deploy || true'])

    def repository_names(self):
        profile = self.dev_profile()
        return {kind: profile['github_owner']+'/'+profile[key] for kind, key in
                [('app', 'app_repository'), ('deploy', 'deployment_repository')]}

    def registration(self):
        repositories = self.repository_names()
        kind = prompt('Runner kind: app or deploy', 'app')
        if kind not in repositories:
            raise ValueError('Select app or deploy.')
        repo = repositories[kind]
        print(f'Open https://github.com/{repo}/settings/actions/runners/new (Linux, x64).')
        print('Copy the current version and SHA256. You will enter the short-lived token only in the interactive EC2 session.')
        version = prompt('Runner version (without v)')
        checksum = prompt('Runner archive SHA256')
        if not re.fullmatch(r'\d+\.\d+\.\d+', version) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
            raise ValueError('Invalid version or SHA256.')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
            raise ValueError('Invalid repository.')
        instance = self.online_runner()
        if not shutil.which('session-manager-plugin'):
            raise ValueError('Install the local Session Manager plugin before registration.')
        if not approved(f'Install registration helper on {instance} and open interactive registration for {repo}?'):
            return
        if self.remote_busy():
            raise ValueError('Previous SSM command is still active.')
        script = base64.b64encode((self.deployment / 'deploy/provisioning/register-runner.sh').read_bytes()).decode()
        self.remote(instance, ['set -eu',
                               f'test ! -f /home/runner-{kind}/actions-runner/.runner || {{ echo \"Runner already registered; inspect GitHub runner status instead.\"; exit 1; }}',
                               'install -d -m 700 /root/banking-setup',
                               f"printf %s {shlex.quote(script)} | base64 -d > /root/banking-setup/register-runner.sh",
                               'chmod 700 /root/banking-setup/register-runner.sh'])
        previous = self.settings['runner_command']
        response = self.aws('ssm', 'list-command-invocations', '--command-id', previous['id'], '--instance-id', instance)
        if not response.get('CommandInvocations') or response['CommandInvocations'][0]['Status'] != 'Success':
            raise ValueError('Helper upload is not complete; poll its status before retrying registration.')
        self.start_session(instance, shlex.join(['sudo', 'bash', '/root/banking-setup/register-runner.sh', repo, kind, version, checksum]))

    def github_configure(self):
        contract = self.contract()
        repositories = self.repository_names()
        profile = self.dev_profile()
        environment = profile.get('github_environment', 'dev')
        if environment != 'dev':
            raise ValueError('The deployment workflow uses environment dev; align the profile before configuring GitHub.')
        print(f"Create/protect environment {environment}: https://github.com/{repositories['deploy']}/settings/environments")
        print('Restrict deployments to main; protect both main branches and allow only trusted runner workflows.')
        # GET only: never silently create an unprotected environment.
        self.run(['gh', 'api', f"repos/{repositories['deploy']}/environments/{environment}"], True)
        if not approved('Write GitHub Actions variables for these repositories and environment?'):
            return
        common = {'AWS_REGION': self.settings['region']}
        variables = {'app': {**common, 'AWS_BUILD_ROLE_ARN': contract['build_role_arn'], 'IMAGE_REPOSITORY': contract['ecr_repositories']['banking-api'],
                             'DEPLOYMENT_REPOSITORY': repositories['deploy']},
                     'deploy': {**common, 'AWS_DEPLOY_ROLE_ARN': contract['deploy_role_arn'], 'STATE_BUCKET': profile['state_bucket'],
                                'API_URL': 'https://'+self.settings['domain'], 'DEV_TFVARS_JSON': json.dumps(profile)}}
        # Alloy publishing uses a main-branch OIDC subject, without the dev environment.
        alloy_variables = {**common, 'AWS_ALLOY_PUBLISH_ROLE_ARN': contract['alloy_publish_role_arn'],
                           'ALLOY_REPOSITORY': contract['ecr_repositories']['banking-alloy']}
        for name, value in alloy_variables.items():
            self.run(['gh', 'variable', 'set', name, '--repo', repositories['deploy'], '--body', value])
        for kind, values in variables.items():
            for name, value in values.items():
                args = ['gh', 'variable', 'set', name, '--repo', repositories[kind]]
                if kind == 'deploy':
                    args += ['--env', environment]
                self.run(args+['--body', value])
        if approved('Copy the existing token-auth credentials from AWS to GitHub environment secrets TOKEN_USERNAME and TOKEN_PASSWORD?'):
            response = self.aws('secretsmanager', 'get-secret-value', '--secret-id', contract['secret_arns']['token-auth'])
            value = json.loads(response['SecretString'])
            for field in ['username', 'password']:
                if not isinstance(value.get(field), str) or not value[field]:
                    raise ValueError('token-auth must contain nonempty username and password.')
            for name, field in [('TOKEN_USERNAME', 'username'), ('TOKEN_PASSWORD', 'password')]:
                subprocess.run(['gh', 'secret', 'set', name, '--repo', repositories['deploy'], '--env', environment],
                               input=value[field], text=True, check=True, env=self.env())
            print('GitHub token secrets stored. Values were not saved in settings or command arguments.')
        print('GitHub settings updated. Image publishing, DB bootstrap and release remain separate guide steps.')

    def github_menu(self):
        print('1. Register app/deploy runner\n2. Configure GitHub variables and token secrets\n3. Check registered runners')
        choice = prompt('Selection (0 back)', '0')
        if choice == '1':
            self.registration()
        elif choice == '2':
            self.github_configure()
        elif choice == '3':
            for repo in self.repository_names().values():
                print(repo)
                print(self.run(['gh', 'api', '--paginate', f'repos/{repo}/actions/runners', '--jq', '.runners[] | {name,status,busy,labels:[.labels[].name]}'], True))
