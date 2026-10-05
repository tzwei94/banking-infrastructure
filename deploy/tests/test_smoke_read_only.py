import contextlib
import io
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'smoke.py'


class ReadOnlySmokeTest(unittest.TestCase):
    def test_read_only_release_smoke_never_requests_banking_accounts_or_cpu_work(self):
        paths = []

        def respond(request, **kwargs):
            path = request.full_url.removeprefix('https://example.test')
            paths.append((request.get_method(), path))
            bodies = {
                '/auth/token': {'token_type': 'Bearer', 'expires_in': 900, 'access_token': 'synthetic-test-token'},
                '/readyz': {'status': 'UP'}, '/livez': {'status': 'UP'},
                '/version': {'version': 'test', 'source': 'test'},
            }
            self.assertIn(path, bodies, 'Read-only mode must never request account routes or CPU work')
            return io.BytesIO(json.dumps(bodies[path]).encode())

        environment = {'API_URL': 'https://example.test', 'TOKEN_USERNAME': 'test',
                       'TOKEN_PASSWORD': 'test-only', 'READ_ONLY_SMOKE': 'true'}
        with patch.dict(os.environ, environment), patch('urllib.request.urlopen', side_effect=respond):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as stop:
                runpy.run_path(str(SCRIPT), run_name='__main__')
        self.assertEqual(stop.exception.code, 0)
        self.assertEqual(paths, [('POST', '/auth/token'), ('GET', '/readyz'), ('GET', '/livez'), ('GET', '/version')])

    def test_invalid_smoke_mode_fails_before_any_network_request(self):
        environment = {'API_URL': 'https://example.test', 'TOKEN_USERNAME': 'test',
                       'TOKEN_PASSWORD': 'test-only', 'READ_ONLY_SMOKE': 'typo'}
        with patch.dict(os.environ, environment), patch('urllib.request.urlopen') as network:
            with self.assertRaises(SystemExit):
                runpy.run_path(str(SCRIPT), run_name='__main__')
        network.assert_not_called()
