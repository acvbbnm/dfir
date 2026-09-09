resource "aws_sfn_state_machine" "collection" {
  provider = aws.security
  name     = "${var.project}-evidence-collection"
  role_arn = aws_iam_role.sfn_execution.arn

  definition = file("${path.module}/asl/collection.asl.json")

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  tags = { Name = "${var.project}-evidence-collection" }
}

resource "aws_cloudwatch_log_group" "sfn" {
  provider          = aws.security
  name              = "/aws/states/${var.project}-evidence-collection"
  retention_in_days = 14

  tags = { Name = "${var.project}-sfn-logs" }
}

resource "aws_iam_role" "sfn_execution" {
  provider = aws.security
  name     = "${var.project}-sfn-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action = "sts:AssumeRole"
      }
    ]
  })

  tags = { Name = "${var.project}-sfn-execution" }
}

resource "aws_iam_role_policy" "sfn_invoke_lambda" {
  provider = aws.security
  name     = "invoke-lambdas"
  role     = aws_iam_role.sfn_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = "arn:aws:lambda:${var.region}:${var.security_account_id}:function:${var.project}-*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ]
        Resource = "*"
      }
    ]
  })
}
