#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Interactive preparation for SETUP.md; no AWS calls occur until a menu action."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from setup_actions import DeploymentActions
import setup_prerequisites
from setup_destroy import DestroyActions


def ask(label, default=''):
    value = input(f'{label}' + (f' [{default}]' if default else '') + ': ').strip()
    return value or default


def confirm(label):
    return input(f'{label} Type yes to continue: ').strip() == 'yes'


class Setup(DeploymentActions, DestroyActions):
    def __init__(self, deployment):
        setup_prerequisites.activate_tools()
        self.deployment = deployment.resolve()
        self.private = self.deployment / '.private/setup'
        self.settings_path = self.private / 'settings.json'
        self.settings = {'profile': os.environ.get('AWS_PROFILE', 'default'),
                         'region': os.environ.get('AWS_REGION', 'ap-southeast-1'),
                         'domain': '', 'plans': {}}
        if self.settings_path.exists():
            self.settings.update(json.loads(self.settings_path.read_text()))

    def save(self):
        self.private.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=self.private, delete=False) as stream:
            path = Path(stream.name)
            os.chmod(path, 0o600)
            json.dump(self.settings, stream, indent=2)
            stream.write('\n')
        path.replace(self.settings_path)

    def env(self):
        env = os.environ.copy()
        for key in list(env):
            if key in {'AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY', 'AWS_SESSION_TOKEN',
                       'AWS_SECURITY_TOKEN', 'AWS_DEFAULT_PROFILE', 'TF_WORKSPACE', 'TF_DATA_DIR'} or key.startswith(('AWS_ENDPOINT_URL', 'TF_CLI_ARGS', 'TF_VAR_')):
                env.pop(key)
        env.update(AWS_PROFILE=self.settings['profile'], AWS_REGION=self.settings['region'],
                   AWS_DEFAULT_REGION=self.settings['region'], AWS_PAGER='',
                   AWS_IGNORE_CONFIGURED_ENDPOINT_URLS='true')
        return env

    def run(self, args, capture=False, cwd=None, input_text=None):
        result = subprocess.run(args, env=self.env(), cwd=cwd or self.deployment,
                                check=True, text=True, input=input_text, stdout=subprocess.PIPE if capture else None)
        return result.stdout if capture else None

    def aws(self, *args):
        return json.loads(self.run(['aws', '--profile', self.settings['profile'],
                                    '--region', self.settings['region'], '--output', 'json', *args], True))

    def tf(self, root, *args, capture=False):
        folder = self.dev_root if root == 'dev' else self.deployment / 'infra/bootstrap' / root
        value = self.run(['terraform', f'-chdir={folder}', *args], capture)
        return json.loads(value) if capture else value

    def identity(self):
        result = self.aws('sts', 'get-caller-identity')
        previous = self.settings.get('account')
        if previous and previous != result['Account']:
            raise ValueError('AWS account differs from saved setup. Use a separate checkout/settings file for another account.')
        self.settings['account'] = result['Account']
        self.save()
        print(f"Account: {result['Account']}  Identity: {result['Arn']}  Region: {self.settings['region']}")

    def configure(self):
        old = self.settings.copy()
        self.settings['profile'] = ask('AWS profile', self.settings['profile'])
        region = ask('AWS region', self.settings['region'])
        if self.settings.get('account') and region != self.settings['region']:
            self.settings = old
            raise ValueError('This setup is bound to its saved region. Use a separate checkout for another region.')
        self.settings['region'] = region
        try:
            self.identity()
        except Exception:
            self.settings = old
            raise
        domain = ask('API hostname', self.settings['domain'])
        if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', domain) or '.' not in domain:
            raise ValueError('Enter a hostname, without https:// or a path.')
        if domain != self.settings['domain']:
            self.settings.pop('certificate_arn', None)
        self.settings['domain'] = domain.lower()
        self.save()

    def local_checks(self):
        choice = ask('1 verify, 2 smoke, 0 back', '0')
        if choice not in {'1', '2'}:
            return
        target = 'verify' if choice == '1' else 'smoke'
        project = self.deployment.parent
        if not (project / 'app/Makefile').exists():
            raise ValueError('Local checks need the parent assignment checkout and app submodule.')
        self.run(['make', target], cwd=project)
        print(f'{target} passed.')

    def certificate(self):
        domain = self.settings['domain']
        if not domain:
            raise ValueError('Select profile, region and hostname using option 1 first.')
        arn = self.settings.get('certificate_arn')
        if not arn:
            result = self.aws('acm', 'list-certificates', '--certificate-statuses', 'ISSUED', 'PENDING_VALIDATION',
                              '--includes', 'keyTypes=RSA_1024,RSA_2048,RSA_3072,RSA_4096,EC_prime256v1,EC_secp384r1,EC_secp521r1')
            matches = [c for c in result['CertificateSummaryList'] if c['DomainName'] == domain]
            if len(matches) == 1:
                arn = matches[0]['CertificateArn']
            elif matches:
                for i, cert in enumerate(matches, 1):
                    print(f"{i}. {cert['CertificateArn']} {cert.get('Status', '')}")
                selection = int(ask('Select existing certificate number'))
                if not 1 <= selection <= len(matches):
                    raise ValueError('Invalid certificate selection.')
                arn = matches[selection - 1]['CertificateArn']
            else:
                if not confirm(f'Request an ACM certificate for {domain}?'):
                    return
                token = hashlib.sha256(domain.encode()).hexdigest()[:32]
                arn = self.aws('acm', 'request-certificate', '--domain-name', domain,
                               '--validation-method', 'DNS', '--idempotency-token', token)['CertificateArn']
            self.settings['certificate_arn'] = arn
            self.save()
        cert = self.aws('acm', 'describe-certificate', '--certificate-arn', arn)['Certificate']
        if cert['DomainName'] != domain:
            raise ValueError('Certificate hostname does not match saved settings.')
        print(f"Certificate: {arn}\nStatus: {cert['Status']}")
        if cert['Status'] in {'FAILED', 'VALIDATION_TIMED_OUT', 'EXPIRED', 'REVOKED'}:
            if confirm('This certificate cannot be used. Select/request a replacement? The old certificate will remain in AWS.'):
                self.settings.pop('certificate_arn', None)
                self.save()
                self.certificate()
            return
        for option in cert.get('DomainValidationOptions', []):
            record = option.get('ResourceRecord')
            if record:
                print(f"DNS: {record['Type']}\nName: {record['Name']}\nTarget: {record['Value']}")
        if cert['Status'] != 'ISSUED':
            print('Add the DNS record at your provider (Cloudflare: DNS only). Keep it for renewal.\nRun this option again to refresh; a new record may take a moment to appear.')

    def discover(self):
        image_id = self.aws('ssm', 'get-parameter', '--name',
                            '/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64')['Parameter']['Value']
        images = self.aws('ec2', 'describe-images', '--image-ids', image_id, '--owners', 'amazon')['Images']
        if len(images) != 1 or images[0]['Architecture'] != 'x86_64' or images[0]['State'] != 'available':
            raise ValueError('Expected an available Amazon-owned x86_64 AMI.')
        image = images[0]
        print(json.dumps({k: image[k] for k in ('ImageId', 'Name', 'Architecture', 'OwnerId')}, indent=2))
        print(json.dumps(self.aws('ec2', 'describe-instance-types', '--instance-types', 't3.small',
                                  '--query', 'InstanceTypes[].{Type:InstanceType,MemoryMiB:MemoryInfo.SizeInMiB,FreeTier:FreeTierEligible}'), indent=2))
        options = self.aws('rds', 'describe-orderable-db-instance-options', '--engine', 'postgres',
                           '--db-instance-class', 'db.t4g.micro')['OrderableDBInstanceOptions']
        versions = sorted({(x['EngineVersion'], x['StorageType']) for x in options if x['EngineVersion'].startswith('17.')})
        if not versions:
            raise ValueError('No PostgreSQL 17 options found for db.t4g.micro in this region.')
        for version, storage in versions:
            print(f'PostgreSQL {version}: {storage}')
        self.settings['runner_ami_id'] = image_id
        self.save()
        print('AMI saved. Availability does not prove account eligibility, quota or build capacity.')

    def context(self):
        return {k: self.settings.get(k) for k in ('profile', 'region', 'account', 'state_bucket')}

    def record_plan(self, root, path):
        self.settings['plans'][root] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'context': self.context()}
        self.save()

    def plan(self, root):
        self.settings['plans'].pop(root, None)
        self.save()
        if root == 'dev':
            return self.dev_plan()
        self.tf(root, 'init', '-input=false')
        args = [f'-var=region={self.settings["region"]}']
        if root == 'backend':
            default = self.settings.get('state_bucket', f'banking-demo-state-{self.settings["account"]}-{self.settings["region"]}')
            self.settings['state_bucket'] = ask('State bucket name', default)
            args.append(f'-var=bucket_name={self.settings["state_bucket"]}')
        path = self.private / f'{root}.tfplan'
        self.tf(root, 'plan', '-input=false', *args, f'-out={path}')
        self.record_plan(root, path)
        print('Plan saved. Select apply separately to review and apply it.')

    def apply(self, root):
        path = self.private / f'{root}.tfplan'
        saved = self.settings['plans'].get(root)
        if not saved or not path.exists() or saved['context'] != self.context() or saved['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('No matching saved plan. Generate a new plan first.')
        self.identity()
        if root == 'dev':
            self.check_dev_plan(saved, path)
        self.tf(root, 'show', str(path))
        if not confirm(f'Apply this {root} plan to account {self.settings["account"]}? AWS resources may incur charges.'):
            return
        # Consume the approval before execution, including failed/partial applies.
        self.settings['plans'].pop(root)
        self.save()
        self.tf(root, 'apply', '-input=false', str(path))
        self.outputs(root)

    def outputs(self, root):
        if root == 'dev':
            self.contract()
            print('Dev contract outputs saved.')
            return
        data = self.tf(root, 'output', '-json', capture=True)
        mapping = {'bucket': 'state_bucket', 'kms_key_arn': 'state_kms_arn'} if root == 'backend' else {'provider_arn': 'github_oidc_arn'}
        for key, setting in mapping.items():
            if key not in data:
                raise ValueError(f'Missing Terraform output {key}; apply the root first.')
            self.settings[setting] = data[key]['value']
        self.save()
        print('Terraform outputs saved.')

    def oidc_import(self):
        providers = self.aws('iam', 'list-open-id-connect-providers')['OpenIDConnectProviderList']
        matches = [p['Arn'] for p in providers if p['Arn'].endswith(':oidc-provider/token.actions.githubusercontent.com')]
        if not matches:
            print('No GitHub OIDC provider exists; choose plan to create one.')
            return
        arn = matches[0]
        print(f'Existing provider: {arn}')
        self.tf('github-oidc', 'init', '-input=false')
        state = self.tf('github-oidc', 'show', '-json', capture=True)
        resources = state.get('values', {}).get('root_module', {}).get('resources', [])
        for resource in resources:
            if resource['address'] == 'aws_iam_openid_connect_provider.github':
                if resource['values']['arn'] != arn:
                    raise ValueError('Terraform tracks a different provider; reconcile its state first.')
                print('Already tracked in this Terraform root.')
                self.outputs('github-oidc')
                return
        if confirm('Import this existing provider into the GitHub OIDC Terraform root?'):
            self.settings['plans'].pop('github-oidc', None)
            self.save()
            self.tf('github-oidc', 'import', '-input=false', f'-var=region={self.settings["region"]}',
                    'aws_iam_openid_connect_provider.github', arn)
            print('Imported. Generate a plan to review configuration and outputs.')

    def terraform_menu(self, root):
        print('1. Plan\n2. Review and apply saved plan\n3. Load Terraform outputs')
        if root == 'github-oidc':
            print('4. Detect/import existing GitHub provider (do this before first plan)')
        choice = ask('Selection (0 back)', '0')
        actions = {'1': lambda: self.plan(root), '2': lambda: self.apply(root), '3': lambda: self.outputs(root)}
        if root == 'github-oidc':
            actions['4'] = self.oidc_import
        if choice in actions:
            actions[choice]()

    def menu(self):
        while True:
            print('\nAWS deployment setup\n\nPrepare workstation and settings\n1. macOS prerequisite checks and installation\n2. Local verification / smoke\n3. Profile, region, identity and API hostname\n4. Alarm email, telemetry and repository settings\n\nPrepare AWS infrastructure\n5. Certificate and DNS validation\n6. Runner AMI / EC2 / PostgreSQL checks\n7. Terraform backend\n8. GitHub OIDC\n9. Dev infrastructure: configure / plan / apply / outputs\n\nConfigure services and runners\n10. API DNS / HTTPS / SNS confirmation\n11. Telemetry and API-login secrets\n12. JWT signing key\n13. Runner: status / connect / diagnose / repair\n14. GitHub runner registration and settings\n\nProgress and teardown\n15. Saved progress\n16. Destroy dev infrastructure (review required)\n0. Exit')
            choice = ask('Selection', '0')
            if choice == '0':
                return
            actions = {'1': setup_prerequisites.menu, '2': self.local_checks, '3': self.configure,
                       '4': self.configure_deployment, '5': self.certificate, '6': self.discover,
                       '7': lambda: self.terraform_menu('backend'), '8': lambda: self.terraform_menu('github-oidc'),
                       '9': self.dev_menu, '10': self.dns_check, '11': self.credentials_menu,
                       '12': self.signing_key, '13': self.runner_menu, '14': self.github_menu,
                       '15': lambda: print(json.dumps(self.settings, indent=2)), '16': self.destroy_menu}
            if choice not in actions:
                print('Choose a listed number.')
                continue
            try:
                if choice in {'5', '6', '7', '8', '9', '10', '11', '12', '13', '14'}:
                    self.identity()
                actions[choice]()
            except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
                print(f'Action failed: {exc}\nProgress retained. Resolve the error and retry the menu option.', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    os.umask(0o077)
    try:
        Setup(Path(__file__).resolve().parents[2]).menu()
        return 0
    except (EOFError, KeyboardInterrupt):
        print('\nExited. Saved settings remain available on the next run.')
        return 0
    except (ValueError, OSError) as exc:
        print(f'Unable to load setup: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
