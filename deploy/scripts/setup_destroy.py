"""Explicit, dev-only teardown. Bootstrap roots are never passed to Terraform."""
import hashlib


PROTECTED = {
    'module.rds.aws_db_instance.database': 'deletion_protection',
    'module.alb.aws_lb.api': 'enable_deletion_protection',
}


class DestroyActions:
    def validate_teardown(self, plan, mode):
        if mode not in {'destroy', 'unprotect'}:
            raise ValueError('Unknown teardown mode.')
        for resource in plan.get('resource_changes', []):
            if resource.get('mode') != 'managed':
                continue
            change = resource['change']
            actions = change['actions']
            if actions == ['no-op']:
                continue
            address = resource['address']
            before = change.get('before') or {}
            after = change.get('after') or {}
            if mode == 'unprotect':
                key = PROTECTED.get(address)
                differences = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
                if actions != ['update'] or not key or differences != {key} or after.get(key) is not False:
                    raise ValueError(f'Expected protection-only update; unexpected change: {address}')
            else:
                if actions != ['delete']:
                    raise ValueError(f'Expected delete-only plan; unexpected change: {address}')
                if resource.get('type') == 'aws_ecr_repository':
                    images = self.aws('ecr', 'list-images', '--repository-name', before['name'], '--max-items', '1')
                    if images.get('imageIds'):
                        raise ValueError(f"ECR repository {before['name']} contains images. Archive/delete those images separately before teardown; this menu never force-deletes them.")
                key = PROTECTED.get(address)
                if key and before.get(key):
                    raise ValueError('Disable deletion protection using steps 1 and 2 first.')
                if address == 'module.rds.aws_db_instance.database':
                    if before.get('skip_final_snapshot') is not False or not before.get('final_snapshot_identifier'):
                        raise ValueError('RDS must retain a named final snapshot before destruction.')
                    print('Final RDS snapshot: ' + before['final_snapshot_identifier'])

    def teardown_plan(self, mode):
        if mode not in {'destroy', 'unprotect'}:
            raise ValueError('Unknown teardown mode.')
        self.identity()
        profile = self.dev_profile()
        for key in ('region', 'state_bucket', 'state_kms_arn'):
            if not profile.get(key) or profile[key] != self.settings.get(key):
                raise ValueError(f'Dev profile {key} differs from saved bootstrap settings.')
        self.settings['plans'].pop('dev-' + mode, None)
        self.save()
        self.tf('dev', 'init', '-input=false', f'-backend-config={self.dev_root}/backend.hcl')
        path = self.private / f'dev-{mode}.tfplan'
        args = ['-destroy'] if mode == 'destroy' else ['-var=deletion_protection=false', *[f'-target={address}' for address in PROTECTED]]
        self.tf('dev', 'plan', '-input=false', f'-var-file={self.dev_root}/dev.tfvars.json', *args, f'-out={path}')
        self.validate_teardown(self.tf('dev', 'show', '-json', str(path), capture=True), mode)
        self.record_plan('dev-' + mode, path)
        self.settings['plans']['dev-' + mode]['inputs'] = self.dev_fingerprint()
        self.save()
        print('Plan saved. Review/apply is a separate selection; no resources changed.')

    def teardown_apply(self, mode):
        if mode not in {'destroy', 'unprotect'}:
            raise ValueError('Unknown teardown mode.')
        key = 'dev-' + mode
        path = self.private / f'{key}.tfplan'
        saved = self.settings['plans'].get(key)
        self.identity()
        if not saved or not path.exists() or saved['context'] != self.context() or saved['sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('No matching saved teardown plan; generate a new plan.')
        if saved.get('inputs') != self.dev_fingerprint():
            raise ValueError('Configuration changed; generate a new teardown plan.')
        self.validate_teardown(self.tf('dev', 'show', '-json', str(path), capture=True), mode)
        self.tf('dev', 'show', str(path))
        phrase = f'{"DESTROY" if mode == "destroy" else "UNPROTECT"} dev {self.settings["account"]} {self.settings["region"]}'
        print('This deletes the dev infrastructure and stops the application.' if mode == 'destroy' else 'This disables RDS/ALB deletion protection. It does not destroy resources.')
        if input(f'Type exactly "{phrase}" to apply: ').strip() != phrase:
            print('Cancelled; no changes applied.')
            return
        # Consume all dev approvals before execution; partial failures require fresh plans.
        for name in ('dev', 'dev-destroy', 'dev-unprotect'):
            self.settings['plans'].pop(name, None)
        self.save()
        self.tf('dev', 'apply', '-input=false', str(path))
        if mode == 'destroy':
            for cached in (self.private / 'contract.json', self.deployment.parent / '.private/setup/contract.json'):
                cached.unlink(missing_ok=True)
            self.settings.pop('runner_command', None)
            self.save()
            print('Dev destruction completed. Backend state storage and GitHub OIDC remain. Final snapshots and other retained items may still incur charges.')
        else:
            print('Deletion protection disabled. Next: generate the destroy plan. If cancelling teardown, use option 9 to plan restoring protection from your profile.')

    def destroy_menu(self):
        print('\nDestroy DEV infrastructure only\nBackend S3/KMS, its state, and GitHub OIDC are preserved.\nRDS retains a final snapshot; secrets have a recovery window. Non-empty ECR repositories block deletion.\nPause GitHub deployment runs before teardown. External DNS, ACM and GitHub settings are not removed.\n1. Plan disabling RDS/ALB deletion protection\n2. Review/apply protection plan\n3. Preview and save destroy plan\n4. Review/apply destroy plan\n0. Back')
        choice = input('Selection [0]: ').strip()
        actions = {'1': lambda: self.teardown_plan('unprotect'), '2': lambda: self.teardown_apply('unprotect'),
                   '3': lambda: self.teardown_plan('destroy'), '4': lambda: self.teardown_apply('destroy')}
        if choice in actions:
            actions[choice]()
