resource "aws_s3_object" "bootstrap_web" {
  bucket                 = "${var.project}-bootstrap-${var.workload_account_id}"
  key                    = "web/${sha256(module.web_bootstrap.cloud_config)}.json"
  content                = module.web_bootstrap.cloud_config
  content_type           = "text/cloud-config"
  server_side_encryption = "AES256"
}
locals {
  web_bootstrap_loader = base64encode(templatefile("${path.module}/../../bootstrap/load_bundle.sh.tpl", {
    settings = base64encode(jsonencode({ role = "web", region = var.region, bucket = aws_s3_object.bootstrap_web.bucket,
    key = aws_s3_object.bootstrap_web.key, version_id = aws_s3_object.bootstrap_web.version_id, sha256 = sha256(module.web_bootstrap.cloud_config) }))
  }))
}

resource "aws_s3_object" "bootstrap_app" {
  bucket                 = "${var.project}-bootstrap-${var.workload_account_id}"
  key                    = "app/${sha256(module.app_bootstrap.cloud_config)}.json"
  content                = module.app_bootstrap.cloud_config
  content_type           = "text/cloud-config"
  server_side_encryption = "AES256"
}
locals {
  app_bootstrap_loader = base64encode(templatefile("${path.module}/../../bootstrap/load_bundle.sh.tpl", {
    settings = base64encode(jsonencode({ role = "app", region = var.region, bucket = aws_s3_object.bootstrap_app.bucket,
    key = aws_s3_object.bootstrap_app.key, version_id = aws_s3_object.bootstrap_app.version_id, sha256 = sha256(module.app_bootstrap.cloud_config) }))
  }))
}

resource "aws_s3_object" "bootstrap_soc" {
  bucket                 = "${var.project}-bootstrap-${var.workload_account_id}"
  key                    = "soc/${sha256(module.soc_bootstrap.cloud_config)}.json"
  content                = module.soc_bootstrap.cloud_config
  content_type           = "text/cloud-config"
  server_side_encryption = "AES256"
}
locals {
  soc_bootstrap_loader = base64encode(templatefile("${path.module}/../../bootstrap/load_bundle.sh.tpl", {
    settings = base64encode(jsonencode({ role = "soc", region = var.region, bucket = aws_s3_object.bootstrap_soc.bucket,
    key = aws_s3_object.bootstrap_soc.key, version_id = aws_s3_object.bootstrap_soc.version_id, sha256 = sha256(module.soc_bootstrap.cloud_config) }))
  }))
}
resource "aws_iam_role_policy" "bootstrap_read" {
  for_each = { web = aws_iam_role.web.id, app = aws_iam_role.app.id, soc = aws_iam_role.soc.id }
  role     = each.value
  name     = "read-versioned-bootstrap"
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Action = ["s3:GetObjectVersion"], Resource = "arn:aws:s3:::${var.project}-bootstrap-${var.workload_account_id}/${each.key}/*"
  }] })
}
