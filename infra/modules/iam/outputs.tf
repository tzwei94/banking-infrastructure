output "aws_iam_role_bootstrap" {
  value = aws_iam_role.bootstrap
}

output "aws_iam_role_build" {
  value = aws_iam_role.build
}

output "aws_iam_role_deploy" {
  value = aws_iam_role.deploy
}

output "aws_iam_role_execution" {
  value = aws_iam_role.execution
}

output "aws_iam_role_task" {
  value = aws_iam_role.task
}

output "deploy_policy" {
  description = "Deployment permission contract, also verified by the dev mock tests."
  value       = jsondecode(aws_iam_role_policy.deploy.policy)
}

output "build_policy" {
  value = jsondecode(aws_iam_role_policy.build.policy)
}

output "execution_image_policies" {
  value = { for key, policy in aws_iam_role_policy.execution_images : key => jsondecode(policy.policy) }
}
