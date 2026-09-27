resource "aws_ecr_repository" "images" {
  for_each             = toset(["banking-api", "banking-alloy"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  encryption_configuration {
    encryption_type = "AES256"
  }
  image_scanning_configuration {
    scan_on_push = true
  }
}

# Retain tagged release images for rollback; only clean up abandoned uploads.
resource "aws_ecr_lifecycle_policy" "untagged" {
  for_each   = aws_ecr_repository.images
  repository = each.value.name
  policy = jsonencode({ rules = [{
    rulePriority = 1
    description  = "Expire untagged images after 7 days"
    selection    = { tagStatus = "untagged", countType = "sinceImagePushed", countUnit = "days", countNumber = 7 }
    action       = { type = "expire" }
  }] })
}
