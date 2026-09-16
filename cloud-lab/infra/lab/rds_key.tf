resource "aws_kms_key" "rds" {
  description             = "EA RDS dedicated customer-managed key; no external sharing by default"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Sid       = "AccountDelegation", Effect = "Allow",
    Principal = { AWS = "arn:aws:iam::${var.workload_account_id}:root" },
    Action    = "kms:*", Resource = "*"
  }] })
  tags = { Name = "${var.project}-rds" }
}
resource "aws_kms_alias" "rds" {
  name          = "alias/${var.project}-rds"
  target_key_id = aws_kms_key.rds.key_id
}
output "rds_kms_key_arn" { value = aws_kms_key.rds.arn }
