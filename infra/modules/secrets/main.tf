resource "aws_secretsmanager_secret" "runtime" {
  for_each                = toset(["app-db", "migration-db", "telemetry", "jwt-signing", "token-auth"])
  name                    = "${var.name}/${each.key}"
  recovery_window_in_days = 7

}
