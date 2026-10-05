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

output "autoscaling_target" {
  value = aws_appautoscaling_target.service
}

output "autoscaling_policy" {
  value = aws_appautoscaling_policy.cpu
}

output "memory_autoscaling_policy" {
  value = aws_appautoscaling_policy.memory
}
