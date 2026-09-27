#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${ALLOY_REPOSITORY:?}" "${SOURCE_SHA:?}" "${AWS_REGION:?}"
[[ $SOURCE_SHA =~ ^[a-f0-9]{40}$ && $ALLOY_REPOSITORY =~ ^[A-Za-z0-9.-]+/[A-Za-z0-9/_.-]+$ ]] || exit 2
umask 077
DOCKER_CONFIG=$(mktemp -d)
export DOCKER_CONFIG
trap 'rm -rf "$DOCKER_CONFIG"' EXIT
registry_host="${ALLOY_REPOSITORY%%/*}"
[[ $registry_host =~ ^[0-9]{12}\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com$ && ${BASH_REMATCH[1]} == "$AWS_REGION" ]] || { echo 'Image must use private ECR in AWS_REGION' >&2; exit 2; }
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$registry_host"
# Operator workstation: credentials with ECR push permission for the Alloy repository.
docker build --platform linux/amd64 -t "$ALLOY_REPOSITORY:$SOURCE_SHA" monitoring
docker run --rm -e ENVIRONMENT=check -e LOKI_URL=https://example.com/loki/api/v1/push -e METRICS_URL=https://example.com/api/v1/write -e TRACES_BASE_URL=https://example.com -e TELEMETRY_USERNAME=check -e TELEMETRY_PASSWORD=check "$ALLOY_REPOSITORY:$SOURCE_SHA" validate /etc/alloy/config.alloy
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969 image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$ALLOY_REPOSITORY:$SOURCE_SHA"
docker push "$ALLOY_REPOSITORY:$SOURCE_SHA"
docker image inspect "$ALLOY_REPOSITORY:$SOURCE_SHA" --format '{{index .RepoDigests 0}}'
