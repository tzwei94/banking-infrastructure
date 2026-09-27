resource "aws_s3_bucket" "alb_logs" {
  bucket = "${var.name}-alb-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  bucket                  = aws_s3_bucket.alb_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true

}

resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }

  }

}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  rule {
    id     = "retention"
    status = "Enabled"
    filter {

    }
    expiration {
      days = 14
    }

  }

}

resource "aws_s3_bucket_policy" "alb_logs" {
  bucket = aws_s3_bucket.alb_logs.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com"
      }, Action = "s3:PutObject", Resource = "${aws_s3_bucket.alb_logs.arn}/AWSLogs/${data.aws_caller_identity.current.account_id}/*"
    },
    { Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.alb_logs.arn, "${aws_s3_bucket.alb_logs.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false"
      }
      }
    }
    ]
  })

}

resource "aws_lb" "api" {
  name                       = var.name
  load_balancer_type         = "application"
  internal                   = false
  security_groups            = [var.aws_security_group_alb.id]
  subnets                    = var.aws_subnet_public[*].id
  drop_invalid_header_fields = true
  enable_deletion_protection = var.deletion_protection
  access_logs {
    bucket  = aws_s3_bucket.alb_logs.id
    enabled = true

  }
  depends_on = [aws_s3_bucket_policy.alb_logs]

}

resource "aws_lb_target_group" "api" {
  name                 = var.name
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.aws_vpc_main.id
  deregistration_delay = 30
  health_check {
    path                = "/readyz"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3

  }

}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.api.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn

  }

}

data "aws_caller_identity" "current" {}
