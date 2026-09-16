resource "aws_s3_bucket" "scenario_data" {
  provider      = aws.workload
  bucket        = "${var.project}-scenario-data-${var.workload_account_id}"
  force_destroy = false
  tags          = { Name = "${var.project}-scenario-data", Purpose = "SyntheticScenarioOnly" }
}
resource "aws_s3_bucket_versioning" "scenario_data" {
  provider = aws.workload
  bucket   = aws_s3_bucket.scenario_data.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "scenario_data" {
  provider = aws.workload
  bucket   = aws_s3_bucket.scenario_data.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_public_access_block" "scenario_data" {
  provider                = aws.workload
  bucket                  = aws_s3_bucket.scenario_data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_policy" "scenario_data" {
  provider = aws.workload
  bucket   = aws_s3_bucket.scenario_data.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.scenario_data.arn, "${aws_s3_bucket.scenario_data.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_s3_bucket_lifecycle_configuration" "scenario_data" {
  provider = aws.workload
  bucket   = aws_s3_bucket.scenario_data.id
  rule {
    id     = "bounded-synthetic-data"
    status = "Enabled"
    filter { prefix = "synthetic/" }
    expiration { days = 7 }
    noncurrent_version_expiration { noncurrent_days = 7 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
output "scenario_s3_prefix_arn" {
  value = "${aws_s3_bucket.scenario_data.arn}/synthetic/"
}
