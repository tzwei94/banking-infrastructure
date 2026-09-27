mock_provider "aws" {
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-southeast-1a", "ap-southeast-1b"] }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/banking-dev-test" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:ap-southeast-1:123456789012:secret:test-123456" }
  }
  mock_resource "aws_db_instance" {
    defaults = {
      address            = "test.rds.amazonaws.com"
      master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:ap-southeast-1:123456789012:secret:master-123456", secret_status = "active", kms_key_id = "test" }]
    }
  }
  mock_resource "aws_ecs_cluster" {
    defaults = { arn = "arn:aws:ecs:ap-southeast-1:123456789012:cluster/banking-dev" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:loadbalancer/app/banking-dev/0123456789abcdef" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:ap-southeast-1:123456789012:targetgroup/banking-dev/0123456789abcdef" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:ap-southeast-1:123456789012:banking-dev-alarms" }
  }
}
override_resource {
  target = module.ecr.aws_ecr_repository.images["banking-api"]
  values = { arn = "arn:aws:ecr:ap-southeast-1:123456789012:repository/banking-dev/banking-api", repository_url = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-api" }
}
override_resource {
  target = module.ecr.aws_ecr_repository.images["banking-alloy"]
  values = { arn = "arn:aws:ecr:ap-southeast-1:123456789012:repository/banking-dev/banking-alloy", repository_url = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-alloy" }
}
variables {
  name                      = "banking-dev"
  state_bucket              = "banking-test-state"
  state_kms_arn             = "arn:aws:kms:ap-southeast-1:123456789012:key/00000000-0000-0000-0000-000000000001"
  github_owner              = "example"
  github_oidc_arn           = "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"
  certificate_arn           = "arn:aws:acm:ap-southeast-1:123456789012:certificate/00000000-0000-0000-0000-000000000001"
  alarm_email               = "test@example.com"
  runner_ami_id             = "ami-0123456789abcdef0"
  final_snapshot_identifier = "banking-dev-test-final"
  image                     = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-api@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  alloy_image               = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-alloy@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  source_sha                = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
}
run "first_prepare_does_not_start_service" {
  command = apply
  assert {
    condition     = alltrue([for repo in values(module.ecr.repositories) : repo.image_tag_mutability == "IMMUTABLE" && !repo.force_delete && repo.image_scanning_configuration[0].scan_on_push])
    error_message = "Release repositories must prevent tag replacement and accidental image deletion, and enable scanning."
  }
  assert {
    condition     = anytrue([for statement in module.iam.build_policy.Statement : contains(statement.Action, "ecr:PutImage") && statement.Resource == module.ecr.repositories["banking-api"].arn]) && alltrue([for statement in module.iam.deploy_policy.Statement : !contains(statement.Action, "ecr:PutImage")])
    error_message = "Only the build role may push application images; the deploy role must remain pull-only."
  }
  assert {
    condition = alltrue([for key, policy in module.iam.execution_image_policies :
      anytrue([for statement in policy.Statement : contains(statement.Action, "ecr:GetAuthorizationToken") && statement.Resource == "*"]) &&
      anytrue([for statement in policy.Statement : contains(statement.Action, "ecr:BatchGetImage") && try(toset(statement.Resource) == toset(key == "app" ? [module.ecr.repositories["banking-api"].arn, module.ecr.repositories["banking-alloy"].arn] : [module.ecr.repositories["banking-api"].arn]), false)])
    ])
    error_message = "All execution roles need ECR authentication and repository-scoped image reads."
  }
  assert {
    condition = alltrue([for task in [module.ecs_service.aws_ecs_task_definition_app, module.ecs_service.aws_ecs_task_definition_migration] :
      alltrue([for c in jsondecode(task.container_definitions) : !contains(keys(c), "repositoryCredentials")])
    ])
    error_message = "ECR pulls must use execution-role IAM without private registry credentials."
  }
  assert {
    condition = alltrue([for action in ["s3:ListBucket", "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration"] :
      anytrue([for statement in module.iam.deploy_policy.Statement :
        contains(statement.Action, action) && statement.Resource == "arn:aws:s3:::banking-dev-alb-123456789012"
      ])
    ])
    error_message = "The release role must support all S3 bucket refresh reads required by the pinned AWS provider."
  }
  assert {
    condition     = length(module.ecs_service.service) == 0 && length(module.ecs_service.aws_ecs_task_definition_bootstrap) == 0
    error_message = "Preparation must not start a service or retain bootstrap capability by default."
  }
  assert {
    condition     = module.ecs_service.aws_ecs_task_definition_app.skip_destroy && module.ecs_service.aws_ecs_task_definition_migration.skip_destroy
    error_message = "Rollback task definitions must be retained."
  }
  assert {
    condition     = toset([for c in jsondecode(module.ecs_service.aws_ecs_task_definition_app.container_definitions) : c.name]) == toset(["app", "alloy"])
    error_message = "Application tasks must run Java and Alloy without an initializer."
  }
  assert {
    condition = alltrue([for task in [module.ecs_service.aws_ecs_task_definition_app, module.ecs_service.aws_ecs_task_definition_migration] :
      alltrue([for c in jsondecode(task.container_definitions) :
        c.user == "10001:10001" && c.readonlyRootFilesystem &&
        contains(c.mountPoints, { sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }) &&
        anytrue([for env in c.environment : endswith(env.value, "sslmode=verify-full&sslrootcert=/opt/app/certs/rds-ca.pem") if env.name == "DB_URL"])
        if contains(["app", "migration"], c.name)
      ]) && !contains([for v in task.volume : v.name], "certs")
    ])
    error_message = "Database clients need image-local verified trust and writable temporary storage, without a certificate volume."
  }
  assert {
    condition = alltrue([for c in jsondecode(module.ecs_service.aws_ecs_task_definition_app.container_definitions) :
      contains(c.mountPoints, { sourceVolume = "logs", containerPath = "/var/log/app", readOnly = c.name == "alloy" })
    ])
    error_message = "Java must write the shared logs while Alloy reads them at the generic path."
  }
  assert {
    condition = alltrue([for c in jsondecode(module.ecs_service.aws_ecs_task_definition_app.container_definitions) :
      alltrue([for env in [
        { name = "SERVICE_NAME", value = "banking-api" },
        { name = "LOG_GLOB", value = "/var/log/app/application*.log" },
        { name = "METRICS_TARGET", value = "127.0.0.1:9000" },
        { name = "METRICS_PATH", value = "/actuator/prometheus" }
      ] : contains(c.environment, env)]) if c.name == "alloy"
    ])
    error_message = "Banking telemetry settings must be passed to the generic Alloy configuration."
  }
  assert {
    condition     = length(jsondecode(module.ecs_service.aws_ecs_task_definition_migration.container_definitions)) == 1 && alltrue([for c in jsondecode(module.ecs_service.aws_ecs_task_definition_migration.container_definitions) : c.name == "migration" && length(try(c.dependsOn, [])) == 0])
    error_message = "Migrations must run independently of Alloy and runtime initialization."
  }

}
run "prepare_retains_explicit_previous_revision" {
  command = plan
  variables {
    service_enabled            = true
    active_task_definition_arn = "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/banking-dev-app:7"
  }
  assert {
    condition     = module.ecs_service.service[0].task_definition == "arn:aws:ecs:ap-southeast-1:123456789012:task-definition/banking-dev-app:7"
    error_message = "Candidate preparation must not implicitly promote the candidate."
  }
  assert {
    condition     = module.ecs_service.service[0].desired_count == 2 && !module.ecs_service.service[0].network_configuration[0].assign_public_ip
    error_message = "The service must have two private tasks."
  }
}
run "invalid_image_is_rejected" {
  command = plan
  variables { image = "123456789012.dkr.ecr.ap-southeast-1.amazonaws.com/banking-dev/banking-api:latest" }
  expect_failures = [var.image]
}

run "bootstrap_uses_image_local_rds_trust" {
  command = apply
  variables { bootstrap_enabled = true }
  assert {
    condition = length(jsondecode(module.ecs_service.aws_ecs_task_definition_bootstrap[0].container_definitions)) == 1 && alltrue([
      for c in jsondecode(module.ecs_service.aws_ecs_task_definition_bootstrap[0].container_definitions) :
      !contains(keys(c), "repositoryCredentials") && c.name == "bootstrap" && c.user == "10001:10001" && c.readonlyRootFilesystem && length(try(c.dependsOn, [])) == 0 &&
      contains(c.mountPoints, { sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }) &&
      anytrue([for env in c.environment : endswith(env.value, "sslmode=verify-full&sslrootcert=/opt/app/certs/rds-ca.pem") if env.name == "DB_URL"])
    ])
    error_message = "Bootstrap must use image-local verified database trust and writable temporary storage without an initializer."
  }
}

run "backup_retention_defaults_to_seven_days" {
  command = plan
  assert {
    condition     = module.rds.aws_db_instance_database.backup_retention_period == 7
    error_message = "The standard environment must retain seven days of automated backups."
  }
}

run "backup_retention_can_use_one_day" {
  command = plan
  variables {
    db_backup_retention_period = 1
  }
  assert {
    condition     = module.rds.aws_db_instance_database.backup_retention_period == 1
    error_message = "The restricted account profile must pass one-day retention through to RDS."
  }
}

run "immutable_github_subjects_keep_context_restrictions" {
  command = plan
  variables {
    github_app_subject_prefix        = "repo:example@123/banking-api@456"
    github_deployment_subject_prefix = "repo:example@123/banking-deployment@789"
  }
  assert {
    condition     = jsondecode(module.iam.aws_iam_role_build.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example@123/banking-api@456:ref:refs/heads/main"
    error_message = "Immutable build subjects must remain restricted to main."
  }
  assert {
    condition     = jsondecode(module.iam.aws_iam_role_deploy.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example@123/banking-deployment@789:environment:dev"
    error_message = "Immutable deploy subjects must remain restricted to dev."
  }
}
run "legacy_github_subjects_remain_supported" {
  command = plan
  assert {
    condition     = jsondecode(module.iam.aws_iam_role_build.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example/banking-api:ref:refs/heads/main"
    error_message = "Legacy repositories must keep their exact name-based subject."
  }
}

run "alloy_publisher_can_push_only_alloy_from_deployment_main" {
  command = apply
  assert {
    condition = alltrue([for statement in module.iam.alloy_publish_policy.Statement :
      statement.Resource == module.ecr.repositories["banking-alloy"].arn ||
      (statement.Resource == "*" && statement.Action == ["ecr:GetAuthorizationToken"])
    ]) && anytrue([for statement in module.iam.alloy_publish_policy.Statement : contains(statement.Action, "ecr:PutImage")])
    error_message = "Alloy publishing must have ECR push access only to the Alloy repository."
  }
  assert {
    condition     = jsondecode(module.iam.aws_iam_role_alloy_publish.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example/banking-deployment:ref:refs/heads/main"
    error_message = "Alloy publishing must trust only deployment main, not PRs or other branches."
  }
  assert {
    condition     = jsondecode(module.iam.aws_iam_role_alloy_publish.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:aud"] == "sts.amazonaws.com"
    error_message = "Alloy publishing must require the AWS OIDC audience."
  }
}

run "alloy_publisher_supports_immutable_repository_subjects" {
  command = plan
  variables { github_deployment_subject_prefix = "repo:example@123/banking-deployment@789" }
  assert {
    condition     = jsondecode(module.iam.aws_iam_role_alloy_publish.assume_role_policy).Statement[0].Condition.StringEquals["token.actions.githubusercontent.com:sub"] == "repo:example@123/banking-deployment@789:ref:refs/heads/main"
    error_message = "Immutable Alloy publishing subjects must retain the main branch restriction."
  }
}

run "runner_user_data_preserves_registered_instance" {
  command = plan
  assert {
    condition     = module.runner.aws_instance_runner.user_data_replace_on_change == false
    error_message = "User-data edits must preserve the registered runner instance."
  }
}
