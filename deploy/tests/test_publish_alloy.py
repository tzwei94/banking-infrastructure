"""Run the publisher with Docker/AWS replaced at the external process boundary."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).parents[1] / 'scripts/publish-alloy.sh'
REPOSITORY = '123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-alloy'
SHA = 'c' * 40
DIGEST = REPOSITORY + '@sha256:' + 'b' * 64


class PublishAlloyTests(unittest.TestCase):
    def publish(self, fail='', digests=None, attempt='2'):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = {'Id': 'sha256:' + 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64',
                     'Config': {'Labels': {'org.opencontainers.image.revision': SHA}},
                     'RepoDigests': digests if digests is not None else ['other/image@sha256:' + 'd' * 64, DIGEST]}
            (root / 'inspect.json').write_text(json.dumps([image]))
            for executable, body in {
                'aws': 'echo test-token\n',
                'docker': '''echo "$*" >> "$TEST_ROOT/commands"
case "$1" in
  login) cat >/dev/null ;;
  run) if [ "$FAIL" = validate ] && [ "$2" = --rm ] && ! echo "$*" | grep -q aquasec/trivy; then exit 1; fi
       if [ "$FAIL" = scan ] && echo "$*" | grep -q aquasec/trivy; then exit 1; fi ;;
  push) if [ "$FAIL" = push ]; then exit 1; fi ;;
  image) cat "$TEST_ROOT/inspect.json" ;;
esac
'''
            }.items():
                path = root / executable
                path.write_text('#!/bin/sh\n' + body)
                path.chmod(0o755)
            env = {**os.environ, 'PATH': str(root) + os.pathsep + os.environ['PATH'],
                   'TEST_ROOT': directory, 'FAIL': fail, 'ALLOY_REPOSITORY': REPOSITORY,
                   'SOURCE_SHA': SHA, 'AWS_REGION': 'ap-southeast-1', 'GITHUB_RUN_ID': '42',
                   'GITHUB_RUN_ATTEMPT': attempt, 'GITHUB_REPOSITORY': 'example/deployment',
                   'GITHUB_SERVER_URL': 'https://github.com', 'GITHUB_STEP_SUMMARY': str(root / 'summary'),
                   'GITHUB_OUTPUT': str(root / 'output'), 'ALLOY_MANIFEST_PATH': str(root / 'manifest.json')}
            result = subprocess.run(['bash', str(SCRIPT)], env=env, text=True, capture_output=True)
            return result, {name: (root / name).read_text() if (root / name).exists() else ''
                            for name in ['commands', 'summary', 'output', 'manifest.json']}

    def test_published_digest_is_copyable_and_manifest_preserves_alloy_provenance(self):
        result, files = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(files['manifest.json'])['alloy_image'], DIGEST)
        self.assertEqual(json.loads(files['manifest.json'])['alloy_source_sha'], SHA)
        self.assertIn('alloy_image=' + DIGEST, files['output'])
        self.assertIn(DIGEST, files['summary'])
        self.assertIn('deploy-dev.yml', files['summary'])
        self.assertIn('source_sha', files['summary'])
        self.assertIn('push ' + REPOSITORY + ':sha-' + SHA + '-42-2', files['commands'])

    def test_validation_scan_and_push_failures_never_emit_deployable_output(self):
        for stage in ['validate', 'scan', 'push']:
            with self.subTest(stage=stage):
                result, files = self.publish(fail=stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(files['manifest.json'], '')
                self.assertEqual(files['summary'], '')
                self.assertEqual(files['output'], '')
                if stage != 'push':
                    self.assertNotIn('\npush ', '\n' + files['commands'])

    def test_wrong_repository_or_malformed_digest_never_emits_deployment_input(self):
        for digests in [[], ['other/image@sha256:' + 'b' * 64], [REPOSITORY + '@sha256:bad']]:
            with self.subTest(digests=digests):
                result, files = self.publish(digests=digests)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(files['manifest.json'], '')
                self.assertEqual(files['output'], '')

    def test_rerun_uses_a_new_immutable_tag(self):
        result, files = self.publish(attempt='3')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('push ' + REPOSITORY + ':sha-' + SHA + '-42-3', files['commands'])
