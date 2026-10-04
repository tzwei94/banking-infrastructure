variable "active_task_definition_arn" {
  type    = string
  default = ""

}

variable "autoscaling_enabled" {
  type        = bool
  default     = false
  description = "Opt in after reviewing the operator plan and approving the two-to-four task cost ceiling."
}

variable "alloy_image" {
  type = string
  validation {
    condition     = can(regex("^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$", var.alloy_image))
    error_message = "Use an immutable Alloy image digest."

  }

}

variable "aws_cloudwatch_log_group_tasks" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_db_instance_database" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_ecs_cluster_main" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_iam_role_bootstrap" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_iam_role_execution" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_iam_role_task" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_lb_target_group_api" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_secretsmanager_secret_runtime" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_security_group_app" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_subnet_private" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "bootstrap_enabled" {
  default = false
}

variable "image" {
  type = string
  validation {
    condition     = can(regex("^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$", var.image))
    error_message = "Use an immutable registry/repository@sha256 digest."

  }

}

variable "jwt_audience" {
  default = "banking-api"
}

variable "jwt_issuer" {
  default = "banking-demo"
}

variable "loki_url" {
  default = "https://logs-ingest.example.com/loki/api/v1/push"
}

variable "metrics_url" {
  default = "https://metrics-ingest.example.com/api/v1/write"
}

variable "name" {
  default = "banking-dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "Use 3-25 lowercase letters, digits and hyphens."

  }

}

variable "region" {
  default = "ap-southeast-1"
}

variable "seed_synthetic" {
  default = false
}

variable "service_enabled" {
  default = false
}

variable "source_sha" {
  type = string
  validation {
    condition     = can(regex("^[a-f0-9]{40}$", var.source_sha))
    error_message = "Use the complete application Git commit SHA."

  }

}

variable "traces_base_url" {
  default = "https://traces-ingest.example.com"
}
