output "aws_ecs_task_definition_app" {
  value = aws_ecs_task_definition.app
}

output "aws_ecs_task_definition_bootstrap" {
  value = aws_ecs_task_definition.bootstrap
}

output "aws_ecs_task_definition_migration" {
  value = aws_ecs_task_definition.migration
}

output "service" {
  value = aws_ecs_service.app
}
