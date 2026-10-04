variable "active_task_definition_arn" {
  type    = string
  default = ""

}

variable "alarm_email" {
  type = string
}

variable "alloy_image" {
  type = string
  validation {
    condition     = can(regex("^[a-zA-Z0-9./:_-]+@sha256:[a-f0-9]{64}$", var.alloy_image))
    error_message = "Use an immutable Alloy image digest."

  }

}

variable "app_repository" {
  default = "banking-api"
}

variable "bootstrap_enabled" {
  default = false
}

variable "certificate_arn" {
  type = string
}

variable "deletion_protection" {
  default = true
}

variable "autoscaling_enabled" {
  type        = bool
  default     = false
  description = "Enable reviewed ECS CPU target tracking between two and four tasks."
}

variable "cpu_demo_enabled" {
  type        = bool
  default     = true
  description = "Enable the JWT-protected, bounded CPU demo endpoint in this demo environment."
}

variable "deployment_repository" {
  default = "banking-deployment"
}

variable "final_snapshot_identifier" {
  type = string
}

variable "github_environment" {
  default = "dev"
}

variable "github_oidc_arn" {
  type        = string
  description = "ARN from the independently managed GitHub OIDC bootstrap root."
}

variable "github_owner" {
  type = string
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

variable "runner_ami_id" {
  type = string
}

variable "runner_instance_type" {
  default = "t3.medium"
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

variable "state_bucket" {
  type = string
}

variable "state_kms_arn" {
  type = string
}

variable "traces_base_url" {
  default = "https://traces-ingest.example.com"
}

variable "vpc_cidr" {
  default = "10.42.0.0/16"
}

variable "db_backup_retention_period" {
  type        = number
  default     = 7
  description = "Automated backup retention in days. Restricted accounts can select 1 while keeping backups enabled."
  validation {
    condition     = var.db_backup_retention_period >= 1 && var.db_backup_retention_period <= 35 && floor(var.db_backup_retention_period) == var.db_backup_retention_period
    error_message = "Backup retention must be a whole number from 1 to 35 days."
  }
}

variable "github_app_subject_prefix" {
  type        = string
  default     = null
  description = "Exact GitHub OIDC sub_claim_prefix; null uses the legacy repository name format."
  validation {
    condition     = var.github_app_subject_prefix == null ? true : can(regex("^repo:[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?$", var.github_app_subject_prefix))
    error_message = "Use an exact repo:OWNER/REPO or repo:OWNER@ID/REPO@ID prefix, without wildcards or a context suffix."
  }
}

variable "github_deployment_subject_prefix" {
  type        = string
  default     = null
  description = "Exact GitHub OIDC sub_claim_prefix; null uses the legacy repository name format."
  validation {
    condition     = var.github_deployment_subject_prefix == null ? true : can(regex("^repo:[A-Za-z0-9_.-]+(@[0-9]+)?/[A-Za-z0-9_.-]+(@[0-9]+)?$", var.github_deployment_subject_prefix))
    error_message = "Use an exact repo:OWNER/REPO or repo:OWNER@ID/REPO@ID prefix, without wildcards or a context suffix."
  }
}
