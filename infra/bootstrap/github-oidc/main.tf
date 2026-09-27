provider "aws" { region = var.region }
variable "region" { default = "ap-southeast-1" }
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}
output "provider_arn" { value = aws_iam_openid_connect_provider.github.arn }
