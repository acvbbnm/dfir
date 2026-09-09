# ea-cases: 사건 상태 관리
resource "aws_dynamodb_table" "cases" {
  provider     = aws.security
  name         = "${var.project}-cases"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "case_id"

  attribute {
    name = "case_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = { Name = "${var.project}-cases" }
}

# ea-dedup: 경보 중복 방지
resource "aws_dynamodb_table" "dedup" {
  provider     = aws.security
  name         = "${var.project}-dedup"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "dedup_key"

  attribute {
    name = "dedup_key"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Name = "${var.project}-dedup" }
}

# ea-alert-queue: medium 이하 경보 대기열
resource "aws_dynamodb_table" "alert_queue" {
  provider     = aws.security
  name         = "${var.project}-alert-queue"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"

  attribute {
    name = "alert_id"
    type = "S"
  }

  attribute {
    name = "rule_id"
    type = "S"
  }

  attribute {
    name = "received_at"
    type = "S"
  }

  global_secondary_index {
    name            = "rule-time-index"
    hash_key        = "rule_id"
    range_key       = "received_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = { Name = "${var.project}-alert-queue" }
}
