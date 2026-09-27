# Banking deployment

For first-time setup from the main repository, follow the ordered **[AWS setup guide](../SETUP.md)**. This document is the detailed deployment reference. Commands below run from the deployment checkout (`cd deployment` from the parent workspace); the application checkout is its sibling `../app`. The parent setup and budget guides are available in the combined workspace.

Run `uv run deploy/scripts/setup.py` for the interactive preparation menu (macOS prerequisites, AWS profile, certificate/DNS, preflight checks, Terraform roots, secrets, runner repair/registration, GitHub settings and explicit dev teardown). Settings resume from ignored `.private/setup/`; see the parent setup guide for details.

Terraform, GitHub Actions, EC2 runner provisioning and release scripts for the companion banking API. Releases deploy immutable image digests.

Terraform has two bootstrap roots, `infra/bootstrap/backend` and `infra/bootstrap/github-oidc`, reusable modules under `infra/modules`, and one application environment at `infra/environments/dev`. Dev owns networking, IAM, ALB, RDS, ECS, runner, secrets metadata, alarms and task/service resources in one S3 state key, `dev/terraform.tfstate`.

Application release scripts use that same root. A saved-plan allowlist rejects every managed change except the application's ECS task definitions and service; infrastructure drift requires an operator plan first. The deployment IAM role has refresh/read permissions and ECS mutation permissions, without IAM resource-management, network or RDS write permissions (`iam:PassRole` is allowed for the ECS roles). Release automation can read the shared dev state, so restrict repository, environment and state-bucket access to trusted operators. Terraform state and plan files remain private.

```text
infra/
  bootstrap/backend/
  bootstrap/github-oidc/
  modules/{networking,security,alb,rds,secrets,iam,runner,cloudwatch,ecr,ecs-cluster,ecs-service}/
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

Users resolve the API hostname through an operator-managed Cloudflare DNS-only CNAME pointing to the ALB, then connect directly to the ALB over HTTPS. The architecture uses two private tasks across two AZs, one NAT, HTTP ALB→Java, isolated single-AZ RDS with verified TLS, and one SSM-only EC2 runner. Initial sizing and one-week budget are planning assumptions, not load or cost guarantees. Terraform owns private ECR repositories; the monitoring operator supplies Grafana/Prometheus/Loki/Tempo; this repository contains no homelab installation or Cloudflare configuration.

## Local validation

```sh
deploy/scripts/validate.sh
```

Requires Terraform >=1.10,<2.0, Docker and uv. This runs formatting/provider validation for both bootstrap roots and dev, Terraform tests using mock AWS data (no AWS calls), all deployment Python unit tests, bundled Alloy configuration validation and shell syntax checks. Provider/image downloads may require network access. It does not run the real Alloy runtime or container-volume checks; see the local verification guide below. The application repository supplies PostgreSQL acceptance/container tests. Mock plans establish code contracts, not AWS deployability in an unconfigured account. Commit each root's `.terraform.lock.hcl` with its provider checksums.

## Prepare AWS

Review the [account compatibility and budget guide](../docs/budget.md) first. The default `t3.medium` runner is not listed for the AWS Free plan; the example profile selects `t3.small` (2 GiB), whose publication/deployment capacity still needs testing; Java builds run on GitHub-hosted runners. Credits do not guarantee access to every service or sufficient quotas.

If upgrading from the earlier foundation/platform/release layout, follow the [state migration notes](docs/state-migration.md) before applying this root.

1. Select the account/region, authenticate with a short-lived operator session, and verify `aws sts get-caller-identity`. Obtain the ACM certificate, API hostname, alarm recipient and a reviewed fixed Amazon Linux 2023 x86_64 AMI. Verify PostgreSQL 17 availability in the selected region.
2. Plan/apply `infra/bootstrap/backend` with a globally unique bucket name. Preserve its local state, then add an S3 backend block and run `terraform init -migrate-state` for that bootstrap root with its own `bootstrap/backend/terraform.tfstate` key when ready. It owns the protected, encrypted/versioned state bucket and KMS key.
3. Plan/apply `infra/bootstrap/github-oidc` once per AWS account. Import an existing provider instead of creating a duplicate. Preserve its independent state and record `provider_arn`; add an S3 backend block and migrate this bootstrap root under its own `bootstrap/github-oidc/terraform.tfstate` key after backend creation.
4. Copy `infra/environments/dev/backend.hcl.example` to ignored `backend.hcl`, and `dev.tfvars.json.example` to ignored `dev.tfvars.json`. Fill the entire non-secret dev profile, including the OIDC ARN, state/KMS details, certificate/AMI and final snapshot name. For initial infrastructure creation before ECR publication, the setup helper writes syntactically valid all-zero image digests and source SHA; keep the service and bootstrap disabled, then replace these placeholders with published, tested digests and the real application SHA before bootstrap/release. The literal `REPLACE` examples do not pass Terraform validation. Secrets Manager values are populated separately. Keep `service_enabled=false` and `bootstrap_enabled=false` for the initial infrastructure apply.
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

User data installs Docker, Git, Java 25, Maven and AWS CLI on Amazon Linux 2023. Use SSM to run `deploy/provisioning/register-runner.sh OWNER/REPO KIND VERSION SHA256` (replace `KIND` with `app` or `deploy`) for the reviewed GitHub runner release archive; the script prompts silently for a short-lived registration token. Register two services for the two repositories, under `runner-app` and `runner-deploy`, with the corresponding labels. Both users can administer the shared Docker daemon: they are equally trusted. Repository protection and refusing all untrusted PR jobs on this host are mandatory. The application workflow’s image-push step and the deployment `ci-release.sh` hold `/var/lock/banking/host.lock` while they run; other workflow steps are outside that lock. Registration installs a systemd-tmpfiles rule to recreate the lock after reboot. Local operator release/bootstrap and Alloy publication do not acquire this lock: schedule them outside runner work.

Changes to EC2 user data keep the existing instance (`user_data_replace_on_change=false`); cloud-init does not rerun the provisioning script automatically. Use the setup menu’s runner repair action to apply reviewed provisioning changes over SSM, then verify Docker, Java and the runner services. A historical cloud-init error may remain after successful manual repair. Registration handles Amazon Linux 2023 runtime dependencies directly.

Protect both `main` branches and restrict the deployment environment `dev` to that branch and approved operators. The dev IAM OIDC trust matches the exact application main ref and deployment environment. Hosted runners validate PRs. The optional `github_app_subject_prefix` and `github_deployment_subject_prefix` inputs accept the exact GitHub repository subject prefix, including `repo:OWNER@ID/REPO@ID` when used by the repository. Null defaults to `repo:OWNER/REPO`; Terraform appends the main-ref or environment suffix. Copy the actual repository prefix and apply trust changes as an operator; the setup menu does not discover these optional values.

Set app workflow variables listed in its README. The deployment workflow needs `AWS_DEPLOY_ROLE_ARN`, `AWS_REGION`, `STATE_BUCKET`, `API_URL`, the `DEV_TFVARS_JSON` environment variable containing the complete non-secret dev profile, and `TOKEN_USERNAME` / `TOKEN_PASSWORD` environment secrets matching `token-auth`. The workflow fixes `NAME=banking-dev` and environment `dev`; `DEV_TFVARS_JSON.name`, `.region` and `.state_bucket` must match the workflow settings. A migrated deployment with a different name needs a reviewed workflow change before dispatch. Keep `seed_synthetic=true` for the demo smoke account; the CI wrapper defaults missing seed settings to false. The smoke check calls `/auth/token` after the service is healthy, so no pre-generated token or private key is stored in Actions.

Publish the tested application first through its Application CI workflow. That workflow builds/tests on hosted runners and pushes the scanned image on `banking-app`; use the resulting `image-manifest` artifact’s digest and source SHA for deployment. An application GitHub release records that existing image and is a separate operation; it does not deploy ECS.

Publish Alloy through [I. Publish Alloy Image](.github/workflows/publish-alloy.yml): run it manually on `main`. Publication is manual-only; pushes do not trigger it. It builds Linux AMD64, validates Alloy, scans with Trivy and pushes that same image on an isolated GitHub-hosted runner. It never deploys ECS. Fixable HIGH/CRITICAL vulnerabilities stop publication; see the historical [scan record](deploy/monitoring/security-review.md) for context, not a substitute for the current scan.

Before its first run, apply the operator Terraform change that creates the dedicated Alloy publisher role. The application release workflow rejects infrastructure changes, so it cannot create this role. Configure these **repository variables** (not `dev` environment variables):

| Variable | Value from the dev Terraform contract |
| --- | --- |
| `AWS_REGION` | The environment's AWS region. |
| `AWS_ALLOY_PUBLISH_ROLE_ARN` | `alloy_publish_role_arn` |
| `ALLOY_REPOSITORY` | `ecr_repositories["banking-alloy"]` |

The setup menu's **Configure GitHub variables and token secrets** action writes these along with existing deployment settings and the app repository's `DEPLOYMENT_REPOSITORY` summary link target. The Alloy role trusts only this deployment repository's `main` branch, with support for its configured immutable GitHub subject prefix. It can push only to Alloy's ECR repository.

After publication, the run summary shows the exact **`alloy_image`** to copy and a deployment workflow link. Download `alloy-image-manifest-RUN_ID-ATTEMPT` for the digest, immutable tag and `alloy_source_sha`. Artifacts are retained for 90 days, subject to repository policy; retain the selected digest for future rollbacks. Copy **`image` and `source_sha`** from the same successful app publish/release summary. Use `action=deploy` and normally `first_release=false`. The summary explains the initial-deployment exception. Alloy's commit is not the application's `source_sha`.

For operator publication, `deploy/scripts/publish-alloy.sh` remains available with scoped AWS credentials and `ALLOY_REPOSITORY`, `SOURCE_SHA`, `AWS_REGION`, Docker and Python 3. It validates and scans before pushing, prints the exact repository digest and optionally writes a manifest to an absolute `ALLOY_MANIFEST_PATH`. The release profile requires digest-pinned application and Alloy images; mutable tags are rejected.

## Database bootstrap and release

Copy `infra/environments/dev/dev.tfvars.json.example` to the ignored `dev.tfvars.json` profile and fill image digests and the full application source SHA. Authenticate Docker to ECR using `aws ecr get-login-password --region "$AWS_REGION" | docker login --username AWS --password-stdin "${IMAGE%%/*}"` and an isolated `DOCKER_CONFIG`. Run the operator-only first bootstrap:

```sh
uv run --no-project python deploy/scripts/bootstrap-database.py \
  --config "$PWD/infra/environments/dev/dev.tfvars.json" \
  --backend "$PWD/infra/environments/dev/backend.hcl" \
  --manifest-bucket YOUR_STATE_BUCKET
```

It refuses an existing successful manifest or active service, temporarily enables the dev bootstrap role, prepares an isolated bootstrap task, runs it, deregisters that definition and removes the role. Confirm the cleanup apply succeeded before release. Cleanup is attempted in a `finally` block after the bootstrap apply begins, including on task failure. A failed cleanup can leave temporary resources; inspect restricted CloudWatch logs and reconcile Terraform before retrying. Only explicit ECS role-assumption failures for the newly created bootstrap role receive bounded retries. It is not a general credential-rotation procedure.

Then dispatch the protected deployment workflow with the tested digest/SHA pair, Alloy digest and `first_release=true`. Later runs leave that flag false. The script checks the image's source label and executes:

1. **Prepare:** register retained candidate app/migration definitions while pinning the service to the successful manifest's old ARN. First release has no service.
2. **Migrate:** run one private ECS task with migration credentials, await successful exit and capture the Liquibase changeset count. Failure leaves the old service active.
3. **Promote:** apply the candidate ARN through Terraform. Require two running tasks, two healthy ALB targets and authenticated smoke tests. Failure reconciles Terraform to the old ARN (or no service on first release).
4. **Record:** write digest, SHA, schema version, current/prior ARNs and workflow run into the versioned S3 manifest. A record failure requires operator reconciliation; do not blindly retry against an old manifest.

`uv run --no-project python deploy/scripts/release.py deploy` can also run locally using the same config/backend/manifest arguments plus `API_URL`, `TOKEN_USERNAME` and `TOKEN_PASSWORD` in its environment. It requires AWS CLI, Terraform, Docker, appropriate operator AWS credentials and an existing Docker ECR login for image verification. Terraform/ECS command failures save private diagnostics under `.private/setup/diagnostics/`; inspect those files locally without publishing their contents. `--first-release` is explicit and accepted only when the manifest does not exist. A network/permission error reading S3 never becomes a first deployment.

Migrations must remain backward compatible with the old application during rollout. For application rollback, dispatch `action=rollback` with `first_release=false`; the workflow still requires valid `image`, `alloy_image` and `source_sha` inputs. Rollback selects its service target from `prior_active_task_definition_arn` in the manifest, applies the retained prior ARN and updates the manifest after health/smoke checks. It never reverses DB migrations. Circuit-breaker rollback is explicitly reconciled through Terraform. No script calls `ecs update-service` or registers competing task definitions.

For manual post-deployment API checks, use the application's [Postman collection and setup guide](https://github.com/tzwei94/app/tree/main/postman). Import the collection and environment template, set the public HTTPS `base_url`, and set `token_username` / `token_password` and send **Get token** to fill `api_token`. Keep certificate verification enabled. The default banking sequence deposits, retries, and withdraws the same amount on the synthetic account.

## Operations and cleanup

See [telemetry configuration](deploy/monitoring/README.md). Confirm alarms and test one notification using a controlled CloudWatch alarm state; the SNS subscription and email delivery are separate acceptance checks. Stop the runner outside build windows. Install runner-local Alloy with `deploy/provisioning/install-runner-alloy.sh VERSION SHA256`, after provisioning a root-only `/etc/alloy/runner.env` containing the metrics URL and scoped telemetry credentials. The host exporter reports disk/CPU/memory to Prometheus as `job="banking-runner"`; add a Grafana disk alert such as available bytes / size < 15%. The AWS runner alarm separately covers EC2 status. Daily cost review remains necessary: the account-wide monthly US$100 budget alert is neither a spending cap nor a one-week enforcement mechanism.

RDS defaults to seven days of encrypted backups and a final snapshot. Set `db_backup_retention_period` explicitly for account restrictions; a value of `1` keeps automated backups with a one-day recovery window. `deploy/scripts/restore-rds.sh SOURCE_DB SNAPSHOT NEW_DB_ID` creates a separate private, single-AZ `db.t4g.micro` restore with the source subnet group, first security group, first parameter group and deletion protection. Set `AWS_REGION` explicitly outside Singapore (the script defaults to `ap-southeast-1`); AWS CLI and `jq` are required. Verify schema and expected synthetic account data from an isolated ECS task before any endpoint cutover; this script intentionally performs no cutover. Record actual restore duration and results. Retain ECR release images needed for rollback.

Before teardown, disable workflow dispatch, unregister both runner services with fresh removal tokens, export evidence and retain required DB snapshots. Explicitly apply `deletion_protection=false` in the dev operator profile, choose a unique final snapshot ID, and archive/empty the ALB log bucket if destroying it. Set `DEV_VARS` and `DEV_BACKEND` to the absolute dev profile/backend paths. The setup menu provides separate protection-change and destroy plans with saved-plan validation and explicit review/apply steps. The lower-level `deploy/scripts/teardown.sh --plan` only shows a destroy plan; `--apply` generates and immediately applies a fresh plan for the one dev root, without the setup menu’s safeguards. ECR repositories must also be explicitly emptied before their deletion can succeed. Retained task definitions can be deregistered afterward; they incur no running-task charge. Backend state/KMS, GitHub OIDC bootstrap, snapshots and external monitoring resources remain. Review residual charges and retention before separately removing state storage.

See [test coverage and verification commands](docs/local-verification.md).

All application replicas require the same `jwt-signing` key and `token-auth` credentials. The token subject defaults to `alice`, matching the synthetic seed. Upgrading an existing installation requires an operator Terraform plan/apply first to create the new secret metadata and update execution-role IAM (the application release plan deliberately rejects infrastructure changes), then populating the new secrets and setting the two GitHub environment secrets; old pre-generated smoke tokens are no longer used. Rollback targets must also support `/auth/token`.

### Java runtime and RDS trust

The application image is an executable-JAR runtime with its checksum-verified RDS CA at `/opt/app/certs/rds-ca.pem`. ECS supplies `LOG_PATH=/var/log/app`, `JAVA_TOOL_OPTIONS`, and matching writable volumes. Java and Alloy prepare compatible volume ownership in their Dockerfiles, then run directly as UID/GID 10001. App tasks contain Java and Alloy; migration and bootstrap tasks run their Java command alone. All database clients retain `sslmode=verify-full` using the image-local certificate.

The reusable Alloy image has no database certificate or initialization script. Its bundled configuration takes the service name, log glob, scrape target/path/interval/timeout and OTLP HTTP listener from environment variables. A mounted config can replace it for other applications; see [reuse and mount examples](deploy/monitoring/README.md#reuse-this-image). When upgrading from the older initializer layout, rebuild and publish both Java and Alloy images for the matching task definitions; retain old image digests and task revisions for rollback.

## Registry migration and retention

For an existing installation, use an operator Terraform plan/apply to create ECR, update IAM and remove the old registry secret resources (seven-day recovery window). The application-only release workflow intentionally rejects infrastructure changes. Publish both images to ECR, update `IMAGE_REPOSITORY`, the release profile and GitHub `DEV_TFVARS_JSON`, then deploy new digest-pinned task definitions. Remove obsolete registry-secret GitHub variables. Keep the previous registry, credentials and task revisions available until its rollback window closes; old task revisions still reference their original registry.

ECR uses immutable tags, encryption at rest and basic scan-on-push; the existing Trivy publication gate still applies. Only untagged images expire after seven days. Tagged release images stay available for rollback and must be pruned deliberately. The Alloy workflow uses `sha-SOURCE_SHA-RUN_ID-ATTEMPT` tags, so reruns never overwrite an immutable tag. Operator publication outside Actions retains the source-SHA tag: reuse an existing digest for that commit or publish a new committed revision. Terraform refuses to delete nonempty repositories (`force_delete=false`); inspect and explicitly empty them only when retiring the environment. Alloy's publisher role has ECR token access and repository-scoped layer upload, `PutImage`, `BatchGetImage` and layer download permissions; the application build role can push only the API repository, and the deployment role remains pull-only.
