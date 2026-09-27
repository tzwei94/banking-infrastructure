variable "aws_security_group_runner" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_subnet_private" {
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

variable "runner_ami_id" {
  type = string
}

variable "runner_instance_type" {
  default = "t3.medium"
}

variable "runner_user_data" {
  type = string
}
