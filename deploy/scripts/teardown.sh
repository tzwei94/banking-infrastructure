#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
mode=${1:---plan}
[[ $mode == --plan || $mode == --apply ]] || exit 2
: "${DEV_VARS:?}" "${DEV_BACKEND:?}"
umask 077
plan=$(mktemp)
trap 'rm -f "$plan"' EXIT
terraform -chdir=infra/environments/dev init -input=false -backend-config="$DEV_BACKEND"
terraform -chdir=infra/environments/dev plan -destroy -input=false -var-file="$DEV_VARS" -out="$plan"
if [[ $mode == --apply ]]; then terraform -chdir=infra/environments/dev apply -input=false "$plan"; fi
printf '%s\n' 'Backend/OIDC bootstrap, retained RDS snapshots and Tools remain. Review residual charges.'
