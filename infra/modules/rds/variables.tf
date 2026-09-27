variable "aws_security_group_database" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_subnet_database" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "deletion_protection" {
  default = true
}

variable "final_snapshot_identifier" {
  type = string
}

variable "name" {
  default = "banking-dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "Use 3-25 lowercase letters, digits and hyphens."

  }

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
