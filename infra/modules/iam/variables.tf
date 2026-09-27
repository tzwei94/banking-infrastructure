variable "app_repository" {
  default = "banking-api"
}

variable "aws_db_instance_database" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "ecr_repository_arns" {
  type        = map(string)
  description = "Private ECR repositories owned by this environment."
}

variable "aws_secretsmanager_secret_runtime" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "bootstrap_enabled" {
  default = false
}

variable "deployment_repository" {
  default = "banking-deployment"
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

variable "state_bucket" {
  type = string
}

variable "state_kms_arn" {
  type = string
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
