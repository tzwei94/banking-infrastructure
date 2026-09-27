# Infrastructure and deployment tests

Run from the deployment repository root with Terraform >=1.10,<2.0, Docker and uv available:

```sh
make verify
```

This checks Terraform formatting and provider validation for both bootstrap roots and the dev root, runs mocked Terraform tests and Python tests, validates the bundled Alloy configuration, and checks shell syntax. It does not apply infrastructure to AWS.

The Terraform tests cover release-plan restrictions, ECR retention, IAM scope and task definitions. Python tests cover deployment and rollback failures, bootstrap cleanup, CI profile validation, setup prerequisites, saved-plan approvals and teardown safeguards. For workflow changes, also run `actionlint` from this repository.

## Container checks

Build the API image from the sibling application repository, then run:

```sh
docker build -t banking-alloy:local deploy/monitoring
uv run deploy/tests/check_alloy_runtime.py
bash deploy/tests/test-container-volumes.sh
```

The runtime test checks service labels with alternate log/scrape paths and starts Alloy with a replacement configuration. The volume test covers both Java-first and Alloy-first log-volume initialization, non-root writes, read-only collector access, CA readability and preservation of existing volumes.

Run `make smoke` from the sibling application repository for the full banking and telemetry test. See the [telemetry guide](../deploy/monitoring/README.md#local-verification) for image overrides and the [image scan record](../deploy/monitoring/security-review.md) for dependency findings.

Mocked plans and local containers do not exercise AWS permissions, Fargate volume initialization, RDS TLS, real release/rollback or remote monitoring storage. Verify those in the target environment before relying on the deployment.
