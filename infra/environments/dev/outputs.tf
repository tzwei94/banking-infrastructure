output "candidate_app_arn" {
  value = module.ecs_service.aws_ecs_task_definition_app.arn
}

output "candidate_migration_arn" {
  value = module.ecs_service.aws_ecs_task_definition_migration.arn
}

output "bootstrap_arn" {
  value = try(module.ecs_service.aws_ecs_task_definition_bootstrap[0].arn, null)
}

output "active_task_definition_arn" {
  value = var.service_enabled ? var.active_task_definition_arn : null
}

output "run_task" {
  value = { cluster = module.ecs_cluster.aws_ecs_cluster_main.arn, subnets = module.networking.aws_subnet_private[*].id, security_groups = [module.security.aws_security_group_migration.id], log_group = module.cloudwatch.aws_cloudwatch_log_group_tasks.name
  }

}

output "contract" {
  value = {
    alb_dns_name        = module.alb.aws_lb_api.dns_name
    database_identifier = module.rds.aws_db_instance_database.id
    runner_instance_id  = module.runner.aws_instance_runner.id
    alarm_topic_arn     = module.cloudwatch.aws_sns_topic_alarms.arn
    build_role_arn      = module.iam.aws_iam_role_build.arn
    deploy_role_arn     = module.iam.aws_iam_role_deploy.arn
    ecr_repositories    = { for key, repo in module.ecr.repositories : key => repo.repository_url }
    secret_arns         = { for key, secret in module.secrets.aws_secretsmanager_secret_runtime : key => secret.arn }
  }
}
