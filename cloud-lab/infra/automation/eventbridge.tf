resource "aws_cloudwatch_event_bus" "security" {
  provider = aws.security
  name     = "${var.project}-security-events"

  tags = { Name = "${var.project}-security-events" }
}

resource "aws_cloudwatch_event_bus_policy" "allow_workload" {
  provider       = aws.security
  event_bus_name = aws_cloudwatch_event_bus.security.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowWorkloadPutEvents"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.workload_account_id}:root" }
        Action    = "events:PutEvents"
        Resource  = aws_cloudwatch_event_bus.security.arn
      }
    ]
  })
}

# high/critical → Step Functions 자동 사건 생성
resource "aws_cloudwatch_event_rule" "auto_case" {
  state          = var.collection_enabled ? "ENABLED" : "DISABLED"
  provider       = aws.security
  name           = "${var.project}-auto-case-creation"
  event_bus_name = aws_cloudwatch_event_bus.security.name

  event_pattern = jsonencode({
    source      = ["evidence-atlas.alert-collector"]
    detail-type = ["SecurityAlertCollected"]
    detail = {
      severity = ["high", "critical"]
      target   = { type = ["ec2"] }
    }
  })

  tags = { Name = "${var.project}-auto-case-rule" }
}

resource "aws_cloudwatch_event_target" "step_functions" {
  provider       = aws.security
  rule           = aws_cloudwatch_event_rule.auto_case.name
  event_bus_name = aws_cloudwatch_event_bus.security.name
  arn            = aws_sfn_state_machine.collection.arn
  role_arn       = aws_iam_role.eventbridge_sfn.arn
  dead_letter_config { arn = aws_sqs_queue.delivery_failure.arn }

  input_transformer {
    input_paths = {
      case_id          = "$.detail.case_id"
      space_id         = "$.detail.space_id"
      playbook_version = "$.detail.playbook_version"
      alert_id         = "$.detail.alert_id"
      rule_name        = "$.detail.rule_name"
      severity         = "$.detail.severity"
      detected_at      = "$.detail.detected_at"
      target           = "$.detail.target"
      signal_fields    = "$.detail.signal_fields"
    }

    input_template = <<-EOT
      {
        "case_id": <case_id>,
        "trigger": {
          "alert_id": <alert_id>,
          "space_id": <space_id>,
          "playbook_version": <playbook_version>,
          "rule_name": <rule_name>,
          "severity": <severity>,
          "detected_at": <detected_at>,
          "scenario": "auto"
        },
        "target": <target>
      }
    EOT
  }
}

resource "aws_iam_role" "eventbridge_sfn" {
  provider = aws.security
  name     = "${var.project}-eventbridge-sfn"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = { Service = "events.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }
    ]
  })

  tags = { Name = "${var.project}-eventbridge-sfn" }
}

resource "aws_iam_role_policy" "eventbridge_sfn" {
  provider = aws.security
  name     = "start-execution"
  role     = aws_iam_role.eventbridge_sfn.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "states:StartExecution"
        Resource = aws_sfn_state_machine.collection.arn
      }
    ]
  })
}

# Retain all alerts for review, including unsupported resource targets. No automatic promotion.
resource "aws_cloudwatch_event_rule" "alert_queue" {
  provider       = aws.security
  name           = "${var.project}-alert-queue"
  event_bus_name = aws_cloudwatch_event_bus.security.name

  event_pattern = jsonencode({
    source      = ["evidence-atlas.alert-collector"]
    detail-type = ["SecurityAlertCollected"]
  })

  tags = { Name = "${var.project}-alert-queue-rule" }
}

resource "aws_sqs_queue" "alert_review" {
  provider                  = aws.security
  name                      = "${var.project}-alert-review"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "delivery_failure" {
  provider                  = aws.security
  name                      = "${var.project}-eventbridge-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue_policy" "eventbridge" {
  provider  = aws.security
  for_each  = { review = aws_sqs_queue.alert_review, failure = aws_sqs_queue.delivery_failure }
  queue_url = each.value.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sqs:SendMessage",
    Resource = each.value.arn, Condition = { ArnEquals = { "aws:SourceArn" = [aws_cloudwatch_event_rule.auto_case.arn, aws_cloudwatch_event_rule.alert_queue.arn] } }
  }] })
}
resource "aws_cloudwatch_event_target" "alert_review" {
  provider       = aws.security
  rule           = aws_cloudwatch_event_rule.alert_queue.name
  event_bus_name = aws_cloudwatch_event_bus.security.name
  arn            = aws_sqs_queue.alert_review.arn
  dead_letter_config { arn = aws_sqs_queue.delivery_failure.arn }
}
