resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "${var.project}-vpc" }
}

locals {
  subnets = {
    egress-a       = { cidr = "10.60.0.0/24", az = var.az_primary, public = true }
    ingress-a      = { cidr = "10.60.1.0/24", az = var.az_primary, public = true }
    ingress-c      = { cidr = "10.60.11.0/24", az = var.az_secondary, public = true }
    dmz-web-a      = { cidr = "10.60.2.0/24", az = var.az_primary, public = false }
    app-a          = { cidr = "10.60.3.0/24", az = var.az_primary, public = false }
    db-a           = { cidr = "10.60.4.0/24", az = var.az_primary, public = false }
    db-c           = { cidr = "10.60.14.0/24", az = var.az_secondary, public = false }
    management-a   = { cidr = "10.60.5.0/24", az = var.az_primary, public = false }
    test-a         = { cidr = "10.60.9.0/24", az = var.az_primary, public = false }
    forensic-a     = { cidr = "10.60.6.0/24", az = var.az_primary, public = false }
    scenario-app-a = { cidr = "10.60.7.0/24", az = var.az_primary, public = false }
  }
}

resource "aws_subnet" "this" {
  for_each = local.subnets

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value.cidr
  availability_zone       = each.value.az
  map_public_ip_on_launch = each.value.public

  tags = { Name = "${var.project}-${each.key}" }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-public-rt" }
}

resource "aws_route" "public_internet" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}

resource "aws_route_table_association" "public" {
  for_each = { for k, v in local.subnets : k => v if v.public }

  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-private-rt" }
}

resource "aws_route" "private_nat" {
  count = var.operation_mode == "setup" ? 1 : 0

  route_table_id         = aws_route_table.private.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.main[0].id
}

resource "aws_route_table_association" "private" {
  for_each = { for k, v in local.subnets : k => v if !v.public && !startswith(k, "db-") }

  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.private.id
}

resource "aws_flow_log" "vpc" {
  vpc_id                   = aws_vpc.main.id
  traffic_type             = "ALL"
  log_destination          = "arn:aws:s3:::${var.project}-flow-logs-${var.workload_account_id}"
  log_destination_type     = "s3"
  max_aggregation_interval = 60

  tags = { Name = "${var.project}-flow-log" }
}

resource "aws_route_table" "database" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "${var.project}-database-rt" }
}
resource "aws_route_table_association" "database" {
  for_each       = { for k, v in local.subnets : k => v if startswith(k, "db-") }
  subnet_id      = aws_subnet.this[each.key].id
  route_table_id = aws_route_table.database.id
}
