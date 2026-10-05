# Enable through a reviewed operator plan after the service has been deployed.
resource "aws_appautoscaling_target" "service" {
  count              = var.autoscaling_enabled && var.service_enabled ? 1 : 0
  min_capacity       = 2
  max_capacity       = 4
  resource_id        = "service/${var.aws_ecs_cluster_main.name}/${aws_ecs_service.app[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  count              = var.autoscaling_enabled && var.service_enabled ? 1 : 0
  name               = "${var.name}-cpu-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.service[0].resource_id
  scalable_dimension = aws_appautoscaling_target.service[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.service[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 60
    scale_out_cooldown = 30
    scale_in_cooldown  = 60
    disable_scale_in   = false
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}

resource "aws_appautoscaling_policy" "memory" {
  count              = var.autoscaling_enabled && var.service_enabled && var.memory_autoscaling_enabled ? 1 : 0
  name               = "${var.name}-memory-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.service[0].resource_id
  scalable_dimension = aws_appautoscaling_target.service[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.service[0].service_namespace

  target_tracking_scaling_policy_configuration {
    target_value       = 70
    scale_out_cooldown = 30
    scale_in_cooldown  = 60
    disable_scale_in   = false
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
  }
}
