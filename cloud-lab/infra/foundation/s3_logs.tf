resource "aws_s3_bucket" "waf_logs" {
  provider      = aws.workload
  bucket        = "aws-waf-logs-${var.project}-${var.workload_account_id}"
  force_destroy = false

  tags = { Name = "${var.project}-waf-logs" }
}

resource "aws_s3_bucket_versioning" "waf_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.waf_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "waf_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.waf_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "waf_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.waf_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "waf_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.waf_logs.id

  rule {
    id     = "expire-after-30d"
    status = "Enabled"
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }

  rule {
    id     = "abort-multipart"
    status = "Enabled"
    abort_incomplete_multipart_upload { days_after_initiation = 3 }
  }
}

resource "aws_s3_bucket" "alb_logs" {
  provider      = aws.workload
  bucket        = "${var.project}-alb-logs-${var.workload_account_id}"
  force_destroy = false

  tags = { Name = "${var.project}-alb-logs" }
}

resource "aws_s3_bucket_versioning" "alb_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.alb_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "alb_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.alb_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "alb_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.alb_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "alb_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.alb_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "ALBLogDelivery"
        Effect    = "Allow"
        Principal = { Service = "logdelivery.elasticloadbalancing.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.alb_logs.arn}/alb/AWSLogs/${var.workload_account_id}/*"
      }
    ]
  })
}

resource "aws_s3_bucket_lifecycle_configuration" "alb_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.alb_logs.id

  rule {
    id     = "expire-after-30d"
    status = "Enabled"
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }

  rule {
    id     = "abort-multipart"
    status = "Enabled"
    abort_incomplete_multipart_upload { days_after_initiation = 3 }
  }
}

resource "aws_s3_bucket" "flow_logs" {
  provider      = aws.workload
  bucket        = "${var.project}-flow-logs-${var.workload_account_id}"
  force_destroy = false

  tags = { Name = "${var.project}-flow-logs" }
}

resource "aws_s3_bucket_versioning" "flow_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.flow_logs.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "flow_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.flow_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "flow_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.flow_logs.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "flow_logs" {
  provider = aws.workload
  bucket   = aws_s3_bucket.flow_logs.id

  rule {
    id     = "expire-after-30d"
    status = "Enabled"
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }

  rule {
    id     = "abort-multipart"
    status = "Enabled"
    abort_incomplete_multipart_upload { days_after_initiation = 3 }
  }
}
