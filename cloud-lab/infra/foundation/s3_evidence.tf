resource "aws_s3_bucket" "evidence_staging" {
  provider      = aws.security
  bucket        = "${var.project}-evidence-staging-${var.security_account_id}"
  force_destroy = false

  tags = { Name = "${var.project}-evidence-staging" }
}

resource "aws_s3_bucket_versioning" "evidence_staging" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_staging.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence_staging" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_staging.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence_s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence_staging" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_staging.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence_staging" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_staging.id

  rule {
    id     = "cleanup-incomplete-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }

  rule {
    id     = "expire-old-staging"
    status = "Enabled"

    expiration {
      days = 30
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}

resource "aws_s3_bucket" "evidence_final" {
  provider      = aws.security
  bucket        = "${var.project}-evidence-final-${var.security_account_id}"
  force_destroy = false

  tags = { Name = "${var.project}-evidence-final" }
}

resource "aws_s3_bucket_versioning" "evidence_final" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_final.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence_final" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_final.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence_s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "evidence_final" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_final.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence_final" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_final.id

  rule {
    id     = "cleanup-incomplete-uploads"
    status = "Enabled"

    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }

  rule {
    id     = "noncurrent-cleanup"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_policy" "evidence_final_deny_delete" {
  provider = aws.security
  bucket   = aws_s3_bucket.evidence_final.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyDeleteFromWorkload"
        Effect    = "Deny"
        Principal = { AWS = "arn:aws:iam::${var.workload_account_id}:root" }
        Action = [
          "s3:DeleteObject",
          "s3:DeleteObjectVersion",
          "s3:DeleteBucket"
        ]
        Resource = [
          aws_s3_bucket.evidence_final.arn,
          "${aws_s3_bucket.evidence_final.arn}/*"
        ]
      }
    ]
  })
}
