resource "aws_cloudwatch_log_group" "tasks" {
  name              = "/ecs/${var.name}"
  retention_in_days = 7

}

resource "aws_sns_topic" "alarms" {
  name = "${var.name}-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email

}

resource "aws_cloudwatch_metric_alarm" "alarms" {
  for_each = {
    alb_5xx = { namespace = "AWS/ApplicationELB", metric = "HTTPCode_Target_5XX_Count", stat = "Sum", threshold = 5, comparison = "GreaterThanOrEqualToThreshold", dimensions = { LoadBalancer = var.aws_lb_api.arn_suffix
      }
    },
    unhealthy = { namespace = "AWS/ApplicationELB", metric = "HealthyHostCount", stat = "Minimum", threshold = 2, comparison = "LessThanThreshold", dimensions = { LoadBalancer = var.aws_lb_api.arn_suffix, TargetGroup = var.aws_lb_target_group_api.arn_suffix
      }
    },
    ecs_cpu = { namespace = "AWS/ECS", metric = "CPUUtilization", stat = "Average", threshold = 80, comparison = "GreaterThanThreshold", dimensions = { ClusterName = var.aws_ecs_cluster_main.name, ServiceName = var.name
      }
    },
    ecs_memory = { namespace = "AWS/ECS", metric = "MemoryUtilization", stat = "Average", threshold = 80, comparison = "GreaterThanThreshold", dimensions = { ClusterName = var.aws_ecs_cluster_main.name, ServiceName = var.name
      }
    },
    rds_storage = { namespace = "AWS/RDS", metric = "FreeStorageSpace", stat = "Minimum", threshold = 3000000000, comparison = "LessThanThreshold", dimensions = { DBInstanceIdentifier = var.aws_db_instance_database.id
      }
    },
    runner_status = { namespace = "AWS/EC2", metric = "StatusCheckFailed", stat = "Maximum", threshold = 1, comparison = "GreaterThanOrEqualToThreshold", dimensions = { InstanceId = var.aws_instance_runner.id
      }
    }

  }
  alarm_name          = "${var.name}-${each.key}"
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  statistic           = each.value.stat
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  dimensions          = each.value.dimensions
  period              = 60
  evaluation_periods  = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]

}

resource "aws_budgets_budget" "week" {
  name         = "${var.name}-credit-guard"
  budget_type  = "COST"
  limit_amount = "100"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alarm_email]

  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alarm_email]

  }

}
