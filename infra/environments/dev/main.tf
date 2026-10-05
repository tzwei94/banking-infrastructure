module "ecr" {
  source = "../../modules/ecr"
  name   = var.name
}

module "alb" {
  source                 = "../../modules/alb"
  aws_security_group_alb = module.security.aws_security_group_alb
  aws_subnet_public      = module.networking.aws_subnet_public
  aws_vpc_main           = module.networking.aws_vpc_main
  certificate_arn        = var.certificate_arn
  deletion_protection    = var.deletion_protection
  name                   = var.name
}

module "cloudwatch" {
  source                   = "../../modules/cloudwatch"
  alarm_email              = var.alarm_email
  aws_db_instance_database = module.rds.aws_db_instance_database
  aws_ecs_cluster_main     = module.ecs_cluster.aws_ecs_cluster_main
  aws_instance_runner      = module.runner.aws_instance_runner
  aws_lb_api               = module.alb.aws_lb_api
  aws_lb_target_group_api  = module.alb.aws_lb_target_group_api
  name                     = var.name
}

module "ecs_cluster" {
  source = "../../modules/ecs-cluster"
  name   = var.name
}

module "ecs_service" {
  memory_headroom_enabled           = var.memory_headroom_enabled
  memory_autoscaling_enabled        = var.memory_autoscaling_enabled
  cpu_demo_enabled                  = var.cpu_demo_enabled
  autoscaling_enabled               = var.autoscaling_enabled
  source                            = "../../modules/ecs-service"
  active_task_definition_arn        = var.active_task_definition_arn
  alloy_image                       = var.alloy_image
  aws_cloudwatch_log_group_tasks    = module.cloudwatch.aws_cloudwatch_log_group_tasks
  aws_db_instance_database          = module.rds.aws_db_instance_database
  aws_ecs_cluster_main              = module.ecs_cluster.aws_ecs_cluster_main
  aws_iam_role_bootstrap            = module.iam.aws_iam_role_bootstrap
  aws_iam_role_execution            = module.iam.aws_iam_role_execution
  aws_iam_role_task                 = module.iam.aws_iam_role_task
  aws_lb_target_group_api           = module.alb.aws_lb_target_group_api
  aws_secretsmanager_secret_runtime = module.secrets.aws_secretsmanager_secret_runtime
  aws_security_group_app            = module.security.aws_security_group_app
  aws_subnet_private                = module.networking.aws_subnet_private
  bootstrap_enabled                 = var.bootstrap_enabled
  image                             = var.image
  jwt_audience                      = var.jwt_audience
  jwt_issuer                        = var.jwt_issuer
  loki_url                          = var.loki_url
  metrics_url                       = var.metrics_url
  name                              = var.name
  region                            = var.region
  seed_synthetic                    = var.seed_synthetic
  service_enabled                   = var.service_enabled
  source_sha                        = var.source_sha
  traces_base_url                   = var.traces_base_url
}

module "iam" {
  github_app_subject_prefix         = var.github_app_subject_prefix
  github_deployment_subject_prefix  = var.github_deployment_subject_prefix
  source                            = "../../modules/iam"
  app_repository                    = var.app_repository
  aws_db_instance_database          = module.rds.aws_db_instance_database
  ecr_repository_arns               = { for key, repo in module.ecr.repositories : key => repo.arn }
  aws_secretsmanager_secret_runtime = module.secrets.aws_secretsmanager_secret_runtime
  bootstrap_enabled                 = var.bootstrap_enabled
  deployment_repository             = var.deployment_repository
  github_environment                = var.github_environment
  github_oidc_arn                   = var.github_oidc_arn
  github_owner                      = var.github_owner
  name                              = var.name
  region                            = var.region
  state_bucket                      = var.state_bucket
  state_kms_arn                     = var.state_kms_arn
}

module "networking" {
  source   = "../../modules/networking"
  vpc_cidr = var.vpc_cidr
}

module "rds" {
  source                      = "../../modules/rds"
  db_backup_retention_period  = var.db_backup_retention_period
  aws_security_group_database = module.security.aws_security_group_database
  aws_subnet_database         = module.networking.aws_subnet_database
  deletion_protection         = var.deletion_protection
  final_snapshot_identifier   = var.final_snapshot_identifier
  name                        = var.name
}

module "runner" {
  source                    = "../../modules/runner"
  aws_security_group_runner = module.security.aws_security_group_runner
  aws_subnet_private        = module.networking.aws_subnet_private
  name                      = var.name
  runner_ami_id             = var.runner_ami_id
  runner_instance_type      = var.runner_instance_type
  runner_user_data          = file("${path.root}/../../../deploy/provisioning/runner-init.sh")
}

module "secrets" {
  source = "../../modules/secrets"
  name   = var.name
}

module "security" {
  source       = "../../modules/security"
  aws_vpc_main = module.networking.aws_vpc_main
  name         = var.name
}
