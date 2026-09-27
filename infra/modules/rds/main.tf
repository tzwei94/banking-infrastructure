resource "aws_db_subnet_group" "database" {
  name       = var.name
  subnet_ids = var.aws_subnet_database[*].id

}

resource "aws_db_parameter_group" "database" {
  name   = var.name
  family = "postgres17"
  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "pending-reboot"

  }
  parameter {
    name  = "log_statement"
    value = "none"

  }

}

resource "aws_db_instance" "database" {
  identifier                  = var.name
  db_name                     = "banking"
  engine                      = "postgres"
  engine_version              = "17"
  instance_class              = "db.t4g.micro"
  allocated_storage           = 20
  max_allocated_storage       = 30
  storage_type                = "gp3"
  storage_encrypted           = true
  username                    = "banking_admin"
  manage_master_user_password = true
  db_subnet_group_name        = aws_db_subnet_group.database.name
  vpc_security_group_ids      = [var.aws_security_group_database.id]
  parameter_group_name        = aws_db_parameter_group.database.name
  multi_az                    = false
  publicly_accessible         = false
  backup_retention_period     = var.db_backup_retention_period
  backup_window               = "18:00-19:00"
  maintenance_window          = "sun:19:00-sun:20:00"
  copy_tags_to_snapshot       = true
  deletion_protection         = var.deletion_protection
  skip_final_snapshot         = false
  final_snapshot_identifier   = var.final_snapshot_identifier
  auto_minor_version_upgrade  = true

}
