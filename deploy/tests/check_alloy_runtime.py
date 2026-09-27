# /// script
# requires-python = ">=3.11"
# dependencies = ["python-snappy==0.7.3"]
# ///
"""Run real Alloy against a disposable HTTP receiver; no cloud credentials needed.

Usage: ALLOY_IMAGE=banking-alloy:local uv run deploy/tests/check_alloy_runtime.py
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def serve():
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def record(self, body=b''):
            with lock, open('/fixture/events.jsonl', 'a') as output:
                output.write(json.dumps({'path': self.path, 'method': self.command,
                                         'body': base64.b64encode(body).decode()}) + '\n')

        def do_GET(self):
            self.record()
            body = b'# TYPE fixture_requests_total counter\nfixture_requests_total 1\n'
            self.send_response(200)
            self.send_header('Content-Type', 'text/plain; version=0.0.4')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            self.record(self.rfile.read(int(self.headers.get('Content-Length', 0))))
            self.send_response(200)
            self.end_headers()

    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()


def check():
    import snappy
    image = os.getenv('ALLOY_IMAGE', 'banking-alloy:local')
    prefix = 'alloy-check-' + uuid.uuid4().hex[:10]
    names = []

    def docker(*args, **kwargs):
        return subprocess.check_output(['docker', *args], text=True, **kwargs).strip()

    def run(name, *args):
        names.append(name)
        return docker('run', '-d', '--name', name, '--network', prefix, *args)

    def events(path):
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def wait_for(predicate, description):
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.5)
        raise AssertionError(description)

    docker('network', 'create', prefix)
    try:
        with tempfile.TemporaryDirectory(prefix=prefix) as directory:
            fixture = Path(directory)
            fixture.chmod(0o755)
            (fixture / 'check.py').write_text(Path(__file__).read_text())
            (fixture / 'inventory.log').write_text('reusable-alloy-log\n')
            (fixture / 'check.py').chmod(0o644)
            (fixture / 'inventory.log').chmod(0o644)
            run(prefix + '-sink', '--network-alias', 'receiver', '-v', f'{fixture}:/fixture',
                'python:3.13.7-alpine@sha256:9ba6d8cbebf0fb6546ae71f2a1c14f6ffd2fdab83af7fa5669734ef30ad48844',
                'python', '/fixture/check.py', 'serve')
            env = {'ENVIRONMENT': 'test', 'SERVICE_NAME': 'inventory-api',
                   'LOG_GLOB': '/input/inventory.log', 'METRICS_TARGET': 'receiver:8080',
                   'METRICS_PATH': '/custom-metrics', 'METRICS_SCRAPE_INTERVAL': '1s',
                   'METRICS_SCRAPE_TIMEOUT': '1s',
                   'OTLP_HTTP_ADDRESS': '0.0.0.0:4318',
                   'LOKI_URL': 'http://receiver:8080/logs', 'METRICS_URL': 'http://receiver:8080/write',
                   'TRACES_BASE_URL': 'http://receiver:8080',
                   'TELEMETRY_USERNAME': 'test', 'TELEMETRY_PASSWORD': 'test'}
            env_args = [arg for key, value in env.items() for arg in ('-e', f'{key}={value}')]
            run(prefix + '-alloy', '--read-only', '-v', f'{fixture}:/input:ro', *env_args, image)
            records = fixture / 'events.jsonl'

            def delivered():
                rows = events(records)
                metrics = [snappy.decompress(base64.b64decode(r['body'])) for r in rows
                           if r['method'] == 'POST' and r['path'] == '/write']
                logs = [snappy.decompress(base64.b64decode(r['body'])) for r in rows
                        if r['method'] == 'POST' and r['path'] == '/logs']
                return (any(r['path'] == '/custom-metrics' for r in rows)
                        and any(b'inventory-api' in body and b'fixture_requests_total' in body for body in metrics)
                        and any(b'inventory-api' in body and b'reusable-alloy-log' in body for body in logs))

            wait_for(delivered, 'Alternate service/log glob/scrape settings did not deliver labeled telemetry')
            print('PASS: alternate service, log glob, metrics target/path and labeled delivery')

            replacement = fixture / 'replacement.alloy'
            replacement.write_text('logging { level = "warn" }\n')
            replacement.chmod(0o644)
            name = prefix + '-override'
            run(name, '--read-only', '-p', '127.0.0.1::12345',
                '-v', f'{replacement}:/etc/alloy/config.alloy:ro', image, 'run',
                '--server.http.listen-addr=0.0.0.0:12345', '--storage.path=/var/lib/alloy/data',
                '/etc/alloy/config.alloy')
            port = docker('port', name, '12345/tcp').rsplit(':', 1)[1]

            def ready():
                try:
                    with urllib.request.urlopen(f'http://127.0.0.1:{port}/-/ready', timeout=2) as response:
                        return response.status == 200
                except (OSError, urllib.error.URLError):
                    return False

            wait_for(ready, 'Mounted replacement configuration did not become ready')
            print('PASS: mounted replacement config runs without bundled-pipeline environment')
    except Exception:
        for name in names:
            subprocess.run(['docker', 'logs', '--tail', '15', name], check=False)
        raise
    finally:
        for name in reversed(names):
            subprocess.run(['docker', 'rm', '-fv', name], stdout=subprocess.DEVNULL, check=False)
        docker('network', 'rm', prefix)


if __name__ == '__main__':
    serve() if sys.argv[1:] == ['serve'] else check()
