output "aws_security_group_alb" {
  value = aws_security_group.alb
}

output "aws_security_group_app" {
  value = aws_security_group.app
}

output "aws_security_group_database" {
  value = aws_security_group.database
}

output "aws_security_group_migration" {
  value = aws_security_group.migration
}

output "aws_security_group_runner" {
  value = aws_security_group.runner
}
