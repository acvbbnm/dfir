data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# WEB instance role
resource "aws_iam_role" "web" {
  name               = "${var.project}-web-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = { Name = "${var.project}-web-role" }
}

resource "aws_iam_role_policy_attachment" "web_ssm" {
  role       = aws_iam_role.web.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "web" {
  name = "${var.project}-web-profile"
  role = aws_iam_role.web.name
}

# APP instance role
resource "aws_iam_role" "app" {
  name               = "${var.project}-app-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = { Name = "${var.project}-app-role" }
}

resource "aws_iam_role_policy_attachment" "app_ssm" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app_secrets" {
  name = "${var.project}-app-secrets"
  role = aws_iam_role.app.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_secretsmanager_secret.wordpress.arn
      }
    ]
  })
}

resource "aws_iam_instance_profile" "app" {
  name = "${var.project}-app-profile"
  role = aws_iam_role.app.name
}

# SOC instance role
resource "aws_iam_role" "soc" {
  name               = "${var.project}-soc-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
  tags               = { Name = "${var.project}-soc-role" }
}

resource "aws_iam_role_policy_attachment" "soc_ssm" {
  role       = aws_iam_role.soc.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "soc_s3_read" {
  name = "${var.project}-soc-s3-read"
  role = aws_iam_role.soc.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadLogBuckets"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::aws-waf-logs-${var.project}-${var.workload_account_id}",
          "arn:aws:s3:::aws-waf-logs-${var.project}-${var.workload_account_id}/*",
          "arn:aws:s3:::${var.project}-alb-logs-${var.workload_account_id}",
          "arn:aws:s3:::${var.project}-alb-logs-${var.workload_account_id}/*",
          "arn:aws:s3:::${var.project}-flow-logs-${var.workload_account_id}",
          "arn:aws:s3:::${var.project}-flow-logs-${var.workload_account_id}/*"
        ]
      },
      {
        Sid    = "SQSConsume"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = "arn:aws:sqs:${var.region}:${var.workload_account_id}:${var.project}-*"
      },
      {
        Sid    = "CloudWatchLogsRead"
        Effect = "Allow"
        Action = [
          "logs:GetLogEvents",
          "logs:FilterLogEvents",
          "logs:DescribeLogGroups",
          "logs:DescribeLogStreams"
        ]
        Resource = "arn:aws:logs:${var.region}:${var.workload_account_id}:log-group:*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "soc_eventbridge" {
  name = "${var.project}-soc-eventbridge"
  role = aws_iam_role.soc.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "PutEventsToSecurity"
        Effect   = "Allow"
        Action   = "events:PutEvents"
        Resource = "arn:aws:events:${var.region}:${var.security_account_id}:event-bus/${var.project}-security-events"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "soc" {
  name = "${var.project}-soc-profile"
  role = aws_iam_role.soc.name
}
