#!/usr/bin/env python3
"""Operator-only bootstrap in dev state; always revoke the temporary capability."""
import argparse
import json
from release import Release


def bootstrap(release):
    release.manifest()  # A failed preflight authorizes no cleanup or mutation.
    release.verify_image()
    release.initialize()
    existing = json.loads(release.command(['terraform', f'-chdir={release.root}', 'output', '-json']))
    if existing.get('active_task_definition_arn', {}).get('value'):
        raise RuntimeError('An active service exists; bootstrap is first-deployment only')
    try:
        outputs = release.apply(None, bootstrap_enabled=True, allow_bootstrap_changes=True)
        release.run_task(outputs['bootstrap_arn']['value'], outputs['run_task']['value'], 'bootstrap')
    finally:
        release.apply(None, allow_bootstrap_changes=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    parser.add_argument('--backend', required=True)
    parser.add_argument('--manifest-bucket', required=True)
    args = parser.parse_args()
    release = Release(args.config, args.backend, args.manifest_bucket, first=True)
    try:
        bootstrap(release)
    finally:
        release.tmp.cleanup()
    print('Database initialized; bootstrap task and IAM role removed. Run first release next.')


if __name__ == '__main__':
    main()
