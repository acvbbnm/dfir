resource "aws_s3_bucket" "cloudtrail" {
  provider      = aws.security
  bucket        = "${var.project}-cloudtrail-${var.security_account_id}"
  force_destroy = false

  tags = { Name = "${var.project}-cloudtrail" }
}

resource "aws_s3_bucket_versioning" "cloudtrail" {
  provider = aws.security
  bucket   = aws_s3_bucket.cloudtrail.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail" {
  provider = aws.security
  bucket   = aws_s3_bucket.cloudtrail.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence_s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "cloudtrail" {
  provider = aws.security
  bucket   = aws_s3_bucket.cloudtrail.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "cloudtrail" {
  provider = aws.security
  bucket   = aws_s3_bucket.cloudtrail.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudTrailAclCheck"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:GetBucketAcl"
        Resource  = aws_s3_bucket.cloudtrail.arn
        Condition = {
          StringEquals = {
            "aws:SourceArn" = ["arn:aws:cloudtrail:${var.region}:${var.security_account_id}:trail/${var.project}-trail", "arn:aws:cloudtrail:${var.region}:${var.workload_account_id}:trail/${var.project}-workload-trail"]
          }
        }
      },
      {
        Sid       = "CloudTrailWrite"
        Effect    = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = ["${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${var.security_account_id}/*", "${aws_s3_bucket.cloudtrail.arn}/AWSLogs/${var.workload_account_id}/*"]
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"  = "bucket-owner-full-control"
            "aws:SourceArn" = ["arn:aws:cloudtrail:${var.region}:${var.security_account_id}:trail/${var.project}-trail", "arn:aws:cloudtrail:${var.region}:${var.workload_account_id}:trail/${var.project}-workload-trail"]
          }
        }
      }
    ]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail" {
  provider = aws.security
  bucket   = aws_s3_bucket.cloudtrail.id

  rule {
    id     = "expire-after-90d"
    status = "Enabled"
    expiration { days = 90 }
    noncurrent_version_expiration { noncurrent_days = 30 }
  }
}

resource "aws_cloudtrail" "main" {
  provider = aws.security
  name     = "${var.project}-trail"

  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  enable_log_file_validation    = true
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_logging                = true
  kms_key_id                    = aws_kms_key.evidence_s3.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true
  }

  tags = { Name = "${var.project}-trail" }

  depends_on = [aws_s3_bucket_policy.cloudtrail]
}

resource "aws_cloudtrail" "workload" {
  provider                      = aws.workload
  name                          = "${var.project}-workload-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  is_multi_region_trail         = true
  include_global_service_events = true
  enable_logging                = true
  enable_log_file_validation    = true
  kms_key_id                    = aws_kms_key.evidence_s3.arn
  event_selector {
    read_write_type           = "All"
    include_management_events = true
  }
  depends_on = [aws_s3_bucket_policy.cloudtrail]
}
