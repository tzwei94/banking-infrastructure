resource "aws_security_group" "alb" {
  name   = "${var.name}-alb"
  vpc_id = var.aws_vpc_main.id

}

resource "aws_security_group" "app" {
  name   = "${var.name}-app"
  vpc_id = var.aws_vpc_main.id

}

resource "aws_security_group" "migration" {
  name   = "${var.name}-migration"
  vpc_id = var.aws_vpc_main.id

}

resource "aws_security_group" "database" {
  name   = "${var.name}-database"
  vpc_id = var.aws_vpc_main.id

}

resource "aws_security_group" "runner" {
  name   = "${var.name}-runner"
  vpc_id = var.aws_vpc_main.id

}

resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443

}

resource "aws_vpc_security_group_egress_rule" "alb_app" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080

}

resource "aws_vpc_security_group_ingress_rule" "app" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080

}

resource "aws_vpc_security_group_ingress_rule" "database" {
  for_each = { app = aws_security_group.app.id, migration = aws_security_group.migration.id
  }
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432

}

resource "aws_vpc_security_group_egress_rule" "database" {
  for_each = { app = aws_security_group.app.id, migration = aws_security_group.migration.id
  }
  security_group_id            = each.value
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432

}

resource "aws_vpc_security_group_egress_rule" "https" {
  for_each = { app = aws_security_group.app.id, migration = aws_security_group.migration.id, runner = aws_security_group.runner.id
  }
  security_group_id = each.value
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443

}
