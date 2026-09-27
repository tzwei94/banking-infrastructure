# Infrastructure and deployment tests

Run from the deployment repository root (`cd deployment` in the combined workspace) with Terraform >=1.10,<2.0, Docker and uv available. CI pins Terraform 1.16.1; provider and container downloads require network access:

```sh
make verify
```

This checks Terraform formatting and provider validation for both bootstrap roots and the dev root, runs mocked Terraform tests and Python tests, validates the bundled Alloy configuration using the pinned upstream image, and checks shell syntax for deployment/provisioning scripts. It does not build either custom image, run the runtime/volume scripts below, scan vulnerabilities or invoke actionlint. It does not apply infrastructure to AWS.

The Terraform tests cover release-plan restrictions, ECR retention, IAM scope and task definitions. Python tests cover deployment and rollback failures, bootstrap cleanup, CI profile validation, setup prerequisites, saved-plan approvals and teardown safeguards. For workflow changes, also run `actionlint` from this repository.

## Container checks

Build the API image as `banking-api:local` from the sibling application repository using its README instructions, then run:

```sh
docker build -t banking-alloy:local deploy/monitoring
ALLOY_IMAGE=banking-alloy:local uv run deploy/tests/check_alloy_runtime.py
API_IMAGE=banking-api:local ALLOY_IMAGE=banking-alloy:local \
  bash deploy/tests/test-container-volumes.sh
```

These checks create and clean up disposable containers, networks and named test volumes. They require Python >=3.11 for the uv script and pull a pinned Python fixture image. The runtime test checks service labels with alternate log/scrape paths and starts Alloy with a replacement configuration. This fixture verifies logs and metrics, plus mounted-config readiness; it does not send a trace. The volume test covers both Java-first and Alloy-first log-volume initialization, non-root writes, read-only collector access, CA readability and preservation of existing volumes.

Run `make smoke` from the sibling application repository for the full banking and telemetry test. See the [telemetry guide](../deploy/monitoring/README.md#local-verification) for image overrides and the [image scan record](../deploy/monitoring/security-review.md) for historical dependency findings; documentation edits do not refresh that scan. Publication reruns the scan gate.

Mocked plans and local containers do not exercise AWS permissions, Fargate volume initialization, RDS TLS, real release/rollback or remote monitoring storage. Verify those in the target environment before relying on the deployment.
