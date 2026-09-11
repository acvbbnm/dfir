resource "aws_lb" "main" {
  name               = "${var.project}-alb"
  internal           = true
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets = [
    aws_subnet.this["ingress-a"].id,
    aws_subnet.this["ingress-c"].id
  ]

  access_logs {
    bucket  = var.s3_alb_logs_bucket
    prefix  = "alb"
    enabled = true
  }

  tags = { Name = "${var.project}-alb" }
}

resource "aws_lb_target_group" "web" {
  name     = "${var.project}-web-tg"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = aws_vpc.main.id

  health_check {
    path                = "/health"
    protocol            = "HTTP"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = { Name = "${var.project}-web-tg" }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.self_signed.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}


resource "tls_private_key" "alb" {
  algorithm = "RSA"
  rsa_bits  = 2048
}
resource "tls_self_signed_cert" "alb" {
  private_key_pem       = tls_private_key.alb.private_key_pem
  dns_names             = [aws_lb.main.dns_name]
  validity_period_hours = 2160
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth"]
  subject { common_name = "Evidence Atlas private lab" }
}
resource "aws_acm_certificate" "self_signed" {
  private_key      = tls_private_key.alb.private_key_pem
  certificate_body = tls_self_signed_cert.alb.cert_pem
  tags             = { Name = "${var.project}-self-signed" }
  lifecycle { create_before_destroy = true }
}
output "alb_certificate_pem" {
  description = "Public certificate to trust explicitly in the private test client."
  value       = tls_self_signed_cert.alb.cert_pem
}
