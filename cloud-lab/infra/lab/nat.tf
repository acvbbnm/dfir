resource "aws_eip" "nat" {
  count  = var.operation_mode == "setup" ? 1 : 0
  domain = "vpc"

  tags = { Name = "${var.project}-nat-eip" }
}

resource "aws_nat_gateway" "main" {
  count = var.operation_mode == "setup" ? 1 : 0

  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.this["egress-a"].id

  tags = { Name = "${var.project}-nat" }

  depends_on = [aws_internet_gateway.main]
}
