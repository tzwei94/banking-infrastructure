"""Exercise the actual embedded CI profile builder without contacting AWS/Docker."""
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = re.search(r"python - <<'PY'\n(.*?)\nPY", (Path(__file__).parents[1] / 'scripts/ci-release.sh').read_text(), re.S).group(1)


class ProfileTests(unittest.TestCase):
    def run_builder(self, directory, name='banking-dev'):
        env = {**os.environ,
            'DEV_TFVARS_JSON': json.dumps({'name': 'banking-dev', 'region': 'ap-southeast-1',
                'state_bucket': 'test-state', 'state_kms_arn': 'arn:aws:kms:ap-southeast-1:123456789012:key/test'}),
            'IMAGE': 'registry/api@sha256:' + 'a' * 64, 'ALLOY_IMAGE': 'registry/alloy@sha256:' + 'b' * 64,
            'SOURCE_SHA': 'c' * 40, 'NAME': name, 'AWS_REGION': 'ap-southeast-1', 'STATE_BUCKET': 'test-state',
            'RELEASE_CONFIG': str(Path(directory) / 'config.json'), 'RELEASE_BACKEND': str(Path(directory) / 'backend.hcl')}
        return subprocess.run([sys.executable, '-c', SCRIPT], env=env, capture_output=True, text=True)
    def test_dev_backend_retains_locking_and_selected_kms_key(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_builder(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            backend = (Path(directory) / 'backend.hcl').read_text()
            self.assertIn('key = "dev/terraform.tfstate"', backend)
            self.assertIn('use_lockfile = true', backend)
            self.assertIn('kms_key_id = "arn:aws:kms:ap-southeast-1:123456789012:key/test"', backend)
            profile = json.loads((Path(directory) / 'config.json').read_text())
            self.assertFalse(profile['seed_synthetic'])
    def test_conflicting_dev_identity_is_rejected_before_profile_is_written(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_builder(directory, 'wrong-environment')
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(directory) / 'config.json').exists())
