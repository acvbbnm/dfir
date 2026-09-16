resource "aws_cloudwatch_log_group" "resolver" {
  name              = "/${var.project}/resolver"
  retention_in_days = 7
}
resource "aws_cloudwatch_log_resource_policy" "resolver" {
  policy_name = "${var.project}-resolver-delivery"
  policy_document = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "delivery.logs.amazonaws.com" },
    Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.resolver.arn}:*",
    Condition = { StringEquals = { "aws:SourceAccount" = var.workload_account_id },
    ArnLike = { "aws:SourceArn" = "arn:aws:logs:${var.region}:${var.workload_account_id}:*" } }
  }] })
}
resource "aws_route53_resolver_query_log_config" "main" {
  name            = "${var.project}-resolver-queries"
  destination_arn = aws_cloudwatch_log_group.resolver.arn
  depends_on      = [aws_cloudwatch_log_resource_policy.resolver]
}
resource "aws_route53_resolver_query_log_config_association" "main" {
  resolver_query_log_config_id = aws_route53_resolver_query_log_config.main.id
  resource_id                  = aws_vpc.main.id
}
