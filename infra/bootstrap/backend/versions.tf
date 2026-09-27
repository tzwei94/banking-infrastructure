terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "6.66.0"
    }

  }

}
provider "aws" {
  region = var.region
  default_tags {
    tags = { Project = var.name, ManagedBy = "Terraform"
    }

  }

}
variable "region" {
  default = "ap-southeast-1"
}
variable "name" {
  default = "banking-demo"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.name))
    error_message = "Use 3-25 lowercase letters, digits and hyphens."

  }

}
