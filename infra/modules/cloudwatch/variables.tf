variable "alarm_email" {
  type = string
}

variable "aws_db_instance_database" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_ecs_cluster_main" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_instance_runner" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_lb_api" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_lb_target_group_api" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "name" {
  default = "banking-dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "Use 3-25 lowercase letters, digits and hyphens."

  }

}
