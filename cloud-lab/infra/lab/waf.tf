resource "aws_wafv2_web_acl" "main" {
  count       = var.enable_aws_waf ? 1 : 0
  name        = "${var.project}-waf"
  description = "EA WordPress WAF"
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  # AWSManagedRulesCommonRuleSet
  rule {
    name     = "CRS"
    priority = 10

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-crs"
    }
  }

  # AWSManagedRulesKnownBadInputsRuleSet
  rule {
    name     = "KnownBad"
    priority = 20

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-knownbad"
    }
  }

  # AWSManagedRulesSQLiRuleSet
  rule {
    name     = "SQLi"
    priority = 30

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-sqli"
    }
  }

  # Rate limit: login 경로 5분 100회
  rule {
    name     = "LoginRateLimit"
    priority = 40

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = 100
        aggregate_key_type = "IP"

        scope_down_statement {
          byte_match_statement {
            search_string         = "/wp-login.php"
            positional_constraint = "STARTS_WITH"

            field_to_match {
              uri_path {}
            }

            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }

    visibility_config {
      sampled_requests_enabled   = true
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project}-login-rate"
    }
  }

  visibility_config {
    sampled_requests_enabled   = true
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project}-waf"
  }

  tags = { Name = "${var.project}-waf" }
}

resource "aws_wafv2_web_acl_association" "alb" {
  count        = var.enable_aws_waf ? 1 : 0
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main[0].arn
}

resource "aws_wafv2_web_acl_logging_configuration" "main" {
  count                   = var.enable_aws_waf ? 1 : 0
  resource_arn            = aws_wafv2_web_acl.main[0].arn
  log_destination_configs = ["arn:aws:s3:::aws-waf-logs-${var.project}-${var.workload_account_id}"]
}
