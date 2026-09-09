resource "aws_s3_bucket" "tofu_state" {
  provider = aws.security
  bucket   = "${var.project}-tofu-state"

  tags = { Name = "${var.project}-tofu-state" }
}

resource "aws_s3_bucket_versioning" "tofu_state" {
  provider = aws.security
  bucket   = aws_s3_bucket.tofu_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tofu_state" {
  provider = aws.security
  bucket   = aws_s3_bucket.tofu_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence_s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tofu_state" {
  provider = aws.security
  bucket   = aws_s3_bucket.tofu_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tofu_lock" {
  provider     = aws.security
  name         = "${var.project}-tofu-lock"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = { Name = "${var.project}-tofu-lock" }
}
