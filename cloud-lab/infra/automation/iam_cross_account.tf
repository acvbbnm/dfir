# Workload 계정의 수집 대상 역할 — Security Lambda가 AssumeRole하여 접근
resource "aws_iam_role" "collection_target" {
  provider = aws.workload
  name     = "${var.project}-collection-target"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.security_account_id}:root" }
        Action = "sts:AssumeRole"
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
          "ssm:SendCommand",
          "ssm:GetCommandInvocation"
        ]
        Resource = [
          "arn:aws:ssm:${var.region}:${var.security_account_id}:document/${var.project}-*",
          "arn:aws:ec2:${var.region}:${var.workload_account_id}:instance/*"
        ]
        Condition = {
          StringEquals = {
            "ssm:resourceTag/EACollectable" = "true"
          }
        }
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

# SSM 문서 — Velociraptor Offline Collect
resource "aws_ssm_document" "velociraptor_collect" {
  provider      = aws.workload
  name          = "${var.project}-VelociraptorOfflineCollect"
  document_type = "Command"
  target_type   = "/AWS::EC2::Instance"

  content = jsonencode({
    schemaVersion = "2.2"
    description   = "EA Velociraptor Offline Collector"
    parameters = {
      CaseId = {
        type        = "String"
        description = "사건 ID"
      }
      StagingBucket = {
        type    = "String"
        default = var.s3_evidence_staging_bucket
      }
      CollectionProfile = {
        type          = "String"
        default       = "standard"
        allowedValues = ["minimal", "standard", "full"]
      }
    }
    mainSteps = [
      {
        action = "aws:runShellScript"
        name   = "runCollector"
        inputs = {
          runCommand = [
            "#!/bin/bash",
            "set -euo pipefail",
            "CASE_DIR=\"/tmp/ea-collect-{{ CaseId }}\"",
            "mkdir -p \"$CASE_DIR\"",
            "/opt/ea-tools/velociraptor-collector --profile {{ CollectionProfile }} --output-dir \"$CASE_DIR\" 2>&1 | tee \"$CASE_DIR/collector.log\"",
            "aws s3 cp \"$CASE_DIR/\" \"s3://{{ StagingBucket }}/cases/{{ CaseId }}/host-triage/\" --recursive",
            "rm -rf \"$CASE_DIR\""
          ]
          timeoutSeconds = "300"
        }
      }
    ]
  })

  tags = { Name = "${var.project}-velociraptor-collect" }
}
