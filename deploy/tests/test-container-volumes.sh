#!/usr/bin/env bash
# Fresh-volume contract for images used by read-only, non-root ECS tasks.
set -euo pipefail
: "${API_IMAGE:=banking-api:local}" "${ALLOY_IMAGE:=banking-alloy:local}"
prefix="volume-check-$(date +%s)-$$"
volumes=()
cleanup() { for volume in "${volumes[@]}"; do docker volume rm "$volume" >/dev/null; done; }
trap cleanup EXIT
for first in "$API_IMAGE" "$ALLOY_IMAGE"; do
  volume="$prefix-${#volumes[@]}"
  volumes+=("$volume")
  docker volume create "$volume" >/dev/null
  docker run --rm --read-only --entrypoint /bin/sh -v "$volume:/var/log/app" "$first" -ec '
    test "$(id -u)" = 10001
    touch /var/log/app/first
  '
  docker run --rm --read-only --entrypoint /bin/sh -v "$volume:/var/log/app" "$API_IMAGE" -ec '
    test "$(id -u)" = 10001
    test -s /opt/app/certs/rds-ca.pem
    test -r /opt/app/certs/rds-ca.pem
    touch /tmp/volume-check /var/log/app/application.log
  '
  docker run --rm --read-only --entrypoint /bin/sh -v "$volume:/var/log/app:ro" "$ALLOY_IMAGE" -ec '
    test "$(id -u)" = 10001
    test -r /var/log/app/application.log
    touch /var/lib/alloy/data/volume-check
    if touch /var/log/app/forbidden 2>/dev/null; then exit 1; fi
  '
done
volume="$prefix-existing"
volumes+=("$volume")
docker volume create "$volume" >/dev/null
docker run --rm --user 0:0 --entrypoint /bin/sh -v "$volume:/old" "$API_IMAGE" -ec 'chown 0:0 /old; chmod 700 /old; echo preserve > /old/sentinel'
if docker run --rm --read-only --entrypoint /bin/sh -v "$volume:/var/log/app" "$API_IMAGE" -ec 'touch /var/log/app/forbidden' 2>/dev/null; then
  echo 'FAIL: application unexpectedly wrote to existing root-owned volume' >&2
  exit 1
fi
docker run --rm --user 0:0 --entrypoint /bin/sh -v "$volume:/old:ro" "$API_IMAGE" -ec 'test "$(cat /old/sentinel)" = preserve; test "$(stat -c %u /old)" = 0'
echo 'PASS: both volume initialization orders, image-local trust, non-root writes, read-only logs and preserved existing volumes'
