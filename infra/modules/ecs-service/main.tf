resource "aws_ecs_task_definition" "app" {
  family                   = "${var.name}-app"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = local.execution_role_arns.app
  task_role_arn            = var.aws_iam_role_task.arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"

  }
  container_definitions = jsonencode([local.app_container, local.alloy_container])
  volume {
    name = "tmp"
  }
  volume {
    name = "logs"
  }
  volume {
    name = "alloy"
  }
  skip_destroy = true
  tags = { SourceSHA = var.source_sha
  }

}

resource "aws_ecs_task_definition" "migration" {
  family                   = "${var.name}-migration"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = local.execution_role_arns.migration
  task_role_arn            = var.aws_iam_role_task.arn
  container_definitions = jsonencode([{
    name    = "migration", image = var.image, essential = true, user = "10001:10001", readonlyRootFilesystem = true,
    command = ["migrate"],
    environment = concat(local.db_environment, [{ name = "DB_USERNAME", value = "banking_migrator"
      }, { name = "SEED_SYNTHETIC", value = tostring(var.seed_synthetic)
    }]),
    secrets = [{ name = "DB_PASSWORD", valueFrom = "${local.secret_arns["migration-db"]}:password::"
    }],
    mountPoints = [local.tmp_mount], logConfiguration = local.log_configuration,

  }])
  volume {
    name = "tmp"
  }
  skip_destroy = true

}

resource "aws_ecs_task_definition" "bootstrap" {
  count                    = var.bootstrap_enabled ? 1 : 0
  family                   = "${var.name}-bootstrap"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = local.execution_role_arns.bootstrap
  task_role_arn            = try(var.aws_iam_role_bootstrap[0].arn, null)
  container_definitions = jsonencode([{
    name    = "bootstrap", image = var.image, essential = true, user = "10001:10001", readonlyRootFilesystem = true,
    command = ["bootstrap"],
    environment = concat(local.db_environment, [{ name = "MASTER_SECRET_ARN", value = var.aws_db_instance_database.master_user_secret[0].secret_arn
      }, { name = "APP_SECRET_ARN", value = local.secret_arns["app-db"]
      }, { name = "MIGRATION_SECRET_ARN", value = local.secret_arns["migration-db"]
    }]),
    mountPoints = [local.tmp_mount], logConfiguration = local.log_configuration,

  }])
  volume {
    name = "tmp"
  }
  lifecycle {
    precondition {
      condition     = try(var.aws_iam_role_bootstrap[0].arn, null) != null
      error_message = "Enable platform bootstrap role before preparing a first release."

    }

  }

}

resource "aws_ecs_service" "app" {
  count                              = var.service_enabled ? 1 : 0
  name                               = var.name
  cluster                            = var.aws_ecs_cluster_main.arn
  task_definition                    = var.active_task_definition_arn
  desired_count                      = 2
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  availability_zone_rebalancing      = "ENABLED"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = 120
  wait_for_steady_state              = true
  deployment_circuit_breaker {
    enable   = true
    rollback = true

  }
  network_configuration {
    subnets          = var.aws_subnet_private[*].id
    security_groups  = [var.aws_security_group_app.id]
    assign_public_ip = false

  }
  load_balancer {
    target_group_arn = var.aws_lb_target_group_api.arn
    container_name   = "app"
    container_port   = 8080

  }
  lifecycle {
    # Application Auto Scaling owns runtime capacity; releases only promote revisions.
    ignore_changes = [desired_count]
    precondition {
      condition     = can(regex("^arn:aws:ecs:[a-z0-9-]+:[0-9]+:task-definition/${var.name}-app:[0-9]+$", var.active_task_definition_arn))
      error_message = "Promotion requires an explicit application task ARN."

    }

  }

}

locals {
  database_url        = "jdbc:postgresql://${var.aws_db_instance_database.address}:5432/banking?sslmode=verify-full&sslrootcert=/opt/app/certs/rds-ca.pem"
  secret_arns         = { for key, secret in var.aws_secretsmanager_secret_runtime : key => secret.arn }
  execution_role_arns = { for key, role in var.aws_iam_role_execution : key => role.arn }
}

locals {
  log_configuration = { logDriver = "awslogs", options = { awslogs-group = var.aws_cloudwatch_log_group_tasks.name, awslogs-region = var.region, awslogs-stream-prefix = "tasks", mode = "non-blocking", max-buffer-size = "1m"
    }

  }
  db_environment = [{ name = "DB_URL", value = local.database_url
  }]
  tmp_mount = { sourceVolume = "tmp", containerPath = "/tmp", readOnly = false
  }
  app_container = {
    name                   = "app", image = var.image, essential = true, user = "10001:10001", cpu = 384, memory = 704, memoryReservation = 512,
    readonlyRootFilesystem = true, stopTimeout = 30,
    portMappings = [{ containerPort = 8080, protocol = "tcp"
    }],
    environment = concat(local.db_environment, [{ name = "LOG_PATH", value = "/var/log/app"
      }, { name = "JAVA_TOOL_OPTIONS", value = "-XX:MaxRAMPercentage=55 -XX:+ExitOnOutOfMemoryError"
      }, { name = "DB_USERNAME", value = "banking_app"
      }, { name = "JWT_ISSUER", value = var.jwt_issuer
      }, { name = "JWT_AUDIENCE", value = var.jwt_audience
      }, { name = "SOURCE_SHA", value = var.source_sha
    }]),
    secrets = [{ name = "DB_PASSWORD", valueFrom = "${local.secret_arns["app-db"]}:password::"
      }, { name = "JWT_PRIVATE_KEY", valueFrom = "${local.secret_arns["jwt-signing"]}:private_key::"
      }, { name = "TOKEN_USERNAME", valueFrom = "${local.secret_arns["token-auth"]}:username::"
      }, { name = "TOKEN_PASSWORD", valueFrom = "${local.secret_arns["token-auth"]}:password::"
    }],
    mountPoints = [local.tmp_mount, { sourceVolume = "logs", containerPath = "/var/log/app", readOnly = false
    }],
    logConfiguration = local.log_configuration,
    dependsOn        = [{ containerName = "alloy", condition = "START" }]

  }
  alloy_container = {
    name                   = "alloy", image = var.alloy_image, essential = true, user = "10001:10001", cpu = 128, memory = 320, memoryReservation = 128,
    readonlyRootFilesystem = true, stopTimeout = 60,
    environment = [{ name = "SERVICE_NAME", value = "banking-api"
      }, { name = "LOG_GLOB", value = "/var/log/app/application*.log"
      }, { name = "METRICS_TARGET", value = "127.0.0.1:9000"
      }, { name = "METRICS_PATH", value = "/actuator/prometheus"
      }, { name = "ENVIRONMENT", value = var.name
      }, { name = "LOKI_URL", value = var.loki_url
      }, { name = "METRICS_URL", value = var.metrics_url
      }, { name = "TRACES_BASE_URL", value = var.traces_base_url
    }],
    secrets = [{ name = "TELEMETRY_USERNAME", valueFrom = "${local.secret_arns["telemetry"]}:username::"
      }, { name = "TELEMETRY_PASSWORD", valueFrom = "${local.secret_arns["telemetry"]}:password::"
    }],
    mountPoints = [{ sourceVolume = "logs", containerPath = "/var/log/app", readOnly = true
      }, { sourceVolume = "alloy", containerPath = "/var/lib/alloy/data", readOnly = false
    }],
    logConfiguration = local.log_configuration

  }

}
