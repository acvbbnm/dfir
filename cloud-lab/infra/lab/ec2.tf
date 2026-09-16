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

  user_data_base64            = local.web_bootstrap_loader
  user_data_replace_on_change = true
  depends_on                  = [aws_route.private_nat, aws_route_table_association.private, aws_secretsmanager_secret_version.wordpress, aws_secretsmanager_secret_version.dvwa, aws_iam_role_policy.bootstrap_read]

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

  user_data_base64            = local.app_bootstrap_loader
  user_data_replace_on_change = true
  depends_on                  = [aws_route.private_nat, aws_route_table_association.private, aws_secretsmanager_secret_version.wordpress, aws_secretsmanager_secret_version.dvwa, aws_iam_role_policy.bootstrap_read]

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


  user_data_base64            = local.soc_bootstrap_loader
  user_data_replace_on_change = true
  depends_on                  = [aws_route.private_nat, aws_route_table_association.private, aws_secretsmanager_secret_version.wordpress, aws_secretsmanager_secret_version.dvwa, aws_iam_role_policy.bootstrap_read]

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
    APP_PRIVATE_IP       = aws_instance.app.private_ip
    WAF_MODE             = var.waf_mode
    COLLECTOR_URL        = "https://github.com/Velocidex/velociraptor/releases/download/v0.77.2/velociraptor-v0.77.2-linux-amd64"
    COLLECTOR_SHA256     = "6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077"
    EVIDENCE_BUCKET      = var.evidence_bucket
    EVIDENCE_KMS_KEY_ARN = var.evidence_kms_key_arn
    ALB_SUBNET_CIDRS     = join(",", [local.subnets["ingress-a"].cidr, local.subnets["ingress-c"].cidr])
    AWS_REGION           = var.region
  }
}

module "app_bootstrap" {
  source = "../modules/bootstrap"
  role   = "app"
  environment = {
    COLLECTOR_URL        = "https://github.com/Velocidex/velociraptor/releases/download/v0.77.2/velociraptor-v0.77.2-linux-amd64"
    COLLECTOR_SHA256     = "6c4c23c466d892788ff56ddcd3a31f844e4c0d797ade454c5e2625eb9e427077"
    EVIDENCE_BUCKET      = var.evidence_bucket
    EVIDENCE_KMS_KEY_ARN = var.evidence_kms_key_arn
    WORDPRESS_VERSION    = var.wordpress_version
    WORDPRESS_SHA256     = var.wordpress_sha256
    DVWA_APP_SECRET_ARN  = aws_secretsmanager_secret.dvwa.arn
    DVWA_URL             = "https://codeload.github.com/digininja/DVWA/tar.gz/a96943dc1f52f390ee5df72144660636c4b7dd06"
    DVWA_SHA256          = "be73e29b187bd9ceadbe7428217a0547687f38557412e13fb32972c40cb4fb35"
    RDS_CA_URL           = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"
    RDS_CA_SHA256        = "e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3"
    WP_APP_SECRET_ARN    = aws_secretsmanager_secret.wordpress.arn
    WP_URL               = "https://${aws_lb.main.dns_name}"
    AWS_REGION           = var.region
  }
}

module "soc_bootstrap" {
  source = "../modules/bootstrap"
  role   = "soc"
  environment = {
    ELASTIC_VERSION     = var.elastic_version
    SOC_DATA_VOLUME_ID  = aws_ebs_volume.soc_data.id
    PROJECT             = var.project
    WORKLOAD_ACCOUNT_ID = var.workload_account_id
    SECURITY_ACCOUNT_ID = var.security_account_id
    AUDIT_EXTRA_REGIONS = join(",", var.audit_extra_regions)
    AWS_REGION          = var.region
  }
}
