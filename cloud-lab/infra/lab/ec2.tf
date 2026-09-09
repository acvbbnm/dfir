# WEB — t3.medium, Nginx + Suricata
resource "aws_instance" "web" {
  ami                    = var.ami_id
  instance_type          = "t3.medium"
  subnet_id              = aws_subnet.this["dmz-web-a"].id
  iam_instance_profile   = aws_iam_instance_profile.web.name
  key_name               = var.key_name != "" ? var.key_name : null

  vpc_security_group_ids = [
    aws_security_group.web.id,
    aws_security_group.ssm.id,
    aws_security_group.s3_access.id,
    aws_security_group.base.id
  ]

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_workload_ebs_arn
  }

  user_data = file("${path.module}/../../bootstrap/web.sh")

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name = "${var.project}-web"
    Role = "web"
    EACollectable = "true"
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

# APP — t3.medium, Apache + PHP-FPM + WordPress
resource "aws_instance" "app" {
  ami                    = var.ami_id
  instance_type          = "t3.medium"
  subnet_id              = aws_subnet.this["app-a"].id
  iam_instance_profile   = aws_iam_instance_profile.app.name
  key_name               = var.key_name != "" ? var.key_name : null

  vpc_security_group_ids = [
    aws_security_group.app.id,
    aws_security_group.ssm.id,
    aws_security_group.s3_access.id,
    aws_security_group.secrets.id,
    aws_security_group.base.id
  ]

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_workload_ebs_arn
  }

  user_data = file("${path.module}/../../bootstrap/app.sh")

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name = "${var.project}-app"
    Role = "app"
    EACollectable = "true"
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

# SOC — t3.xlarge, Elasticsearch + Kibana + Fleet
resource "aws_instance" "soc" {
  ami                    = var.ami_id
  instance_type          = "t3.xlarge"
  subnet_id              = aws_subnet.this["management-a"].id
  iam_instance_profile   = aws_iam_instance_profile.soc.name
  key_name               = var.key_name != "" ? var.key_name : null

  vpc_security_group_ids = [
    aws_security_group.soc.id,
    aws_security_group.ssm.id,
    aws_security_group.s3_access.id,
    aws_security_group.base.id
  ]

  root_block_device {
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_workload_ebs_arn
  }

  ebs_block_device {
    device_name = "/dev/sdf"
    volume_size = 50
    volume_type = "gp3"
    encrypted   = true
    kms_key_id  = var.kms_workload_ebs_arn
  }

  user_data = file("${path.module}/../../bootstrap/soc.sh")

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name = "${var.project}-soc"
    Role = "soc"
  }

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_lb_target_group_attachment" "web" {
  target_group_arn = aws_lb_target_group.web.arn
  target_id        = aws_instance.web.id
  port             = 8080
}
