# WEB — t3.medium, Nginx + Suricata
resource "aws_instance" "web" {
  ami                  = var.ami_id
  instance_type        = "t3.medium"
  subnet_id            = aws_subnet.this["dmz-web-a"].id
  iam_instance_profile = aws_iam_instance_profile.web.name
  key_name             = var.key_name != "" ? var.key_name : null

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

  user_data_base64            = module.web_bootstrap.user_data_base64
  user_data_replace_on_change = true
  depends_on                  = [aws_route.private_nat, aws_route_table_association.private, aws_secretsmanager_secret_version.wordpress]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name          = "${var.project}-web"
    Role          = "web"
    EACollectable = "true"
  }

  lifecycle {
    ignore_changes = [ami]
  }
}

# APP — t3.medium, Apache + PHP-FPM + WordPress
resource "aws_instance" "app" {
  ami                  = var.ami_id
  instance_type        = "t3.medium"
  subnet_id            = aws_subnet.this["app-a"].id
  iam_instance_profile = aws_iam_instance_profile.app.name
  key_name             = var.key_name != "" ? var.key_name : null

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

  user_data_base64            = module.app_bootstrap.user_data_base64
  user_data_replace_on_change = true
  depends_on                  = [aws_route.private_nat, aws_route_table_association.private, aws_secretsmanager_secret_version.wordpress]

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  tags = {
    Name          = "${var.project}-app"
    Role          = "app"
    EACollectable = "true"
  }

  lifecycle {
    ignore_changes = [ami]
  }
}

# SOC — t3.xlarge, Elasticsearch + Kibana + Fleet
resource "aws_instance" "soc" {
  ami                  = var.ami_id
  instance_type        = "t3.xlarge"
  subnet_id            = aws_subnet.this["management-a"].id
  iam_instance_profile = aws_iam_instance_profile.soc.name
  key_name             = var.key_name != "" ? var.key_name : null

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


  user_data_base64            = module.soc_bootstrap.user_data_base64
  user_data_replace_on_change = true
  depends_on                  = [aws_route.private_nat, aws_route_table_association.private, aws_secretsmanager_secret_version.wordpress]

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
    ignore_changes = [ami]
  }
}

resource "aws_lb_target_group_attachment" "web" {
  target_group_arn = aws_lb_target_group.web.arn
  target_id        = aws_instance.web.id
  port             = 8080
}


resource "aws_ebs_volume" "soc_data" {
  availability_zone = var.az_primary
  size              = 50
  type              = "gp3"
  encrypted         = true
  kms_key_id        = var.kms_workload_ebs_arn
  tags              = { Name = "${var.project}-soc-data" }
}

resource "aws_volume_attachment" "soc_data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.soc_data.id
  instance_id = aws_instance.soc.id
}

module "web_bootstrap" {
  source = "../modules/bootstrap"
  role   = "web"
  environment = {
    APP_PRIVATE_IP   = aws_instance.app.private_ip
    ALB_SUBNET_CIDRS = join(",", [local.subnets["ingress-a"].cidr, local.subnets["ingress-c"].cidr])
    AWS_REGION       = var.region
  }
}

module "app_bootstrap" {
  source = "../modules/bootstrap"
  role   = "app"
  environment = {
    WORDPRESS_VERSION = var.wordpress_version
    WORDPRESS_SHA256  = var.wordpress_sha256
    WP_APP_SECRET_ARN = aws_secretsmanager_secret.wordpress.arn
    WP_URL            = "https://${aws_lb.main.dns_name}"
    AWS_REGION        = var.region
  }
}

module "soc_bootstrap" {
  source = "../modules/bootstrap"
  role   = "soc"
  environment = {
    ELASTIC_VERSION    = var.elastic_version
    SOC_DATA_VOLUME_ID = aws_ebs_volume.soc_data.id
    AWS_REGION         = var.region
  }
}
