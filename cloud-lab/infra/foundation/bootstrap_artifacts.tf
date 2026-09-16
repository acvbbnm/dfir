resource "aws_s3_bucket" "bootstrap" {
  provider      = aws.workload
  bucket        = "${var.project}-bootstrap-${var.workload_account_id}"
  force_destroy = false
}
resource "aws_s3_bucket_versioning" "bootstrap" {
  provider = aws.workload
  bucket   = aws_s3_bucket.bootstrap.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "bootstrap" {
  provider = aws.workload
  bucket   = aws_s3_bucket.bootstrap.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "bootstrap" {
  provider                = aws.workload
  bucket                  = aws_s3_bucket.bootstrap.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_policy" "bootstrap" {
  provider = aws.workload
  bucket   = aws_s3_bucket.bootstrap.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.bootstrap.arn, "${aws_s3_bucket.bootstrap.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
