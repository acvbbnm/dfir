# N01: test → ALB
resource "aws_security_group" "alb" {
  name_prefix = "${var.project}-alb-"
  description = "ALB - --/--- HTTPS --"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from test subnet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [local.subnets["test-a"].cidr]
  }

  egress {
    description     = "To WEB"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [aws_security_group.web.id]
  }

  tags = { Name = "${var.project}-sg-alb" }

  lifecycle { create_before_destroy = true }
}

# N02: ALB → WEB
resource "aws_security_group" "web" {
  name_prefix = "${var.project}-web-"
  description = "WEB - Nginx+Suricata"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-sg-web" }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group_rule" "web_from_alb" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.web.id
  source_security_group_id = aws_security_group.alb.id
  description              = "N02: ALB - WEB"
}

# N03: WEB → APP
resource "aws_security_group" "app" {
  name_prefix = "${var.project}-app-"
  description = "APP - Apache+PHP-FPM+WordPress"
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${var.project}-sg-app" }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group_rule" "app_from_web" {
  type                     = "ingress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.web.id
  description              = "N03: WEB - APP"
}

# N04: APP → RDS
resource "aws_security_group" "rds" {
  name_prefix = "${var.project}-rds-"
  description = "RDS MySQL"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "N04: APP - RDS"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  tags = { Name = "${var.project}-sg-rds" }
  lifecycle { create_before_destroy = true }
}

# N05: Agent → SOC (Fleet 8220 + ES 9200)
resource "aws_security_group" "soc" {
  name_prefix = "${var.project}-soc-"
  description = "SOC - Elasticsearch+Kibana+Fleet"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "N05: Agent enrollment (Fleet)"
    from_port   = 8220
    to_port     = 8220
    protocol    = "tcp"
    security_groups = [
      aws_security_group.web.id,
      aws_security_group.app.id
    ]
  }

  ingress {
    description = "N05: Agent data - ES"
    from_port   = 9200
    to_port     = 9200
    protocol    = "tcp"
    security_groups = [
      aws_security_group.web.id,
      aws_security_group.app.id
    ]
  }

  ingress {
    description = "Kibana from management"
    from_port   = 5601
    to_port     = 5601
    protocol    = "tcp"
    cidr_blocks = [local.subnets["management-a"].cidr, local.subnets["test-a"].cidr]
  }

  tags = { Name = "${var.project}-sg-soc" }
  lifecycle { create_before_destroy = true }
}

# N06: SSM — 모든 관리 대상
resource "aws_security_group" "ssm" {
  name_prefix = "${var.project}-ssm-"
  description = "SSM HTTPS -----"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "N06: HTTPS to SSM endpoints / NAT"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-sg-ssm" }
  lifecycle { create_before_destroy = true }
}

# N07: S3 gateway — prefix list로 제한
resource "aws_security_group" "s3_access" {
  name_prefix = "${var.project}-s3-"
  description = "S3 gateway endpoint --"
  vpc_id      = aws_vpc.main.id

  egress {
    description     = "N07: S3 via gateway endpoint"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.s3.prefix_list_id]
  }

  tags = { Name = "${var.project}-sg-s3-access" }
  lifecycle { create_before_destroy = true }
}

# N08: Secrets Manager
resource "aws_security_group" "secrets" {
  name_prefix = "${var.project}-secrets-"
  description = "Secrets Manager --"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "N08: HTTPS to Secrets Manager"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${var.project}-sg-secrets" }
  lifecycle { create_before_destroy = true }
}

# N09: DNS + NTP
resource "aws_security_group" "base" {
  name_prefix = "${var.project}-base-"
  description = "DNS + NTP -- --"
  vpc_id      = aws_vpc.main.id

  egress {
    description = "N09: DNS UDP"
    from_port   = 53
    to_port     = 53
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "N09: DNS TCP"
    from_port   = 53
    to_port     = 53
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "N09: NTP"
    from_port   = 123
    to_port     = 123
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
  }


  dynamic "egress" {
    for_each = var.operation_mode == "setup" ? [1] : []
    content {
      description = "Ubuntu package repositories during setup only"
      from_port   = 80
      to_port     = 80
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }
  tags = { Name = "${var.project}-sg-base" }
  lifecycle { create_before_destroy = true }
}

# 격리 SG — 대응 시 교체용
resource "aws_security_group" "isolation" {
  name_prefix = "${var.project}-isolation-"
  description = "-- - SSM + S3 endpoint- --"
  vpc_id      = aws_vpc.main.id

  egress {
    description     = "SSM HTTPS"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.vpce.id]
  }

  egress {
    description     = "S3 gateway"
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.s3.prefix_list_id]
  }

  tags = { Name = "${var.project}-sg-isolation" }
  lifecycle { create_before_destroy = true }
}

resource "aws_security_group_rule" "web_to_app" {
  type                     = "egress"
  from_port                = 8080
  to_port                  = 8080
  protocol                 = "tcp"
  security_group_id        = aws_security_group.web.id
  source_security_group_id = aws_security_group.app.id
}
resource "aws_security_group_rule" "app_to_rds" {
  type                     = "egress"
  from_port                = 3306
  to_port                  = 3306
  protocol                 = "tcp"
  security_group_id        = aws_security_group.app.id
  source_security_group_id = aws_security_group.rds.id
}
resource "aws_security_group_rule" "agents_to_soc" {
  for_each                 = { web_fleet = ["web", 8220], web_es = ["web", 9200], app_fleet = ["app", 8220], app_es = ["app", 9200] }
  type                     = "egress"
  from_port                = each.value[1]
  to_port                  = each.value[1]
  protocol                 = "tcp"
  security_group_id        = each.value[0] == "web" ? aws_security_group.web.id : aws_security_group.app.id
  source_security_group_id = aws_security_group.soc.id
}
