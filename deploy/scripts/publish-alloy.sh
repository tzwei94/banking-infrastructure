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
image_tag="$ALLOY_REPOSITORY:$SOURCE_SHA"
if [[ -n ${GITHUB_RUN_ID:-} ]]; then
  [[ $GITHUB_RUN_ID =~ ^[1-9][0-9]*$ && ${GITHUB_RUN_ATTEMPT:-} =~ ^[1-9][0-9]*$ ]] || exit 2
  image_tag="$ALLOY_REPOSITORY:sha-$SOURCE_SHA-$GITHUB_RUN_ID-$GITHUB_RUN_ATTEMPT"
fi
aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$registry_host"
# CI uses the dedicated OIDC publisher role; operators may use scoped AWS credentials.
docker build --platform linux/amd64 --label "org.opencontainers.image.revision=$SOURCE_SHA" -t "$image_tag" monitoring
docker run --rm -e ENVIRONMENT=check -e LOKI_URL=https://example.com/loki/api/v1/push -e METRICS_URL=https://example.com/api/v1/write -e TRACES_BASE_URL=https://example.com -e TELEMETRY_USERNAME=check -e TELEMETRY_PASSWORD=check "$image_tag" validate /etc/alloy/config.alloy
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.74.0@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969 image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$image_tag"
docker push "$image_tag"
docker image inspect "$image_tag" > "$DOCKER_CONFIG/published.json"
python3 - "$DOCKER_CONFIG/published.json" "$image_tag" <<'PY'
import json
import os
from pathlib import Path
import re
import sys

image, = json.loads(Path(sys.argv[1]).read_text())
repository = os.environ['ALLOY_REPOSITORY']
sha = os.environ['SOURCE_SHA']
digests = [value for value in image.get('RepoDigests', [])
           if re.fullmatch(re.escape(repository) + r'@sha256:[a-f0-9]{64}', value)]
if len(digests) != 1:
    raise SystemExit('Expected one published digest for the selected Alloy repository.')
if (image.get('Os') != 'linux' or image.get('Architecture') != 'amd64' or
        image.get('Config', {}).get('Labels', {}).get('org.opencontainers.image.revision') != sha):
    raise SystemExit('Published Alloy platform or source label does not match the build.')
digest = digests[0]
manifest = {'schema_version': 1, 'alloy_image': digest, 'image_tag': sys.argv[2],
            'alloy_source_sha': sha, 'repository': os.environ.get('GITHUB_REPOSITORY'),
            'run_id': int(os.environ['GITHUB_RUN_ID']) if os.environ.get('GITHUB_RUN_ID') else None,
            'run_attempt': int(os.environ['GITHUB_RUN_ATTEMPT']) if os.environ.get('GITHUB_RUN_ID') else None}
if os.environ.get('ALLOY_MANIFEST_PATH'):
    Path(os.environ['ALLOY_MANIFEST_PATH']).write_text(json.dumps(manifest, indent=2) + '\n')
if os.environ.get('GITHUB_OUTPUT'):
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write(f'alloy_image={digest}\n')
if os.environ.get('GITHUB_STEP_SUMMARY'):
    base = f"{os.environ['GITHUB_SERVER_URL']}/{os.environ['GITHUB_REPOSITORY']}"
    run = f"{base}/actions/runs/{manifest['run_id']}"
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
        stream.write(f'''## Alloy published — deployment input

Copy this value into **alloy_image** in [the deployment workflow]({base}/actions/workflows/deploy-dev.yml):

```text
{digest}
```

| Deployment input | Value or source |
| --- | --- |
| `alloy_image` | `{digest}` |
| `image` | Copy from the selected application publish or release summary. |
| `source_sha` | Copy from that same application summary. |
| `action` | `deploy` |
| `first_release` | `false`; use `true` only for the initial deployment after database bootstrap. |

Alloy source commit: `{sha}`. This is **not** the application's `source_sha`.

[Download the Alloy manifest from this run's artifacts]({run}#artifacts).
Publication does not deploy ECS. The manifest is retained for 90 days, subject to repository policy.
''')
print(digest)
PY
