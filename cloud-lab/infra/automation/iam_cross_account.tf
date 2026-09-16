# Workload 계정의 수집 대상 역할 — Security Lambda가 AssumeRole하여 접근
resource "aws_iam_role" "collection_target" {
  provider = aws.workload
  name     = "${var.project}-collection-target"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:root" }
        Action    = "sts:AssumeRole"
        Condition = {
          StringLike = {
            "aws:PrincipalArn" = "arn:aws:iam::${var.security_account_id}:role/${var.project}-lambda-*"
          }
        }
      }
    ]
  })

  tags = { Name = "${var.project}-collection-target" }
}

resource "aws_iam_role_policy" "collection_target_describe" {
  provider = aws.workload
  name     = "describe-resources"
  role     = aws_iam_role.collection_target.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "LookupWorkloadAudit"
        Effect   = "Allow"
        Action   = "cloudtrail:LookupEvents"
        Resource = "*"
      },
      {
        Sid    = "DescribeForMetadata"
        Effect = "Allow"
        Action = [
          "ec2:DescribeInstances",
          "ec2:DescribeSecurityGroups",
          "ec2:DescribeNetworkInterfaces",
          "ec2:DescribeVolumes",
          "ec2:DescribeSnapshots",
          "ec2:DescribeImages",
          "iam:GetRole",
          "iam:GetRolePolicy",
          "iam:ListRolePolicies",
          "iam:ListAttachedRolePolicies",
          "iam:GetInstanceProfile",
          "rds:DescribeDBInstances",
          "rds:DescribeDBSubnetGroups",
          "elasticloadbalancing:DescribeTargetGroups",
          "elasticloadbalancing:DescribeTargetHealth"
        ]
        Resource = "*"
      },
      {
        Sid    = "SSMForCollection"
        Effect = "Allow"
        Action = [
          "ssm:SendCommand"
        ]
        Resource = [
          "arn:aws:ec2:${var.region}:${var.workload_account_id}:instance/*"
        ]
        Condition = {
          StringEquals = {
            "ssm:resourceTag/EACollectable" = "true"
          }
        }
      },

      {
        Sid      = "RunFixedCollectionDocument"
        Effect   = "Allow"
        Action   = "ssm:SendCommand"
        Resource = "arn:aws:ssm:${var.region}:${var.workload_account_id}:document/${var.project}-VelociraptorOfflineCollect"
      },
      {
        Sid      = "ReadCollectionStatus"
        Effect   = "Allow"
        Action   = "ssm:GetCommandInvocation"
        Resource = "*"
      },
      {
        Sid    = "EBSSnapshot"
        Effect = "Allow"
        Action = [
          "ec2:CreateSnapshot",
          "ec2:CreateTags"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "ec2:ResourceTag/EACollectable" = "true"
          }
        }
      }
    ]
  })
}


# SSM environment interpolation prevents command construction from request strings.
resource "aws_ssm_document" "velociraptor_collect" {
  provider      = aws.workload
  name          = "${var.project}-VelociraptorOfflineCollect"
  document_type = "Command"
  target_type   = "/AWS::EC2::Instance"
  content = jsonencode({
    schemaVersion = "2.2"
    description   = "Fixed Linux triage with scoped evidence upload"
    parameters = {
      CaseId    = { type = "String", allowedPattern = "^CASE-[A-Za-z0-9_-]{1,59}$", interpolationType = "ENV_VAR" }
      UploadUrl = { type = "String", allowedPattern = "^https://[a-zA-Z0-9.-]+/cases/.+$", interpolationType = "ENV_VAR" }
    }
    mainSteps = [{
      action = "aws:runShellScript"
      name   = "runCollector"
      inputs = {
        runCommand     = ["set -eu", "python3 /opt/ea-tools/host_collect.py --case-id \"$SSM_CaseId\""]
        timeoutSeconds = "300"
      }
    }]
  })
}

resource "aws_iam_role" "central_log_reader" {
  provider = aws.security
  name     = "${var.project}-central-log-reader"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { AWS = "arn:aws:iam::${var.workload_account_id}:root" }, Action = "sts:AssumeRole",
    Condition = { ArnEquals = { "aws:PrincipalArn" = "arn:aws:iam::${var.workload_account_id}:role/${var.project}-soc-role" } }
  }] })
}
resource "aws_iam_role_policy" "central_log_reader" {
  provider = aws.security
  role     = aws_iam_role.central_log_reader.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:aws:s3:::${var.project}-cloudtrail-${var.security_account_id}",
    Condition = { StringLike = { "s3:prefix" = ["AWSLogs/${var.workload_account_id}/*", "AWSLogs/${var.security_account_id}/*"] } } },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = ["arn:aws:s3:::${var.project}-cloudtrail-${var.security_account_id}/AWSLogs/${var.workload_account_id}/*", "arn:aws:s3:::${var.project}-cloudtrail-${var.security_account_id}/AWSLogs/${var.security_account_id}/*"] },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = var.kms_evidence_s3_arn }
  ] })
}
