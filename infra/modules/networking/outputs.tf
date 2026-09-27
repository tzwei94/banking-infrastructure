output "aws_subnet_database" {
  value = aws_subnet.database
}

output "aws_subnet_private" {
  value = aws_subnet.private
}

output "aws_subnet_public" {
  value = aws_subnet.public
}

output "aws_vpc_main" {
  value = aws_vpc.main
}
