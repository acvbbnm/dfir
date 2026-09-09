# S3 Gateway endpoint — 항상 활성
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]

  tags = { Name = "${var.project}-vpce-s3" }
}

# SSM Interface endpoints — operate 모드에서만 활성
resource "aws_security_group" "vpce" {
  count = var.operation_mode == "operate" ? 1 : 0

  name_prefix = "${var.project}-vpce-"
  description = "VPC endpoint ENI — HTTPS 수신"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = { Name = "${var.project}-sg-vpce" }
  lifecycle { create_before_destroy = true }
}

resource "aws_vpc_endpoint" "ssm" {
  count = var.operation_mode == "operate" ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ssm"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.this["management-a"].id]
  security_group_ids  = [aws_security_group.vpce[0].id]

  tags = { Name = "${var.project}-vpce-ssm" }
}

resource "aws_vpc_endpoint" "ssmmessages" {
  count = var.operation_mode == "operate" ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ssmmessages"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.this["management-a"].id]
  security_group_ids  = [aws_security_group.vpce[0].id]

  tags = { Name = "${var.project}-vpce-ssmmessages" }
}

resource "aws_vpc_endpoint" "ec2messages" {
  count = var.operation_mode == "operate" ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.ec2messages"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [aws_subnet.this["management-a"].id]
  security_group_ids  = [aws_security_group.vpce[0].id]

  tags = { Name = "${var.project}-vpce-ec2messages" }
}
