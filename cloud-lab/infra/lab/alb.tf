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

resource "aws_acm_certificate" "self_signed" {
  # self-signed 인증서는 실제 배포 시 tls provider로 생성하거나
  # ACM에서 사설 CA를 사용한다. 여기서는 placeholder.
  # 실제 구현 시: tls_self_signed_cert + aws_acm_certificate import
  private_key      = "TODO_GENERATE_AT_DEPLOY"
  certificate_body = "TODO_GENERATE_AT_DEPLOY"

  lifecycle {
    ignore_changes = [private_key, certificate_body]
  }

  tags = { Name = "${var.project}-self-signed" }
}
