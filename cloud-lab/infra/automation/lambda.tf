locals {
  lambda_functions = {
    validate-case = {
      handler = "handler.lambda_handler"
      timeout = 30
      memory  = 256
    }
    preserve-metadata = {
      handler = "handler.lambda_handler"
      timeout = 120
      memory  = 512
    }
    collect-aws-logs = {
      handler = "handler.lambda_handler"
      timeout = 300
      memory  = 512
    }
    trigger-host-collection = {
      handler = "handler.lambda_handler"
      timeout = 600
      memory  = 256
    }
    verify-finalize = {
      handler = "handler.lambda_handler"
      timeout = 120
      memory  = 512
    }
  }
}

data "archive_file" "lambda" {
  for_each = local.lambda_functions

  type = "zip"

  source {
    content  = file("${path.module}/lambda_src/${replace(each.key, "-", "_")}/handler.py")
    filename = "handler.py"
  }
  dynamic "source" {
    for_each = fileset("${path.module}/lambda_src/common", "*.py")
    content {
      content  = file("${path.module}/lambda_src/common/${source.value}")
      filename = "common/${source.value}"
    }
  }
  output_path = "${path.module}/lambda_${each.key}.zip"
}

resource "aws_lambda_function" "this" {
  provider = aws.security

  for_each = local.lambda_functions

  function_name = "${var.project}-${each.key}"
  role          = aws_iam_role.lambda[each.key].arn
  handler       = each.value.handler
  runtime       = "python3.12"
  timeout       = each.value.timeout
  memory_size   = each.value.memory

  filename         = data.archive_file.lambda[each.key].output_path
  source_code_hash = data.archive_file.lambda[each.key].output_base64sha256

  environment {
    variables = {
      EVIDENCE_KMS_KEY_ARN = var.kms_evidence_s3_arn
      PROJECT              = var.project
      REGION               = var.region
      AUDIT_EXTRA_REGIONS  = join(",", var.audit_extra_regions)
      SECURITY_ACCOUNT_ID  = var.security_account_id
      WORKLOAD_ACCOUNT_ID  = var.workload_account_id
      CASES_TABLE          = aws_dynamodb_table.cases.name
      DEDUP_TABLE          = aws_dynamodb_table.dedup.name
      STAGING_BUCKET       = var.s3_evidence_staging_bucket
      FINAL_BUCKET         = var.s3_evidence_final_bucket
      CLOUDTRAIL_BUCKET    = "${var.project}-cloudtrail-${var.security_account_id}"
    }
  }

  tags = { Name = "${var.project}-${each.key}" }
}

resource "aws_iam_role" "lambda" {
  provider = aws.security

  for_each = local.lambda_functions

  name = "${var.project}-lambda-${each.key}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "lambda.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = { Name = "${var.project}-lambda-${each.key}" }
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  for_each = local.lambda_functions

  provider   = aws.security
  role       = aws_iam_role.lambda[each.key].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  for_each = local.lambda_functions

  provider = aws.security
  name     = "dynamodb-access"
  role     = aws_iam_role.lambda[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:Query"
        ]
        Resource = [
          aws_dynamodb_table.cases.arn,
          "${aws_dynamodb_table.cases.arn}/index/*",
          aws_dynamodb_table.dedup.arn
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_s3" {
  for_each = local.lambda_functions

  provider = aws.security
  name     = "s3-access"
  role     = aws_iam_role.lambda[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:PutObject",
          "s3:ListBucket"
        ]
        Resource = [
          var.s3_evidence_staging_arn,
          "${var.s3_evidence_staging_arn}/*",
          var.s3_evidence_final_arn,
          "${var.s3_evidence_final_arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey*"
        ]
        Resource = var.kms_evidence_s3_arn
      }
    ]
  })
}

# preserve-metadata 전용: Workload AssumeRole
resource "aws_iam_role_policy" "lambda_assume_workload" {
  provider = aws.security
  name     = "assume-workload"
  for_each = toset(["validate-case", "preserve-metadata", "collect-aws-logs"])
  role     = aws_iam_role.lambda[each.key].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = "arn:aws:iam::${var.workload_account_id}:role/${var.project}-collection-target"
      }
    ]
  })
}

# collect-aws-logs 전용: CloudTrail LookupEvents
resource "aws_iam_role_policy" "lambda_cloudtrail" {
  provider = aws.security
  name     = "cloudtrail-lookup"
  role     = aws_iam_role.lambda["collect-aws-logs"].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "cloudtrail:LookupEvents"
        Resource = "*"
      }
    ]
  })
}

# trigger-host-collection 전용: SSM SendCommand (Workload)
resource "aws_iam_role_policy" "lambda_ssm" {
  provider = aws.security
  name     = "ssm-cross-account"
  role     = aws_iam_role.lambda["trigger-host-collection"].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "sts:AssumeRole"
        Resource = "arn:aws:iam::${var.workload_account_id}:role/${var.project}-collection-target"
      }
    ]
  })
}

resource "aws_iam_role_policy" "original_cloudtrail" {
  provider = aws.security
  name     = "original-cloudtrail-read"
  role     = aws_iam_role.lambda["collect-aws-logs"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = "arn:aws:s3:::${var.project}-cloudtrail-${var.security_account_id}",
    Condition = { StringLike = { "s3:prefix" = ["AWSLogs/${var.workload_account_id}/*", "AWSLogs/${var.security_account_id}/*"] } } },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion"],
    Resource = ["arn:aws:s3:::${var.project}-cloudtrail-${var.security_account_id}/AWSLogs/${var.workload_account_id}/*", "arn:aws:s3:::${var.project}-cloudtrail-${var.security_account_id}/AWSLogs/${var.security_account_id}/*"] }
  ] })
}
