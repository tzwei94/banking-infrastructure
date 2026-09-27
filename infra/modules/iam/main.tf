resource "aws_iam_role" "build" {
  name = "${var.name}-build"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Federated = var.github_oidc_arn
    }, Action = "sts:AssumeRoleWithWebIdentity", Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = "${coalesce(var.github_app_subject_prefix, "repo:${var.github_owner}/${var.app_repository}")}:ref:refs/heads/main"
    }
    }
    }]
  })

}

resource "aws_iam_role_policy" "build" {
  role = aws_iam_role.build.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart", "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"], Resource = var.ecr_repository_arns["banking-api"] }
  ] })
}

resource "aws_iam_role" "deploy" {
  name = "${var.name}-deploy"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Federated = var.github_oidc_arn
    }, Action = "sts:AssumeRoleWithWebIdentity", Condition = { StringEquals = { "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com", "token.actions.githubusercontent.com:sub" = "${coalesce(var.github_deployment_subject_prefix, "repo:${var.github_owner}/${var.deployment_repository}")}:environment:${var.github_environment}"
    }
    }
    }]
  })

}

resource "aws_iam_role_policy" "deploy" {
  role = aws_iam_role.deploy.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:aws:s3:::${var.state_bucket}"
    },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["arn:aws:s3:::${var.state_bucket}/dev/terraform.tfstate"]
    },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = ["arn:aws:s3:::${var.state_bucket}/dev/*", "arn:aws:s3:::${var.state_bucket}/manifests/*"]
    },
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucket*", "s3:GetAccelerateConfiguration", "s3:GetReplicationConfiguration", "s3:GetLifecycleConfiguration", "s3:GetEncryptionConfiguration"], Resource = "arn:aws:s3:::${var.name}-alb-${data.aws_caller_identity.current.account_id}" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = var.state_kms_arn
    },
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability", "ecr:DescribeRepositories", "ecr:GetLifecyclePolicy", "ecr:ListTagsForResource"], Resource = values(var.ecr_repository_arns) },
    { Effect = "Allow", Action = ["ecs:RegisterTaskDefinition", "ecs:Describe*", "ecs:List*", "ecs:TagResource"], Resource = "*"
    },
    { Effect = "Allow", Action = ["ecs:CreateService", "ecs:UpdateService", "ecs:DeleteService"], Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:service/${var.name}/${var.name}"
    },
    { Effect = "Allow", Action = ["ecs:RunTask"], Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task-definition/${var.name}-*:*"
    },
    { Effect = "Allow", Action = ["ecs:StopTask"], Resource = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:task/${var.name}/*"
    },
    { Effect = "Allow", Action = ["iam:PassRole"], Resource = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/${var.name}-*", Condition = { StringEquals = { "iam:PassedToService" = "ecs-tasks.amazonaws.com"
      }
      }
    },
    { Effect = "Allow", Action = ["ec2:Describe*", "elasticloadbalancing:Describe*", "rds:Describe*", "rds:ListTagsForResource", "iam:GetRole", "iam:GetRolePolicy", "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:GetInstanceProfile", "secretsmanager:DescribeSecret", "secretsmanager:GetResourcePolicy", "logs:DescribeLogGroups", "logs:ListTagsForResource", "logs:GetLogEvents", "logs:DescribeLogStreams", "cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource", "sns:GetTopicAttributes", "sns:GetSubscriptionAttributes", "sns:ListTagsForResource", "budgets:ViewBudget", "budgets:ListTagsForResource"], Resource = "*"
    }
    ]
  })

}

resource "aws_iam_role" "task" {
  name               = "${var.name}-task"
  assume_role_policy = local.ecs_trust

}

resource "aws_iam_role" "execution" {
  for_each           = toset(["app", "migration", "bootstrap"])
  name               = "${var.name}-execution-${each.key}"
  assume_role_policy = local.ecs_trust

}

resource "aws_iam_role_policy" "execution_images" {
  for_each = aws_iam_role.execution
  role     = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = each.key == "app" ? values(var.ecr_repository_arns) : [var.ecr_repository_arns["banking-api"]] },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:aws:logs:${var.region}:${data.aws_caller_identity.current.account_id}:log-group:/ecs/${var.name}:*" }
  ] })
}

resource "aws_iam_role_policy" "execution" {
  for_each = { app = ["app-db", "telemetry", "jwt-signing", "token-auth"], migration = ["migration-db"]
  }
  role = aws_iam_role.execution[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [for key in each.value : var.aws_secretsmanager_secret_runtime[key].arn]
    }]
  })

}

resource "aws_iam_role" "bootstrap" {
  count              = var.bootstrap_enabled ? 1 : 0
  name               = "${var.name}-bootstrap"
  assume_role_policy = local.ecs_trust

}

resource "aws_iam_role_policy" "bootstrap" {
  count = var.bootstrap_enabled ? 1 : 0
  role  = aws_iam_role.bootstrap[0].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [var.aws_db_instance_database.master_user_secret[0].secret_arn, var.aws_secretsmanager_secret_runtime["app-db"].arn, var.aws_secretsmanager_secret_runtime["migration-db"].arn]
    },
    { Effect = "Allow", Action = ["secretsmanager:PutSecretValue"], Resource = [var.aws_secretsmanager_secret_runtime["app-db"].arn, var.aws_secretsmanager_secret_runtime["migration-db"].arn]
    }
    ]
  })

}

locals {
  ecs_trust = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com"
    }, Action = "sts:AssumeRole", Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id
      }, ArnLike = { "aws:SourceArn" = "arn:aws:ecs:${var.region}:${data.aws_caller_identity.current.account_id}:*"
    }
    }
    }]
  })

}

data "aws_caller_identity" "current" {}
