#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
: "${DEV_TFVARS_JSON:?}" "${IMAGE:?}" "${ALLOY_IMAGE:?}" "${SOURCE_SHA:?}" "${STATE_BUCKET:?}" "${AWS_REGION:?}" "${NAME:?}"
# Workflow inputs are data, never shell-expanded code or Terraform expressions.
exec 9>/var/lock/banking/host.lock
flock 9
umask 077
scratch=$(mktemp -d)
export DOCKER_CONFIG="$scratch/docker"
mkdir "$DOCKER_CONFIG"
trap 'rm -rf "$scratch"' EXIT
registry_host="${IMAGE%%/*}"
[[ $registry_host =~ ^[0-9]{12}\.dkr\.ecr\.([a-z0-9-]+)\.amazonaws\.com$ && ${BASH_REMATCH[1]} == "$AWS_REGION" ]] || { echo 'Image must use private ECR in AWS_REGION' >&2; exit 2; }
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$registry_host"
export RELEASE_CONFIG="$scratch/release.tfvars.json" RELEASE_BACKEND="$scratch/backend.hcl"
uv run --no-project python - <<'PY'
import json,os
from pathlib import Path
v=json.loads(os.environ['DEV_TFVARS_JSON'])
identity={'name':os.environ['NAME'],'region':os.environ['AWS_REGION'],'state_bucket':os.environ['STATE_BUCKET']}
if any(v.get(k)!=value for k,value in identity.items()):
    raise SystemExit('Dev profile identity must match workflow configuration')
v.update({k:os.environ[e] for k,e in [('image','IMAGE'),('alloy_image','ALLOY_IMAGE'),('source_sha','SOURCE_SHA'),('state_bucket','STATE_BUCKET'),('region','AWS_REGION'),('name','NAME')]})
# This is a synthetic-account demonstration, explicitly seeded by its migration task.
v.setdefault('seed_synthetic',False)
Path(os.environ['RELEASE_CONFIG']).write_text(json.dumps(v))
Path(os.environ['RELEASE_BACKEND']).write_text('\n'.join(f'{k} = {json.dumps(v)}' for k,v in {'bucket':os.environ['STATE_BUCKET'],'key':'dev/terraform.tfstate','region':os.environ['AWS_REGION'],'encrypt':True,'use_lockfile':True,'kms_key_id':v['state_kms_arn']}.items()))
PY
args=()
[[ ${FIRST_RELEASE:-false} == true ]] && args+=(--first-release)
uv run --no-project python deploy/scripts/release.py "${ACTION:-deploy}" --config "$RELEASE_CONFIG" --backend "$RELEASE_BACKEND" --manifest-bucket "$STATE_BUCKET" "${args[@]}"
