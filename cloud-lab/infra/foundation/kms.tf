resource "aws_kms_key" "workload_ebs" {
  provider    = aws.security
  description = "EA Workload EBS 볼륨 암호화"

  key_usage                = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  enable_key_rotation      = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecurityAccountAdmin"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "WorkloadUseOnly"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.workload_account_id}:root" }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:ReEncrypt*",
          "kms:GenerateDataKey*",
          "kms:DescribeKey",
          "kms:CreateGrant"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ec2.${var.region}.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = { Name = "${var.project}-workload-ebs" }
}

resource "aws_kms_alias" "workload_ebs" {
  provider      = aws.security
  name          = "alias/${var.project}-workload-ebs"
  target_key_id = aws_kms_key.workload_ebs.key_id
}

resource "aws_kms_key" "evidence_s3" {
  provider    = aws.security
  description = "EA 증거 S3 버킷 암호화"

  key_usage                = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  enable_key_rotation      = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecurityAccountAdmin"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "CollectionRoleEncrypt"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:role/${var.project}-collection-role" }
        Action = [
          "kms:Encrypt",
          "kms:GenerateDataKey*",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "AnalystDecrypt"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:role/${var.project}-analyst-role" }
        Action = [
          "kms:Decrypt",
          "kms:DescribeKey"
        ]
        Resource = "*"
      }
    ]
  })

  tags = { Name = "${var.project}-evidence-s3" }
}

resource "aws_kms_alias" "evidence_s3" {
  provider      = aws.security
  name          = "alias/${var.project}-evidence-s3"
  target_key_id = aws_kms_key.evidence_s3.key_id
}

resource "aws_kms_key" "evidence_ebs" {
  provider    = aws.security
  description = "EA 증거 EBS 스냅샷 교차 계정 복사용"

  key_usage                = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  enable_key_rotation      = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SecurityAccountAdmin"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "WorkloadSnapshotCopy"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.workload_account_id}:root" }
        Action = [
          "kms:CreateGrant",
          "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ec2.${var.region}.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = { Name = "${var.project}-evidence-ebs" }
}

resource "aws_kms_alias" "evidence_ebs" {
  provider      = aws.security
  name          = "alias/${var.project}-evidence-ebs"
  target_key_id = aws_kms_key.evidence_ebs.key_id
}
