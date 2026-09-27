output "aws_cloudwatch_log_group_tasks" {
  value = aws_cloudwatch_log_group.tasks
}

output "aws_sns_topic_alarms" {
  value = aws_sns_topic.alarms
}
