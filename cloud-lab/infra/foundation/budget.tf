resource "aws_sns_topic" "budget_alerts" {
  provider = aws.security
  name     = "${var.project}-budget-alerts"

  tags = { Name = "${var.project}-budget-alerts" }
}

resource "aws_sns_topic_subscription" "budget_email" {
  provider  = aws.security
  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "email"
  endpoint  = var.budget_notification_email
}

resource "aws_budgets_budget" "monthly" {
  provider    = aws.security
  name        = "${var.project}-security-monthly-early-warning"
  budget_type = "COST"
  time_unit   = "MONTHLY"

  limit_amount = tostring(var.budget_limit_usd * 0.2)
  limit_unit   = "USD"

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = (var.budget_warning_usd / var.budget_limit_usd) * 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.budget_alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = (var.budget_critical_usd / var.budget_limit_usd) * 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.budget_alerts.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.budget_alerts.arn]
  }
}

resource "aws_budgets_budget" "workload_monthly" {
  provider     = aws.workload
  name         = "${var.project}-workload-monthly-early-warning"
  budget_type  = "COST"
  time_unit    = "MONTHLY"
  limit_amount = tostring(var.budget_limit_usd * 0.8)
  limit_unit   = "USD"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 75
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_notification_email]
  }
}
resource "aws_sns_topic_policy" "budgets" {
  provider = aws.security
  arn      = aws_sns_topic.budget_alerts.arn
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Principal = { Service = "budgets.amazonaws.com" }, Action = "sns:Publish",
    Resource = aws_sns_topic.budget_alerts.arn, Condition = { StringEquals = { "aws:SourceAccount" = var.security_account_id } }
  }] })
}
