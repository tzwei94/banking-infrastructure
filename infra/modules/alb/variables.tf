variable "aws_security_group_alb" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_subnet_public" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "aws_vpc_main" {
  type        = any
  description = "Resource contract supplied by the composing environment."
}

variable "certificate_arn" {
  type = string
}

variable "deletion_protection" {
  default = true
}

variable "name" {
  default = "banking-dev"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "Use 3-25 lowercase letters, digits and hyphens."

  }

}
