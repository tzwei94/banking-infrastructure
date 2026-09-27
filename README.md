# Banking deployment

For first-time setup from the main repository, follow the ordered **[AWS setup guide](../SETUP.md)**. This document is the detailed deployment reference.

Run `uv run deploy/scripts/setup.py` for the interactive preparation menu (macOS prerequisites, AWS profile, certificate/DNS, preflight checks, Terraform roots, secrets, runner repair/registration, GitHub settings and explicit dev teardown). Settings resume from ignored `.private/setup/`; see the parent setup guide for details.

Terraform, GitHub Actions, EC2 runner provisioning and release scripts for the companion banking API. Releases deploy immutable image digests.

Terraform has two bootstrap roots, `infra/bootstrap/backend` and `infra/bootstrap/github-oidc`, reusable modules under `infra/modules`, and one application environment at `infra/environments/dev`. Dev owns networking, IAM, ALB, RDS, ECS, runner, secrets metadata, alarms and task/service resources in one S3 state key, `dev/terraform.tfstate`.

Application release scripts use that same root. A saved-plan allowlist rejects every managed change except the application's ECS task definitions and service; infrastructure drift requires an operator plan first. The deployment IAM role has refresh/read permissions and ECS mutation permissions, without IAM/network/RDS write permissions. Release automation can read the shared dev state, so restrict repository, environment and state-bucket access to trusted operators. Terraform state and plan files remain private.

```text
infra/
  bootstrap/backend/
  bootstrap/github-oidc/
  modules/{networking,security,alb,rds,secrets,iam,runner,cloudwatch,ecs-cluster,ecs-service}/
  environments/dev/    # backend, providers, versions, variables, main, outputs, examples and tests
deploy/
  scripts/
  monitoring/
  provisioning/
  tests/
.github/workflows/
  terraform-ci.yml
  deploy-dev.yml
```

The architecture uses two private tasks across two AZs, one NAT, HTTP ALB→Java, isolated single-AZ RDS with verified TLS, and one SSM-only EC2 runner. Initial sizing and one-week budget are planning assumptions, not load or cost guarantees. Terraform owns private ECR repositories; the monitoring operator supplies Grafana/Prometheus/Loki/Tempo; this repository contains no homelab installation or Cloudflare configuration.

## Local validation

```sh
deploy/scripts/validate.sh
```

Requires Terraform >=1.10,<2.0, Docker and uv. This runs formatting/provider validation for both bootstrap roots and dev, Terraform tests using mock AWS data (no AWS calls), release failure-path tests and Alloy validation. The application repository supplies PostgreSQL acceptance/container tests. Mock plans establish code contracts, not AWS deployability in an unconfigured account. Commit each root's `.terraform.lock.hcl` with its provider checksums.

## Prepare AWS

Review the [account compatibility and budget guide](../docs/budget.md) first. The default `t3.medium` runner is not listed for the AWS Free plan; the example profile selects `t3.small` (2 GiB), whose build capacity still needs testing. Credits do not guarantee access to every service or sufficient quotas.

If upgrading from the earlier foundation/platform/release layout, follow the [state migration notes](docs/state-migration.md) before applying this root.

1. Select the account/region, authenticate with a short-lived operator session, and verify `aws sts get-caller-identity`. Obtain the ACM certificate, API hostname, alarm recipient and a reviewed fixed Amazon Linux 2023 x86_64 AMI. Verify PostgreSQL 17 availability in the selected region.
2. Plan/apply `infra/bootstrap/backend` with a globally unique bucket name. Preserve its local state, then add an S3 backend block and run `terraform init -migrate-state` for that bootstrap root with its own `bootstrap/backend/terraform.tfstate` key when ready. It owns the protected, encrypted/versioned state bucket and KMS key.
3. Plan/apply `infra/bootstrap/github-oidc` once per AWS account. Import an existing provider instead of creating a duplicate. Preserve its independent state and record `provider_arn`; add an S3 backend block and migrate this bootstrap root under its own `bootstrap/github-oidc/terraform.tfstate` key after backend creation.
4. Copy `infra/environments/dev/backend.hcl.example` to ignored `backend.hcl`, and `dev.tfvars.json.example` to ignored `dev.tfvars.json`. Fill the entire non-secret dev profile, including the OIDC ARN, state/KMS details, certificate/AMI, final snapshot name and tested app/Alloy digest/SHA. Secrets Manager values are populated separately. Keep `service_enabled=false` and `bootstrap_enabled=false` for the initial infrastructure apply.
5. Initialize the dev root, create and inspect a saved operator plan, then apply it. Set up DNS, confirm the SNS subscription and verify private routing/SSM reachability. A configuration's hostname is not a verified service.

From this repository:

```sh
terraform -chdir=infra/environments/dev init -backend-config="$PWD/infra/environments/dev/backend.hcl"
terraform -chdir=infra/environments/dev plan -var-file="$PWD/infra/environments/dev/dev.tfvars.json" -out=dev.tfplan
terraform -chdir=infra/environments/dev apply dev.tfplan
```

Before **later operator plans**, synchronize the profile's `service_enabled` and `active_task_definition_arn` with the successful deployment manifest (and current verified service), as well as its image/SHA inputs. Reusing the initial service-disabled profile after deployment would plan to remove the service. Application release scripts set these fields from the successful manifest automatically and preserve the old ARN until migration succeeds.

## External endpoints and secrets

Apply the dev root as an operator to create immutable ECR repositories `${name}/banking-api` and `${name}/banking-alloy`. Read their URLs from `terraform output -json contract` (`ecr_repositories`). CI uses OIDC plus ECR login; Fargate uses execution-role IAM. Confirm real image push/pull and a fresh Fargate pull. Configure verified external telemetry endpoints separately; `example.com` addresses are placeholders.

Terraform creates secret metadata, never values. Pipe protected JSON to `uv run --no-project python deploy/scripts/populate-secret.py SECRET_ARN` (optionally `--region REGION`). Do not paste secret values into shell command arguments or Terraform variables.

| Secret | JSON fields | Consumer |
|---|---|---|
| `telemetry` | `username`, `password` | Alloy Basic auth over HTTPS |
| `jwt-signing` | `private_key` (PKCS#8 PEM) | Shared RS256 signing and validation key |
| `token-auth` | `username`, `password` | Basic authentication for `POST /auth/token` |
| `app-db` | Created by DB bootstrap | Runtime only |
| `migration-db` | Created by DB bootstrap | Migration only |

ECR push and pull permissions are separated by IAM role. RDS manages its master secret. A temporary bootstrap ECS role creates the two restricted database users and secret values. The normal task role has no AWS data permissions. Injected secret rotation requires replacing tasks. Keep JWT private keys out of source control. ECS injects the shared signing key into API tasks from Secrets Manager.

## Runner and images

User data installs Docker, Git, Java 25, Maven and AWS CLI on Amazon Linux 2023. Use SSM to run `deploy/provisioning/register-runner.sh OWNER/REPO app|deploy VERSION SHA256` for the reviewed GitHub runner release archive; the script prompts silently for a short-lived registration token. Register two services for personal repositories, under `runner-app` and `runner-deploy`, with the corresponding labels. Both users can administer the shared Docker daemon: they are equally trusted. Repository protection and refusing all untrusted PR jobs on this host are mandatory. Build and deployment scripts acquire `/var/lock/banking/host.lock` for the full job.

Protect both `main` branches and restrict the deployment environment `dev` to that branch and approved operators. The dev IAM OIDC trust matches the exact application main ref and deployment environment. Hosted runners validate PRs. Set app workflow variables listed in its README. The deployment workflow needs `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `STATE_BUCKET`, `API_URL`, the `DEV_TFVARS_JSON` environment variable containing the complete non-secret dev profile, and `TOKEN_USERNAME` / `TOKEN_PASSWORD` environment secrets matching `token-auth`. The smoke check calls `/auth/token` after the service is healthy, so no pre-generated token or private key is stored in Actions.

Publish the tested application first. Build/publish the configured Alloy image from this repository with `deploy/scripts/publish-alloy.sh`, using operator AWS credentials and `ALLOY_REPOSITORY`, `SOURCE_SHA`, `AWS_REGION`. The script validates Alloy and scans the image before push. The pinned Alloy 1.20.0 image passed the recorded scan; see the [scan record](deploy/monitoring/security-review.md). Publication reruns the scan. Record the published digest. The release profile requires digest-pinned application and Alloy images; mutable tags are rejected.

## Database bootstrap and release

Copy `infra/environments/dev/dev.tfvars.json.example` to the ignored `dev.tfvars.json` profile and fill image digests and the full application source SHA. Authenticate Docker to ECR using `aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${IMAGE%%/*}"` and an isolated `DOCKER_CONFIG`. Run the operator-only first bootstrap:

```sh
uv run --no-project python deploy/scripts/bootstrap-database.py \
  --config "$PWD/infra/environments/dev/dev.tfvars.json" \
  --backend "$PWD/infra/environments/dev/backend.hcl" \
  --manifest-bucket YOUR_STATE_BUCKET
```

It refuses an existing successful manifest or active service, temporarily enables the dev bootstrap role, prepares an isolated bootstrap task, runs it, deregisters that definition and removes the role. Confirm the cleanup apply succeeded before release. A failed command stops; inspect restricted CloudWatch logs and reconcile Terraform before retrying. It is not a general credential-rotation procedure.

Then dispatch the protected deployment workflow with the tested digest/SHA pair, Alloy digest and `first_release=true`. Later runs leave that flag false. The script checks the image's source label and executes:

1. **Prepare:** register retained candidate app/migration definitions while pinning the service to the successful manifest's old ARN. First release has no service.
2. **Migrate:** run one private ECS task with migration credentials, await successful exit and capture the Liquibase changeset count. Failure leaves the old service active.
3. **Promote:** apply the candidate ARN through Terraform. Require two running tasks, two healthy ALB targets and authenticated smoke tests. Failure reconciles Terraform to the old ARN (or no service on first release).
4. **Record:** write digest, SHA, schema version, current/prior ARNs and workflow run into the versioned S3 manifest. A record failure requires operator reconciliation; do not blindly retry against an old manifest.

`release.py deploy` can also run locally using the same config/backend/manifest arguments plus `API_URL`, `TOKEN_USERNAME` and `TOKEN_PASSWORD` in its environment. `--first-release` is explicit and accepted only when the manifest does not exist. A network/permission error reading S3 never becomes a first deployment.

Migrations must remain backward compatible with the old application during rollout. For application rollback, dispatch `action=rollback`; this applies the retained prior ARN and updates the manifest after health/smoke checks. It never reverses DB migrations. Circuit-breaker rollback is explicitly reconciled through Terraform. No script calls `ecs update-service` or registers competing task definitions.

For manual post-deployment API checks, use the application's [Postman collection and setup guide](https://github.com/tzwei94/app/tree/main/postman). Import the collection and environment template, set the public HTTPS `base_url`, and set `token_username` / `token_password` and send **Get token** to fill `api_token`. Keep certificate verification enabled. The default banking sequence deposits, retries, and withdraws the same amount on the synthetic account.

## Operations and cleanup

See [telemetry configuration](deploy/monitoring/README.md). Confirm alarms and test one notification using a controlled CloudWatch alarm state; the SNS subscription and email delivery are separate acceptance checks. Stop the runner outside build windows. Install runner-local Alloy with `deploy/provisioning/install-runner-alloy.sh VERSION SHA256`, after provisioning a root-only `/etc/alloy/runner.env` containing the metrics URL and scoped telemetry credentials. The host exporter reports disk/CPU/memory to Prometheus as `job="banking-runner"`; add a Grafana disk alert such as available bytes / size < 15%. The AWS runner alarm separately covers EC2 status. Daily cost review remains necessary: the account-wide monthly US$100 budget alert is neither a spending cap nor a one-week enforcement mechanism.

RDS defaults to seven days of encrypted backups and a final snapshot. Set `db_backup_retention_period` explicitly for account restrictions; a value of `1` keeps automated backups with a one-day recovery window. `deploy/scripts/restore-rds.sh SOURCE_DB SNAPSHOT NEW_DB_ID` creates a separate private restore with the source subnet/security/parameter groups and deletion protection. Verify schema and expected synthetic account data from an isolated ECS task before any endpoint cutover; this script intentionally performs no cutover. Record actual restore duration and results. Retain ECR release images needed for rollback.

Before teardown, disable workflow dispatch, unregister both runner services with fresh removal tokens, export evidence and retain required DB snapshots. Explicitly apply `deletion_protection=false` in the dev operator profile, choose a unique final snapshot ID, and archive/empty the ALB log bucket if destroying it. Set `DEV_VARS` and `DEV_BACKEND` to the absolute dev profile/backend paths. `deploy/scripts/teardown.sh --plan` only shows destroy plans; `--apply` destroys the one dev root. Retained task definitions can be deregistered afterward; they incur no running-task charge. Backend state/KMS, GitHub OIDC bootstrap, snapshots and external monitoring resources remain. Review residual charges and retention before separately removing state storage.

See [test coverage and verification commands](docs/local-verification.md).

All application replicas require the same `jwt-signing` key and `token-auth` credentials. The token subject defaults to `alice`, matching the synthetic seed. Upgrading an existing installation requires an operator Terraform plan/apply first to create the new secret metadata and update execution-role IAM (the application release plan deliberately rejects infrastructure changes), then populating the new secrets and setting the two GitHub environment secrets; old pre-generated smoke tokens are no longer used. Rollback targets must also support `/auth/token`.

### Java runtime and RDS trust

The application image is an executable-JAR runtime with its checksum-verified RDS CA at `/opt/app/certs/rds-ca.pem`. ECS supplies `LOG_PATH=/var/log/app`, `JAVA_TOOL_OPTIONS`, and matching writable volumes. Java and Alloy prepare compatible volume ownership in their Dockerfiles, then run directly as UID/GID 10001. App tasks contain Java and Alloy; migration and bootstrap tasks run their Java command alone. All database clients retain `sslmode=verify-full` using the image-local certificate.

The reusable Alloy image has no database certificate or initialization script. Its bundled configuration takes the service name, log glob, scrape target/path/interval/timeout and OTLP HTTP listener from environment variables. A mounted config can replace it for other applications; see [reuse and mount examples](deploy/monitoring/README.md#reuse-this-image). Rebuild and publish both Java and Alloy images for the new task definitions; retain old image digests and task revisions for rollback.

## Registry migration and retention

For an existing installation, use an operator Terraform plan/apply to create ECR, update IAM and remove the old registry secret resources (seven-day recovery window). The application-only release workflow intentionally rejects infrastructure changes. Publish both images to ECR, update `IMAGE_REPOSITORY`, the release profile and GitHub `DEV_TFVARS_JSON`, then deploy new digest-pinned task definitions. Remove obsolete registry-secret GitHub variables. Keep the previous registry, credentials and task revisions available until its rollback window closes; old task revisions still reference their original registry.

ECR uses immutable tags, encryption at rest and basic scan-on-push; the existing Trivy publication gate still applies. Only untagged images expire after seven days. Tagged release images stay available for rollback and must be pruned deliberately. Alloy uses its source SHA as an immutable tag: reuse the existing digest for that commit, or publish a new committed revision. Terraform refuses to delete nonempty repositories (`force_delete=false`); inspect and explicitly empty them only when retiring the environment. Operator Alloy publication requires `ecr:GetAuthorizationToken` plus repository-scoped layer upload, `PutImage`, `BatchGetImage` and layer download permissions for the Alloy repository; the application build role can push only the API repository.
