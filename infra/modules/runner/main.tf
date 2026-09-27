resource "aws_iam_role" "runner" {
  name = "${var.name}-runner"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com"
    }, Action = "sts:AssumeRole"
    }]
  })

}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.runner.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"

}

resource "aws_iam_instance_profile" "runner" {
  name = var.name
  role = aws_iam_role.runner.name

}

resource "aws_instance" "runner" {
  ami                         = var.runner_ami_id
  instance_type               = var.runner_instance_type
  subnet_id                   = var.aws_subnet_private[0].id
  vpc_security_group_ids      = [var.aws_security_group_runner.id]
  iam_instance_profile        = aws_iam_instance_profile.runner.name
  associate_public_ip_address = false
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1

  }
  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true

  }
  user_data = var.runner_user_data
  # Preserve registered runners and their EBS disk when bootstrap text changes.
  # Terraform stops/starts the instance; cloud-init does not rerun automatically.
  # Apply provisioning changes explicitly through the setup menu repair action.
  user_data_replace_on_change = false
  tags = { Name = "${var.name}-runner"
  }

}
