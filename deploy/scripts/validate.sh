#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
terraform fmt -check -recursive infra
for root in infra/bootstrap/backend infra/bootstrap/github-oidc infra/environments/dev; do
  terraform -chdir="$root" init -backend=false -input=false >/dev/null
  terraform -chdir="$root" validate
done
terraform -chdir=infra/environments/dev test
uv run --no-project python -m unittest discover -s deploy/tests -v
docker run --rm -e ENVIRONMENT=test -e LOKI_URL=http://localhost:3100/loki/api/v1/push -e METRICS_URL=http://localhost:9090/api/v1/write -e TRACES_BASE_URL=http://localhost:4318 -e TELEMETRY_USERNAME=test -e TELEMETRY_PASSWORD=test -v "$PWD/deploy/monitoring/config.alloy:/etc/alloy/config.alloy:ro" grafana/alloy:v1.20.0@sha256:f111cce835516c5f99166342be7038496b52ced16667be5a11e19258a3e4cd30 validate /etc/alloy/config.alloy
for script in deploy/scripts/*.sh deploy/provisioning/*.sh; do bash -n "$script"; done
